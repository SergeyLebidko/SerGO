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

    def test_balance_bar_drawn(self):
        from sergo.ui.app import App, _black_share

        app = App(size=9)
        app._draw()
        # Шкала: ровно -> 50%, коми -> чуть меньше 50%.
        self.assertAlmostEqual(_black_share(0, 9, 81), 0.5)
        self.assertLess(_black_share(-6.5, 9, 81), 0.5)
        self.assertGreater(_black_share(20, 9, 81), 0.5)
        # Ограничения шкалы.
        self.assertLessEqual(_black_share(1000, 9, 81), 0.98)
        self.assertGreaterEqual(_black_share(-1000, 9, 81), 0.02)

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
