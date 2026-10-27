"""Движок правил Го.

Доска хранится плоским массивом bytearray: 0 — пусто, 1 — чёрный, 2 — белый.
Индекс точки: y * size + x, где (0, 0) — верхний левый угол.

Поддерживается:
  * снятие групп без дамэ;
  * запрет самоубийства (кроме захвата);
  * простой ко;
  * позиционное суперко по Zobrist-хешу.
"""

from __future__ import annotations

from .zobrist import tables

EMPTY = 0
BLACK = 1
WHITE = 2

# Ход-пас в коде обозначается -1, чтобы не смешивать с индексом точки.
PASS = -1

LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"

_GEO_CACHE: dict[int, tuple] = {}


def other(color: int) -> int:
    return WHITE if color == BLACK else BLACK


def format_point(size: int, point: int) -> str:
    """Человекочитаемая координата: 'D4', 'Q16', 'пас'."""
    if point == PASS:
        return "пас"
    x = point % size
    y = point // size
    return f"{LETTERS[x]}{size - y}"


def parse_point(size: int, text: str) -> int | None:
    """Разбор координаты вида 'D4'. Возвращает None, если не получилось."""
    text = text.strip().upper()
    if text in ("PASS", "ПАС"):
        return PASS
    if len(text) < 2:
        return None
    letter = text[0]
    if letter not in LETTERS:
        return None
    x = LETTERS.index(letter)
    try:
        number = int(text[1:])
    except ValueError:
        return None
    y = size - number
    if not (0 <= x < size and 0 <= y < size):
        return None
    return y * size + x


def _geometry(size: int) -> tuple:
    """Соседи, диагонали и точки «рядом» (для эвристик)."""
    cached = _GEO_CACHE.get(size)
    if cached is not None:
        return cached

    n = size * size
    nei: list[tuple[int, ...]] = [()] * n
    diag: list[tuple[int, ...]] = [()] * n
    near2: list[tuple[int, ...]] = [()] * n

    for y in range(size):
        for x in range(size):
            i = y * size + x

            lst = []
            if x > 0:
                lst.append(i - 1)
            if x < size - 1:
                lst.append(i + 1)
            if y > 0:
                lst.append(i - size)
            if y < size - 1:
                lst.append(i + size)
            nei[i] = tuple(lst)

            dl = []
            for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < size and 0 <= ny < size:
                    dl.append(ny * size + nx)
            diag[i] = tuple(dl)

            nl = []
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    if abs(dx) + abs(dy) > 3:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size and 0 <= ny < size:
                        nl.append(ny * size + nx)
            near2[i] = tuple(nl)

    result = (tuple(nei), tuple(diag), tuple(near2))
    _GEO_CACHE[size] = result
    return result


class MoveRecord:
    """Всё, что нужно, чтобы отменить ход."""

    __slots__ = ("point", "color", "captured", "prev_ko", "prev_hash", "prev_caps", "tracked")

    def __init__(self, point, color, captured, prev_ko, prev_hash, prev_caps, tracked):
        self.point = point
        self.color = color
        self.captured = captured
        self.prev_ko = prev_ko
        self.prev_hash = prev_hash
        self.prev_caps = prev_caps
        self.tracked = tracked


