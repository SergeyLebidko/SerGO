#!/usr/bin/env python3
"""Точка входа SerGO.

Запуск графической игры:
    python3 start.py
    python3 start.py --size 13 --level hard
    python3 start.py --cli --size 9
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback


def _show_error(title: str, message: str) -> None:
    """Показать ошибку так, чтобы её увидели при запуске двойным кликом.

    При запуске из ярлыка терминала нет, поэтому обычный traceback
    пропадёт. Пробуем диалог, а если не вышло — пишем файл рядом.
    """
    print(f"{title}\n{message}", file=sys.stderr)

    # 1. Диалог через zenity или xmessage — они есть в Cinnamon/X11.
    for cmd in (
        ["zenity", "--error", "--title", title, "--no-wrap",
         "--text", message],
        ["xmessage", "-center", f"{title}\n\n{message}"],
    ):
        try:
            import subprocess
            if subprocess.run(cmd, timeout=120).returncode == 0:
                return
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    # 2. tkinter, если установлен.
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
        return
    except Exception:
        pass

    # 3. Файл с подробностями — последний вариант.
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "sergo_error.log")
    try:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(f"{title}\n\n{message}\n")
        print(f"Подробности записаны в {log_path}", file=sys.stderr)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SerGO — Го с собственным ИИ",
        add_help=True,
    )
    parser.add_argument("--size", type=int, default=9, choices=(9, 13, 19),
                        help="размер доски (по умолчанию 9)")
    parser.add_argument("--level", default="normal",
                        choices=("easy", "normal", "hard"),
                        help="уровень ИИ (по умолчанию normal)")
    parser.add_argument("--cli", action="store_true",
                        help="играть в терминале без графики")
    args = parser.parse_args()

    if args.cli:
        from sergo.cli import run_cli
        return run_cli(args.size, args.level)

    try:
        import pygame  # noqa: F401
    except ImportError:
        _show_error(
            "SerGO — не найден pygame",
            "Для графического режима нужен pygame.\n\n"
            "Установите его командой:\n"
            "    pip install pygame\n\n"
            "Либо запустите терминальную версию:\n"
            "    python3 start.py --cli",
        )
        return 1

    try:
        from sergo.ui import main as run_ui
        run_ui(size=args.size, level=args.level)
    except Exception:
        _show_error("SerGO — ошибка запуска", traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
