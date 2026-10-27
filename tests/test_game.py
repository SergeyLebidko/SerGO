"""Тесты модели партии."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sergo.board import Board, BLACK, WHITE, PASS, LETTERS  # noqa: E402
from sergo.game import Game, GamePhase  # noqa: E402


def at(board, text):
    return (board.size - int(text[1:])) * board.size + LETTERS.index(text[0])


class TestGameFlow(unittest.TestCase):
    def test_new_game(self):
        g = Game(size=9)
        self.assertEqual(g.phase, GamePhase.PLAYING)
        self.assertEqual(g.turn, BLACK)
        self.assertEqual(len(g.moves), 0)

    def test_turn_alternates(self):
        g = Game(size=9)
        self.assertTrue(g.play(at(g.board, "E5")))
        self.assertEqual(g.turn, WHITE)
        self.assertTrue(g.play(at(g.board, "D4")))
        self.assertEqual(g.turn, BLACK)

    def test_rejects_wrong_color(self):
        g = Game(size=9)
        self.assertFalse(g.play(at(g.board, "E5"), WHITE))
        self.assertEqual(len(g.moves), 0)

    def test_rejects_illegal(self):
        g = Game(size=9)
        g.play(at(g.board, "E5"))
        self.assertFalse(g.play(at(g.board, "E5")))
        self.assertEqual(len(g.moves), 1)

    def test_undo(self):
        g = Game(size=9)
        g.play(at(g.board, "E5"))
        g.play(at(g.board, "D4"))
        self.assertTrue(g.undo())
        self.assertEqual(len(g.moves), 1)
        self.assertEqual(g.turn, WHITE)
        self.assertTrue(g.board.is_legal(at(g.board, "D4"), WHITE))

    def test_undo_restores_empty_board(self):
        g = Game(size=9)
        g.play(at(g.board, "E5"))
        g.undo()
        self.assertEqual(g.board.stones.count(0), 81)
        self.assertFalse(g.undo())

    def test_two_passes_trigger_scoring(self):
        g = Game(size=9)
        g.play(at(g.board, "E5"))
        g.play(at(g.board, "D4"))
        g.play(PASS)
        g.play(PASS)
        self.assertEqual(g.phase, GamePhase.SCORING)
        self.assertIsNotNone(g.result)

    def test_resume_play(self):
        g = Game(size=9)
        g.play(PASS)
        g.play(PASS)
        g.resume_play()
        self.assertEqual(g.phase, GamePhase.PLAYING)
        self.assertTrue(g.can_play())

    def test_resign(self):
        g = Game(size=9)
        g.play(at(g.board, "E5"))
        g.resign(BLACK)
        self.assertEqual(g.phase, GamePhase.FINISHED)
        self.assertEqual(g.winner, WHITE)
        self.assertIn("Чёрные", g.message)

    def test_captures_recorded(self):
        g = Game(size=9)
        # Белый камень E5 в атари, чёрные забирают его на E6.
        for t in ("D5", "F5", "E4"):
            g.play(at(g.board, t))
            g.play(PASS)
        g.board.stones[at(g.board, "E5")] = WHITE
        self.assertTrue(g.play(at(g.board, "E6")))
        self.assertEqual(g.captured(BLACK), 1)
        self.assertEqual(g.moves[-1].captures, (at(g.board, "E5"),))

    def test_finish_scoring_sets_message(self):
        g = Game(size=9)
        g.play(PASS)
        g.play(PASS)
        g.finish_scoring()
        self.assertEqual(g.phase, GamePhase.FINISHED)
        self.assertTrue(g.message)

    def test_toggle_dead(self):
        g = Game(size=9)
        g.board.stones[at(g.board, "E5")] = WHITE
        g.play(PASS)
        g.play(PASS)
        before = g.result.white_stones if g.result else 0
        g.toggle_dead(at(g.board, "E5"))
        self.assertIn(at(g.board, "E5"), g.dead)
        g.toggle_dead(at(g.board, "E5"))
        self.assertNotIn(at(g.board, "E5"), g.dead)

    def test_status_line(self):
        g = Game(size=9)
        self.assertIn("Ход 1", g.status_line())
        self.assertIn("Чёрные", g.status_line())

    def test_move_labels(self):
        g = Game(size=9)
        g.play(at(g.board, "E5"))
        self.assertEqual(g.moves[0].label(9), "1. Ч E5")

    def test_all_sizes(self):
        for size in (9, 13, 19):
            g = Game(size=size)
            self.assertEqual(g.board.size, size)
            self.assertTrue(g.play(g.board.n // 2))


class TestGameScoring(unittest.TestCase):
    def test_komi_affects_result(self):
        g = Game(size=9, komi=0.0)
        g.play(PASS)
        g.play(PASS)
        s0 = g.result
        g.resume_play()
        g.komi = 10.0
        g.play(PASS)
        g.play(PASS)
        s1 = g.result
        self.assertGreater(s1.white, s0.white)


if __name__ == "__main__":
    unittest.main()
