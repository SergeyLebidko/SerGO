"""Главное окно игры.

Структура экрана:
  * слева — доска;
  * справа — панель: состояние, счёт, кнопки, настройки;
  * сверху — меню новой игры (настройки размера, уровня, коми).

ИИ работает в фоновом потоке; его результат забирается в основном цикле
через очередь, поэтому интерфейс не подвисает.
"""

from __future__ import annotations

import queue
import random
import threading
import time

import pygame

from ..board import BLACK, WHITE, PASS, format_point, other
from ..engine import Engine, DEFAULT_LEVEL, LEVELS
from ..game import Game, GamePhase
from .board_view import BoardView
from .effects import Effects
from .widgets import (
    BG, PANEL, TEXT, TEXT_DIM, ACCENT, ACCENT_DARK,
    Button, Slider, ToggleGroup, draw_text,
)

WINDOW_W = 1120
WINDOW_H = 800
PANEL_W = 330
FPS = 60


def _black_share(black: float, white: float) -> float:
    """Доля доски за чёрными по их доле в общем счёте (0..1).

    Считается прямо из очков: `чёрные / (чёрные + белые)`. Это честнее
    любой «вероятности победы» — полоса показывает реальное соотношение
    счёта, а не категоричность оценки.
    """
    total = black + white
    if total <= 0:
        return 0.5
    return max(0.02, min(0.98, black / total))


