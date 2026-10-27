"""Тесты анимаций доски."""

import os
import sys
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from sergo.board import BLACK, WHITE, LETTERS  # noqa: E402
from sergo.ui.effects import Effects, _distance  # noqa: E402
from sergo.ui.widgets import reset_fonts  # noqa: E402


def at(size, text):
    return (size - int(text[1:])) * size + LETTERS.index(text[0])


def _alive(effects) -> bool:
    """Есть ли ещё незавершённые эффекты.

    Проверяем по фактическому времени, а не состоянием списка: update()
    вызывается отдельно, и между вызовами список ещё не очищен.
    """
    now = time.monotonic()
    for item in effects._captures:
        if now < item.start + item.delay + effects.capture_duration:
            return True
    for item in effects._places:
        if now < item.start + effects.place_duration:
            return True
    return False


def _wait_until(predicate, timeout: float = 2.0, step: float = 0.01) -> None:
    """Ждать условия с запасом по времени.

    Фиксированный sleep под нагрузкой может не дождаться, и тест
    начнёт «мигать». Здесь ждём до выполнения или до таймаута.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(step)


class TestDistance(unittest.TestCase):
    def test_horizontal(self):
        self.assertAlmostEqual(_distance(at(9, "A5"), at(9, "C5"), 9), 2.0)

    def test_vertical(self):
        self.assertAlmostEqual(_distance(at(9, "C5"), at(9, "C8"), 9), 3.0)

    def test_diagonal(self):
        self.assertAlmostEqual(_distance(at(9, "A1"), at(9, "B2"), 9),
                               2 ** 0.5)

    def test_same_point(self):
        self.assertEqual(_distance(40, 40, 9), 0.0)

    def test_does_not_assume_board_width(self):
        # Старая реализация делила на 100 и ломалась на 9×9.
        self.assertAlmostEqual(_distance(at(9, "A9"), at(9, "J1"), 9),
                               (8 ** 2 + 8 ** 2) ** 0.5)


class TestEffects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        reset_fonts()
        pygame.quit()

    def test_empty_is_idle(self):
        e = Effects()
        self.assertFalse(e.busy())
        self.assertFalse(e.hides(0))

    def test_capture_expires(self):
        e = Effects(capture_duration=0.05)
        e.add_capture([40], WHITE, origin=40, radius=18, size=9)
        self.assertTrue(e.busy())
        _wait_until(lambda: not _alive(e), timeout=2.0)
        e.update()
        self.assertFalse(e.busy())

    def test_place_expires(self):
        e = Effects(place_duration=0.05)
        e.add_place(40, BLACK, radius=18)
        self.assertTrue(e.busy())
        _wait_until(lambda: not _alive(e), timeout=2.0)
        e.update()
        self.assertFalse(e.busy())

    def test_hides_only_active_points(self):
        e = Effects()
        e.add_capture([40, 41], WHITE, origin=40, radius=18, size=9)
        self.assertTrue(e.hides(40))
        self.assertTrue(e.hides(41))
        self.assertFalse(e.hides(42))

    def test_clear_removes_everything(self):
        e = Effects()
        e.add_capture([40], WHITE, radius=18, size=9)
        e.add_place(40, BLACK, radius=18)
        e.clear()
        self.assertFalse(e.busy())

    def test_add_capture_ignores_empty_list(self):
        e = Effects()
        e.add_capture([], WHITE, radius=18, size=9)
        self.assertFalse(e.busy())

    def test_wave_delays_grow_with_distance(self):
        e = Effects()
        origin = at(9, "E5")
        e.add_capture([origin, at(9, "F5"), at(9, "G5")], WHITE,
                      origin=origin, radius=18, size=9)
        delays = [it.delay for it in e._captures]
        self.assertEqual(delays[0], 0.0)
        self.assertLess(delays[0], delays[1])
        self.assertLess(delays[1], delays[2])

    def test_wave_delay_is_capped(self):
        e = Effects()
        e.add_capture([at(9, "A1")], WHITE, origin=at(9, "J9"),
                      radius=18, size=9)
        self.assertLessEqual(e._captures[0].delay, 0.15)

    def test_draw_does_not_crash_on_empty(self):
        e = Effects()
        screen = pygame.Surface((400, 400))
        from sergo.ui.board_view import BoardView
        view = BoardView((0, 0, 400, 400), 9)
        e.draw(screen, view, None)

    def test_draw_does_not_crash_on_occupied_point(self):
        """Эффект не должен ронять отрисовку, если точка уже занята."""
        e = Effects()
        e.add_capture([40], WHITE, radius=18, size=9)
        screen = pygame.Surface((400, 400))
        from sergo.ui.board_view import BoardView
        view = BoardView((0, 0, 400, 400), 9)
        e.draw(screen, view, None)

    def test_draw_on_tiny_board(self):
        """19×19 — маленький радиус камня, не должно быть падений."""
        e = Effects(capture_duration=5.0)
        e.add_capture([0, 180], WHITE, origin=0, radius=3, size=19)
        e.add_place(90, BLACK, radius=3)
        screen = pygame.Surface((400, 400))
        from sergo.ui.board_view import BoardView
        view = BoardView((0, 0, 400, 400), 19)
        e.draw(screen, view, None)


class TestAppEffects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        reset_fonts()
        pygame.quit()

    def _capture_position(self, app):
        """Позиция, где белый камень в атари и чёрные его забирают."""
        b = app.game.board
        for t in ("E4", "E6", "F4", "F6", "G5"):
            b.stones[at(9, t)] = BLACK
        b.stones[at(9, "F5")] = WHITE
        b.empties = [i for i in range(81) if b.stones[i] == 0]
        b.epos = [0] * 81
        for k, i in enumerate(b.empties):
            b.epos[i] = k

    def test_capture_creates_effect(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        self._capture_position(app)
        app._play_human(at(9, "E5"))
        self.assertEqual(len(app.game.moves[-1].captures), 1)
        self.assertTrue(app.effects.busy())
        self.assertTrue(app.effects.hides(at(9, "F5")))

    def test_place_always_creates_effect(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        self.assertTrue(app.effects.hides(at(9, "E5")))

    def test_undo_clears_effects(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        self._capture_position(app)
        app._play_human(at(9, "E5"))
        self.assertTrue(app.effects.busy())
        app._undo()
        self.assertFalse(app.effects.busy())

    def test_new_game_clears_effects(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.mode = "human_human"
        app._play_human(at(9, "E5"))
        app._action("new")
        self.assertFalse(app.effects.busy())

    def test_ai_move_waits_for_effect(self):
        """Ответ ИИ не должен накладываться на текущую анимацию."""
        from sergo.ui.app import App

        app = App(size=9)
        app.effects.capture_duration = 5.0
        app.effects.add_capture([40], WHITE, radius=18, size=9)
        app.pending_move = (app.ai_token, 41, 0.5, 10)
        app.pending_since = time.monotonic()
        before = len(app.game.moves)
        app._poll_ai()
        self.assertEqual(len(app.game.moves), before,
                         "ход применился во время анимации")
        self.assertIsNotNone(app.pending_move)

    def test_ai_move_applied_after_effect(self):
        from sergo.ui.app import App

        app = App(size=9)
        app.effects.capture_duration = 0.05
        app.effects.add_capture([40], WHITE, radius=18, size=9)
        app.pending_move = (app.ai_token, 41, 0.5, 10)
        app.pending_since = time.monotonic()
        _wait_until(lambda: not _alive(app.effects), timeout=2.0)
        app.effects.update()
        app._poll_ai()
        self.assertEqual(len(app.game.moves), 1)
        self.assertIsNone(app.pending_move)

    def test_ai_move_applied_after_timeout(self):
        """Если эффект «завис», ход всё равно применяется."""
        from sergo.ui.app import App

        app = App(size=9)
        app.effects.capture_duration = 100.0
        app.effects.add_capture([40], WHITE, radius=18, size=9)
        app.pending_move = (app.ai_token, 41, 0.5, 10)
        app.pending_since = time.monotonic() - app.MAX_EFFECT_WAIT - 0.1
        app._poll_ai()
        self.assertEqual(len(app.game.moves), 1)


if __name__ == "__main__":
    unittest.main()
