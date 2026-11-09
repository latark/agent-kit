#!/usr/bin/env python3
"""Сверка карты решений Пантеона с файлом пересмотров.

Что проверяет:
  - у каждой строки 8 колонок и уникальный ID;
  - состояние — из словаря карты;
  - у каждой строки, кроме «отклонено», есть файл; у каждой строки «план», «частично», «вы» есть проверка;
  - каждая ссылка «Пересм.» есть в revisits.toml, а каждая строка revisits.toml ссылается на существующие ID;
  - строки со словами «на время», «временно», «пока так», «до пересмотра» (вне кавычек «») без строки
    пересмотра — предупреждение;
  - с --files: файлы строк «есть» и «проверено» существуют на диске — нынешнее место, до «→»
    (для недельной сверки библиотекаря).

Запуск: python3 -I decision-map-check.py [путь к decision-map.md] [--files] [--by-step]
По умолчанию берёт ~/ai/pantheon/decision-map.md и revisits.toml рядом с ним.
Код выхода 0 — ошибок нет (предупреждения не считаются), 1 — есть ошибки.
"""
import os
import re
import sys
try:
    import tomllib
except ImportError:  # системный python 3.9 на macOS
    sys.exit("pantheon: нужен Python 3.11+ (нет tomllib)")
from collections import Counter, defaultdict

STATES = {"план", "есть", "частично", "вы", "не сейчас", "отклонено", "проверено"}
NEED_CHECK = {"план", "частично", "вы"}
TEMP_WORDS = re.compile(r"(на время|\bвременно\b|пока так|до пересмотра|проверить в пилоте)", re.IGNORECASE)
QUOTED = re.compile(r"«[^»]*»")
# «ak/<плагин>/…» — файл кода agent-kit: рабочая копия ~/ai/agent-kit (metis-0899), пока её нет на этом Mac —
# клон маркетплейса с тем же main
AGENT_KIT = "~/ai/agent-kit"
AGENT_KIT_CLONE = "~/.claude/plugins/marketplaces/agent-kit"


def parse_rows(text):
    rows = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| ") or line.startswith("| ---") or line.startswith("| ID "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if not re.match(r"^[A-Z]+-\d+$", cells[0]):
            continue
        rows.append((n, cells))
    return rows


def expand(path):
    path = path.strip("`")
    if path.startswith("ak/"):
        parts = path.split("/", 2)
        kit = os.path.expanduser(AGENT_KIT)
        kit = kit if os.path.isdir(kit) else os.path.expanduser(AGENT_KIT_CLONE)
        return os.path.join(kit, "plugins", parts[1], parts[2] if len(parts) > 2 else "")
    if path.startswith("ms/"):
        return os.path.expanduser("~/projects/mac-setup/" + path[3:])
    if path.startswith("роль "):
        return os.path.expanduser(f"~/.claude/agents/{path[5:]}.md")
    return os.path.expanduser(path)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    map_path = args[0] if args else os.path.expanduser("~/ai/pantheon/decision-map.md")
    rev_path = os.path.join(os.path.dirname(map_path), "revisits.toml")

    text = open(map_path, encoding="utf-8").read()
    rows = parse_rows(text)
    with open(rev_path, "rb") as f:
        revisits = tomllib.load(f).get("revisit", [])
    rev_ids = {r["id"] for r in revisits}

    errors, warnings = [], []
    ids = Counter(c[0] for _, c in rows)
    for i, k in ids.items():
        if k > 1:
            errors.append(f"{i}: ID повторяется {k} раз")

    known = set(ids)
    used_revs = set()
    for n, c in rows:
        if len(c) != 8:
            errors.append(f"строка {n} ({c[0]}): {len(c)} колонок вместо 8")
            continue
        rid, decision, _where, file_, check, _step, state, rev = c
        if state not in STATES:
            errors.append(f"{rid}: неизвестное состояние «{state}»")
        if state != "отклонено" and (file_ == "" or file_.startswith("—")):
            errors.append(f"{rid}: нет файла")
        if state in NEED_CHECK and check in ("", "—"):
            errors.append(f"{rid}: нет проверки")
        for r in re.findall(r"R-[a-z0-9-]+", rev):
            used_revs.add(r)
            if r not in rev_ids:
                errors.append(f"{rid}: пересмотр {r} не найден в revisits.toml")
        if TEMP_WORDS.search(QUOTED.sub("", decision)) and rev == "—" and state not in ("отклонено", "не сейчас"):
            warnings.append(f"{rid}: в решении есть признак временного, а строки пересмотра нет")
        if "--files" in sys.argv and state in ("есть", "проверено"):
            for p in re.findall(r"`([^`]+)`", file_.split("→")[0]):
                if p.startswith(("~", "ak/", "ms/")) and "<" not in p and "*" not in p:
                    if not os.path.exists(expand(p)):
                        errors.append(f"{rid}: файла нет на диске — {p}")

    for r in revisits:
        if not r.get("decisions"):
            errors.append(f"revisits.toml {r['id']}: нет ссылок на строки карты")
        for d in r.get("decisions", []):
            if d not in known:
                errors.append(f"revisits.toml {r['id']}: ссылка на несуществующую строку {d}")
        if r["id"] not in used_revs:
            warnings.append(f"revisits.toml {r['id']}: на него не ссылается ни одна строка карты")

    states = Counter(c[6] for _, c in rows if len(c) == 8)
    print(f"Строк: {len(rows)}; " + ", ".join(f"{k} — {v}" for k, v in states.most_common()))
    print(f"Пересмотров: {len(revisits)}")
    if "--by-step" in sys.argv:
        by_step = defaultdict(list)
        for _, c in rows:
            if len(c) == 8 and c[6] not in ("отклонено",):
                by_step[c[5]].append(c[0])
        def key(s):
            m = re.match(r"(\d+)(?:\.(\d+))?", s)
            return (0, int(m.group(1)), int(m.group(2) or 0)) if m else (1, 0, 0)
        for s in sorted(by_step, key=key):
            print(f"  шаг {s}: {', '.join(by_step[s])}")
    for w in warnings:
        print("предупреждение:", w)
    for e in errors:
        print("ошибка:", e)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
