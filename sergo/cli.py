"""Терминальный режим: полезен для отладки без графики."""

from __future__ import annotations

import random

from .board import Board, BLACK, WHITE, PASS, other, parse_point, format_point
from .engine import Engine


def render(board: Board) -> str:
    """Доска в текстовом виде."""
    letters = "ABCDEFGHJKLMNOPQRSTUVWXYZ"[:board.size]
    lines = []
    header = "   " + " ".join(letters)
    lines.append(header)
    for y in range(board.size):
        row = []
        for x in range(board.size):
            v = board.stones[y * board.size + x]
            row.append("." if v == 0 else ("X" if v == BLACK else "O"))
        lines.append(f"{board.size - y:2d} " + " ".join(row))
    lines.append(header)
    return "\n".join(lines)


def run_cli(size: int = 9, level: str = "normal") -> int:
    """Партия человек против ИИ в терминале."""
    board = Board(size)
    komi = 6.5
    engine = Engine(board, level=level, komi=komi,
                    seed=random.randrange(1 << 30))
    color = BLACK
    human = BLACK
    passes = 0

    print("SerGO — терминальный режим")
    print("Вводите координаты (например D4), 'пас' или 'сдаться'.")
    print()

    while True:
        print()
        print(render(board))
        print()

        if color == human:
            try:
                text = input("Ваш ход: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nДо встречи.")
                return 0
            if text.lower() in ("сдаться", "resign", "quit", "выход"):
                print("Вы сдались.")
                return 0
            point = parse_point(size, text)
            if point is None:
                print("Не понял координату. Пример: D4")
                continue
            rec = board.play(point, color)
            if rec is None:
                print("Так ходить нельзя.")
                continue
            print(f"Вы: {format_point(size, point)}")
        else:
            print("ИИ думает…")
            point = engine.choose_move(color)
            rec = board.play(point, color)
            if rec is None:
                print("ИИ не смог найти ход, пас.")
                point = PASS
                board.play(PASS, color)
            print(f"ИИ: {format_point(size, point)}")

        if point == PASS:
            passes += 1
            if passes >= 2:
                break
        else:
            passes = 0
        color = other(color)

    from .scoring import score_area
    result = score_area(board, komi=komi)
    print()
    print(render(board))
    print()
    print(result.detail())
    print(result.text())
    return 0
