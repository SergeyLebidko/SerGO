"""Модель партии: ходы, история, сдача, подсчёт.

Отделена от интерфейса, чтобы правила и логику партии можно было
тестировать без pygame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .board import Board, BLACK, WHITE, PASS, EMPTY, format_point, other
from .scoring import Score, score, dead_stones_heuristic


class GamePhase:
    PLAYING = "playing"
    SCORING = "scoring"
    FINISHED = "finished"


@dataclass
class Move:
    """Запись хода для истории и отмены."""

    number: int
    color: int
    point: int
    record: object
    captures: tuple[int, ...] = ()
    analysis: float = 0.5
    simulations: int = 0
    by_ai: bool = False

    def label(self, size: int) -> str:
        name = "Ч" if self.color == BLACK else "Б"
        return f"{self.number}. {name} {format_point(size, self.point)}"


@dataclass
class Game:
    """Состояние партии."""

    size: int = 9
    komi: float = 6.5
    rules: str = "chinese"
    handicap: int = 0
    board: Board = field(default=None)  # type: ignore[assignment]
    phase: str = GamePhase.PLAYING
    turn: int = BLACK
    passes: int = 0
    moves: list[Move] = field(default_factory=list)
    result: Score | None = None
    winner: int = 0
    resigned: int = 0          # кто сдался (0 — никто)
    dead: set[int] = field(default_factory=set)
    last_move: int = -1
    message: str = ""

    def __post_init__(self) -> None:
        if self.board is None:
            self.new_game(self.size, self.komi, self.rules)

    # ------------------------------------------------------------------ партия

    def new_game(self, size: int | None = None, komi: float | None = None,
                 rules: str | None = None) -> None:
        if size is not None:
            self.size = size
        if komi is not None:
            self.komi = komi
        if rules is not None:
            self.rules = rules

        self.board = Board(self.size)
        self.phase = GamePhase.PLAYING
        self.turn = BLACK
        self.passes = 0
        self.moves.clear()
        self.result = None
        self.winner = 0
        self.resigned = 0
        self.dead.clear()
        self.last_move = -1
        self.message = ""

    def can_play(self) -> bool:
        return self.phase == GamePhase.PLAYING and not self.resigned

    def play(self, point: int, color: int | None = None,
             analysis: float = 0.5, simulations: int = 0,
             by_ai: bool = False) -> bool:
        """Сделать ход. Возвращает False, если ход невозможен."""
        if not self.can_play():
            return False
        if color is None:
            color = self.turn
        if color != self.turn:
            return False

        rec = self.board.play(point, color)
        if rec is None:
            return False

        move = Move(
            number=len(self.moves) + 1,
            color=color,
            point=point,
            record=rec,
            captures=rec.captured if hasattr(rec, "captured") else (),
            analysis=analysis,
            simulations=simulations,
            by_ai=by_ai,
        )
        self.moves.append(move)

        self.last_move = point if point != PASS else -1
        if point == PASS:
            self.passes += 1
        else:
            self.passes = 0
        self.turn = other(color)

        if self.passes >= 2:
            self.begin_scoring()
        return True

    def undo(self) -> bool:
        """Отменить последний ход."""
        if not self.moves:
            return False
        if self.phase == GamePhase.FINISHED:
            return False

        move = self.moves.pop()
        self.board.undo(move.record)
        self.turn = move.color
        self.last_move = self.moves[-1].point if self.moves else -1
        if self.last_move == PASS:
            self.last_move = self._previous_point()
        self.passes = self._count_trailing_passes()
        self.phase = GamePhase.PLAYING
        self.result = None
        self.dead.clear()
        return True

    def _previous_point(self) -> int:
        for m in reversed(self.moves):
            if m.point != PASS:
                return m.point
        return -1

    def _count_trailing_passes(self) -> int:
        count = 0
        for m in reversed(self.moves):
            if m.point == PASS:
                count += 1
            else:
                break
        return count

    def resign(self, color: int) -> None:
        """Игрок цвета color сдаётся."""
        if self.phase != GamePhase.PLAYING:
            return
        self.resigned = color
        self.winner = other(color)
        self.phase = GamePhase.FINISHED
        name = "Чёрные" if color == BLACK else "Белые"
        self.message = f"{name} сдались."

    # ------------------------------------------------------------------ подсчёт

    def begin_scoring(self) -> None:
        """Перейти к разметке территории после двух пасов."""
        self.phase = GamePhase.SCORING
        self.dead = dead_stones_heuristic(self.board)
        self.update_score()

    def update_score(self) -> Score:
        self.result = score(self.board, self.komi, self.dead, self.rules)
        self.winner = self.result.winner()
        return self.result

    def toggle_dead(self, point: int) -> None:
        """Пометить/снять пометку мёртвого камня и пересчитать."""
        if self.phase != GamePhase.SCORING:
            return
        if self.board.stones[point] == EMPTY:
            return
        grp, _ = self.board.group_info(point)
        if point in self.dead:
            self.dead.difference_update(grp)
        else:
            self.dead.update(grp)
        self.update_score()

    def finish_scoring(self) -> None:
        if self.phase != GamePhase.SCORING:
            return
        self.update_score()
        self.phase = GamePhase.FINISHED
        if self.result is not None:
            self.message = self.result.text()

    def resume_play(self) -> None:
        """Продолжить партию, если разметка оказалась неверной."""
        if self.phase != GamePhase.SCORING:
            return
        self.phase = GamePhase.PLAYING
        self.dead.clear()
        self.result = None
        self.passes = 0

    # ------------------------------------------------------------------ сводка

    def captured(self, color: int) -> int:
        """Сколько камней захватил color."""
        return self.board.caps[color]

    def move_number(self) -> int:
        return len(self.moves)

    def status_line(self) -> str:
        """Строка состояния для панели."""
        if self.phase == GamePhase.FINISHED:
            return self.message or "Партия окончена"
        if self.phase == GamePhase.SCORING:
            return "Разметка территории"
        if self.phase == GamePhase.PLAYING:
            name = "Чёрные" if self.turn == BLACK else "Белые"
            extra = " (пас)" if self.passes else ""
            return f"Ход {self.move_number() + 1}: {name}{extra}"
        return ""
