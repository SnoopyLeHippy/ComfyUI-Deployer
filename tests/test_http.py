"""core.http.download_file: certifi first, then Windows' trust store — no PowerShell.

The fallback for a stale CA bundle used to start ``powershell
Invoke-WebRequest`` (a script-host chain endpoint security flags, reachable
from the window's workflow resolution). It is now a second ``urllib`` attempt
with the system's default SSL context. No network: ``urlopen`` is faked.
Run: python tests/test_http.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import io  # noqa: E402
import ssl  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
import urllib.error  # noqa: E402
from unittest import mock  # noqa: E402

from _support import SANDBOX, ProcessSpy  # noqa: E402
from deployer.core import http  # noqa: E402


class FakeUrlopen:
    """Answers ``urlopen`` in turn: an exception is raised, bytes are the body."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.contexts: list[ssl.SSLContext] = []

    def __call__(self, request, timeout=None, context=None):
        self.contexts.append(context)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return io.BytesIO(answer)


class DownloadFileTest(unittest.TestCase):
    def setUp(self):
        self.dest = os.path.join(tempfile.mkdtemp(dir=SANDBOX), "file.json")
        self.certifi = ssl.create_default_context()
        self.system = ssl.create_default_context()
        patch = mock.patch.object(http, "_certifi_context", return_value=self.certifi)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(http.ssl, "create_default_context", return_value=self.system)
        patch.start()
        self.addCleanup(patch.stop)

    def download(self, fake: FakeUrlopen):
        with mock.patch.object(http.urllib.request, "urlopen", fake), ProcessSpy([]) as spy:
            try:
                http.download_file("https://example.invalid/file.json", self.dest, timeout=5)
            finally:
                self.assertEqual(spy.calls, [], "no process may start")

    def read(self) -> bytes:
        with open(self.dest, "rb") as fh:
            return fh.read()

    def test_certifi_is_tried_first(self):
        fake = FakeUrlopen(b"payload")
        self.download(fake)
        self.assertEqual(self.read(), b"payload")
        self.assertEqual(fake.contexts, [self.certifi])

    def test_a_certificate_failure_retries_with_the_system_store(self):
        failure = urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer"))
        fake = FakeUrlopen(failure, b"payload")
        self.download(fake)
        self.assertEqual(self.read(), b"payload")
        self.assertEqual(fake.contexts, [self.certifi, self.system])

    def test_both_failing_raises_the_last_error(self):
        fake = FakeUrlopen(urllib.error.URLError("offline"), urllib.error.URLError("still offline"))
        with self.assertRaises(urllib.error.URLError) as caught:
            self.download(fake)
        self.assertIn("still offline", str(caught.exception))
        self.assertFalse(os.path.exists(self.dest))

    def test_an_http_error_is_not_retried(self):
        refusal = urllib.error.HTTPError("https://example.invalid", 404, "Not Found", {}, None)
        fake = FakeUrlopen(refusal, b"never")
        with self.assertRaises(urllib.error.HTTPError):
            self.download(fake)
        self.assertEqual(len(fake.contexts), 1)

    def test_without_certifi_the_system_store_is_the_only_attempt(self):
        fake = FakeUrlopen(urllib.error.URLError("offline"))
        with mock.patch.object(http, "_certifi_context", return_value=None):
            with self.assertRaises(urllib.error.URLError):
                self.download(fake)
        self.assertEqual(fake.contexts, [self.system])


if __name__ == "__main__":
    unittest.main()
