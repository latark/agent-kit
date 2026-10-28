#!/usr/bin/env python3
"""Субагенты главной сессии окна штаба и координаторов (P0-6 плана автономности; SEC-09, SEC-13, ROLE-32).

  agents.py <список через запятую>
      PreToolUse Agent|Task|Skill. Хук ставит `pantheon domains build` в настройки окон hq и направлений, список —
      в pantheon.py (HQ_AGENTS, COORDINATOR_AGENTS, COORDINATOR_EXTRA_AGENTS и лиды направления из реестра).
      - Событие с agent_id (зовёт субагент окна: лид — dev-*, argus) — пропуск: его границы — tools: роли и deny окна.
      - Agent/Task: тип — tool_input.subagent_type, пустой — general-purpose (так делает Claude Code). Тип не из
        списка (точное совпадение, регистр важен) — отказ JSON-ом (permissionDecision deny), код 0.
      - Skill: навык с context: fork в шапке SKILL.md идёт субагентом своего agent: (по умолчанию general-purpose)
        мимо инструмента Agent. Кандидаты — все SKILL.md, у которых имя папки или поле name: шапки совпадает с именем
        навыка, во всех корнях: ~/.claude/skills, .claude/skills в CLAUDE_PROJECT_DIR и в папке события и каждом её
        родителе; вложенное имя <путь>:<имя> — <папка>/<путь>/.claude/skills и навыки плагина <путь>. Отказ, если хоть
        у одного кандидата fork с неположенным agent: (лучше лишний отказ, чем пропуск).
      Отказ при сбое: исключение, битый stdin, пустой список — причина в stderr и код 2 (блок на любой версии Claude
      Code; onFailure: block появился только в 2.1.295). Отдельный файл, а не команда ctx.py: старая копия ctx.py без
      команды пропускала бы всё, а отсутствующий файл — тоже код 2.
Только стандартная библиотека; хуки запускает hooks/python.sh на Python 3.11+ (metis-0571).
"""
import glob
import json
import os
import re
import stat
import sys

SKILL_NAME = re.compile(r"[A-Za-z0-9_.:/-]+")
HEAD_MAX = 64 << 10       # шапку читаем из начала файла
FILES_MAX = 2000          # SKILL.md на один вызов: уложиться в таймаут хука 10 с


class Broken(Exception):
    """Вызов не разобрать — блок кодом 2."""


def deny(why, allowed):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "P0-6: %s Этому окну можно: %s. Веб — через prometheus, код — через своего лида "
                                    "(у Пританея — поручение направлению)." % (why, ", ".join(allowed))}}))
    # ensure_ascii по умолчанию: у хука без LANG stdout бывает ascii, а \\u-escape — тот же JSON


def read_head(p):
    """Начало обычного файла или None. Ссылки — как есть (папки навыков бывают ссылками); FIFO и устройство не
    читаются и не вешают хук (O_NONBLOCK)."""
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        return os.read(fd, HEAD_MAX).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def head_of(text):
    """Поля name, context, agent шапки YAML (между первыми ---); {} — шапки нет."""
    lines = text.lstrip(chr(0xFEFF)).splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            return out
        m = re.match(r"(name|context|agent)\s*:(.*)$", ln)
        if m:
            out[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\"").strip()
    return {}  # шапка не закрыта — не шапка


class Finder:
    def __init__(self, name):
        self.name, self.read, self.found = name, 0, []

    def file(self, p, folder):
        """SKILL.md — кандидат, если имя папки или name: шапки совпадает с именем навыка."""
        if self.read >= FILES_MAX:
            raise Broken("навыков больше %d — не проверить за время хука" % FILES_MAX)
        self.read += 1
        text = read_head(p)
        if text is None:
            return
        h = head_of(text)
        if folder == self.name or h.get("name") == self.name:
            self.found.append((p, h))

    def root(self, skills):
        """<корень>/*/SKILL.md."""
        try:
            names = sorted(os.listdir(skills))
        except OSError:
            return
        for n in names:
            self.file(os.path.join(skills, n, "SKILL.md"), n)

    def plugin(self, plugin):
        cache = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache")
        for p in sorted(glob.glob(os.path.join(cache, "*", glob.escape(plugin), "*", "skills", "*", "SKILL.md"))):
            self.file(p, os.path.basename(os.path.dirname(p)))


def parents(d):
    d = os.path.abspath(d)
    while True:
        yield d
        up = os.path.dirname(d)
        if up == d:
            return
        d = up


def skill_types(ev, ti):
    """(имя навыка, [типы субагентов кандидатов с context: fork]). Не навык (имя не по образцу) — []: Claude Code его
    тоже не найдёт. guard — защита от ошибок агента, а не от намеренного обхода (AGENTS.md)."""
    name = ti.get("skill")
    if not isinstance(name, str):
        raise Broken("имя навыка не строка")
    name = name.strip().lstrip("/")
    if not SKILL_NAME.fullmatch(name) or ".." in name:
        return name, []
    cwd = ev.get("cwd") if isinstance(ev.get("cwd"), str) and ev.get("cwd") else None
    up = list(parents(cwd)) if cwd else []
    proj = [os.environ["CLAUDE_PROJECT_DIR"]] if os.environ.get("CLAUDE_PROJECT_DIR") else []
    if ":" in name:
        # <путь>:<имя> — вложенный .claude/skills (apps/web:deploy) или навык плагина <путь>
        prefix, base = name.rsplit(":", 1)
        if not prefix or not base:
            return name, []
        f = Finder(base)
        for d in up[:1] + proj + up[1:]:
            f.root(os.path.join(d, prefix, ".claude", "skills"))
        if "/" not in prefix:
            f.plugin(prefix)
    else:
        f = Finder(name)
        for d in [os.path.join(os.path.expanduser("~"), ".claude")] + [os.path.join(d, ".claude") for d in proj + up]:
            f.root(os.path.join(d, "skills"))
    types = [h.get("agent") or "general-purpose" for _, h in f.found if h.get("context") == "fork"]
    return name, types


def check(ev, allowed):
    """Причина отказа или None. Broken — блок кодом 2."""
    if not isinstance(ev, dict) or not ev:
        raise Broken("событие не разобрать")
    if ev.get("agent_id"):
        return None
    ti = ev.get("tool_input")
    if not isinstance(ti, dict):
        raise Broken("аргументы вызова не разобрать")
    if ev.get("tool_name") == "Skill":
        name, types = skill_types(ev, ti)
        bad = [t for t in types if t not in allowed]
        return "навык %s идёт субагентом %s, окну он не положен." % (name, bad[0]) if bad else None
    typ = ti.get("subagent_type")
    if typ is None or typ == "":
        typ = "general-purpose"
    if not isinstance(typ, str):
        raise Broken("тип субагента не строка")
    return None if typ in allowed else "субагент %s этому окну не положен." % typ


def main():
    allowed = [x for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x]
    if not allowed:
        raise Broken("списка разрешённых субагентов нет (настройки окна собраны с ошибкой) — отказ всем")
    try:
        ev = json.loads(sys.stdin.read())
    except ValueError:
        raise Broken("событие не JSON")
    why = check(ev, allowed)
    if why:
        deny(why, allowed)


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:  # noqa: B036 — любой сбой, и KeyboardInterrupt тоже, — блок, а не пропуск
        msg = str(e) if isinstance(e, Broken) else "сбой хука: %s: %r" % (type(e).__name__, e)
        try:
            sys.stderr.write("P0-6, отказ при сбое: %s\n" % msg)
        finally:
            os._exit(2)
    sys.exit(0)
