#!/usr/bin/env python3
"""Генерация скриншотов для README.

Запуск (нужен только pygame, окно не открывается):

    SDL_VIDEODRIVER=dummy python3 tools/make_screenshots.py

Скриншоты детерминированы: партии играются с фиксированными seed, поэтому
при повторном запуске картинки получаются те же.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

from sergo.board import BLACK, WHITE, LETTERS  # noqa: E402
from sergo.ui.app import App  # noqa: E402

OUT_DIR = os.path.join(ROOT, "docs", "screenshots")


def at(size: int, text: str) -> int:
    return (size - int(text[1:])) * size + LETTERS.index(text[0])


def save(app: App, name: str) -> None:
    path = os.path.join(OUT_DIR, name)
    pygame.image.save(app.screen, path)
    width, height = app.screen.get_size()
    print(f"  {name}  ({width}×{height})")


def fresh_app(size: int = 9, level: str = "normal") -> App:
    app = App(size=size, level=level)
    app.mode = "human_human"
    return app


def place(app: App, moves) -> None:
    """Расставить камни минуя правила, но с правдоподобным журналом.

    moves — список (цвет, "E5") в том порядке, в каком их «сыграли».
    Через game.play не выходит: он требует строгого чередования цветов,
    а для скриншотов нужны позиции с перевесом одного цвета.
    """
    from sergo.game import Move

    board = app.game.board
    size = app.game.size

    for color, text in moves:
        point = at(size, text)
        board.stones[point] = color
        app.game.moves.append(Move(
            number=len(app.game.moves) + 1,
            color=color,
            point=point,
            record=None,
        ))

    board.empties = [i for i in range(board.n) if board.stones[i] == 0]
    board.epos = [0] * board.n
    for k, i in enumerate(board.empties):
        board.epos[i] = k

    if app.game.moves:
        app.game.last_move = app.game.moves[-1].point
        last = app.game.moves[-1].color
        app.game.turn = WHITE if last == BLACK else BLACK


def interleave(black: str, white: str) -> list:
    """Ходы чёрных и белых вперемешку, как в настоящей партии."""
    b = black.split()
    w = white.split()
    result = []
    for i in range(max(len(b), len(w))):
        if i < len(b):
            result.append((BLACK, b[i]))
        if i < len(w):
            result.append((WHITE, w[i]))
    return result


def shot_start() -> None:
    """Стартовый экран 9×9: дебют, у обоих цветов уже есть камни."""
    app = fresh_app(9)
    for text in ("E5", "D4", "F5", "C6"):
        app._play_human(at(9, text))
    app.hover_point = at(9, "G5")
    app._draw()
    save(app, "start-9x9.png")


def shot_settings() -> None:
    """Панель настроек партии."""
    app = fresh_app(9)
    app.show_settings = True
    app._draw()
    save(app, "settings.png")


def play_real_game(app: App, seed: int, max_moves: int = 200) -> None:
    """Сыграть настоящую партию бот-бот, чтобы позиция была правдоподобной.

    Расставленные вручную камни выглядят неестественно, а счёт по ним
    часто показывает «терр. 0 / 0»: стены не соединены, и вся доска
    оказывается одной нейтральной областью. Настоящая партия даёт
    связные группы и реальную территорию.
    """
    from sergo.board import PASS, other
    from sergo.engine import Engine

    black = Engine(app.game.board, komi=app.game.komi, level="normal",
                   time_override=0.05, seed=seed)
    white = Engine(app.game.board, komi=app.game.komi, level="normal",
                   time_override=0.05, seed=seed + 1000)
    color = BLACK
    passes = 0
    for _ in range(max_moves):
        engine = black if color == BLACK else white
        move = engine.choose_move(color)
        if not app.game.play(move, color):
            break
        if move == PASS:
            passes += 1
            if passes >= 2:
                break
        else:
            passes = 0
        color = other(color)


def shot_midgame() -> None:
    """Середина партии на 13×13 с реальным счётом."""
    app = fresh_app(13)
    # Останавливаем партию задолго до заполнения доски: так видны
    # и группы, и территория, а картинка остаётся читаемой.
    play_real_game(app, seed=13, max_moves=60)
    while app.game.phase != "playing" and app.game.moves:
        app.game.undo()
    app._draw()
    save(app, "midgame-13x13.png")


def shot_capture() -> None:
    """Захват группы: снятые камни в середине анимации."""
    app = fresh_app(9)
    # Белая группа E5-F6 в атари, дамэ одно — G5.
    # Ходы чередуются, белые «затыкают» дальний угол заглушками.
    place(app, [
        (BLACK, "E4"),
        (WHITE, "E5"),
        (BLACK, "F4"),
        (WHITE, "F5"),
        (BLACK, "D5"),
        (WHITE, "E6"),
        (BLACK, "D6"),
        (WHITE, "F6"),
        (BLACK, "E7"),
        (WHITE, "J9"),
        (BLACK, "F7"),
        (WHITE, "J8"),
        (BLACK, "G6"),
        (WHITE, "J7"),
    ])
    app._play_human(at(9, "G5"))
    # Останавливаем время в середине затухания, чтобы попал эффект.
    app.effects.capture_duration = 1.0
    time.sleep(0.45)
    app.effects.update()
    app._draw()
    save(app, "capture.png")


def shot_19x19() -> None:
    """Доска 19×19: реальная партия, чтобы счёт был осмысленным."""
    app = fresh_app(19)
    play_real_game(app, seed=23, max_moves=90)
    while app.game.phase != "playing" and app.game.moves:
        app.game.undo()
    app._draw()
    save(app, "board-19x19.png")


def shot_scoring() -> None:
    """Разметка территории."""
    app = fresh_app(9)
    place(app, interleave("B3 C4 D4 E3 F2 C6 D6 B5 B6 A4",
                          "E4 F4 G3 G5 H5 H6 J4 J5 H7 H8"))
    app.game.passes = 1
    app.game.play(-1, app.game.turn)
    app.game.play(-1, app.game.turn)
    app._draw()
    save(app, "scoring.png")


def shot_hint() -> None:
    """Подсказка хода."""
    app = fresh_app(9)
    place(app, interleave("E5 D4 F6", "D5 F5 E6"))
    app.hint_point = at(9, "F4")
    app._note("Подсказка: F4 (78%)", 60)
    app._draw()
    save(app, "hint.png")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    pygame.init()
    pygame.font.init()

    print("Генерация скриншотов:")
    for fn in (shot_start, shot_settings, shot_midgame, shot_capture,
               shot_19x19, shot_scoring, shot_hint):
        fn()

    pygame.quit()
    print(f"\nГотово. Файлы в {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
