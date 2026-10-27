#!/usr/bin/env python3
"""Сторож личных следов: ищет в отслеживаемых файлах репозитория маркеры из файла (имена людей, проектов, меток).

Запуск: check-traces.py [--markers ФАЙЛ] [--repo ПАПКА] [-- pathspec…]
Маркеры — по одной строке; пустые и строки с «#» в начале пропускаются. Файл — аргументом или из переменной
PANTHEON_TRACE_MARKERS. Сам список маркеров в репозиторий не кладём и в вывод не печатаем (только совпавший).
Исключений нет: ни путей, ни меток в строке — проверяется весь репозиторий (metis-0182, guard 0.5.10).
Коды выхода: 0 — следов нет; 1 — найдены; 2 — файла маркеров нет, он пуст или не читается (пропуск, но не «зелёный»).
Только стандартная библиотека, Python 3.11+ (metis-0571).
"""
import os
import subprocess
import sys
import tempfile

def load_markers(path):
    """Список маркеров из файла; None — файла нет, он не читается или в нём нет ни одного маркера."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh.read().splitlines()]
    except (OSError, UnicodeDecodeError):
        return None
    return [ln for ln in lines if ln and not ln.startswith("#")] or None


def main(argv):
    args, spec = argv, []
    if "--" in argv:
        i = argv.index("--")
        args, spec = argv[:i], argv[i + 1:]
    markers_path = os.environ.get("PANTHEON_TRACE_MARKERS")
    repo = None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--markers", "--repo") and i + 1 < len(args):
            if a == "--markers":
                markers_path = args[i + 1]
            else:
                repo = args[i + 1]
            i += 2
        else:
            print(f"check-traces: непонятный аргумент {a!r}", file=sys.stderr)
            return 2
    if repo is None:
        here = os.path.dirname(os.path.realpath(__file__))
        r = subprocess.run(["git", "-C", here, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode != 0:
            print("check-traces: папка скрипта не в репозитории, укажите --repo", file=sys.stderr)
            return 2
        repo = r.stdout.strip()
    markers = load_markers(markers_path)
    if markers is None:
        print("check-traces: предупреждение — файла маркеров нет, он пуст или не читается "
              "(--markers ФАЙЛ или PANTHEON_TRACE_MARKERS): проверка пропущена", file=sys.stderr)
        return 2
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(markers) + "\n")  # без пустых строк: пустой шаблон поиска совпал бы со всем
        tmp = fh.name
    try:
        r = subprocess.run(["git", "-C", repo, "grep", "-n", "-I", "-F", "-f", tmp, "--", *(spec or ["."])],
                           capture_output=True)
    finally:
        os.remove(tmp)
    if r.returncode not in (0, 1):
        print("check-traces: поиск не отработал: " + r.stderr.decode("utf-8", "replace").strip()[:200],
              file=sys.stderr)
        return 2
    found = []
    for raw in r.stdout.decode("utf-8", "replace").splitlines():
        parts = raw.split(":", 2)
        if len(parts) < 3:
            continue
        hit = next((m for m in markers if m in parts[2]), None)
        if hit:
            found.append(f"{parts[0]}:{parts[1]}: {hit}")
    if found:
        print("\n".join(found))
        return 1
    print("следов нет")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
