"""Run every test with ComfyUI's embedded python:

    ComfyUI_windows_portable\\python_embeded\\python.exe tests\\run_tests.py

Discovers ``tests/test_*.py`` as top-level modules: the embedded python puts
``ComfyUI/`` first on ``sys.path``, and ComfyUI has a ``tests`` package of its own
that ``python -m unittest discover`` would import instead of this folder.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
    # buffer: the package's prints show only for a failing test (git's own output still does).
    result = unittest.TextTestRunner(verbosity=2, buffer=True).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
