"""Monte-Carlo Tree Search с UCT и RAVE.

Бюджет задаётся временем: бот думает не «N симуляций», а «пока не вышло
время». Это единственный способ вести себя предсказуемо на досках
9×9, 13×13 и 19×19 одновременно.

Поддерживается:
  * переиспользование дерева между ходами;
  * отмена по флагу (для интерфейса);
  * учёт двух пасов подряд;
  * оценка позиции быстрым подсчётом площади.
"""

from __future__ import annotations

import math
import random
import time

from .board import Board, BLACK, WHITE, PASS, other
from .policy import candidate_moves, is_self_eye, play_rollout_move
from .scoring import estimate_score_fast

INF = float("inf")


class Node:
    """Узел дерева поиска."""

    __slots__ = (
        "move", "parent", "children", "untried", "color",
        "visits", "value", "amaf_visits", "amaf_value", "passes",
    )

    def __init__(self, move: int, parent: "Node | None", color: int, passes: int):
        self.move = move
        self.parent = parent
        self.children: list[Node] = []
        self.untried: list[int] | None = None
        self.color = color      # цвет, которым сыгран move
        self.visits = 0
        self.value = 0.0        # сумма выигрышей с точки зрения color
        self.amaf_visits = 0
        self.amaf_value = 0.0
        self.passes = passes    # сколько пасов подряд привело сюда

    def q(self) -> float:
        return self.value / self.visits if self.visits else 0.0

    def amaf_q(self) -> float:
        return self.amaf_value / self.amaf_visits if self.amaf_visits else 0.0

    def uct(self, c: float, rave_k: float = 900.0) -> float:
        if self.visits == 0:
            return INF
        parent_visits = self.parent.visits if self.parent else 1
        explore = c * math.sqrt(math.log(max(parent_visits, 1)) / self.visits)

        if self.amaf_visits:
            beta = math.sqrt(rave_k / (3.0 * self.visits + rave_k))
            mean = (1.0 - beta) * self.q() + beta * self.amaf_q()
        else:
            mean = self.q()
        return mean + explore


