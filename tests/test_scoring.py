"""Тесты подсчёта очков."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sergo.board import (  # noqa: E402
    Board, BLACK, WHITE, EMPTY, LETTERS,
)
from sergo.scoring import (  # noqa: E402
    Zone, score, score_area, score_territory, estimate_score_fast,
    score_zones,
)


def at(board, text):
    x = LETTERS.index(text[0])
    y = board.size - int(text[1:])
    return y * board.size + x


def put(board, color, coords):
    for text in coords.split():
        board.stones[at(board, text)] = color


class TestAreaScore(unittest.TestCase):
    def test_empty_board_is_neutral(self):
        b = Board(9)
        s = score_area(b, komi=6.5)
        self.assertEqual(s.black, 0)
        self.assertEqual(s.white, 6.5)
        self.assertEqual(s.neutral, 81)
        self.assertEqual(s.winner(), WHITE)

    def test_simple_split_board(self):
        # Вертикальное разделение 5x5: чёрные слева (2 столбца),
        # белые справа (2 столбца), средний столбец ничей.
        b = Board(5)
        for y in range(5):
            b.stones[y * 5 + 1] = BLACK
            b.stones[y * 5 + 3] = WHITE
        s = score_area(b, komi=0)
        self.assertEqual(s.black_stones, 5)
        self.assertEqual(s.white_stones, 5)
        self.assertEqual(s.black_territory, 5)
        self.assertEqual(s.white_territory, 5)
        self.assertEqual(s.black, 10)
        self.assertEqual(s.white, 10)
        self.assertEqual(s.winner(), 0)

    def test_corner_territory(self):
        b = Board(5)
        # Чёрная стена по линии B, белая по линии D: A-файл — территория
        # чёрных, E-файл — белых, C-файл нейтрален.
        put(b, BLACK, "B1 B2 B3 B4 B5")
        put(b, WHITE, "D1 D2 D3 D4 D5")
        s = score_area(b, komi=0)
        self.assertEqual(s.black_territory, 5)
        self.assertEqual(s.white_territory, 5)
        self.assertEqual(s.neutral, 5)

    def test_only_one_color_encloses_whole_board(self):
        # Стена чёрных без белых: вся остальная доска — их территория.
        b = Board(5)
        put(b, BLACK, "B1 B2 B3 B4 B5")
        s = score_area(b, komi=0)
        self.assertEqual(s.black_territory, 20)
        self.assertEqual(s.neutral, 0)

    def test_both_colors_region_is_neutral(self):
        b = Board(5)
        put(b, BLACK, "A1")
        put(b, WHITE, "E1")
        s = score_area(b, komi=0)
        self.assertEqual(s.neutral, 23)

    def test_dead_stones_removed(self):
        b = Board(5)
        # Чёрные окружают одиночный белый камень C3.
        put(b, WHITE, "C3")
        put(b, BLACK, "C2 C4 B3 D3")
        s_no_dead = score_area(b, komi=0)
        self.assertEqual(s_no_dead.white_stones, 1)
        self.assertEqual(s_no_dead.black_territory, 20)
        self.assertEqual(s_no_dead.black_captures, 0)
        s_dead = score_area(b, komi=0, dead={at(b, "C3")})
        self.assertEqual(s_dead.white_stones, 0)
        self.assertEqual(s_dead.black_territory, 21)
        self.assertEqual(s_dead.black_captures, 1)

    def test_komi_applied(self):
        b = Board(9)
        s = score_area(b, komi=7.5)
        self.assertEqual(s.white, 7.5)


def board_captures(b, color_removed):
    """Сколько камней цвета color_removed было снято при подсчёте."""
    return 0


class TestTerritoryScore(unittest.TestCase):
    def test_empty_board(self):
        b = Board(9)
        s = score_territory(b, komi=6.5)
        self.assertEqual(s.black, 0)
        self.assertEqual(s.white, 6.5)

    def test_captures_counted(self):
        b = Board(9)
        b.caps[BLACK] = 3
        b.caps[WHITE] = 1
        s = score_territory(b, komi=0)
        self.assertEqual(s.black_captures, 3)
        self.assertEqual(s.white_captures, 1)
        self.assertEqual(s.black, 3)

    def test_stones_not_counted(self):
        b = Board(5)
        put(b, BLACK, "B1 B2 B3 B4 B5")
        put(b, WHITE, "D1 D2 D3 D4 D5")
        s = score_territory(b, komi=0)
        self.assertEqual(s.black_stones, 5)
        self.assertEqual(s.black, 5)  # только территория


class TestDispatch(unittest.TestCase):
    def test_rules_dispatch(self):
        b = Board(9)
        self.assertEqual(score(b, rules="chinese").rules, "chinese")
        self.assertEqual(score(b, rules="japanese").rules, "japanese")


class TestFastEstimate(unittest.TestCase):
    def test_empty_board_komi(self):
        b = Board(9)
        self.assertAlmostEqual(estimate_score_fast(b, komi=6.5), -6.5)

    def test_matches_area_roughly(self):
        b = Board(5)
        for y in range(5):
            b.stones[y * 5 + 1] = BLACK
            b.stones[y * 5 + 3] = WHITE
        diff = estimate_score_fast(b, komi=0)
        self.assertEqual(diff, 0)

    def test_black_lead(self):
        b = Board(5)
        put(b, BLACK, "B1 B2 B3 B4 B5")
        self.assertGreater(estimate_score_fast(b, komi=0), 0)


class TestInfluenceEstimate(unittest.TestCase):
    """Пропорциональное деление спорных областей."""

    def test_fully_surrounded_goes_to_owner(self):
        # Чёрная стена и белая стена, между ними ничейный столбец:
        # область касается обоих — делится, а не отдаётся целиком.
        b = Board(5)
        put(b, BLACK, "B1 B2 B3 B4 B5")
        put(b, WHITE, "D1 D2 D3 D4 D5")
        diff = estimate_score_fast(b, komi=0)
        # C-столбец (5 точек) касается 5 чёрных и 5 белых -> ровно пополам.
        # A-столбец (5) — только чёрные, E-столбец (5) — только белые.
        self.assertAlmostEqual(diff, 0.0, places=6)

    def test_three_to_one_split(self):
        b = Board(5)
        # Область C3 касается трёх чёрных и одного белого.
        put(b, BLACK, "C2 C4 B3")
        put(b, WHITE, "D3")
        diff = estimate_score_fast(b, komi=0)
        # Чёрные: 3 камня, белые: 1 камень, спорных точек много.
        self.assertGreater(diff, 0)

    def test_empty_board_is_minus_komi(self):
        self.assertAlmostEqual(estimate_score_fast(Board(9), komi=6.5), -6.5)

    def test_influence_can_be_disabled(self):
        b = Board(5)
        put(b, BLACK, "C2 C4 B3")
        put(b, WHITE, "D3")
        with_infl = estimate_score_fast(b, komi=0, influence=True)
        without = estimate_score_fast(b, komi=0, influence=False)
        self.assertGreater(with_infl, without)


class TestScoreText(unittest.TestCase):
    def test_winner_text(self):
        b = Board(9)
        s = score_area(b, komi=6.5)
        self.assertIn("Белые", s.text())
        s2 = score_area(b, komi=0)
        self.assertIn("Ничья", s2.text())

    def test_detail_mentions_komi(self):
        b = Board(9)
        self.assertIn("6.5", score_area(b, komi=6.5).detail())


if __name__ == "__main__":
    unittest.main()


class TestScoreZones(unittest.TestCase):
    """Разбиение территории на зоны для наглядного разбора."""

    def _prepare(self, size=9):
        b = Board(size)
        b.empties = list(range(size * size))
        b.epos = list(range(size * size))
        return b

    def test_empty_board_is_one_zone(self):
        b = self._prepare()
        zones = score_zones(b)
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0].size, 81)
        self.assertEqual(zones[0].owner, 0)

    def test_sizes_sum_to_empty_points(self):
        b = self._prepare()
        put(b, BLACK, "B1 C1 D1 B2 D2 B3 C3 D3")
        put(b, WHITE, "F7 G7 H7 F8 H8 F9 G9 H9")
        b.empties = [i for i in range(81) if b.stones[i] == 0]
        b.epos = [0] * 81
        for k, i in enumerate(b.empties):
            b.epos[i] = k

        zones = score_zones(b)
        self.assertEqual(sum(z.size for z in zones), b.stones.count(0))

    def test_owners_match_score_area(self):
        b = self._prepare()
        put(b, BLACK, "B1 C1 D1 B2 D2 B3 C3 D3")
        put(b, WHITE, "F7 G7 H7 F8 H8 F9 G9 H9")
        b.empties = [i for i in range(81) if b.stones[i] == 0]
        b.epos = [0] * 81
        for k, i in enumerate(b.empties):
            b.epos[i] = k

        zones = score_zones(b)
        result = score_area(b)
        black_zone = sum(z.size for z in zones if z.owner == BLACK)
        white_zone = sum(z.size for z in zones if z.owner == WHITE)
        neutral = sum(z.size for z in zones if z.owner == 0)
        self.assertEqual(black_zone, result.black_territory)
        self.assertEqual(white_zone, result.white_territory)
        self.assertEqual(neutral, result.neutral)

    def test_center_inside_zone(self):
        b = self._prepare()
        put(b, BLACK, "B1 C1 D1 B2 D2 B3 C3 D3")
        put(b, WHITE, "F7 G7 H7 F8 H8 F9 G9 H9")
        b.empties = [i for i in range(81) if b.stones[i] == 0]
        b.epos = [0] * 81
        for k, i in enumerate(b.empties):
            b.epos[i] = k

        for zone in score_zones(b):
            self.assertIn(zone.center, zone.points,
                          "центр подписи должен лежать внутри зоны")

    def test_center_is_not_a_stone(self):
        b = self._prepare()
        # Зона «кольцо» вокруг камня: центроид попадает на камень.
        for t in ("E4", "E6", "D5", "F5"):
            b.stones[self._at(t)] = BLACK
        b.empties = [i for i in range(81) if b.stones[i] == 0]
        b.epos = [0] * 81
        for k, i in enumerate(b.empties):
            b.epos[i] = k

        for zone in score_zones(b):
            self.assertEqual(b.stones[zone.center], 0,
                             "центр подписи не должен попадать на камень")

    def test_border_stones_counted(self):
        b = self._prepare(5)
        # Кольцо вокруг единственного пункта C3.
        for t in ("C2", "C4", "B3", "D3"):
            b.stones[self._at(t, 5)] = BLACK
        b.empties = [i for i in range(25) if b.stones[i] == 0]
        b.epos = [0] * 25
        for k, i in enumerate(b.empties):
            b.epos[i] = k

        zones = score_zones(b)
        enclosed = [z for z in zones if z.size == 1]
        self.assertTrue(enclosed)
        self.assertEqual(enclosed[0].border_stones, 4)

    def test_dead_stones_are_removed(self):
        b = self._prepare(5)
        put(b, WHITE, "C3")
        put(b, BLACK, "C2 C4 B3 D3")
        b.empties = [i for i in range(25) if b.stones[i] == 0]
        b.epos = [0] * 25
        for k, i in enumerate(b.empties):
            b.epos[i] = k

        without_dead = score_zones(b)
        with_dead = score_zones(b, dead={self._at("C3", 5)})
        self.assertNotEqual([z.size for z in without_dead],
                            [z.size for z in with_dead],
                            "снятие мёртвого камня должно менять зоны")

    def test_all_sizes(self):
        for size in (9, 13, 19):
            b = self._prepare(size)
            zones = score_zones(b)
            self.assertEqual(sum(z.size for z in zones), size * size)

    @staticmethod
    def _at(text, size=9):
        return (size - int(text[1:])) * size + LETTERS.index(text[0])
