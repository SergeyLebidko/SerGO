"""Тесты движка правил."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sergo.board import (  # noqa: E402
    Board, BLACK, WHITE, EMPTY, PASS, LETTERS, format_point, parse_point,
)


def at(board, text):
    """'D4' -> индекс точки."""
    x = LETTERS.index(text[0])
    y = board.size - int(text[1:])
    return y * board.size + x


def put(board, color, coords):
    """Поставить камни напрямую (в обход правил) для подготовки позиции."""
    for text in coords.split():
        board.stones[at(board, text)] = color


class TestBasics(unittest.TestCase):
    def test_empty_board(self):
        b = Board(9)
        self.assertEqual(b.stones.count(EMPTY), 81)
        self.assertTrue(b.is_legal(at(b, "E5"), BLACK))

    def test_occupied_point_rejected(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        self.assertFalse(b.is_legal(at(b, "E5"), WHITE))
        self.assertIsNone(b.play(at(b, "E5"), WHITE))

    def test_single_capture(self):
        b = Board(9)
        put(b, BLACK, "D5 F5 E4")
        put(b, WHITE, "E5")
        rec = b.play(at(b, "E6"), BLACK)
        self.assertIsNotNone(rec)
        self.assertEqual(b.stones[at(b, "E5")], EMPTY)
        self.assertEqual(len(rec.captured), 1)
        self.assertEqual(b.caps[BLACK], 1)

    def test_group_capture(self):
        b = Board(9)
        # Белая пара E5-E6: единственное дамэ — F5.
        put(b, WHITE, "E5 E6")
        put(b, BLACK, "D5 D6 E4 D7 F7 E7 F6")
        self.assertEqual(b.liberties(at(b, "E5")), 1)
        rec = b.play(at(b, "F5"), BLACK)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.captured), 2)
        self.assertEqual(b.stones[at(b, "E5")], EMPTY)
        self.assertEqual(b.stones[at(b, "E6")], EMPTY)
        self.assertEqual(b.caps[BLACK], 2)

    def test_suicide_forbidden(self):
        b = Board(9)
        put(b, WHITE, "D5 F5 E4 E6")
        self.assertFalse(b.is_legal(at(b, "E5"), BLACK))
        self.assertIsNone(b.play(at(b, "E5"), BLACK))
        self.assertEqual(b.stones[at(b, "E5")], EMPTY)

    def test_suicide_allowed_when_capturing(self):
        b = Board(9)
        # Белый F5 в атари: единственное дамэ — E5.
        put(b, WHITE, "F5")
        put(b, BLACK, "E4 E6 F4 F6 G5")
        self.assertEqual(b.liberties(at(b, "F5")), 1)
        rec = b.play(at(b, "E5"), BLACK)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.captured), 1)
        self.assertEqual(b.stones[at(b, "E5")], BLACK)
        self.assertGreaterEqual(b.liberties(at(b, "E5")), 1)

    def test_pass_is_legal(self):
        b = Board(9)
        self.assertTrue(b.is_legal(PASS, BLACK))
        rec = b.play(PASS, BLACK)
        self.assertIsNotNone(rec)
        self.assertTrue(b.undo(rec))

    def test_all_sizes(self):
        for size in (2, 5, 9, 13, 19):
            b = Board(size)
            self.assertEqual(b.n, size * size)
            self.assertTrue(b.is_legal(b.n // 2, BLACK))


class TestKo(unittest.TestCase):
    def setup_ko(self):
        """Позиция, где чёрный ход C4 создаёт ко в точке C3."""
        b = Board(5)
        put(b, WHITE, "C3 B4 D4 C5")
        put(b, BLACK, "B3 D3 C2")
        return b

    def test_ko_point_detected(self):
        b = self.setup_ko()
        rec = b.play(at(b, "C4"), BLACK)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.captured), 1)
        self.assertEqual(b.ko, at(b, "C3"))

    def test_ko_recapture_forbidden(self):
        b = self.setup_ko()
        b.play(at(b, "C4"), BLACK)
        self.assertFalse(b.is_legal(at(b, "C3"), WHITE))
        self.assertIsNone(b.play(at(b, "C3"), WHITE))

    def test_ko_recapture_after_threat(self):
        b = self.setup_ko()
        b.play(at(b, "C4"), BLACK)
        b.play(at(b, "A1"), WHITE)   # ко-угроза в другом месте
        b.play(at(b, "A2"), BLACK)   # ответ на угрозу
        self.assertTrue(b.is_legal(at(b, "C3"), WHITE))
        self.assertIsNotNone(b.play(at(b, "C3"), WHITE))

    def test_superko_blocks_repetition(self):
        b = self.setup_ko()
        b.play(at(b, "C4"), BLACK)
        b.play(at(b, "A1"), WHITE)
        b.play(at(b, "A2"), BLACK)
        b.play(at(b, "C3"), WHITE)   # взятие обратно — разрешено
        # Теперь чёрный не может повторить позицию ходом C4 (суперко).
        self.assertFalse(b.is_legal(at(b, "C4"), BLACK))

    def test_pass_keeps_hash(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        h = b.hash
        b.play(PASS, WHITE)
        b.play(PASS, BLACK)
        self.assertEqual(b.hash, h)


class TestUndo(unittest.TestCase):
    def test_undo_simple_move(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        b.play(at(b, "E6"), WHITE)
        before = bytes(b.stones)
        before_hash = b.hash
        rec = b.play(at(b, "D5"), BLACK)
        self.assertNotEqual(bytes(b.stones), before)
        self.assertTrue(b.undo(rec))
        self.assertEqual(bytes(b.stones), before)
        self.assertEqual(b.hash, before_hash)
        self.assertEqual(b.stones.count(EMPTY), 81 - 2)

    def test_undo_capture_restores_stones(self):
        b = Board(9)
        put(b, BLACK, "D5 F5 E4")
        put(b, WHITE, "E5")
        before = bytes(b.stones)
        rec = b.play(at(b, "E6"), BLACK)
        self.assertEqual(len(rec.captured), 1)
        self.assertEqual(b.caps[BLACK], 1)
        b.undo(rec)
        self.assertEqual(bytes(b.stones), before)
        self.assertEqual(b.stones[at(b, "E5")], WHITE)
        self.assertEqual(b.caps[BLACK], 0)

    def test_undo_ko_restores_ko_point(self):
        b = TestKo().setup_ko()
        rec = b.play(at(b, "C4"), BLACK)
        self.assertTrue(b.undo(rec))
        self.assertEqual(b.ko, -1)
        self.assertTrue(b.is_legal(at(b, "C4"), BLACK))

    def test_undo_pass(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        h = b.hash
        rec = b.play(PASS, WHITE)
        b.undo(rec)
        self.assertEqual(b.hash, h)


class TestCopy(unittest.TestCase):
    def test_copy_independent(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        c = b.copy()
        c.play(at(b, "F5"), WHITE)
        self.assertEqual(b.stones[at(b, "F5")], EMPTY)
        self.assertEqual(c.stones[at(b, "F5")], WHITE)

    def test_copy_keeps_superko_history(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        c = b.copy()
        self.assertEqual(c.hash_set, b.hash_set)
        self.assertEqual(c.history, b.history)

    def test_fast_copy_no_history(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        c = b.fast_copy()
        self.assertEqual(c.stones, b.stones)
        self.assertFalse(c.superko)
        self.assertEqual(c.hash_set, set())


class TestCoordinates(unittest.TestCase):
    def test_roundtrip(self):
        for size in (9, 13, 19):
            for p in range(size * size):
                self.assertEqual(parse_point(size, format_point(size, p)), p)

    def test_no_letter_i(self):
        self.assertNotIn("I", LETTERS)

    def test_pass_text(self):
        self.assertEqual(format_point(9, PASS), "пас")
        self.assertEqual(parse_point(9, "пас"), PASS)
        self.assertEqual(parse_point(9, "PASS"), PASS)

    def test_bad_input(self):
        self.assertIsNone(parse_point(9, "Z9"))
        self.assertIsNone(parse_point(9, ""))
        self.assertIsNone(parse_point(9, "A99"))


class TestBoardStr(unittest.TestCase):
    def test_render(self):
        b = Board(9)
        b.play(at(b, "E5"), BLACK)
        text = str(b)
        self.assertIn("X", text)
        self.assertEqual(len(text.splitlines()), 10)


if __name__ == "__main__":
    unittest.main()
