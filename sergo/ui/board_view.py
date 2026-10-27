"""Отрисовка доски.

Отдельный класс отвечает за геометрию (перевод клика в точку и обратно)
и за картинку: дерево, сетка, камни, подсветка, метки территории.
"""

from __future__ import annotations

import math

import pygame

from ..board import BLACK, WHITE, EMPTY, LETTERS, format_point
from .widgets import font, draw_text

# Цвета доски
WOOD = (222, 184, 135)
WOOD_DARK = (205, 165, 116)
GRID = (70, 50, 30)
STAR = (60, 42, 25)
BLACK_STONE = (26, 26, 30)
WHITE_STONE = (245, 243, 238)
STONE_EDGE = (20, 20, 24)
SHADOW = (0, 0, 0, 60)

HOSHI = {
    9: [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)],
    13: [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)],
    19: [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15),
         (15, 3), (15, 9), (15, 15)],
}


class BoardView:
    """Доска с адаптивным масштабом."""

    def __init__(self, rect, size: int = 9):
        self.rect = pygame.Rect(rect)
        self.size = size
        self.margin = 0
        self.cell = 0
        self.origin = (0, 0)
        self._recalc()

    def set_size(self, size: int) -> None:
        self.size = size
        self._recalc()

    def resize(self, rect) -> None:
        self.rect = pygame.Rect(rect)
        self._recalc()

    def _recalc(self) -> None:
        """Подобрать отступ и размер клетки под текущее окно.

        Поля рассчитываются от реальных размеров подписей координат:
        камень у края выступает за линию сетки на 0.46 клетки, подпись
        стоит в середине поля и не должна с ним соприкасаться.
        """
        side = min(self.rect.width, self.rect.height)
        count = max(1, self.size - 1)

        # Начальное приближение, затем уточняем по фактической ширине
        # самой широкой подписи (двузначные числа на 13×13 и 19×19).
        margin = int(side * 0.07)
        for _ in range(4):
            cell = (side - 2 * margin) / count
            font_size = max(9, int(cell * 0.36))
            f = font(font_size)
            widest = max(
                f.size(str(n))[0] for n in range(1, self.size + 1)
            )
            widest = max(widest, f.size(LETTERS[self.size - 1])[0])
            label_h = f.get_height()
            span = max(widest, label_h)

            # margin/2 — центр полосы; половина подписи + камень + зазор.
            needed = 2 * (cell * 0.46 + span / 2 + 3)
            if abs(needed - margin) < 2:
                margin = int(needed)
                break
            margin = int(needed)

        self.margin = margin
        self.cell = (side - self.margin * 2) / count
        self.origin = (
            self.rect.x + (self.rect.width - side) // 2 + self.margin,
            self.rect.y + (self.rect.height - side) // 2 + self.margin,
        )
        self.side = side

    # ------------------------------------------------------------------ геометрия

    def point_to_pixel(self, point: int) -> tuple[int, int]:
        x = point % self.size
        y = point // self.size
        px = self.origin[0] + x * self.cell
        py = self.origin[1] + y * self.cell
        return int(round(px)), int(round(py))

    def pixel_to_point(self, pos) -> int | None:
        """Ближайшее пересечение, если клик достаточно близко."""
        mx, my = pos
        sx, sy = self.origin
        x = round((mx - sx) / self.cell) if self.cell else -1
        y = round((my - sy) / self.cell) if self.cell else -1
        if not (0 <= x < self.size and 0 <= y < self.size):
            return None
        px, py = self.point_to_pixel(y * self.size + x)
        dist = math.hypot(mx - px, my - py)
        if dist > self.cell * 0.48:
            return None
        return y * self.size + x

    # ------------------------------------------------------------------ отрисовка

    def draw(self, surface, game, hover_point: int | None = None,
             show_territory: bool = False, effects=None) -> None:
        self._draw_wood(surface)
        self._draw_grid(surface)
        self._draw_stones(surface, game, effects)
        if show_territory:
            self._draw_territory(surface, game)
        self._draw_last_move(surface, game, effects)
        if hover_point is not None:
            self._draw_ghost(surface, game, hover_point)
        self._draw_coords(surface)

    def _draw_wood(self, surface) -> None:
        # Прямые углы: доска занимает весь левый край окна, и скругления
        # оставляли бы в углах тёмные «вырезы» фона.
        pygame.draw.rect(surface, WOOD, self.rect)
        # Мягкие полосы «дерева».
        for i in range(0, self.rect.height, 7):
            alpha = 12 if i % 3 else 6
            color = (*WOOD_DARK, alpha)
            pygame.draw.line(surface, color[:3], (self.rect.x, self.rect.y + i),
                             (self.rect.right, self.rect.y + i))
        pygame.draw.rect(surface, GRID, self.rect, 1)

    def _draw_grid(self, surface) -> None:
        x0, y0 = self.origin
        end = (self.size - 1) * self.cell
        w = 1 if self.size >= 13 else 1
        for i in range(self.size):
            pos = int(round(i * self.cell))
            pygame.draw.line(surface, GRID,
                             (x0, y0 + pos), (x0 + int(end), y0 + pos), w)
            pygame.draw.line(surface, GRID,
                             (x0 + pos, y0), (x0 + pos, y0 + int(end)), w)

        r = max(2, int(self.cell * 0.08))
        for hx, hy in HOSHI.get(self.size, []):
            px = int(x0 + hx * self.cell)
            py = int(y0 + hy * self.cell)
            pygame.draw.circle(surface, STAR, (px, py), r)

    def _draw_coords(self, surface) -> None:
        """Координаты по краям доски, по центру свободных полос.

        Подписи стоят ровно в середине поля между крайней линией сетки и
        краем дерева — так они выровнены и не прижаты к границе.
        """
        size = self.size
        letters = "".join(LETTERS[:size])
        font_size = max(9, int(self.cell * 0.36))
        f = font(font_size)
        end = int((size - 1) * self.cell)

        # Центр свободной полосы: половина отступа от края до линии сетки.
        offset = self.margin // 2

        top_y = self.origin[1] - offset
        bottom_y = self.origin[1] + end + offset
        left_x = self.origin[0] - offset
        right_x = self.origin[0] + end + offset

        for i in range(size):
            px = self.point_to_pixel(i)[0]
            label = letters[i]
            surf = f.render(label, True, GRID)
            surface.blit(surf, (px - surf.get_width() // 2,
                                top_y - surf.get_height() // 2))
            surface.blit(surf, (px - surf.get_width() // 2,
                                bottom_y - surf.get_height() // 2))

            py = self.point_to_pixel(i * size)[1]
            number = f.render(str(size - i), True, GRID)
            surface.blit(number, (left_x - number.get_width() // 2,
                                  py - number.get_height() // 2))
            surface.blit(number, (right_x - number.get_width() // 2,
                                  py - number.get_height() // 2))

    def _draw_stones(self, surface, game, effects=None) -> None:
        board = game.board
        radius = self.stone_radius()
        stones = board.stones
        for p in range(board.n):
            color = stones[p]
            if color == EMPTY:
                continue
            # Анимируемый камень рисует сам эффект — иначе он
            # появится дважды (статично и в анимации).
            if effects is not None and effects.hides(p):
                continue
            px, py = self.point_to_pixel(p)
            self._draw_stone(surface, px, py, radius, color)

    def stone_radius(self) -> int:
        """Радиус камня для текущего масштаба доски."""
        return max(4, int(self.cell * 0.46))

    def _draw_stone(self, surface, px: int, py: int, radius: int,
                    color: int) -> None:
        # Тень
        shadow = pygame.Surface((radius * 2 + 4, radius * 2 + 4),
                                pygame.SRCALPHA)
        pygame.draw.circle(shadow, (0, 0, 0, 70),
                           (radius + 2, radius + 3), radius)
        surface.blit(shadow, (px - radius - 2, py - radius - 3))

        if color == BLACK:
            base = BLACK_STONE
            light = (70, 72, 80)
        else:
            base = WHITE_STONE
            light = (255, 255, 255)

        pygame.draw.circle(surface, base, (px, py), radius)
        pygame.draw.circle(surface, light,
                           (px - radius // 3, py - radius // 3),
                           max(1, radius // 4))
        pygame.draw.circle(surface, STONE_EDGE, (px, py), radius, 1)

    def _draw_last_move(self, surface, game, effects=None) -> None:
        if game.last_move is None or game.last_move < 0:
            return
        point = game.last_move
        if game.board.stones[point] == EMPTY:
            return
        # На камне, который ещё «появляется», метку не рисуем.
        if effects is not None and effects.hides(point):
            return
        px, py = self.point_to_pixel(point)
        radius = max(4, int(self.cell * 0.46))
        marker = (240, 120, 90) if game.board.stones[point] == BLACK else (200, 60, 50)
        pygame.draw.circle(surface, marker, (px, py), max(3, radius // 3), 2)

    def _draw_ghost(self, surface, game, point: int) -> None:
        if not game.can_play():
            return
        if game.board.stones[point] != EMPTY:
            return
        if not game.board.is_legal(point, game.turn):
            return

        px, py = self.point_to_pixel(point)
        radius = max(4, int(self.cell * 0.46))
        overlay = pygame.Surface((radius * 2 + 4, radius * 2 + 4),
                                 pygame.SRCALPHA)
        center = (radius + 2, radius + 2)
        if game.turn == BLACK:
            fill = (26, 26, 30, 130)
            edge = (26, 26, 30, 210)
        else:
            fill = (250, 248, 244, 190)
            edge = (120, 118, 112, 230)
        pygame.draw.circle(overlay, fill, center, radius)
        pygame.draw.circle(overlay, edge, center, radius, 2)
        surface.blit(overlay, (px - radius - 2, py - radius - 2))

    def draw_hint(self, surface, point: int) -> None:
        """Отметить рекомендованный ход пунктирным кружком."""
        if point < 0 or point >= self.size * self.size:
            return
        px, py = self.point_to_pixel(point)
        radius = max(6, int(self.cell * 0.42))
        segments = 16
        for i in range(segments):
            if i % 2:
                continue
            a0 = i * (2 * math.pi / segments)
            a1 = (i + 1) * (2 * math.pi / segments)
            pygame.draw.arc(
                surface, (90, 170, 240),
                pygame.Rect(px - radius, py - radius, radius * 2, radius * 2),
                a0, a1, 2)

    def _draw_territory(self, surface, game) -> None:
        if game.result is None:
            return
        radius = max(3, int(self.cell * 0.16))
        for p in game.result.black_area:
            px, py = self.point_to_pixel(p)
            pygame.draw.circle(surface, (20, 20, 20), (px, py), radius)
        for p in game.result.white_area:
            px, py = self.point_to_pixel(p)
            pygame.draw.circle(surface, (250, 250, 250), (px, py), radius)
            pygame.draw.circle(surface, (90, 90, 90), (px, py), radius, 1)
        # Нейтральные пункты не помечаем: на пустой доске их десятки,
        # и крестики превращают доску в шум. Показываем только спорные
        # области, когда их немного и они действительно важны.
        if 0 < len(game.result.neutral_area) <= 12:
            r = max(3, int(self.cell * 0.13))
            for p in game.result.neutral_area:
                px, py = self.point_to_pixel(p)
                pygame.draw.line(surface, (150, 120, 85),
                                 (px - r, py - r), (px + r, py + r), 1)
                pygame.draw.line(surface, (150, 120, 85),
                                 (px - r, py + r), (px + r, py - r), 1)

        # Мёртвые камни помечаем крестом.
        for p in game.dead:
            px, py = self.point_to_pixel(p)
            r = max(4, int(self.cell * 0.28))
            pygame.draw.line(surface, (220, 80, 70),
                             (px - r, py - r), (px + r, py + r), 2)
            pygame.draw.line(surface, (220, 80, 70),
                             (px - r, py + r), (px + r, py - r), 2)