class Board:
    """Позиция на доске и правила ходов."""

    __slots__ = (
        "size", "n", "stones", "nei", "diag", "near2",
        "caps", "ko", "hash", "superko", "history", "hash_set",
        "empties", "epos", "_mark", "_libmark", "_stamp", "_z",
    )

    def __init__(self, size: int = 9):
        if size < 2:
            raise ValueError("Размер доски должен быть не меньше 2")
        self.size = size
        self.n = size * size
        self.stones = bytearray(self.n)
        self.nei, self.diag, self.near2 = _geometry(size)
        self.caps = [0, 0, 0]          # caps[BLACK] — сколько белых камней съедено
        self.ko = -1
        self.hash = 0
        self.superko = True
        self.history = [0]
        self.hash_set = {0}
        self.empties = list(range(self.n))
        self.epos = list(range(self.n))
        self._mark = [0] * self.n
        self._libmark = [0] * self.n
        self._stamp = 0
        self._z = tables(size)

    # ------------------------------------------------------------------ утилиты

    def _remove_empty(self, idx: int) -> None:
        empties = self.empties
        epos = self.epos
        k = epos[idx]
        last = empties[-1]
        empties[k] = last
        epos[last] = k
        empties.pop()

    def _add_empty(self, idx: int) -> None:
        self.epos[idx] = len(self.empties)
        self.empties.append(idx)

    def _group(self, idx: int) -> tuple[list[int], list[int]]:
        """Камни группы и её дамэ (списком)."""
        stones = self.stones
        color = stones[idx]
        if color == EMPTY:
            return [], []

        mark = self._mark
        libmark = self._libmark
        self._stamp += 1
        stamp = self._stamp
        nei = self.nei

        stack = [idx]
        mark[idx] = stamp
        group: list[int] = []
        libs: list[int] = []

        while stack:
            p = stack.pop()
            group.append(p)
            for q in nei[p]:
                sq = stones[q]
                if sq == EMPTY:
                    if libmark[q] != stamp:
                        libmark[q] = stamp
                        libs.append(q)
                elif sq == color and mark[q] != stamp:
                    mark[q] = stamp
                    stack.append(q)

        return group, libs

    def group_info(self, point: int) -> tuple[list[int], list[int]]:
        """Публичный доступ к группе (для эвристик и интерфейса)."""
        return self._group(point)

    def liberties(self, point: int) -> int:
        if self.stones[point] == EMPTY:
            return 0
        _, libs = self._group(point)
        return len(libs)

    # ------------------------------------------------------------------ ходы

    def play(self, point: int, color: int, record: bool = True):
        """Поставить камень.

        Возвращает MoveRecord (или True при record=False), либо None,
        если ход нелегален. При нелегальном ходе доска не меняется.
        """
        stones = self.stones

        if point == PASS:
            if record:
                rec = MoveRecord(PASS, color, (), self.ko, self.hash,
                                 tuple(self.caps), False)
            else:
                rec = True
            self.ko = -1
            return rec

        if point < 0 or point >= self.n:
            return None
        if stones[point] != EMPTY or point == self.ko:
            return None

        old_ko = self.ko
        old_hash = self.hash
        old_caps = tuple(self.caps)

        zb, zw = self._z
        z_self = zb if color == BLACK else zw
        z_enemy = zw if color == BLACK else zb

        stones[point] = color
        self._remove_empty(point)
        h = old_hash ^ z_self[point]
        enemy = other(color)
        captured: list[int] = []

        for q in self.nei[point]:
            if stones[q] != enemy:
                continue
            grp, libs = self._group(q)
            if libs:
                continue
            for g in grp:
                stones[g] = EMPTY
                self._add_empty(g)
                h ^= z_enemy[g]
                captured.append(g)

        if captured:
            self.caps[color] += len(captured)

        grp, libs = self._group(point)

        # Самоубийство: своих дамэ нет, и никто не снят.
        if not libs:
            for g in captured:
                stones[g] = enemy
                self._remove_empty(g)
            stones[point] = EMPTY
            self._add_empty(point)
            if captured:
                self.caps[color] -= len(captured)
            return None

        # Позиционное суперко.
        if self.superko and h in self.hash_set:
            for g in captured:
                stones[g] = enemy
                self._remove_empty(g)
            stones[point] = EMPTY
            self._add_empty(point)
            if captured:
                self.caps[color] -= len(captured)
            return None

        ko_point = -1
        # Простой ко: снят ровно один камень, а поставивший сам оказался
        # одиночным камнем с одним дамэ.
        if len(captured) == 1 and len(grp) == 1 and len(libs) == 1:
            ko_point = captured[0]

        tracked = False
        if self.superko:
            self.history.append(h)
            self.hash_set.add(h)
            tracked = True

        self.hash = h
        self.ko = ko_point

        if record:
            return MoveRecord(point, color, tuple(captured), old_ko, old_hash,
                              old_caps, tracked)
        return True

    def undo(self, rec) -> bool:
        """Откатить ход, записанный в rec."""
        if rec is None or rec is True:
            return False

        if rec.point == PASS:
            self.ko = rec.prev_ko
            self.hash = rec.prev_hash
            self.caps = list(rec.prev_caps)
            return True

        cur_hash = self.hash
        stones = self.stones
        stones[rec.point] = EMPTY
        self._add_empty(rec.point)

        enemy = other(rec.color)
        for g in rec.captured:
            stones[g] = enemy
            self._remove_empty(g)

        self.caps = list(rec.prev_caps)
        self.ko = rec.prev_ko
        self.hash = rec.prev_hash

        if rec.tracked:
            self.history.pop()
            self.hash_set.discard(cur_hash)

        return True

    def legal_moves(self, color: int, include_pass: bool = False) -> list[int]:
        """Все легальные ходы для указанного цвета."""
        result = [p for p in self.empties if self.is_legal(p, color)]
        if include_pass:
            result.append(PASS)
        return result

    def is_legal(self, point: int, color: int) -> bool:
        """Проверка легальности без побочных эффектов."""
        rec = self.play(point, color, record=True)
        if rec is None:
            return False
        self.undo(rec)
        return True

    def _count_liberties(self, idx: int, cap: int = 2) -> int:
        """Число дамэ группы, но не больше cap (быстрый выход)."""
        stones = self.stones
        color = stones[idx]
        mark = self._mark
        libmark = self._libmark
        self._stamp += 1
        stamp = self._stamp
        nei = self.nei

        stack = [idx]
        mark[idx] = stamp
        count = 0

        while stack:
            p = stack.pop()
            for q in nei[p]:
                sq = stones[q]
                if sq == EMPTY:
                    if libmark[q] != stamp:
                        libmark[q] = stamp
                        count += 1
                        if count >= cap:
                            return count
                elif sq == color and mark[q] != stamp:
                    mark[q] = stamp
                    stack.append(q)

        return count

    def try_play(self, point: int, color: int) -> bool:
        """Быстрый ход для розыгрышей MCTS.

        Учитывает занятость, самоубийство и захват, но игнорирует ко,
        суперко и счётчики пленных (в розыгрышах они не нужны).
        Доска не меняется, если ход нелегален.
        """
        stones = self.stones

        if point == PASS:
            self.ko = -1
            return True
        if stones[point] != EMPTY:
            return False

        stones[point] = color
        self._remove_empty(point)
        enemy = other(color)
        nei = self.nei
        captured_any = False
        has_liberty = False

        for q in nei[point]:
            sq = stones[q]
            if sq == EMPTY:
                has_liberty = True
                continue
            if sq != enemy:
                continue

            # Быстрый путь: у соседа есть дамэ помимо нашей точки.
            free = False
            for r in nei[q]:
                if r != point and stones[r] == EMPTY:
                    free = True
                    break
            if free:
                continue

            if self._count_liberties(q, 1):
                continue

            grp, _ = self._group(q)
            for g in grp:
                stones[g] = EMPTY
                self._add_empty(g)
            self.caps[color] += len(grp)
            captured_any = True

        if not has_liberty and not captured_any:
            if not self._count_liberties(point, 1):
                stones[point] = EMPTY
                self._add_empty(point)
                return False

        self.ko = -1
        return True

    # ------------------------------------------------------------------ копии

    def copy(self) -> "Board":
        """Полная копия (с историей — для суперко)."""
        b = Board.__new__(Board)
        b.size = self.size
        b.n = self.n
        b.stones = bytearray(self.stones)
        b.nei = self.nei
        b.diag = self.diag
        b.near2 = self.near2
        b.caps = list(self.caps)
        b.ko = self.ko
        b.hash = self.hash
        b.superko = self.superko
        b.history = list(self.history)
        b.hash_set = set(self.hash_set)
        b.empties = list(self.empties)
        b.epos = list(self.epos)
        b._mark = [0] * self.n
        b._libmark = [0] * self.n
        b._stamp = 0
        b._z = self._z
        return b

    def fast_copy(self) -> "Board":
        """Лёгкая копия для розыгрышей: без истории и суперко."""
        b = Board.__new__(Board)
        b.size = self.size
        b.n = self.n
        b.stones = bytearray(self.stones)
        b.nei = self.nei
        b.diag = self.diag
        b.near2 = self.near2
        b.caps = list(self.caps)
        b.ko = self.ko
        b.hash = self.hash
        b.superko = False
        b.history = []
        b.hash_set = set()
        b.empties = list(self.empties)
        b.epos = list(self.epos)
        b._mark = [0] * self.n
        b._libmark = [0] * self.n
        b._stamp = 0
        b._z = self._z
        return b

    # ------------------------------------------------------------------ мелочи

    def stone_count(self) -> tuple[int, int]:
        black = self.stones.count(BLACK)
        white = self.stones.count(WHITE)
        return black, white

    def empty_count(self) -> int:
        return len(self.empties)

    def __str__(self) -> str:  # для отладки в консоли
        sym = {EMPTY: ".", BLACK: "X", WHITE: "O"}
        rows = []
        for y in range(self.size):
            row = "".join(sym[self.stones[y * self.size + x]] for x in range(self.size))
            rows.append(f"{self.size - y:2d} {row}")
        footer = "   " + "".join(LETTERS[x] for x in range(self.size))
        return "\n".join(rows) + "\n" + footer
