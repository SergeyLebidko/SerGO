"""Zobrist-хеши позиций.

Хеш зависит только от расстановки камней (позиционное суперко):
пас и смена очереди хода его не меняют.
"""

from __future__ import annotations

import random

# Кэш таблиц по размеру доски: (таблица чёрных, таблица белых)
_CACHE: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}


def tables(size: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Вернуть (z_black, z_white) для доски size×size."""
    cached = _CACHE.get(size)
    if cached is not None:
        return cached

    rng = random.Random(0x5E4600 + size * 7919)
    n = size * size
    black = [0] * n
    white = [0] * n
    for i in range(n):
        black[i] = rng.getrandbits(64)
        white[i] = rng.getrandbits(64)

    result = (tuple(black), tuple(white))
    _CACHE[size] = result
    return result
