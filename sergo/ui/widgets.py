"""Простые виджеты pygame: кнопка, ползунок, переключатель.

Всё рисуется вручную — без внешних зависимостей и без «нативных» тем.
"""

from __future__ import annotations

import pygame

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Палитра интерфейса
BG = (28, 30, 34)
PANEL = (40, 43, 48)
PANEL_LIGHT = (54, 58, 64)
TEXT = (232, 230, 224)
TEXT_DIM = (150, 150, 150)
ACCENT = (222, 168, 84)
ACCENT_DARK = (168, 120, 52)
OK = (110, 190, 120)
WARN = (220, 110, 100)

_font_cache: dict[tuple[int, bool], pygame.font.Font] = {}


def reset_fonts() -> None:
    """Сбросить кэш шрифтов (обязательно после pygame.quit())."""
    _font_cache.clear()


def font(size: int, bold: bool = False) -> pygame.font.Font:
    """Шрифт с поддержкой кириллицы."""
    key = (size, bold)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    path = FONT_BOLD_PATH if bold else FONT_PATH
    try:
        f = pygame.font.Font(path, size)
    except OSError:
        f = pygame.font.SysFont("dejavusans", size, bold=bold)
    _font_cache[key] = f
    return f


def draw_text(surface, text: str, pos, size: int = 16,
              color=TEXT, bold: bool = False, center: bool = False,
              right: bool = False, max_width: int | None = None):
    """Нарисовать текст и вернуть его прямоугольник.

    right=True — pos задаёт правый край (для чисел в панели).
    max_width — обрезать строку многоточием, чтобы не вылезала за панель.
    """
    f = font(size, bold)
    if max_width is not None and f.size(text)[0] > max_width:
        while text and f.size(text + "…")[0] > max_width:
            text = text[:-1]
        text = text + "…"
    surf = f.render(text, True, color)
    rect = surf.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.topright = pos
    else:
        rect.topleft = pos
    surface.blit(surf, rect)
    return rect


class Button:
    """Кнопка с состоянием наведения и блокировкой."""

    def __init__(self, rect, label: str, action: str,
                 size: int = 16, hotkey: str = ""):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action
        self.size = size
        self.hotkey = hotkey
        self.hover = False
        self.enabled = True

    def handle(self, event) -> bool:
        """Вернуть True, если кнопка нажата."""
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface, active: bool = False) -> None:
        if not self.enabled:
            bg = (46, 48, 52)
            fg = (100, 100, 104)
        elif active:
            bg = ACCENT
            fg = (30, 25, 15)
        elif self.hover:
            bg = PANEL_LIGHT
            fg = ACCENT
        else:
            bg = PANEL
            fg = TEXT

        pygame.draw.rect(surface, bg, self.rect, border_radius=6)
        if active:
            pygame.draw.rect(surface, ACCENT_DARK, self.rect, 1, border_radius=6)
        elif self.hover and self.enabled:
            pygame.draw.rect(surface, ACCENT_DARK, self.rect, 1, border_radius=6)

        draw_text(surface, self.label, self.rect.center, self.size,
                  fg, center=True)


class Slider:
    """Горизонтальный ползунок для дробных значений."""

    def __init__(self, rect, label: str, minimum: float, maximum: float,
                 value: float, step: float = 0.5, fmt: str = "{:.1f} с"):
        self.rect = pygame.Rect(rect)      # область дорожки
        self.label = label
        self.min = minimum
        self.max = maximum
        self.value = value
        self.step = step
        self.fmt = fmt
        self.dragging = False

    @property
    def track(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x, self.rect.centery - 3,
                           self.rect.width, 6)

    def _value_from_x(self, x: int) -> float:
        t = (x - self.rect.x) / max(1, self.rect.width)
        t = max(0.0, min(1.0, t))
        raw = self.min + t * (self.max - self.min)
        steps = round((raw - self.min) / self.step)
        return min(self.max, self.min + steps * self.step)

    def handle(self, event) -> bool:
        """Вернуть True, если значение изменилось."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.inflate(0, 16).collidepoint(event.pos):
                self.dragging = True
                self.value = self._value_from_x(event.pos[0])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            new = self._value_from_x(event.pos[0])
            if new != self.value:
                self.value = new
                return True
        return False

    def draw(self, surface) -> None:
        draw_text(surface, self.label, (self.rect.x, self.rect.y - 20),
                  14, TEXT_DIM)
        value_text = self.fmt.format(self.value)
        surf = font(14, True).render(value_text, True, ACCENT)
        surface.blit(surf, (self.rect.right - surf.get_width(),
                            self.rect.y - 20))

        track = self.track
        pygame.draw.rect(surface, (60, 64, 70), track, border_radius=3)
        t = (self.value - self.min) / max(1e-9, self.max - self.min)
        filled = pygame.Rect(track.x, track.y, int(track.width * t), track.height)
        pygame.draw.rect(surface, ACCENT, filled, border_radius=3)

        knob_x = track.x + int(track.width * t)
        pygame.draw.circle(surface, TEXT, (knob_x, track.centery), 7)
        pygame.draw.circle(surface, ACCENT_DARK, (knob_x, track.centery), 7, 2)


class ToggleGroup:
    """Группа взаимоисключающих кнопок (размер доски, режим)."""

    def __init__(self, rects_labels_actions, size: int = 14):
        self.buttons = [Button(r, label, action, size)
                        for r, label, action in rects_labels_actions]

    @property
    def value(self) -> str | None:
        for b in self.buttons:
            if getattr(b, "_active", False):
                return b.action
        return None

    def set_value(self, action: str) -> None:
        for b in self.buttons:
            b._active = (b.action == action)

    def handle(self, event) -> str | None:
        for b in self.buttons:
            if b.handle(event):
                self.set_value(b.action)
                return b.action
        return None

    def draw(self, surface) -> None:
        for b in self.buttons:
            b.draw(surface, active=getattr(b, "_active", False))
