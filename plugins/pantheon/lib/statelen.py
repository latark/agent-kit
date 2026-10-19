"""Длина файлов состояния (metis-0160, metis-0274): общая проверка для дежурного (`pantheon check`) и хука
PostToolUse (hooks/ctx.py state-len). Только стандартная библиотека и Python 3.9: хук запускает системный python3."""
import glob
import os

STATE_FILE_LIMIT = 9000  # знаков: после сжатия хук кладёт первые ~9 800, хвост файла теряется (metis-0160)


def state_files(pantheon):
    """Файлы состояния: STATUS.md направлений и board.md штаба (пути под pantheon)."""
    return sorted(glob.glob(os.path.join(pantheon, "directions", "*", "STATUS.md"))) + [os.path.join(pantheon, "board.md")]


def is_state_file(path, pantheon):
    """path — файл состояния (по тем же адресам, что state_files); ссылки раскрываются."""
    try:
        p = os.path.realpath(path)
        root = os.path.realpath(pantheon)
    except (OSError, ValueError, TypeError):
        return False
    if p == os.path.join(root, "board.md"):
        return True
    rel = os.path.relpath(p, root).split(os.sep)
    return len(rel) == 3 and rel[0] == "directions" and rel[2] == "STATUS.md" and rel[1] not in ("", ".", "..")


def length(path):
    """Знаков (символов, не байт) в файле; None — файл не прочитать."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return len(fh.read())
    except OSError:
        return None