class MCTS:
    """Поиск лучшего хода для указанного цвета."""

    def __init__(self, board: Board, komi: float = 6.5,
                 rng: random.Random | None = None,
                 max_candidates: int = 64, c: float = 1.1,
                 rollout_limit: int | None = None):
        self.board = board
        self.komi = komi
        self.rng = rng or random.Random()
        self.max_candidates = max_candidates
        self.c = c
        self.rollout_limit = rollout_limit or max(120, board.n * 2)
        self.root: Node | None = None
        self.simulations = 0
        self.elapsed = 0.0
        self.cancelled = False
        self._root_player = BLACK
        self._root_hash = -1
        self._played: tuple[int, ...] = ()

    # ------------------------------------------------------------------ API

    def think(self, color: int, thinking_time: float = 2.0, cancel=None):
        """Вернуть (ход, winrate 0..1, число симуляций)."""
        self.cancelled = False
        self._root_player = color
        deadline = time.monotonic() + max(0.02, thinking_time)
        self.simulations = 0

        root = self.root
        if root is None or root.color != other(color) or \
                self._root_hash != self.board.hash:
            root = Node(-1, None, other(color), 0)
            self.root = root
        self._root_hash = self.board.hash

        start = time.monotonic()
        while self.simulations < 400000:
            self._iterate()
            self.simulations += 1
            if self.simulations >= 12 and time.monotonic() >= deadline:
                break
            if self.simulations % 32 == 0 and cancel is not None and cancel():
                self.cancelled = True
                break

        self.elapsed = time.monotonic() - start

        best = self.best_move()
        if best is None:
            return PASS, 0.5, self.simulations

        child = self._child_for(best)
        winrate = child.q() if child and child.visits else 0.5
        return best, winrate, self.simulations

    def best_move(self, min_visits: int = 1) -> int | None:
        """Самый посещённый ход (при равенстве — лучший по оценке)."""
        if self.root is None:
            return None
        best: Node | None = None
        for ch in self.root.children:
            if ch.visits < min_visits:
                continue
            if best is None or ch.visits > best.visits or (
                    ch.visits == best.visits and ch.q() > best.q()):
                best = ch
        return best.move if best else None

    def advance(self, move: int) -> None:
        """Сдвинуть корень на сыгранный ход (переиспользование дерева)."""
        if self.root is None:
            return
        for ch in self.root.children:
            if ch.move == move:
                ch.parent = None
                self.root = ch
                return
        self.root = None

    def root_value(self) -> float:
        """Оценка текущей позиции (winrate ходящего) по главной ветке."""
        if self.root is None or not self.root.children:
            return 0.5
        return max(ch.q() for ch in self.root.children)

    def move_stats(self) -> list[tuple[int, int, float]]:
        """(ход, посещения, winrate) — для подсказки в интерфейсе."""
        if self.root is None:
            return []
        data = [(ch.move, ch.visits, ch.q()) for ch in self.root.children]
        data.sort(key=lambda t: -t[1])
        return data

    # ------------------------------------------------------------------ внутреннее

    def _child_for(self, move: int) -> Node | None:
        if self.root is None:
            return None
        for ch in self.root.children:
            if ch.move == move:
                return ch
        return None

    def _iterate(self) -> None:
        board = self.board.fast_copy()
        root = self.root
        assert root is not None

        node = root
        path: list[Node] = []
        passes = root.passes

        # 1. Спуск по дереву.
        while node.children and not node.untried:
            node = self._select(node)
            path.append(node)
            if board.try_play(node.move, node.color) is False:
                # Позиция разошлась с деревом — считаем узел тупиком.
                self._backprop(path, 0.5, ())
                return
            passes = node.passes
            if node.move == PASS and passes >= 2:
                self._backprop(path, self._terminal_win(board), ())
                return

        # 2. Расширение.
        if not node.untried:
            color = other(node.color)
            moves = candidate_moves(board, color, self.max_candidates, self.rng)
            node.untried = [
                m for m in moves
                if m == PASS or not is_self_eye(board, m, color)
            ]

        if node.untried:
            idx = self.rng.randrange(len(node.untried))
            move = node.untried.pop(idx)
            color = other(node.color)
            if board.try_play(move, color) is False:
                return
            child = Node(move, node, color,
                         node.passes + 1 if move == PASS else 0)
            node.children.append(child)
            node = child
            path.append(node)
            passes = child.passes

            if move == PASS and passes >= 2:
                self._backprop(path, self._terminal_win(board), ())
                return
        elif not node.children:
            # Ходов нет вовсе — оцениваем позицию напрямую.
            self._backprop(path, self._terminal_win(board), ())
            return

        # 3. Розыгрыш.
        win = self._rollout(board, other(node.color), passes)
        self._backprop(path, win, self._played)

    def _select(self, node: Node) -> Node:
        best = None
        best_score = -INF
        for ch in node.children:
            score = ch.uct(self.c)
            if score > best_score:
                best_score = score
                best = ch
        assert best is not None
        return best

    def _terminal_win(self, board: Board) -> float:
        return self._diff_to_win(estimate_score_fast(board, self.komi))

    def _diff_to_win(self, diff: float) -> float:
        """Превратить разницу очков в «вероятность победы».

        Строгий 0/1 насыщается на выигранных позициях: все ходы кажутся
        одинаково выигрышными, и бот перестаёт замечать мелкую тактику.
        Поэтому используем сглаженную функцию — она даёт частичное
        предпочтение ходам, увеличивающим отрыв.
        """
        scale = max(4.0, self.board.size / 2.0)
        p_black = 0.5 + 0.5 * math.tanh(diff / scale)
        return p_black if self._root_player == BLACK else 1.0 - p_black

    def _rollout(self, board: Board, color: int, passes: int) -> float:
        """Случайная доигровка до двух пасов или лимита ходов."""
        played: list[int] = []
        last = PASS
        limit = self.rollout_limit

        for _ in range(limit):
            mv = play_rollout_move(board, color, last, self.rng)
            if mv == PASS:
                passes += 1
                if passes >= 2:
                    break
                last = PASS
                color = other(color)
                continue
            played.append(mv)
            passes = 0
            last = mv
            color = other(color)

        self._played = tuple(played)
        return self._diff_to_win(estimate_score_fast(board, self.komi))

    def _backprop(self, path: list[Node], win: float,
                  played: tuple[int, ...]) -> None:
        """Обновить статистику узлов вдоль пути.

        win — вероятность победы root_player.
        """
        root_player = self._root_player
        played_set = set(played) if played else ()
        for node in reversed(path):
            node.visits += 1
            if node.color == root_player:
                node.value += win
            else:
                node.value += 1.0 - win

            if played_set:
                for ch in node.children:
                    if ch.move in played_set:
                        ch.amaf_visits += 1
                        if ch.color == root_player:
                            ch.amaf_value += win
                        else:
                            ch.amaf_value += 1.0 - win

        if self.root is not None:
            self.root.visits += 1
