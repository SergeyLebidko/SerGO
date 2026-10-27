"""Анимации доски: снятие камней и появление нового камня.

Зачем это нужно: без анимации снятые камни исчезают в тот же кадр, что
и ход, и непонятно, почему они пропали. Здесь два эффекта:

  * CaptureEffect — снятые камни гаснут и сжимаются (400 мс);
  * PlaceEffect   — новый камень растёт от 0.8 до полного радиуса (150 мс).

Время считается от time.monotonic() в момент создания, а не накоплением
dt: если окно подвиснет, эффект просто уже закончится, а не застрянет
на середине.
"""

from __future__ import annotations

import math
import time

import pygame

from ..board import BLACK
from .board_view import BLACK_STONE, STONE_EDGE, WHITE_STONE


# Длительности по умолчанию (секунды). Тесты выставляют 0, чтобы
# не замедлять прогон.
CAPTURE_DURATION = 0.40
PLACE_DURATION = 0.15

# Насколько камень сжимается к концу затухания.
CAPTURE_SHRINK = 0.45      # остаётся 55% радиуса
# Максимальная задержка старта (волна по удалённости от места захвата).
MAX_WAVE_DELAY = 0.15
# Задержка на одну клетку расстояния. При захвате группы камни стоят
# вплотную (1–2 клетки), поэтому шаг должен быть заметным.
WAVE_DELAY_PER_CELL = 0.055


def _stone_sprite(radius: int, color: int) -> pygame.Surface:
    """Круглый камень на прозрачной поверхности."""
    size = radius * 2 + 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size // 2, size // 2)

    if color == BLACK:
        base = (*BLACK_STONE, 255)
        light = (70, 72, 80, 255)
    else:
        base = (*WHITE_STONE, 255)
        light = (255, 255, 255, 255)

    pygame.draw.circle(surf, base, center, radius)
    pygame.draw.circle(surf, light,
                       (center[0] - radius // 3, center[1] - radius // 3),
                       max(1, radius // 4))
    pygame.draw.circle(surf, (*STONE_EDGE, 255), center, radius, 1)
    return surf


class _CaptureItem:
    """Один снимаемый камень."""

    __slots__ = ("point", "color", "start", "delay", "radius")

    def __init__(self, point: int, color: int, start: float, delay: float,
                 radius: int):
        self.point = point
        self.color = color
        self.start = start
        self.delay = delay
        self.radius = radius


class _PlaceItem:
    """Один появляющийся камень."""

    __slots__ = ("point", "color", "start", "radius")

    def __init__(self, point: int, color: int, start: float, radius: int):
        self.point = point
        self.color = color
        self.start = start
        self.radius = radius


class Effects:
    """Набор активных анимаций доски."""

    def __init__(self, capture_duration: float = CAPTURE_DURATION,
                 place_duration: float = PLACE_DURATION):
        self.capture_duration = capture_duration
        self.place_duration = place_duration
        self._captures: list[_CaptureItem] = []
        self._places: list[_PlaceItem] = []
        # Кэш спрайтов: (радиус, цвет) -> поверхность.
        self._sprites: dict[tuple[int, int], pygame.Surface] = {}

    # ------------------------------------------------------------------ API

    def clear(self) -> None:
        """Убрать все эффекты (отмена хода, новая партия)."""
        self._captures.clear()
        self._places.clear()

    def busy(self) -> bool:
        """Идёт ли сейчас хоть одна анимация."""
        return bool(self._captures or self._places)

    def hides(self, point: int) -> bool:
        """Точку рисуем мы сами — BoardView должен её пропустить."""
        return any(item.point == point for item in self._captures) or \
            any(item.point == point for item in self._places)

    def add_capture(self, points, color: int, origin: int | None = None,
                    radius: int = 20, size: int = 19) -> None:
        """Запустить затухание снятых камней.

        color — цвет снятых камней; origin — точка сыгранного камня,
        от которой отсчитывается волна задержек.
        """
        if not points:
            return
        now = time.monotonic()
        for p in points:
            delay = 0.0
            if origin is not None:
                d = _distance(p, origin, size)
                delay = min(MAX_WAVE_DELAY, d * WAVE_DELAY_PER_CELL)
            self._captures.append(
                _CaptureItem(p, color, now, delay, radius))

    def add_place(self, point: int, color: int, radius: int = 20) -> None:
        """Запустить появление камня."""
        if point < 0:
            return
        self._places.append(
            _PlaceItem(point, color, time.monotonic(), radius))

    def update(self) -> None:
        """Выбросить завершённые эффекты."""
        now = time.monotonic()
        cd = self.capture_duration
        pd = self.place_duration

        if self._captures:
            self._captures = [it for it in self._captures
                              if now < it.start + it.delay + cd]
        if self._places:
            self._places = [it for it in self._places
                            if now < it.start + pd]

    # ------------------------------------------------------------------ отрисовка

    def draw(self, surface, view, board) -> None:
        """Нарисовать активные эффекты поверх доски."""
        now = time.monotonic()

        for item in self._places:
            elapsed = now - item.start
            t = 1.0 if self.place_duration <= 0 else \
                min(1.0, elapsed / self.place_duration)
            if t < 0:
                continue
            # Плавное появление: от 0.8 до полного радиуса.
            scale = 0.8 + 0.2 * _ease_out(t)
            radius = max(2, int(item.radius * scale))
            self._blit_stone(surface, view, item.point, item.color,
                             radius, 255)

        for item in self._captures:
            elapsed = now - item.start - item.delay
            if elapsed < 0:
                # Задержка ещё не прошла — камень пока неподвижен.
                self._blit_stone(surface, view, item.point, item.color,
                                 item.radius, 255)
                continue
            t = 1.0 if self.capture_duration <= 0 else \
                min(1.0, elapsed / self.capture_duration)
            # Затухание быстрее в конце — камень «тает».
            alpha = int(255 * (1.0 - _ease_in(t)))
            scale = 1.0 - CAPTURE_SHRINK * _ease_in(t)
            radius = max(2, int(item.radius * scale))
            if alpha > 0:
                self._blit_stone(surface, view, item.point, item.color,
                                 radius, alpha)

    def _blit_stone(self, surface, view, point: int, color: int,
                    radius: int, alpha: int) -> None:
        """Нарисовать камень с заданными радиусом и прозрачностью."""
        if radius < 2:
            return
        key = (radius, color)
        sprite = self._sprites.get(key)
        if sprite is None:
            sprite = _stone_sprite(radius, color)
            self._sprites[key] = sprite
        if alpha < 255:
            sprite = sprite.copy()
            sprite.set_alpha(alpha)
        px, py = view.point_to_pixel(point)
        surface.blit(sprite, (px - sprite.get_width() // 2,
                              py - sprite.get_height() // 2))


def _distance(a: int, b: int, size: int) -> float:
    """Расстояние между двумя точками доски в клетках."""
    return math.hypot(abs(a % size - b % size), abs(a // size - b // size))


def _ease_out(t: float) -> float:
    """Быстрый старт, мягкое завершение."""
    return 1.0 - (1.0 - t) ** 2


def _ease_in(t: float) -> float:
    """Медленный старт, быстрый конец."""
    return t * t
