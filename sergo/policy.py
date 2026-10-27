"""Эвристики для MCTS: выбор кандидатов и политика розыгрыша.

Чистый случайный розыгрыш на Го играет очень слабо, поэтому здесь
используются простые, но важные правила:
  * не закрашивать собственные глаза;
  * отвечать на атари (спасать свои камни, снимать чужие);
  * снимать висящие группы;
  * на 19×19 не рассматривать всю доску, а только точки рядом с камнями.

Все функции, которые «пробуют» ход, реально ставят камень через
Board.try_play и возвращают точку — повторно играть её не нужно.
"""

from __future__ import annotations

import random

from .board import EMPTY, BLACK, WHITE, PASS, other


def is_self_eye(board, point: int, color: int) -> bool:
    """Похоже ли пустое пересечение на собственный глаз.

    Заполнять свои глаза нельзя — иначе группа теряет жизнь.
    """
    stones = board.stones
    if stones[point] != EMPTY:
        return False
    for q in board.nei[point]:
        if stones[q] != color:
            return False

    enemy = other(color)
    x = point % board.size
    y = point // board.size
    last = board.size - 1
    corner = (x == 0 or x == last) + (y == 0 or y == last)

    bad = 0
    for q in board.diag[point]:
        if stones[q] == enemy:
            bad += 1

    if corner == 2:
        return bad == 0
    if corner == 1:
        return bad <= 1
    return bad <= 1


def _libs(board, point: int) -> list[int]:
    _, libs = board.group_info(point)
    return libs


def _try_capture(board, color: int, group_point: int) -> int | None:
    """Сыграть в единственное дамэ группы, если она в атари."""
    libs = _libs(board, group_point)
    if len(libs) != 1:
        return None
    p = libs[0]
    return p if board.try_play(p, color) else None


def _try_rescue(board, color: int, group_point: int,
                rng: random.Random) -> int | None:
    """Попытаться спасти свою группу в атари: дамэ или рядом."""
    libs = _libs(board, group_point)
    if len(libs) != 1:
        return None

    keep = libs[0]
    grp, _ = board.group_info(group_point)
    options: list[int] = []
    for p in grp:
        for t in board.nei[p]:
            if board.stones[t] == EMPTY and t != keep:
                options.append(t)
    options.append(keep)

    rng.shuffle(options)
    for t in options:
        if is_self_eye(board, t, color):
            continue
        if board.try_play(t, color):
            return t
    return None


def tactical_move(board, color: int, last: int,
                  rng: random.Random) -> int | None:
    """Тактический ход рядом с последним. Камень уже поставлен."""
    if last is None or last == PASS:
        return None

    stones = board.stones
    enemy = other(color)

    # Сканируем только непосредственное окружение последнего хода:
    # полный near2 (~40 точек) слишком дорог для розыгрыша.
    scope = board.nei[last] + board.diag[last]

    # 1. Снять чужую группу в атари.
    doomed: list[int] = []
    for q in scope:
        if stones[q] == enemy and len(_libs(board, q)) == 1:
            doomed.append(q)
    if doomed:
        mv = _try_capture(board, color, doomed[0])
        if mv is not None:
            return mv

    # 2. Спасти свою группу в атари.
    for q in scope:
        if stones[q] == color and len(_libs(board, q)) == 1:
            mv = _try_rescue(board, color, q, rng)
            if mv is not None:
                return mv

    return None


def find_free_capture(board, color: int) -> int | None:
    """Найти безопасный захват: снять самую большую группу в атари.

    Ход оценивается настоящими правилами (play/undo), поэтому ко и
    суперко учитываются. Возвращает точку (ход ещё не сыгран) или None.
    """
    stones = board.stones
    enemy = other(color)
    seen: set[int] = set()
    best = None
    best_size = 0

    for p in board.empties:
        for q in board.nei[p]:
            if stones[q] != enemy or q in seen:
                continue
            grp, libs = board.group_info(q)
            seen.update(grp)
            if len(libs) != 1:
                continue
            point = libs[0]
            rec = board.play(point, color)
            if rec is None:
                continue
            my_libs = board.liberties(point)
            board.undo(rec)
            if my_libs >= 2 and len(grp) > best_size:
                best = point
                best_size = len(grp)

    return best


def play_rollout_move(board, color: int, last: int,
                      rng: random.Random) -> int:
    """Выбрать и сразу сыграть ход розыгрыша. Возвращает точку или PASS."""
    empties = board.empties
    if not empties:
        return PASS

    # Тактика — по вероятности, чтобы не тратить время на каждом ходу.
    if last is not None and last != PASS and rng.random() < 0.42:
        mv = tactical_move(board, color, last, rng)
        if mv is not None:
            return mv

    n = len(empties)
    start = rng.randrange(n)
    for k in range(min(n, 12)):
        p = empties[(start + k) % n]
        if is_self_eye(board, p, color):
            continue
        if board.try_play(p, color):
            return p

    # Быстрый проход по оставшимся (без проверки глаз).
    for _ in range(min(n, 30)):
        p = empties[rng.randrange(n)]
        if board.try_play(p, color):
            return p

    return PASS


def candidate_moves(board, color: int, limit: int = 64,
                    rng: random.Random | None = None) -> list[int]:
    """Кандидаты для дерева поиска.

    Берём только точки вблизи камней — на 19×19 это сокращает перебор
    в разы и заметно усиливает игру при малом бюджете.
    """
    stones = board.stones
    empties = board.empties
    if not empties:
        return [PASS]

    if not any(stones):
        return opening_candidates(board, color)[:limit]

    near: set[int] = set()

    for p in empties:
        for q in board.nei[p]:
            sq = stones[q]
            if sq == EMPTY:
                continue
            near.add(p)
            # Группы в атари — приоритетные точки вокруг них.
            if len(_libs(board, q)) <= 2:
                for r in board.nei[q]:
                    if stones[r] == EMPTY:
                        near.add(r)

    # Точка ко запрещена по правилам — не предлагаем её вовсе.
    ko = board.ko
    result = [p for p in near if p != ko]
    if rng is not None:
        rng.shuffle(result)
    result = result[:limit]
    result.append(PASS)
    return result


def opening_candidates(board, color: int) -> list[int]:
    """Точки для пустой доски (симметричные варианты)."""
    size = board.size
    hoshi = {
        9: [(4, 4), (2, 6), (6, 2), (2, 2), (6, 6)],
        13: [(6, 6), (3, 9), (9, 3), (3, 3), (9, 9)],
        19: [(3, 3), (3, 15), (15, 3), (15, 15), (9, 9), (3, 9), (9, 3)],
    }.get(size, [(size // 2, size // 2)])
    return [y * size + x for x, y in hoshi]
