"""Тесты интерфейса без реального окна (SDL dummy driver).

Проверяется геометрия доски, обработка кликов и отсутствие падений при
отрисовке — то, что чаще всего ломается при правках.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from sergo.board import BLACK, WHITE, LETTERS, format_point  # noqa: E402
from sergo.ui.board_view import BoardView  # noqa: E402
from sergo.ui.widgets import reset_fonts  # noqa: E402


def at(size, text):
    return (size - int(text[1:])) * size + LETTERS.index(text[0])


class TestBoardGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        reset_fonts()
        pygame.quit()

    def test_roundtrip_pixel_point(self):
        for size in (9, 13, 19):
            view = BoardView((0, 0, 800, 800), size)
            for p in range(size * size):
                pixel = view.point_to_pixel(p)
                self.assertEqual(view.pixel_to_point(pixel), p,
                                 f"{size}×{size} {format_point(size, p)}")

    def test_click_far_away_returns_none(self):
        view = BoardView((0, 0, 800, 800), 9)
        self.assertIsNone(view.pixel_to_point((2, 2)))
        self.assertIsNone(view.pixel_to_point((900, 900)))

    def test_geometry_inside_rect(self):
        rect = pygame.Rect(10, 10, 700, 700)
        view = BoardView(rect, 19)
        x0, y0 = view.origin
        x1, y1 = view.point_to_pixel(18 * 19 + 18)
        self.assertGreaterEqual(x0, rect.x)
        self.assertGreaterEqual(y0, rect.y)
        self.assertLessEqual(x1, rect.right)
        self.assertLessEqual(y1, rect.bottom)

    def test_coord_labels_do_not_touch_stones(self):
        """Подписи координат должны иметь зазор до камней у края."""
        from sergo.ui.widgets import font

        for size in (9, 13, 19):
            view = BoardView((0, 0, 790, 800), size)
            font_size = max(9, int(view.cell * 0.36))
            label_h = font(font_size).get_height()
            stone_r = view.cell * 0.46

            # Центр подписи — margin//2 от линии сетки.
            gap = view.margin / 2 - stone_r - label_h / 2
            self.assertGreaterEqual(
                gap, 4.0,
                f"{size}×{size}: подпись почти касается камня (зазор {gap:.1f} px)")

    def test_resize_keeps_points_valid(self):
        view = BoardView((0, 0, 800, 800), 13)
        view.resize((0, 0, 500, 500))
        for p in (0, 30, 84, 168):
            self.assertEqual(view.pixel_to_point(view.point_to_pixel(p)), p)


class TestAppSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        reset_fonts()
        pygame.quit()

    def test_draw_all_phases(self):
        from sergo.ui.app import App

        app = App(size=9)
        app._draw()

        app.mode = "human_human"
        for text in ("E5", "D4", "F5", "D5"):
            app._play_human(at(9, text))
        app._draw()

        app._play_human(-1)
        app._play_human(-1)
        app._draw()
        self.assertEqual(app.game.phase, "scoring")

        app.game.finish_scoring()
        app._draw()

    def test_move_log_has_no_winrate(self):
        """В журнале ходов не должно быть процентов."""
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        for text in ("E5", "D4", "F5", "D5"):
            app._play_human(at(9, text))
        # Проверяем через модуль отрисовки: процентов в тексте нет.
        app._draw()
        # Проценты приходили из Move.analysis; теперь их не печатают.
        import inspect
        from sergo.ui import app as app_module
        src = inspect.getsource(app_module.App._draw_move_log)
        self.assertNotIn("%", src)

    def test_balance_bar_shows_real_score(self):
        """Полоса показывает настоящий счёт, а не прогноз."""
        from sergo.ui.app import App, _black_share
        from sergo.scoring import score_area

        app = App(size=9)
        app.mode = "human_human"
        for text in ("E5", "D4", "F5"):
            app._play_human(at(9, text))
        app._draw()

        result = score_area(app.game.board, app.game.komi)
        # Доля чёрных = их очки / сумма очков.
        expected = max(0.02, min(0.98,
                                 result.black / (result.black + result.white)))
        self.assertAlmostEqual(_black_share(result.black, result.white),
                               expected)

    def test_share_is_balanced_when_equal(self):
        from sergo.ui.app import _black_share

        self.assertAlmostEqual(_black_share(50, 50), 0.5)
        self.assertGreater(_black_share(60, 40), 0.5)
        self.assertLess(_black_share(40, 60), 0.5)

    def test_share_clamped(self):
        from sergo.ui.app import _black_share

        self.assertLessEqual(_black_share(1000, 0), 0.98)
        self.assertGreaterEqual(_black_share(0, 1000), 0.02)
        # Нулевой счёт не должен давать деления на ноль.
        self.assertAlmostEqual(_black_share(0, 0), 0.5)

    def test_score_undefined_until_both_colors_play(self):
        """Пока камни только одного цвета, счёт не показываем."""
        import inspect

        from sergo.ui import app as app_module

        # Логика внутри _draw_balance: known = оба цвета на доске.
        src = inspect.getsource(app_module.App._draw_balance)
        self.assertIn("black_stones > 0 and white_stones > 0", src)
        self.assertIn("позиция не определена", src)

    def test_breakdown_toggles_by_click_on_score_block(self):
        """Клик по блоку «Счёт сейчас» включает и выключает разбор."""
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        app._play_human(at(9, "D4"))
        app._draw()

        self.assertFalse(app.show_breakdown)
        self.assertIsNotNone(app._score_rect)

        center = app._score_rect.center
        app._handle_click(center)
        self.assertTrue(app.show_breakdown, "клик не включил разбор")

        app._draw()
        app._handle_click(app._score_rect.center)
        self.assertFalse(app.show_breakdown, "повторный клик не выключил")

    def test_breakdown_toggles_by_key(self):
        from sergo.ui.app import App

        app = App(size=9)
        self.assertFalse(app.show_breakdown)
        app.toggle_breakdown()
        self.assertTrue(app.show_breakdown)
        app.toggle_breakdown()
        self.assertFalse(app.show_breakdown)

    def test_breakdown_available_during_ai_turn(self):
        """Разбор доступен, пока думает ИИ."""
        from sergo.ui.app import App

        app = App(size=9)
        app.ai_thinking = True
        app.toggle_breakdown()
        self.assertTrue(app.show_breakdown)
        app._draw()

    def test_zones_cache_invalidated_by_move(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        first = app.zones()
        app._play_human(at(9, "D4"))
        second = app.zones()
        self.assertIsNot(first, second, "кэш не сбросился после хода")

    def test_zones_cache_reused(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        self.assertIs(app.zones(), app.zones(), "кэш не используется")

    def test_draw_with_breakdown_all_sizes(self):
        from sergo.ui.app import App

        for size in (9, 13, 19):
            app = App(size=size)
            app.mode = "human_human"
            app.show_breakdown = True
            app._play_human(app.game.board.n // 2)
            app._draw()
            app.game.new_game()
            app._draw()

    def test_draw_without_score_known(self):
        """Один камень на доске: разбор рисуется, но пишет «нечего»."""
        from sergo.ui.app import App

        app = App(size=9)
        app.show_breakdown = True
        app._play_human(at(9, "E5"))
        app._draw()

    def test_breakdown_does_not_draw_strip(self):
        """В режиме разбора обычная полоса не рисуется — нет наложения."""
        import inspect

        from sergo.ui import app as app_module

        src = inspect.getsource(app_module.App._draw_balance)
        self.assertIn("if self.show_breakdown:", src)

    def test_zones_have_rounded_corners(self):
        """Внешний угол зоны должен быть скруглён, центр — закрашен."""
        import pygame as pg
        from sergo.scoring import Zone
        from sergo.ui.app import App, WINDOW_W, WINDOW_H

        app = App(size=9)
        view = app.board_view
        radius = max(2, min(14, int(view.cell * 0.18)))

        # Одна зона из двух горизонтально соседних клеток.
        point = at(9, "E5")
        zone = Zone(owner=1, points=[point, point + 1], center=point)

        surf = pg.Surface((WINDOW_W, WINDOW_H), pg.SRCALPHA)
        # Пустая прозрачная поверхность: видно только то, что рисует зона.
        view._draw_zones(surf, [zone])

        left, top = view.point_to_pixel(point)
        left -= view.cell / 2
        top -= view.cell / 2

        def alpha_at(dx, dy):
            return surf.get_at((int(left + dx), int(top + dy)))[3]

        # Самый угол — прозрачен (действует скругление).
        self.assertEqual(alpha_at(1, 1), 0, "угол зоны не скруглён")
        # Центр клетки — закрашен.
        self.assertGreater(alpha_at(view.cell / 2, view.cell / 2), 0,
                           "центр зоны не закрашен")

    def test_zone_bridge_closes_seam(self):
        """Стык двух клеток одной зоны не должен давать выемку."""
        import pygame as pg
        from sergo.scoring import Zone
        from sergo.ui.app import App, WINDOW_W, WINDOW_H

        app = App(size=9)
        view = app.board_view
        point = at(9, "E5")
        zone = Zone(owner=1, points=[point, point + 1], center=point)

        surf = pg.Surface((WINDOW_W, WINDOW_H), pg.SRCALPHA)
        view._draw_zones(surf, [zone])

        x0, y0 = view.point_to_pixel(point)
        # Граница между клетками — ровно посередине, чуть выше/ниже центра.
        seam_x = int(x0 + view.cell / 2)
        for dy in (-6, 0, 6):
            y = int(y0 + dy)
            self.assertGreater(surf.get_at((seam_x, y))[3], 0,
                               f"на стыке клеток выемка (dy={dy})")

    def test_zone_number_plate_rounded(self):
        """Плашка под числом тоже со скруглёнными углами."""
        import pygame as pg
        from sergo.scoring import Zone
        from sergo.ui.app import App, WINDOW_W, WINDOW_H

        app = App(size=9)
        view = app.board_view
        point = at(9, "E5")
        # Зоны меньше 3 пунктов не подписываются, поэтому берём 3.
        zone = Zone(owner=1, points=[point, point + 1, point + 2],
                    center=point)

        surf = pg.Surface((WINDOW_W, WINDOW_H), pg.SRCALPHA)
        view._draw_zone_numbers(surf, [zone])

        px, py = view.point_to_pixel(point)
        font_size = max(11, int(view.cell * 0.42))
        from sergo.ui.widgets import font
        text_w = font(font_size, bold=True).size(str(zone.size))[0]
        plate_w = text_w + 8
        plate_h = font(font_size, bold=True).get_height() + 3

        corner_x = int(px - plate_w // 2 + 1)
        corner_y = int(py - plate_h // 2 + 1)
        self.assertEqual(surf.get_at((corner_x, corner_y))[3], 0,
                         "угол плашки не скруглён")
        # Полоса плашки чуть выше текста — там только фон, без цифры.
        self.assertGreater(
            surf.get_at((px, py - plate_h // 2 + 1))[3], 0,
            "плашка не нарисована")

    def test_draw_zones_all_sizes(self):
        """Скругления не должны падать на любом размере доски."""
        import pygame as pg
        from sergo.scoring import Zone
        from sergo.ui.app import App, WINDOW_W, WINDOW_H

        for size in (9, 13, 19):
            app = App(size=size)
            view = app.board_view
            point = app.game.board.n // 2
            zone = Zone(owner=1, points=[point], center=point)
            surf = pg.Surface((WINDOW_W, WINDOW_H), pg.SRCALPHA)
            view._draw_zones(surf, [zone])

    def test_settings_panel(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.show_settings = True
        app._draw()
        app.size_group.set_value("19")
        app._draw()

    def test_click_plays_stone(self):
        from sergo.ui.app import App

        app = App(size=9)
        app._handle_click(app.board_view.point_to_pixel(at(9, "E5")))
        self.assertEqual(len(app.game.moves), 1)
        self.assertEqual(app.game.turn, WHITE)

    def test_illegal_move_note_cleared_after_valid_move(self):
        """Сообщение об ошибке не должно висеть после удачного хода."""
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        self.assertEqual(app.status_note, "")

        app._play_human(at(9, "E5"))          # занятая точка
        self.assertEqual(app.status_note, "Так ходить нельзя")
        self.assertTrue(app._note_alive())

        app._play_human(at(9, "D4"))          # корректный ход
        self.assertEqual(app.status_note, "")
        self.assertFalse(app._note_alive())

    def test_note_expires(self):
        import time
        from sergo.ui.app import App

        app = App(size=9)
        app._note("проверка", 0.15)
        self.assertTrue(app._note_alive())
        time.sleep(0.25)
        self.assertFalse(app._note_alive())

    def test_hint_available_on_human_turn(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app.engine.time_override = 0.3
        app._play_human(at(9, "E5"))
        app._request_hint()
        deadline = 5.0
        import time
        start = time.monotonic()
        while time.monotonic() - start < deadline:
            app._poll_hint()
            if app.hint_point is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(app.hint_point)
        self.assertIn("Подсказка", app.status_note)

    def test_hint_refused_for_ai_turn(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        app.mode = "human_ai"
        app.human_color = BLACK
        app._request_hint()
        self.assertIsNone(app.hint_point)
        self.assertIn("вашем ходу", app.status_note)

    def test_click_ignored_when_ai_turn(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "ai_ai"
        app._handle_click(app.board_view.point_to_pixel(at(9, "E5")))
        self.assertEqual(len(app.game.moves), 0)


if __name__ == "__main__":
    unittest.main()
