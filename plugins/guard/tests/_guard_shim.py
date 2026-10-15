#!/usr/bin/env python3
"""Запуск hooks/guard.py для тестов так, чтобы результат не зависел от того, где их запускают (metis-0090).

    python3 -I _guard_shim.py <путь к guard.py> [--strict|--managed]   (stdin — событие хука)

guard.py не меняется. Подменяется только обвязка запуска:
1. Временный HOME тестов лежит в $TMPDIR, а в окне агента это /tmp/claude-<uid>: guard считает /tmp и /private/tmp
   временными корнями (TEMP_ROOTS) и разрешает запись во всё, что внутри, — в том числе в ~/ai/pantheon тестового HOME.
   Для путей внутри HOME теста корни, в которых лежит сам HOME, из TEMP_ROOTS не берутся. Пути вне HOME
   (/tmp/out.txt и т. п.) остаются временными, как в боевом guard. Если HOME не внутри временной папки — ничего не меняется.
2. Разрешение имён (check_cdp_role: «WebFetch в интернет») ходит в сеть; в песочнице DNS нет, и guard закрывает
   «не разрешилось». Имена разрешаются в публичный адрес (93.184.216.34, example.com: TEST-NET у ipaddress считается частным), IP-адреса — сами в себя.
"""
import importlib.util
import os
import socket
import sys

path, sys.argv = sys.argv[1], [sys.argv[1]] + sys.argv[2:]

_real_getaddrinfo = socket.getaddrinfo


def _getaddrinfo(host, port, *a, **kw):
    try:
        socket.inet_pton(socket.AF_INET, host)
        return _real_getaddrinfo(host, port, *a, **kw)
    except (OSError, TypeError):
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return _real_getaddrinfo(host, port, *a, **kw)
    except (OSError, TypeError):
        pass
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]


socket.getaddrinfo = _getaddrinfo

spec = importlib.util.spec_from_file_location("guard", path)
g = importlib.util.module_from_spec(spec)
sys.modules["guard"] = g
spec.loader.exec_module(g)

_home = g._key(os.path.realpath(os.environ["HOME"]))
_orig_inside = g._inside


def _inside(p, roots):
    if g._key(p).startswith(_home.rstrip("/") + "/") or g._key(p) == _home:
        roots = [r for r in roots
                 if not (r in g.TEMP_ROOTS and (_home + "/").startswith(g._key(r).rstrip("/") + "/"))]
    return _orig_inside(p, roots)


g._inside = _inside

try:
    g.main()
except Exception as e:  # как в блоке __main__ guard.py
    g.log_failure("main", e)
    if g.MODE == "strict":
        print(f"guard: сбой проверки ({type(e).__name__}) — действие остановлено", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)
