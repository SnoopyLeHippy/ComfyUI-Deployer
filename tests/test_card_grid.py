"""ResponsiveCardGrid: a pinned card leads the grid, whatever arrived before it.

The "Linked" card (a node another program keeps in ``custom_nodes``) is found
by a background scan, after the tracked nodes: appended, it came 23rd behind
22 nodes, out of sight until the user scrolled. It is now pinned to the top.

Offscreen Qt; skipped when PyQt6 is not installed (``cli.py install-deps``).
Run: python tests/test_card_grid.py
"""

import contextlib
import io
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the embedded python won't
import _support  # noqa: E402,F401  (first: sandbox + import path)

import unittest  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402
except ImportError:  # pragma: no cover - the headless path has no Qt
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
class ResponsiveCardGridTest(unittest.TestCase):
    COLS = 3

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from deployer.ui.widgets import ResponsiveCardGrid

        self.grid = ResponsiveCardGrid()
        self.addCleanup(self.grid.deleteLater)
        width = self.COLS * (self.grid.CARD_WIDTH + self.grid.CARD_SPACING) - self.grid.CARD_SPACING
        self.grid.update_cols(width)
        self.assertEqual(self.grid._cols, self.COLS)

    def card(self, name):
        card = QWidget()
        card.setObjectName(name)
        return card

    def shown(self):
        """The grid's widgets in reading order (row by row, left to right)."""
        grid = self.grid
        widgets = []
        for i in range(grid._grid.count()):
            item = grid._grid.itemAtPosition(*divmod(i, grid._cols))
            widgets.append(item.widget() if item is not None else None)
        return widgets

    def test_a_pinned_card_comes_first_after_22_others(self):
        nodes = [self.card(f"node{i}") for i in range(22)]
        for card in nodes:
            self.grid.add_card(card)
        linked = self.card("linked")
        self.grid.add_card(linked, pinned=True)
        self.assertEqual(self.shown(), [linked, *nodes])

    def test_pinned_cards_keep_their_arrival_order(self):
        a, b = self.card("a"), self.card("b")
        n1, n2 = self.card("n1"), self.card("n2")
        self.grid.add_card(n1)
        self.grid.add_card(a, pinned=True)
        self.grid.add_card(n2)
        self.grid.add_card(b, pinned=True)
        self.assertEqual(self.shown(), [a, b, n1, n2])

    def test_the_add_button_stays_last(self):
        plus = self.card("+")
        node = self.card("node")
        self.grid.add_card(node)
        self.grid.set_add_button(plus)
        linked = self.card("linked")
        self.grid.add_card(linked, pinned=True)
        self.assertEqual(self.shown(), [linked, node, plus])

    def test_a_pinned_card_can_be_removed(self):
        a, b, node = self.card("a"), self.card("b"), self.card("node")
        self.grid.add_card(node)
        self.grid.add_card(a, pinned=True)
        self.grid.add_card(b, pinned=True)
        self.grid.remove_card(a)
        self.assertIsNone(a.parent())
        self.assertEqual(self.shown(), [b, node])

    def test_the_size_hint_counts_pinned_cards(self):
        self.grid.add_card(self.card("n1"))
        self.grid.add_card(self.card("n2"))
        self.grid.add_card(self.card("linked"), pinned=True)
        self.grid.set_add_button(self.card("+"))
        rows = 2  # 4 items, 3 columns
        expected = rows * self.grid.CARD_HEIGHT + (rows - 1) * self.grid.CARD_SPACING
        self.assertEqual(self.grid.sizeHint().height(), expected)

    def test_the_window_pins_the_linked_card(self):
        from deployer.ui.app import CustomNodeDeployerApp
        from deployer.ui.widgets import LinkedNodeCard

        nodes = [self.card(f"node{i}") for i in range(22)]
        for card in nodes:
            self.grid.add_card(card)
        window = types.SimpleNamespace(card_grid=self.grid, _linked_cards=[])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            CustomNodeDeployerApp._add_linked_card(window, "ComfyUI-MoodMiner", r"D:\Apps\MoodMiner")
        [card] = window._linked_cards
        self.assertIsInstance(card, LinkedNodeCard)
        self.assertEqual(self.shown(), [card, *nodes])
        self.assertIn(r"Linked: ComfyUI-MoodMiner -> D:\Apps\MoodMiner", out.getvalue())


if __name__ == "__main__":
    unittest.main()
