#!/usr/bin/env python3
"""Хук PermissionDenied: строка отказа классификатора в журнал (metis-1135, часть Д).

  denials.py hook   событие со stdin → STATE/denials/<дата>.jsonl; логика — lib/denials.py.
Тонкая обёртка: запускатель hooks/python.sh берёт скрипты хуков из hooks/. Любой сбой — код 0 без вывода.
"""
import importlib.util
import os
import sys


def main():
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib", "denials.py")
    spec = importlib.util.spec_from_file_location("pantheon_denials_hook", lib)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.main(sys.argv[1:])


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:  # noqa: BLE001 — хук не должен мешать работе
        rc = 0
    sys.exit(rc)
