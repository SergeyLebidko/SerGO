"""Тесты параметров командной строки.

Проверяется то, что обещает README: значения по умолчанию, допустимые
варианты и передача параметров дальше в приложение.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

START_PY = os.path.join(ROOT, "start.py")


def run_start(args, stdin_text=None, timeout=30):
    """Запустить start.py с аргументами и вернуть (код, stdout, stderr)."""
    env = {**os.environ, "SDL_VIDEODRIVER": "dummy",
           "SDL_AUDIODRIVER": "dummy"}
    proc = subprocess.run(
        [sys.executable, START_PY] + args,
        input=stdin_text if stdin_text is not None else "",
        capture_output=True, text=True, timeout=timeout, env=env, cwd=ROOT,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestHelp(unittest.TestCase):
    def test_help_lists_all_options(self):
        code, out, err = run_start(["--help"])
        self.assertEqual(code, 0)
        text = out + err
        for option in ("--size", "--level", "--cli"):
            self.assertIn(option, text)

    def test_help_shows_defaults(self):
        code, out, err = run_start(["--help"])
        text = out + err
        self.assertIn("по умолчанию 9", text)
        self.assertIn("normal", text)


class TestInvalidValues(unittest.TestCase):
    def test_bad_size_rejected(self):
        code, out, err = run_start(["--size", "11"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_bad_level_rejected(self):
        code, out, err = run_start(["--level", "impossible"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_non_numeric_size_rejected(self):
        code, out, err = run_start(["--size", "abc"])
        self.assertEqual(code, 2)


class TestCliMode(unittest.TestCase):
    """Терминальный режим работает без графики."""

    def test_cli_9x9(self):
        code, out, err = run_start(["--cli"], stdin_text="сдаться\n")
        self.assertEqual(code, 0, err)
        self.assertIn("терминальный режим", out)
        self.assertIn("J", out)      # буква J есть только на 9×9
        self.assertNotIn("T", out)   # на 9×9 её нет

    def test_cli_13x13_board_size(self):
        code, out, err = run_start(["--cli", "--size", "13"],
                                   stdin_text="сдаться\n")
        self.assertEqual(code, 0, err)
        self.assertIn("N", out)      # последняя буква 13×13

    def test_cli_19x19_board_size(self):
        code, out, err = run_start(["--cli", "--size", "19"],
                                   stdin_text="сдаться\n")
        self.assertEqual(code, 0, err)
        self.assertIn("T", out)      # последняя буква 19×19

    def test_cli_accepts_named_moves(self):
        code, out, err = run_start(
            ["--cli"], stdin_text="E5\nD4\nсдаться\n")
        self.assertEqual(code, 0, err)
        self.assertIn("Вы: E5", out)

    def test_cli_rejects_bad_coordinate(self):
        code, out, err = run_start(
            ["--cli"], stdin_text="ZZZ\nсдаться\n")
        self.assertEqual(code, 0, err)
        self.assertIn("Не понял координату", out)


class TestArgumentWiring(unittest.TestCase):
    """--level должен доходить до движка, а не только парситься."""

    def test_level_reaches_engine_in_gui(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        pygame.init()
        try:
            from sergo.ui.app import App

            for level, expected in (("easy", 1.0), ("normal", 3.0),
                                    ("hard", 6.0)):
                app = App(size=9, level=level)
                self.assertEqual(app.engine.level, level)
                self.assertEqual(app.engine.budget(), expected,
                                 f"{level}: неверный бюджет времени")
        finally:
            from sergo.ui.widgets import reset_fonts
            reset_fonts()
            pygame.quit()

    def test_run_ui_accepts_level(self):
        import inspect

        from sergo.ui import main as run_ui

        params = inspect.signature(run_ui).parameters
        self.assertIn("size", params)
        self.assertIn("level", params)

    def test_start_passes_level_to_ui(self):
        """start.py передаёт --level в run_ui, а не теряет его."""
        with open(START_PY, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("run_ui(size=args.size, level=args.level)", source)


if __name__ == "__main__":
    unittest.main()
