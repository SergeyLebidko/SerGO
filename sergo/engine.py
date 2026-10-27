"""Фасад ИИ: уровни сложности и удобный интерфейс для UI.

ИИ считает в отдельном потоке, поэтому здесь всё сделано так, чтобы
расчёт можно было безопасно отменить (флаг cancel) — например, когда
игрок нажал «Новая игра».
"""

from __future__ import annotations

import random
import threading

from .board import Board, BLACK, PASS
from .mcts import MCTS
from .policy import find_free_capture
from .scoring import estimate_score_fast


# Уровни: сила задаётся бюджетом времени, числом кандидатов и шансом
# намеренной ошибки. Время зависит ещё и от размера доски: на 19×19
# нужно заметно больше симуляций, чтобы получить ту же глубину тактики.
LEVELS = {
    "easy": {
        "label": "Легко",
        "blunder": 0.35,
        "candidates": 40,
        "time": {9: 1.0, 13: 1.5, 19: 2.0},
    },
    "normal": {
        "label": "Средне",
        "blunder": 0.10,
        "candidates": 64,
        "time": {9: 3.0, 13: 4.0, 19: 5.0},
    },
    "hard": {
        "label": "Сложно",
        "blunder": 0.00,
        "candidates": 96,
        "time": {9: 6.0, 13: 8.0, 19: 10.0},
    },
}

DEFAULT_LEVEL = "normal"


def _diff_to_winrate(diff: float, size: int, color: int) -> float:
    """Перевести разницу очков в вероятность победы (0..1).

    Масштаб тот же, что в MCTS: так оценка тактического хода
    согласована с оценками поиска.
    """
    import math
    scale = max(4.0, size / 2.0)
    p_black = 0.5 + 0.5 * math.tanh(diff / scale)
    return p_black if color == BLACK else 1.0 - p_black


def level_time(level: str, size: int) -> float:
    """Сколько секунд думает ИИ данного уровня на доске size×size."""
    cfg = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    table = cfg["time"]
    # Для нестандартных размеров берём ближайший из известных.
    if size in table:
        return table[size]
    nearest = min(table, key=lambda s: abs(s - size))
    return table[nearest]


class Engine:
    """Обёртка над MCTS с уровнями сложности."""

    def __init__(self, board: Board, komi: float = 6.5,
                 level: str = DEFAULT_LEVEL, seed: int | None = None,
                 time_override: float | None = None):
        self.board = board
        self.komi = komi
        self.level = level if level in LEVELS else DEFAULT_LEVEL
        # Служебный параметр для тестов: фиксированное время вместо
        # расчётного по уровню. В интерфейсе не используется.
        self.time_override = time_override
        self.rng = random.Random(seed)
        self.mcts: MCTS | None = None
        # Счётчик поколений вместо Event: отмена не должна
        # распространяться на следующий расчёт.
        self._generation = 0

    # ------------------------------------------------------------------ настройки

    def set_board(self, board: Board) -> None:
        """Сменить доску (новая партия) и сбросить дерево."""
        self.board = board
        self.mcts = None

    def set_level(self, level: str) -> None:
        """Сменить уровень. Время и число кандидатов меняются вместе с ним."""
        if level in LEVELS:
            self.level = level
            self.mcts = None

    def cancel(self) -> None:
        """Попросить ИИ остановиться при первой возможности.

        Увеличиваем счётчик поколений: расчёт, запущенный раньше, увидит
        расхождение и остановится. Новый расчёт получает свежий номер,
        поэтому отмена не «залипает» — в отличие от простого флага,
        который после смены настроек обрывал следующий поиск на 32-й
        симуляции.
        """
        self._generation += 1

    # ------------------------------------------------------------------ ход

    def budget(self) -> float:
        """Сколько секунд думать на этом уровне и размере доски."""
        if self.time_override is not None:
            return max(0.05, self.time_override)
        return level_time(self.level, self.board.size)

    def _ensure_mcts(self) -> MCTS:
        if self.mcts is None:
            # Длина розыгрыша проверена матчами: увеличение лимита
            # (120 на 9×9) давало меньше симуляций за то же время и
            # проигрывало по силе. Оставлено прежнее значение.
            self.mcts = MCTS(
                self.board, self.komi, self.rng,
                max_candidates=LEVELS[self.level]["candidates"],
                rollout_limit=max(36, min(64, self.board.n // 2)),
            )
        return self.mcts

    def choose_move(self, color: int) -> int:
        """Синхронно выбрать ход (для тестов и CLI)."""
        return self.choose_move_detailed(color)[0]

    def choose_move_detailed(self, color: int) -> tuple[int, float, int]:
        """(ход, winrate, симуляции)."""
        # Простая тактическая страховка: если есть безопасный захват,
        # берём его, не тратя время на поиск. MCTS на малом бюджете
        # иногда «не замечает» очевидное.
        free = find_free_capture(self.board, color)
        if free is not None and free not in self.board.hash_set:
            # Оценку всё равно считаем по позиции после этого хода:
            # возвращать заглушку 0.5 нельзя, иначе в интерфейсе
            # появляются фиктивные «50%».
            rec = self.board.play(free, color)
            if rec is not None:
                diff = estimate_score_fast(self.board, self.komi)
                self.board.undo(rec)
                winrate = _diff_to_winrate(diff, self.board.size, color)
            else:
                winrate = 0.5
            return free, winrate, 0

        mcts = self._ensure_mcts()
        budget = self.budget()

        # Запоминаем поколение на старте: если за время поиска случится
        # отмена (новая партия, смена настроек), номер изменится и поиск
        # остановится. Следующий расчёт начнёт с нового номера.
        token = self._generation
        move, winrate, sims = mcts.think(
            color, budget, cancel=lambda: self._generation != token)

        # На лёгком уровне иногда намеренно ошибаемся — иначе новичку
        # будет неинтересно играть.
        blunder = LEVELS[self.level]["blunder"]
        if blunder and self.rng.random() < blunder:
            legal = self.board.legal_moves(color, include_pass=True)
            if len(legal) > 1:
                move = self.rng.choice(legal)

        return move, winrate, sims

    def think_async(self, color: int, callback) -> threading.Thread:
        """Запустить расчёт в фоне и вызвать callback(move, winrate, sims)."""
        def worker():
            try:
                result = self.choose_move_detailed(color)
            except Exception as exc:  # pragma: no cover - защита UI
                result = (PASS, 0.5, 0, exc)
            callback(result)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def forget(self) -> None:
        """Начать поиск «с нуля» (после отмены или новой партии)."""
        self.mcts = None
