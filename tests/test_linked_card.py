"""LinkedNodeCard: an untracked junction is shown read-only — a click never arms it.

Offscreen Qt; skipped when PyQt6 is not installed (``cli.py install-deps``).
Run: python tests/test_linked_card.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import unittest  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
    from PyQt6.QtGui import QMouseEvent  # noqa: E402
    from PyQt6.QtWidgets import QApplication  # noqa: E402
except ImportError:  # pragma: no cover - the headless path has no Qt
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
class LinkedNodeCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, target=r"D:\Apps\MoodMiner"):
        from deployer.ui.widgets import LinkedNodeCard

        card = LinkedNodeCard("ComfyUI-MoodMiner", target)
        self.addCleanup(card.deleteLater)
        return card

    def click(self, card):
        point = QPointF(QPoint(10, 10))
        event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, point, point,
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        card.mousePressEvent(event)

    def test_it_reads_linked_and_names_its_target(self):
        card = self.make()
        self.assertEqual(card.badge.text(), "Linked")
        self.assertIn(r"D:\Apps\MoodMiner", card.toolTip())

    def test_a_click_never_selects_it(self):
        card = self.make()
        self.click(card)
        self.click(card)
        self.assertFalse(card.is_selected)
        self.assertEqual(card.badge.text(), "Linked")

    def test_it_offers_no_requirements_checkbox(self):
        card = self.make()
        self.assertTrue(card.req_checkbox.isHidden())

    def test_an_unreadable_target_still_shows(self):
        card = self.make(target="")
        self.assertEqual(card.badge.text(), "Linked")


if __name__ == "__main__":
    unittest.main()
