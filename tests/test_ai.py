"""Тесты ИИ: легальность ходов и превосходство над случайным ботом."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sergo.board import Board, BLACK, WHITE, PASS, other  # noqa: E402
from sergo.engine import Engine, LEVELS, level_time  # noqa: E402
from sergo.mcts import MCTS  # noqa: E402
from sergo.policy import is_self_eye, candidate_moves  # noqa: E402
from sergo.scoring import score_area  # noqa: E402


def play_game(black_engine_move, white_engine_move, size=9, komi=6.5,
              max_moves=300):
    """Провести партию. Функции принимают (board, color) -> ход."""
    board = Board(size)
    color = BLACK
    passes = 0
    history = []
    for _ in range(max_moves):
        move = (black_engine_move if color == BLACK else white_engine_move)(
            board, color)
        rec = board.play(move, color)
        if rec is None:
            return board, history, f"нелегальный ход {move} за {color}"
        history.append((move, color))
        if move == PASS:
            passes += 1
            if passes >= 2:
                return board, history, None
        else:
            passes = 0
        color = other(color)
    return board, history, "лимит ходов"


class TestPolicy(unittest.TestCase):
    def test_self_eye_detection(self):
        b = Board(5)
        # Глаз в углу: A1 окружён чёрными B1 и A2.
        b.stones[1 * 5 + 0] = BLACK
        b.stones[0 * 5 + 1] = BLACK
        self.assertTrue(is_self_eye(b, 0, BLACK))

    def test_center_eye(self):
        b = Board(5)
        # C3 окружён чёрными со всех сторон.
        for p in b.nei[2 * 5 + 2]:
            b.stones[p] = BLACK
        self.assertTrue(is_self_eye(b, 2 * 5 + 2, BLACK))

    def test_false_eye_not_eye(self):
        b = Board(5)
        for p in b.nei[2 * 5 + 2]:
            b.stones[p] = BLACK
        # Диагональные белые делают глаз ложным.
        b.stones[1 * 5 + 1] = WHITE
        b.stones[1 * 5 + 3] = WHITE
        self.assertFalse(is_self_eye(b, 2 * 5 + 2, BLACK))

    def test_candidates_near_stones(self):
        b = Board(9)
        b.play(40, BLACK)
        cands = candidate_moves(b, WHITE, 20, random.Random(1))
        self.assertIn(PASS, cands)
        self.assertTrue(all(c == PASS or c in b.empties for c in cands))

    def test_candidates_empty_board(self):
        b = Board(9)
        cands = candidate_moves(b, BLACK, 20, random.Random(1))
        self.assertTrue(cands)
        self.assertTrue(all(c in b.empties for c in cands))


class TestMCTS(unittest.TestCase):
    def test_returns_legal_move(self):
        for size in (9, 13):
            b = Board(size)
            b.play(b.n // 2, BLACK)
            mcts = MCTS(b, komi=6.5, rng=random.Random(1))
            move, winrate, sims = mcts.think(WHITE, thinking_time=0.3)
            self.assertTrue(move == PASS or b.is_legal(move, WHITE))
            self.assertGreaterEqual(winrate, 0.0)
            self.assertLessEqual(winrate, 1.0)
            self.assertGreater(sims, 0)

    def test_respects_time(self):
        import time
        b = Board(9)
        mcts = MCTS(b, komi=6.5, rng=random.Random(1))
        t0 = time.monotonic()
        mcts.think(BLACK, thinking_time=0.5)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 3.0)

    def test_cancel(self):
        b = Board(9)
        mcts = MCTS(b, komi=6.5, rng=random.Random(1))
        move, _, _ = mcts.think(BLACK, thinking_time=10.0, cancel=lambda: True)
        self.assertTrue(move == PASS or b.is_legal(move, BLACK))

    def test_advance_reuses_tree(self):
        b = Board(9)
        mcts = MCTS(b, komi=6.5, rng=random.Random(1))
        move, _, _ = mcts.think(BLACK, thinking_time=0.3)
        mcts.advance(move)
        # Корень сместился или сброшен, но поиск продолжает работать.
        move2, _, sims = mcts.think(WHITE, thinking_time=0.2)
        self.assertGreater(sims, 0)

    def test_takesFreeCapture(self):
        """Бот должен забрать камень в атари, а не пройти мимо."""
        b = Board(9)
        from sergo.board import LETTERS

        def at(t):
            return (9 - int(t[1:])) * 9 + LETTERS.index(t[0])

        # Белый камень F5 в атари: единственное дамэ E5.
        for t in ("E4", "E6", "F4", "F6", "G5"):
            b.stones[at(t)] = BLACK
        b.stones[at("F5")] = WHITE
        # Проверяем именно тактическую страховку движка.
        eng = Engine(b, level="hard", time_override=0.3, seed=2)
        move = eng.choose_move(BLACK)
        self.assertEqual(move, at("E5"), "движок не снял группу в атари")
        self.assertEqual(b.stones[at("F5")], WHITE, "ход не должен меняться")


class TestAnalysisValue(unittest.TestCase):
    """Тактический ход не должен возвращать фиктивные 0.5."""

    def test_tactical_capture_has_real_estimate(self):
        from sergo.board import LETTERS

        def at(t):
            return (9 - int(t[1:])) * 9 + LETTERS.index(t[0])

        b = Board(9)
        for t in ("E4", "E6", "F4", "F6", "G5"):
            b.stones[at(t)] = BLACK
        b.stones[at("F5")] = WHITE
        eng = Engine(b, level="hard", time_override=0.2, seed=2)
        move, winrate, sims = eng.choose_move_detailed(BLACK)
        self.assertEqual(move, at("E5"))
        self.assertEqual(sims, 0, "тактический ход не должен тратить поиск")
        self.assertNotEqual(winrate, 0.5,
                            "заглушка 0.5 вернулась — в журнале будут фиктивные 50%")


class TestEngineLevels(unittest.TestCase):
    def test_levels_exist(self):
        for size in (9, 13, 19):
            b = Board(size)
            for level in ("easy", "normal", "hard"):
                eng = Engine(b, level=level, seed=1)
                self.assertGreater(eng.budget(), 0)

    def test_harder_level_gets_more_time(self):
        """Более высокий уровень обязан думать дольше."""
        for size in (9, 13, 19):
            b = Board(size)
            easy = Engine(b, level="easy").budget()
            normal = Engine(b, level="normal").budget()
            hard = Engine(b, level="hard").budget()
            self.assertLess(easy, normal, f"{size}×{size}")
            self.assertLess(normal, hard, f"{size}×{size}")

    def test_time_grows_with_board(self):
        """19×19 требует больше времени, чем 9×9 на том же уровне."""
        for level in ("easy", "normal", "hard"):
            small = Engine(Board(9), level=level).budget()
            large = Engine(Board(19), level=level).budget()
            self.assertLess(small, large, level)

    def test_level_time_table(self):
        self.assertEqual(level_time("easy", 9), 1.0)
        self.assertEqual(level_time("hard", 19), 10.0)
        # Нестандартный размер берёт ближайший из известных.
        self.assertEqual(level_time("normal", 12), 4.0)   # ближе к 13
        self.assertEqual(level_time("normal", 10), 3.0)   # ближе к 9

    def test_time_override_for_tests(self):
        b = Board(9)
        eng = Engine(b, level="hard", time_override=0.2)
        self.assertEqual(eng.budget(), 0.2)

    def test_set_level_resets_tree(self):
        b = Board(9)
        eng = Engine(b, level="easy", seed=3)
        b.play(b.n // 2, BLACK)
        eng.mcts = object()          # имитируем построенное дерево
        eng.set_level("hard")
        self.assertIsNone(eng.mcts, "дерево должно сбрасываться")
        self.assertEqual(eng.budget(), level_time("hard", 9))

    def test_hard_level_no_blunders(self):
        self.assertEqual(LEVELS["hard"]["blunder"], 0.0)
        self.assertGreater(LEVELS["hard"]["candidates"],
                           LEVELS["easy"]["candidates"])

    def test_move_is_legal(self):
        b = Board(9)
        eng = Engine(b, level="easy", time_override=0.3, seed=7)
        b.play(b.n // 2, BLACK)
        move = eng.choose_move(WHITE)
        self.assertTrue(move == PASS or b.is_legal(move, WHITE))


class TestVersusRandom(unittest.TestCase):
    """Бот должен уверенно обыгрывать случайного игрока."""

    def _random_move(self, rng):
        def chooser(board, color):
            legal = board.legal_moves(color)
            if not legal:
                return PASS
            return rng.choice(legal)
        return chooser

    def test_bot_beats_random_9x9(self):
        wins = 0
        games = 3
        for seed in range(games):
            rng = random.Random(100 + seed)
            engines: dict[int, Engine] = {}

            def bot(board, color, seed=seed):
                eng = engines.get(id(board))
                if eng is None:
                    eng = Engine(board, level="normal", time_override=0.4,
                                 seed=seed)
                    engines[id(board)] = eng
                return eng.choose_move(color)

            random_player = self._random_move(rng)
            final, history, err = play_game(bot, random_player, size=9,
                                            max_moves=250)
            self.assertIsNone(err, err)
            # Считаем по площади; мёртвые камни не размечаем — так
            # результат ближе к «сырой» оценке MCTS.
            s = score_area(final, komi=6.5, dead=set())
            if s.black > s.white:
                wins += 1
        self.assertGreaterEqual(wins, 2,
                                f"бот выиграл только {wins} из {games}")


if __name__ == "__main__":
    unittest.main()