class App:
    """Приложение игры."""

    def __init__(self, size: int = 9, level: str = DEFAULT_LEVEL):
        pygame.init()
        pygame.display.set_caption("SerGO")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self._set_window_icon()
        self.clock = pygame.time.Clock()
        self.running = True

        self.game = Game(size=size)
        self.engine = Engine(self.game.board, komi=self.game.komi,
                             level=level, seed=random.randrange(1 << 30))

        self.mode = "human_ai"
        self.human_color = BLACK
        self.effects = Effects()
        # Ход ИИ, ждущий окончания анимации.
        self.pending_move: tuple | None = None
        self.pending_since = 0.0
        self.show_territory = False
        # Разбор счёта: заливка зон на доске и расшифровка в панели.
        self.show_breakdown = False
        self._zones_cache: tuple | None = None
        self._score_rect: pygame.Rect | None = None
        self._hover_score_block = False
        self._hover_group_info: tuple[int, int] | None = None
        self.hover_point: int | None = None
        self.ai_thinking = False
        self.result_queue: queue.Queue = queue.Queue()
        self.ai_thread: threading.Thread | None = None
        self.ai_token = 0
        self.status_note = ""
        self.status_note_until = 0.0
        self.show_settings = False
        self.last_ai_stats = (0.5, 0)
        self.hint_point: int | None = None
        self.hint_queue: queue.Queue = queue.Queue()
        self.hint_thinking = False
        self.hint_token = 0

        self.board_view = BoardView(self._board_rect(), size)
        self._build_widgets()

    # ------------------------------------------------------------------ раскладка

    def _set_window_icon(self) -> None:
        """Иконка окна и панели задач."""
        import os

        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "icon.png")
        try:
            pygame.display.set_icon(pygame.image.load(path))
        except (pygame.error, FileNotFoundError):
            pass

    def _board_rect(self) -> pygame.Rect:
        return pygame.Rect(0, 0, WINDOW_W - PANEL_W, WINDOW_H)

    def _build_widgets(self) -> None:
        px = WINDOW_W - PANEL_W + 20
        width = PANEL_W - 40
        y = 322
        h = 36
        gap = 8

        self.btn_pass = Button((px, y, width // 2 - 4, h), "Пас", "pass")
        self.btn_resign = Button((px + width // 2 + 4, y, width // 2 - 4, h),
                                 "Сдаться", "resign")
        y += h + gap
        self.btn_undo = Button((px, y, width // 2 - 4, h), "Отменить", "undo")
        self.btn_new = Button((px + width // 2 + 4, y, width // 2 - 4, h),
                              "Новая", "new")
        y += h + gap
        self.btn_hint = Button((px, y, width, h), "Подсказка", "hint")
        y += h + gap
        self.btn_confirm = Button((px, y, width, h), "Подтвердить счёт",
                                  "confirm")
        y += h + gap
        self.btn_settings = Button((px, y, width, h), "Настройки партии",
                                   "settings")

        self.buttons = [
            self.btn_pass, self.btn_resign, self.btn_undo,
            self.btn_new, self.btn_hint, self.btn_confirm, self.btn_settings,
        ]

        # Настройки в отдельной панели (показываются поверх правой части).
        sx = WINDOW_W - PANEL_W + 12
        sw = PANEL_W - 24
        self.settings_rect = pygame.Rect(sx, 108, sw, 436)
        inner = sx + 16
        iw = sw - 32

        self.size_group = ToggleGroup([
            ((inner, 186, iw // 3 - 4, 32), "9×9", "9"),
            ((inner + iw // 3, 186, iw // 3 - 4, 32), "13×13", "13"),
            ((inner + 2 * iw // 3, 186, iw // 3 - 4, 32), "19×19", "19"),
        ])
        self.size_group.set_value(str(self.game.size))

        self.color_group = ToggleGroup([
            ((inner, 262, iw // 2 - 4, 32), "Чёрными", "black"),
            ((inner + iw // 2 + 4, 262, iw // 2 - 4, 32), "Белыми", "white"),
        ])
        self.color_group.set_value("black")

        self.level_group = ToggleGroup([
            ((inner, 338, iw // 3 - 4, 32), "Легко", "easy"),
            ((inner + iw // 3, 338, iw // 3 - 4, 32), "Средне", "normal"),
            ((inner + 2 * iw // 3, 338, iw // 3 - 4, 32), "Сложно", "hard"),
        ])
        self.level_group.set_value(self.engine.level)

        # Ползунок коми тянется ровно до правого края кнопки «Сложно»,
        # чтобы край колонки элементов был единым.
        slider_w = self.level_group.buttons[-1].rect.right - inner
        self.komi_slider = Slider((inner, 434, slider_w, 6), "Коми",
                                  0.0, 15.0, self.game.komi, 0.5, "{:.1f}")
        self.btn_close_settings = Button((sx + sw - 34, 126, 26, 26),
                                         "×", "close_settings", 18)

    # ------------------------------------------------------------------ цикл

    def run(self) -> None:
        while self.running:
            self._pump_events()
            self.effects.update()
            self._poll_ai()
            self._poll_hint()
            self._maybe_start_ai()
            self._draw()
            self.clock.tick(FPS)
        pygame.quit()

    def _pump_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                self._cancel_ai()
                continue

            if event.type == pygame.KEYDOWN:
                if self._handle_key(event):
                    continue

            if self.show_settings:
                self._handle_settings_event(event)
                continue

            if event.type == pygame.MOUSEMOTION:
                self.hover_point = self.board_view.pixel_to_point(event.pos)
                self._hover_score_block = (
                    self._score_rect is not None
                    and self._score_rect.collidepoint(event.pos))

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

            for btn in self.buttons:
                if btn.handle(event):
                    self._action(btn.action)

    def _handle_key(self, event) -> bool:
        key = event.key
        if key == pygame.K_ESCAPE:
            if self.show_settings:
                self.show_settings = False
            else:
                self.running = False
                self._cancel_ai()
            return True
        if key == pygame.K_F1:
            self.show_settings = not self.show_settings
            return True
        if key == pygame.K_p:
            self._action("pass")
            return True
        if key == pygame.K_u and (event.mod & pygame.KMOD_CTRL):
            self._action("undo")
            return True
        if key == pygame.K_s:
            self.toggle_breakdown()
            return True
        return False

    def _handle_click(self, pos) -> None:
        if self.show_settings:
            return
        # Клик по блоку «Счёт сейчас» включает разбор счёта.
        if self._score_rect is not None and self._score_rect.collidepoint(pos):
            self.toggle_breakdown()
            return
        if not self.game.can_play():
            # В режиме разметки клик по камню помечает его мёртвым.
            point = self.board_view.pixel_to_point(pos)
            if point is not None:
                self.game.toggle_dead(point)
            return
        if not self._human_to_move():
            return
        point = self.board_view.pixel_to_point(pos)
        if point is None:
            return
        self._play_human(point)

    def _handle_settings_event(self, event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.settings_rect.collidepoint(event.pos):
                self.show_settings = False
                return
            if self.btn_close_settings.handle(event):
                self.show_settings = False
                return

        changed_size = self.size_group.handle(event)
        if changed_size:
            self.game.new_game(size=int(changed_size))
            self.board_view.set_size(self.game.size)
            self._reset_ai()
            self._note(f"Новая партия {changed_size}×{changed_size}")
            return

        changed_color = self.color_group.handle(event)
        if changed_color:
            self.human_color = BLACK if changed_color == "black" else WHITE
            self._reset_ai()
            self._note("Вы играете чёрными" if self.human_color == BLACK
                       else "Вы играете белыми")
            return

        changed_level = self.level_group.handle(event)
        if changed_level:
            self.engine.set_level(changed_level)
            self._reset_ai()
            self._note(f"Уровень: {LEVELS[changed_level]['label']}")
            return

        if self.komi_slider.handle(event):
            self.game.komi = self.komi_slider.value
            if self.game.phase == GamePhase.SCORING:
                self.game.update_score()
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if event.pos[1] > 600 and event.pos[0] > WINDOW_W - PANEL_W:
                self.show_settings = False
    # ------------------------------------------------------------------ ходы

    def _note(self, text: str, seconds: float = 3.5) -> None:
        """Показать сообщение под строкой состояния на несколько секунд.

        Раньше текст висел до следующего события и путал игрока: надпись
        «Так ходить нельзя» оставалась даже после удачных ходов.
        """
        self.status_note = text
        self.status_note_until = time.monotonic() + seconds

    def _clear_note(self) -> None:
        self.status_note = ""
        self.status_note_until = 0.0

    def _note_alive(self) -> bool:
        return bool(self.status_note) and time.monotonic() < self.status_note_until

    def _human_to_move(self) -> bool:
        if self.mode == "ai_ai":
            return False
        if self.mode == "human_human":
            return True
        return self.game.turn == self.human_color

    def _play_human(self, point: int) -> None:
        if self.game.play(point, self.game.turn):
            self._after_move()
        else:
            self._note("Так ходить нельзя", 2.5)

    def _after_move(self) -> None:
        self._start_move_effects()
        # Сообщение об ошибке относилось к прошлой попытке — убираем,
        # чтобы не путать с текущей позицией.
        self._clear_note()
        if self.game.phase == GamePhase.SCORING:
            self.show_territory = True
        else:
            self.show_territory = False
        # Дерево ИИ относится к прежней позиции — сбрасываем.
        self.engine.forget()
        self.hint_point = None

    # ------------------------------------------------------------------ разбор счёта

    def zones(self) -> list:
        """Зоны территории с кэшем по позиции.

        score_zones делает flood fill по всей доске; на 19×19 это
        дорого для каждого кадра, поэтому кэшируем по хешу позиции.
        """
        from ..scoring import score_zones

        board = self.game.board
        key = (board.hash, self.game.komi, frozenset(self.game.dead))
        if self._zones_cache is not None and self._zones_cache[0] == key:
            return self._zones_cache[1]
        zones = score_zones(board, self.game.komi, self.game.dead)
        self._zones_cache = (key, zones)
        return zones

    def toggle_breakdown(self) -> None:
        """Включить или выключить разбор счёта."""
        self.show_breakdown = not self.show_breakdown
        if self.show_breakdown:
            self._note("Разбор счёта включён", 2.0)
        else:
            self._note("Разбор счёта выключен", 2.0)

    def _start_move_effects(self) -> None:
        """Запустить анимации по последнему сыгранному ходу."""
        if not self.game.moves:
            return
        move = self.game.moves[-1]
        radius = self.board_view.stone_radius()

        # Снятые камни — это всегда камни противника.
        if move.captures:
            self.effects.add_capture(
                move.captures, other(move.color),
                origin=move.point, radius=radius, size=self.game.size)
        if move.point >= 0:
            self.effects.add_place(move.point, move.color, radius)

    def _maybe_start_ai(self) -> None:
        if not self.game.can_play() or self.ai_thinking:
            return
        if self.mode == "human_human":
            return
        if self.mode == "human_ai" and self.game.turn == self.human_color:
            return

        # Небольшая пауза, чтобы ход человека успел отрисоваться.
        self.ai_thinking = True
        self.ai_token += 1
        token = self.ai_token
        color = self.game.turn
        self.ai_thread = threading.Thread(
            target=self._ai_worker, args=(token, color), daemon=True)
        self.ai_thread.start()

    def _ai_worker(self, token: int, color: int) -> None:
        try:
            move, winrate, sims = self.engine.choose_move_detailed(color)
            self.result_queue.put((token, move, winrate, sims, None))
        except Exception as exc:  # pragma: no cover - защита UI
            self.result_queue.put((token, PASS, 0.5, 0, exc))

    # Дольше этого ход ИИ не ждёт окончания анимации.
    MAX_EFFECT_WAIT = 0.6

    def _poll_ai(self) -> None:
        # Отложенный ход применяем, когда анимация закончилась: иначе
        # два взятия подряд наложатся друг на друга и превратятся в
        # нечитаемую кашу. Ограничение по времени — чтобы не зависнуть,
        # если эффект почему-то не завершился.
        if self.pending_move is not None:
            if self.effects.busy() and time.monotonic() - self.pending_since < self.MAX_EFFECT_WAIT:
                return
            token, move, winrate, sims = self.pending_move
            self.pending_move = None
            self._apply_ai_move(token, move, winrate, sims)
            return

        try:
            token, move, winrate, sims, exc = self.result_queue.get_nowait()
        except queue.Empty:
            return

        self.ai_thinking = False
        if token != self.ai_token:
            return
        if exc is not None:
            self._note(f"Ошибка ИИ: {exc}", 8.0)
            return
        if not self.game.can_play():
            return
        if self.effects.busy():
            self.pending_move = (token, move, winrate, sims)
            self.pending_since = time.monotonic()
            return

        self._apply_ai_move(token, move, winrate, sims)

    def _apply_ai_move(self, token: int, move: int, winrate: float,
                       sims: int) -> None:
        if token != self.ai_token or not self.game.can_play():
            return
        self.last_ai_stats = (winrate, sims)
        if self.game.play(move, self.game.turn, analysis=winrate,
                          simulations=sims, by_ai=True):
            self._after_move()
        else:
            self._note("ИИ предложил нелегальный ход", 8.0)

    # ------------------------------------------------------------------ подсказка

    def _request_hint(self) -> None:
        """Посчитать лучший ход для человека в отдельном потоке."""
        if not self.game.can_play() or self.hint_thinking:
            return
        if not self._human_to_move():
            self._note("Подсказка доступна на вашем ходу", 2.5)
            return

        self.hint_token += 1
        token = self.hint_token
        self.hint_thinking = True
        self.hint_point = None
        color = self.game.turn

        # Отдельный движок: подсказка не должна ломать дерево игрового ИИ.
        # Время ограничено: ждать 6–10 секунд ради подсказки неудобно,
        # двух секунд достаточно для осмысленного совета.
        hint_engine = Engine(self.game.board, komi=self.game.komi,
                             level="hard",
                             time_override=min(2.0, self.engine.budget()),
                             seed=random.randrange(1 << 30))

        def worker():
            try:
                move, winrate, sims = hint_engine.choose_move_detailed(color)
                self.hint_queue.put((token, move, winrate, sims, None))
            except Exception as exc:  # pragma: no cover
                self.hint_queue.put((token, PASS, 0.5, 0, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_hint(self) -> None:
        try:
            token, move, winrate, sims, exc = self.hint_queue.get_nowait()
        except queue.Empty:
            return

        self.hint_thinking = False
        if token != self.hint_token or exc is not None:
            return
        self.hint_point = move
        if move == PASS:
            self._note(f"Подсказка: пас ({int(winrate * 100)}%)", 6.0)
        else:
            self._note(
                f"Подсказка: {format_point(self.game.size, move)} "
                f"({int(winrate * 100)}%)", 6.0)

    def _cancel_ai(self) -> None:
        self.ai_token += 1
        self.hint_token += 1
        self.engine.cancel()
        self.ai_thinking = False
        self.hint_thinking = False
        self.hint_point = None

    def _reset_ai(self) -> None:
        self._cancel_ai()
        self.effects.clear()
        self.pending_move = None
        self.engine.set_board(self.game.board)
        self.engine.forget()
        self.show_territory = False
        # Новая доска может быть меньше: старый hover_point тогда
        # указывает за её пределы. Без сброса отрисовка падала с
        # IndexError, и интерфейс выглядел зависшим.
        self.hover_point = None
        self._hover_score_block = False

    # ------------------------------------------------------------------ действия

    def _action(self, action: str) -> None:
        if action == "pass":
            if self._human_to_move() and self.game.can_play():
                self._play_human(PASS)
        elif action == "resign":
            if self.game.can_play():
                # Сдаётся тот, чей сейчас ход; в режиме «человек — ИИ»
                # сдаться может только человек.
                if self.mode == "human_ai" and self.game.turn != self.human_color:
                    self._note("Сейчас ход ИИ", 2.5)
                    return
                self.game.resign(self.game.turn)
                self._cancel_ai()
        elif action == "undo":
            self._undo()
        elif action == "new":
            self.game.new_game()
            self._reset_ai()
            self._note("Новая партия")
        elif action == "confirm":
            if self.game.phase == GamePhase.SCORING:
                self.game.finish_scoring()
                self.show_territory = True
        elif action == "hint":
            self._request_hint()
        elif action == "settings":
            self.show_settings = not self.show_settings

    def _undo(self) -> None:
        self._cancel_ai()
        # Возвращённые камни не должны оказаться под призраками.
        self.effects.clear()
        undone = self.game.undo()
        # В режиме «человек — ИИ» отменяем пару ходов, чтобы ход снова
        # был за человеком.
        if undone and self.mode == "human_ai" and self.game.turn != self.human_color:
            self.game.undo()
        self.engine.set_board(self.game.board)
        self.engine.forget()
        self._note("Ход отменён" if undone else "Нечего отменять")

    # ------------------------------------------------------------------ отрисовка

    def _draw(self) -> None:
        self.screen.fill(BG)
        # На случай, если размер доски сменили в обход обработчика событий.
        if self.board_view.size != self.game.size:
            self.board_view.set_size(self.game.size)
        self.board_view.draw(
            self.screen, self.game,
            hover_point=self.hover_point if self._human_to_move() else None,
            show_territory=self.show_territory or
            self.game.phase != GamePhase.PLAYING,
            effects=self.effects,
            zones=self.zones() if self.show_breakdown else None,
        )
        self._hover_group_info = None
        if self.show_breakdown:
            self._draw_hover_group()
        self.effects.draw(self.screen, self.board_view, self.game.board)
        if self.hint_point is not None:
            self.board_view.draw_hint(self.screen, self.hint_point)
        self._draw_panel()
        if self.show_settings:
            self._draw_settings()
        pygame.display.flip()

    def _draw_panel(self) -> None:
        px = WINDOW_W - PANEL_W
        panel = pygame.Rect(px, 0, PANEL_W, WINDOW_H)
        pygame.draw.rect(self.screen, PANEL, panel)
        pygame.draw.line(self.screen, (20, 22, 25), (px, 0), (px, WINDOW_H), 2)

        x = px + 20
        draw_text(self.screen, "SerGO", (x, 18), 26, ACCENT, bold=True)

        # Состояние партии
        y = 60
        draw_text(self.screen, self.game.status_line(), (x, y), 15, TEXT,
                  max_width=PANEL_W - 40)
        y += 26

        if self.hint_thinking:
            draw_text(self.screen, "Считаю подсказку…", (x, y), 15, ACCENT)
        elif self.ai_thinking:
            draw_text(self.screen, "ИИ думает…", (x, y), 15, ACCENT)
        elif self._note_alive():
            draw_text(self.screen, self.status_note, (x, y), 14, TEXT_DIM,
                      max_width=PANEL_W - 40)
        y += 26

        # Счёт. Во время партии территория ещё не определена (по площади
        # один камень «владеет» всей доской), поэтому показываем только
        # камни и пленных, а полный счёт — на этапе разметки.
        y = 132
        s = self.game.result
        if s is None or self.game.phase == GamePhase.PLAYING:
            y = self._draw_balance(x, y, px)
            draw_text(self.screen, f"Коми: {self.game.komi:.1f}", (x, y), 14,
                      TEXT_DIM)
            y += 28
        else:
            draw_text(self.screen, "Счёт (китайские)", (x, y), 14, TEXT_DIM)
            y += 22
            draw_text(self.screen, "Чёрные", (x, y), 15, TEXT)
            draw_text(self.screen, f"{s.black:.1f}", (px + PANEL_W - 22, y),
                      15, TEXT, bold=True, right=True)
            y += 20
            draw_text(self.screen, "Белые", (x, y), 15, TEXT)
            draw_text(self.screen, f"{s.white:.1f}", (px + PANEL_W - 22, y),
                      15, TEXT, bold=True, right=True)
            y += 24
            if s.winner():
                name = "Чёрные" if s.winner() == BLACK else "Белые"
                draw_text(self.screen, f"Впереди: {name}", (x, y), 14, ACCENT)
            else:
                draw_text(self.screen, "Ровно", (x, y), 14, TEXT_DIM)
            y += 24

        # Захваченные камни. В разборе счёта не показываем: места нет,
        # да и в китайских правилах пленные в счёт не входят.
        if not self.show_breakdown:
            y += 10
            draw_text(self.screen, "Пленные", (x, y), 14, TEXT_DIM)
            y += 20
            draw_text(self.screen, f"Чёрные: {self.game.captured(BLACK)}",
                      (x, y), 14, TEXT)
            y += 18
            draw_text(self.screen, f"Белые: {self.game.captured(WHITE)}",
                      (x, y), 14, TEXT)

        # Кнопки
        for btn in self.buttons:
            btn.enabled = self._button_enabled(btn.action)
            btn.draw(self.screen, active=False)

        # Захваты: последний ход
        self._draw_move_log()

    def _button_enabled(self, action: str) -> bool:
        if action == "pass":
            return self.game.can_play() and self._human_to_move()
        if action == "resign":
            return self.game.can_play() and (self.mode != "human_ai"
                                             or self.game.turn == self.human_color)
        if action == "undo":
            return bool(self.game.moves)
        if action == "confirm":
            return self.game.phase == GamePhase.SCORING
        if action == "hint":
            return (self.game.can_play() and self._human_to_move()
                    and not self.hint_thinking)
        return True

    def _draw_balance(self, x: int, y: int, panel_x: int) -> int:
        """Счёт текущей позиции — как если бы партия закончилась сейчас.

        Это настоящий подсчёт по китайским правилам (камни + территория
        + коми), тот же, что будет при «Подтвердить счёт». Полоса
        показывает соотношение очков, подпись — разницу.

        Пока на доске камни только одного цвета, счёт формально отдаёт
        всю доску этому цвету (один камень в углу «замыкает» край).
        В этом случае вместо цифры честно пишем, что позиция не
        определена.
        """
        from ..scoring import score_area

        board = self.game.board
        black_stones = board.stones.count(BLACK)
        white_stones = board.stones.count(WHITE)
        known = black_stones > 0 and white_stones > 0

        result = score_area(board, self.game.komi) if known else None
        diff = (result.black - result.white) if result else 0.0
        share = _black_share(result.black, result.white) if result else 0.5

        arrow = "▾" if self.show_breakdown else "▸"
        title_color = ACCENT if (self._hover_score_block or
                                 self.show_breakdown) else TEXT_DIM
        title = f"{arrow} Счёт сейчас"
        draw_text(self.screen, title, (x, y), 14, title_color)
        # Запоминаем область блока: по ней ловим клик.
        self._score_rect = pygame.Rect(x - 6, y - 4, PANEL_W - 28, 0)
        y += 22

        bar_w = PANEL_W - 40
        bar_h = 16
        bar = pygame.Rect(x, y, bar_w, bar_h)
        # Светлая подложка под белые, тёмно-серый под чёрные: на панели
        # #282b30 чисто чёрная половина была бы неразличима.
        pygame.draw.rect(self.screen, (248, 246, 240), bar)

        if known:
            split = int(bar_w * share)
            if split > 0:
                pygame.draw.rect(self.screen, (24, 24, 28),
                                 pygame.Rect(bar.x, bar.y, split, bar_h))
        else:
            # Нейтральная полоса: считать пока нечего.
            pygame.draw.rect(self.screen, (120, 120, 128),
                             pygame.Rect(bar.x, bar.y, bar_w, bar_h))

        pygame.draw.rect(self.screen, (130, 130, 136), bar, 1)
        # Метка «ровно» посередине.
        mid = bar.x + bar_w // 2
        pygame.draw.line(self.screen, ACCENT_DARK,
                         (mid, bar.y - 3), (mid, bar.y + bar_h + 2), 1)
        y += bar_h + 8

        if not known:
            draw_text(self.screen, "позиция не определена", (x, y), 13,
                      TEXT_DIM, bold=True)
            y += 20
        elif abs(diff) < 0.05:
            draw_text(self.screen, "ровно", (x, y), 13, TEXT_DIM, bold=True)
            y += 20
        elif diff > 0:
            draw_text(self.screen, f"Чёрные +{diff:.1f}", (x, y), 13, TEXT,
                      bold=True)
            y += 20
        else:
            draw_text(self.screen, f"Белые +{-diff:.1f}", (x, y), 13, TEXT,
                      bold=True)
            y += 20

        if known and result is not None:
            draw_text(self.screen,
                      f"камни {result.black_stones} / {result.white_stones}"
                      f" · терр. {result.black_territory} / {result.white_territory}",
                      (x, y), 12, TEXT_DIM, max_width=PANEL_W - 40)
        else:
            draw_text(self.screen, f"камней: {black_stones} / {white_stones}",
                      (x, y), 12, TEXT_DIM)
        y += 22

        if self.show_breakdown:
            y = self._draw_breakdown(x, y, result, known)
            self._score_rect.height = y - self._score_rect.y + 2
        else:
            self._score_rect.height = y - self._score_rect.y + 18
        return y

    def _draw_breakdown(self, x: int, y: int, result, known: bool) -> int:
        """Расшифровка: из чего складывается счёт каждой стороны."""
        if not known or result is None:
            draw_text(self.screen, "Считать пока нечего", (x, y + 4), 12,
                      TEXT_DIM)
            return y + 24

        right = x + PANEL_W - 46
        # Компактно: две строки на сторону + итог + строка о группе.
        draw_text(self.screen,
                  f"Ч {result.black_stones}кам + {result.black_territory}терр",
                  (x, y), 12, TEXT)
        draw_text(self.screen, f"{result.black:.1f}", (right, y), 12, TEXT,
                  bold=True, right=True)
        y += 16

        draw_text(self.screen,
                  f"Б {result.white_stones}кам + {result.white_territory}терр"
                  f" + {result.komi:.1f}",
                  (x, y), 12, TEXT)
        draw_text(self.screen, f"{result.white:.1f}", (right, y), 12, TEXT,
                  bold=True, right=True)
        y += 18

        pygame.draw.line(self.screen, (70, 74, 80), (x, y), (right, y), 1)
        y += 5

        diff = result.black - result.white
        if abs(diff) < 0.05:
            draw_text(self.screen, "ровно", (x, y), 12, TEXT_DIM, bold=True)
        elif diff > 0:
            draw_text(self.screen, f"Чёрные +{diff:.1f}", (x, y), 12, ACCENT,
                      bold=True)
        else:
            draw_text(self.screen, f"Белые +{-diff:.1f}", (x, y), 12, ACCENT,
                      bold=True)

        zones = self.zones()
        neutral = sum(z.size for z in zones if z.owner == 0)
        if neutral:
            draw_text(self.screen, f"спорных: {neutral}", (right, y), 11,
                      TEXT_DIM, right=True)
        y += 16

        info = self._hover_group_info
        if info is not None:
            stones, libs = info
            draw_text(self.screen,
                      f"группа {stones} камн., дамэ {libs}",
                      (x, y), 11, ACCENT, max_width=PANEL_W - 40)
            y += 15
        return y

    def _draw_hover_group(self) -> None:
        """Подсветить группу под курсором, если включён разбор счёта.

        В режиме разметки территории клик по камню означает «мёртвый»,
        поэтому подсветку там не показываем — только зоны и числа.
        """
        if self.game.phase == GamePhase.SCORING:
            return
        point = self.hover_point
        if point is None:
            return
        board = self.game.board
        if board.stones[point] == 0:
            return
        group, liberties = board.group_info(point)
        self.board_view._draw_group_highlight(
            self.screen, board, group, liberties)
        # Текст в панель дописывает _draw_breakdown через атрибут.
        self._hover_group_info = (len(group), len(liberties))

    def _draw_move_log(self) -> None:
        """Небольшой журнал последних ходов внизу панели."""
        px = WINDOW_W - PANEL_W + 20
        y = 620
        draw_text(self.screen, "Последние ходы", (px, y), 14, TEXT_DIM)
        y += 20
        for m in self.game.moves[-6:]:
            name = "Ч" if m.color == BLACK else "Б"
            text = f"{m.number:3d}. {name} {format_point(self.game.size, m.point)}"
            draw_text(self.screen, text, (px, y), 13, TEXT)
            y += 18

    def _draw_settings(self) -> None:
        r = self.settings_rect
        # Непрозрачный фон: иначе сквозь панель просвечивают подписи
        # основного интерфейса и получается мешанина.
        pygame.draw.rect(self.screen, PANEL, r)
        pygame.draw.rect(self.screen, ACCENT_DARK, r, 1)

        x = r.x + 16
        y = r.y + 14
        draw_text(self.screen, "Настройки партии", (x, y), 18, ACCENT, bold=True)
        draw_text(self.screen, "Размер доски", (x, y + 40), 13, TEXT_DIM)
        draw_text(self.screen, "Ваш цвет", (x, y + 116), 13, TEXT_DIM)
        draw_text(self.screen, "Уровень ИИ", (x, y + 192), 13, TEXT_DIM)

        self.size_group.draw(self.screen)
        self.color_group.draw(self.screen)
        self.level_group.draw(self.screen)
        self.komi_slider.draw(self.screen)
        self.btn_close_settings.draw(self.screen)

        # Время на ход задаётся уровнем и размером доски — показываем,
        # чтобы не было вопросов «сколько ждать».
        seconds = self.engine.budget()
        text = f"≈ {seconds:.1f} с на ход".replace(".0 с", " с")
        draw_text(self.screen, text, (x, y + 254), 12, ACCENT)

        # Пояснение к коми: что это вообще такое.
        draw_text(self.screen,
                  "компенсация белым за первый ход",
                  (x, y + 326), 12, TEXT_DIM,
                  max_width=self.settings_rect.width - 32)

        # Подпись правил в две строки: одной строкой она упиралась в
        # правый край панели и выглядела обрезанной.
        draw_text(self.screen, "Правила: китайские", (x, r.bottom - 44),
                  12, TEXT_DIM)
        draw_text(self.screen, "позиционное суперко", (x, r.bottom - 28),
                  12, TEXT_DIM)


def main(size: int = 9, level: str = "normal") -> None:
    App(size=size, level=level).run()
