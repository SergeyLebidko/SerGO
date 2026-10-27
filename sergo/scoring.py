"""Подсчёт очков.

Основной режим — китайский (Tromp–Taylor): очки = камни на доске
+ территория + коми. Он однозначен и не спорит о даме и сэки.

Японский режим (территория + пленные) реализован как дополнительный;
он приближённый, о чём интерфейс честно предупреждает.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .board import EMPTY, BLACK, WHITE, other


@dataclass
class Score:
    """Результат подсчёта."""

    black: float = 0.0
    white: float = 0.0
    komi: float = 6.5
    black_territory: int = 0
    white_territory: int = 0
    black_stones: int = 0
    white_stones: int = 0
    black_captures: int = 0
    white_captures: int = 0
    neutral: int = 0
    rules: str = "chinese"
    black_area: list[int] = field(default_factory=list)
    white_area: list[int] = field(default_factory=list)
    neutral_area: list[int] = field(default_factory=list)

    @property
    def margin(self) -> float:
        """Разница в пользу чёрных (может быть отрицательной)."""
        return self.black - self.white

    def winner(self) -> int:
        """BLACK, WHITE или 0 при ничьей."""
        if self.margin > 0:
            return BLACK
        if self.margin < 0:
            return WHITE
        return 0

    def text(self) -> str:
        """Короткая строка результата по-русски."""
        w = self.winner()
        if w == 0:
            return f"Ничья (коми {self.komi})"
        name = "Чёрные" if w == BLACK else "Белые"
        return f"{name} победили с разницей {abs(self.margin):.1f}"

    def detail(self) -> str:
        """Подробная расшифровка для панели."""
        if self.rules == "chinese":
            return (
                f"Чёрные: {self.black_stones} камней + {self.black_territory} терр. "
                f"= {self.black:.1f}\n"
                f"Белые: {self.white_stones} камней + {self.white_territory} терр. "
                f"+ {self.komi} коми = {self.white:.1f}\n"
                f"Нейтральных пунктов: {self.neutral}"
            )
        return (
            f"Чёрные: {self.black_territory} терр. + {self.black_captures} пленных "
            f"= {self.black:.1f}\n"
            f"Белые: {self.white_territory} терр. + {self.white_captures} пленных "
            f"+ {self.komi} коми = {self.white:.1f}\n"
            f"Нейтральных пунктов: {self.neutral}"
        )


def _regions(board) -> tuple[list[list[int]], list[list[int]]]:
    """Разбить пустые пункты на связные области.

    Возвращает (области, цвет границы каждой области), где цвет границы —
    BLACK/WHITE, если область касается камней только одного цвета,
    иначе 0 (нейтральная).
    """
    stones = board.stones
    size = board.size
    seen = bytearray(board.n)
    regions: list[list[int]] = []
    borders: list[int] = []

    for start in range(board.n):
        if stones[start] != EMPTY or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        cells: list[int] = []
        border = 0
        while stack:
            p = stack.pop()
            cells.append(p)
            x = p % size
            y = p // size
            for q in board.nei[p]:
                sq = stones[q]
                if sq == EMPTY:
                    if not seen[q]:
                        seen[q] = 1
                        stack.append(q)
                elif border == 0:
                    border = sq
                elif border != sq:
                    border = 3  # касается обоих цветов — нейтрально
        regions.append(cells)
        borders.append(0 if border == 3 else border)

    return regions, borders


@dataclass
class Zone:
    """Одна область пустых пунктов — единица территории на доске."""

    owner: int             # BLACK / WHITE / 0 (спорная)
    points: list[int]      # точки области
    center: int = -1       # точка для подписи с числом
    border_stones: int = 0  # сколько камней её ограничивает

    @property
    def size(self) -> int:
        return len(self.points)


def _zone_center(board, points: list[int]) -> int:
    """Точка внутри зоны, ближайшая к её центроиду.

    Ставить подпись в центроид нельзя: он может попасть на камень или
    за пределы зоны при её изогнутой форме.
    """
    if not points:
        return -1
    size = board.size
    cx = sum(p % size for p in points) / len(points)
    cy = sum(p // size for p in points) / len(points)
    return min(points, key=lambda p: (p % size - cx) ** 2
               + (p // size - cy) ** 2)


def score_zones(board, komi: float = 6.5, dead=()) -> list[Zone]:
    """Разбить территорию на зоны — для наглядного разбора счёта.

    Возвращает список зон, каждая со своим владельцем:
    BLACK, WHITE или 0 для спорной (касается камней обоих цветов).
    Сумма размеров всех зон равна числу пустых пунктов.
    """
    work = board.copy()
    if dead:
        _remove_dead(work, dead)

    regions, borders = _regions(work)
    zones: list[Zone] = []
    stones = work.stones

    for cells, border in zip(regions, borders):
        # Считаем, сколько камней ограничивает зону: это подсказывает,
        # какая группа её держит.
        touching: set[int] = set()
        for p in cells:
            for q in work.nei[p]:
                if stones[q] != EMPTY:
                    touching.add(q)
        zones.append(Zone(
            owner=border,
            points=list(cells),
            center=_zone_center(work, cells),
            border_stones=len(touching),
        ))

    return zones


def _remove_dead(board, dead) -> None:
    """Убрать помеченные мёртвые камни (изменяет stones на копии)."""
    if not dead:
        return
    stones = board.stones
    for p in dead:
        stones[p] = EMPTY
    # пересобрать список пустых пунктов
    board.empties = [i for i in range(board.n) if stones[i] == EMPTY]
    board.epos = [0] * board.n
    for k, i in enumerate(board.empties):
        board.epos[i] = k


def score_area(board, komi: float = 6.5, dead=()) -> Score:
    """Китайский подсчёт: камни на доске + территория + коми."""
    work = board.copy()
    captured_by_removal = {BLACK: 0, WHITE: 0}
    if dead:
        for p in dead:
            c = work.stones[p]
            if c == BLACK:
                captured_by_removal[WHITE] += 1
            elif c == WHITE:
                captured_by_removal[BLACK] += 1
        _remove_dead(work, dead)

    regions, borders = _regions(work)
    result = Score(komi=komi, rules="chinese")
    result.black_stones = work.stones.count(BLACK)
    result.white_stones = work.stones.count(WHITE)
    result.black_captures = board.caps[BLACK] + captured_by_removal[BLACK]
    result.white_captures = board.caps[WHITE] + captured_by_removal[WHITE]

    for cells, border in zip(regions, borders):
        if border == BLACK:
            result.black_territory += len(cells)
            result.black_area.extend(cells)
        elif border == WHITE:
            result.white_territory += len(cells)
            result.white_area.extend(cells)
        else:
            result.neutral += len(cells)
            result.neutral_area.extend(cells)

    result.black = result.black_stones + result.black_territory
    result.white = result.white_stones + result.white_territory + komi
    return result


def score_territory(board, komi: float = 6.5, dead=()) -> Score:
    """Японский подсчёт: территория + снятые камни + коми.

    Приближённый режим: спорные области (в том числе сэки и открытое
    даме) считаются нейтральными.
    """
    work = board.copy()
    removed = {BLACK: 0, WHITE: 0}
    if dead:
        for p in dead:
            c = work.stones[p]
            if c == BLACK:
                removed[WHITE] += 1
            elif c == WHITE:
                removed[BLACK] += 1
        _remove_dead(work, dead)

    regions, borders = _regions(work)
    result = Score(komi=komi, rules="japanese")
    result.black_stones = work.stones.count(BLACK)
    result.white_stones = work.stones.count(WHITE)
    result.black_captures = board.caps[BLACK] + removed[BLACK]
    result.white_captures = board.caps[WHITE] + removed[WHITE]

    for cells, border in zip(regions, borders):
        if border == BLACK:
            result.black_territory += len(cells)
            result.black_area.extend(cells)
        elif border == WHITE:
            result.white_territory += len(cells)
            result.white_area.extend(cells)
        else:
            result.neutral += len(cells)
            result.neutral_area.extend(cells)

    result.black = result.black_territory + result.black_captures
    result.white = result.white_territory + result.white_captures + komi
    return result


def score(board, komi: float = 6.5, dead=(), rules: str = "chinese") -> Score:
    """Подсчёт по названию правил: 'chinese' или 'japanese'."""
    if rules == "japanese":
        return score_territory(board, komi, dead)
    return score_area(board, komi, dead)


def estimate_score_fast(board, komi: float = 6.5,
                        influence: bool = True) -> float:
    """Быстрая оценка счёта для MCTS, без создания копии доски.

    Возвращает разницу (чёрные − белые) в китайских правилах.

    Области, окружённые камнями только одного цвета, отдаются ему
    целиком. Если область касается обоих цветов, она делится
    пропорционально числу ограничивающих камней (influence=True).
    Без этого деления на полупустой доске почти все области считались
    нейтральными, и оценка вырождалась в «минус коми» — из-за этого
    бот считал, что белые выигрывают почти всегда.
    """
    stones = board.stones
    seen = bytearray(board.n)
    nei = board.nei
    # В китайских правилах пленные формально не считаются, но для
    # эвристики розыгрыша они полезны: захват — это реальное преимущество.
    diff = (stones.count(BLACK) - board.caps[WHITE]
            - stones.count(WHITE) + board.caps[BLACK] - komi)

    for start in range(board.n):
        if stones[start] != EMPTY or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        count = 0
        touch_black = 0
        touch_white = 0
        has_black = False
        has_white = False

        while stack:
            p = stack.pop()
            count += 1
            for q in nei[p]:
                sq = stones[q]
                if sq == EMPTY:
                    if not seen[q]:
                        seen[q] = 1
                        stack.append(q)
                elif sq == BLACK:
                    touch_black += 1
                    has_black = True
                else:
                    touch_white += 1
                    has_white = True

        if not has_black and not has_white:
            continue
        if has_black and not has_white:
            diff += count
        elif has_white and not has_black:
            diff -= count
        elif influence and (touch_black or touch_white):
            # Спорная область: делим по числу ограничивающих камней.
            total = touch_black + touch_white
            diff += count * (touch_black - touch_white) / total

    return diff


def dead_stones_heuristic(board) -> set[int]:
    """Простая эвристика мёртвых камней для автоподсчёта в интерфейсе.

    Помечает группы, у которых меньше двух настоящих глаз и мало дамэ.
    Игрок всегда может поправить пометки вручную.
    """
    stones = board.stones
    dead: set[int] = set()
    seen = bytearray(board.n)

    for start in range(board.n):
        if stones[start] == EMPTY or seen[start]:
            continue
        color = stones[start]
        grp, libs = board.group_info(start)
        for p in grp:
            seen[p] = 1
        if len(libs) >= 2:
            # проверяем, есть ли два глаза
            eyes = 0
            for p in grp:
                for q in board.nei[p]:
                    if stones[q] != EMPTY:
                        continue
                    if q in libs and _is_eyeish(board, q, color):
                        eyes += 1
            if eyes >= 2:
                continue
        if len(libs) <= 2 and len(grp) <= 6:
            dead.update(grp)
    return dead


def _is_eyeish(board, point: int, color: int) -> bool:
    """Похоже ли пустое пересечение на глаз цвета color."""
    stones = board.stones
    if stones[point] != EMPTY:
        return False
    for q in board.nei[point]:
        if stones[q] != color:
            return False
    enemy = other(color)
    bad = 0
    for q in board.diag[point]:
        if stones[q] == enemy:
            bad += 1
    # В углу достаточно одного диагонального врага для ложного глаза.
    x = point % board.size
    y = point // board.size
    edge_corner = (x in (0, board.size - 1)) + (y in (0, board.size - 1))
    if edge_corner == 2:
        return bad == 0
    if edge_corner == 1:
        return bad <= 1
    return bad <= 1
