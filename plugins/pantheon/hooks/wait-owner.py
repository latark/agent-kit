#!/usr/bin/env python3
"""Окно роли встало на запросе разрешения → строка в alerts.md, её видит Зевс (metis-0900, 0874).

PermissionRequest (metis-0874): тревога — вопросом «окно X просит разрешение — <инструмент>: <команда>. Зачем:
<description вызова>. Совет: …»; совет — по маршрутам handoff.route (у действия свой исполнитель — отклонить и передать ему).
Notification permission_prompt того же запроса ждёт DELAY секунд (хук асинхронный) и молчит по общей отметке «раз в
2 минуты»; без PermissionRequest (старый Claude Code) — прежняя строка «ждёт вас: <message>».

Хук Notification с matcher permission_prompt (hooks.json). Claude Code шлёт его, когда окну нужно разрешение
владельца: правка защищённого файла, команда вне правил, окно доверия. Поля события (документация Claude Code,
Notification input): session_id, cwd, hook_event_name = "Notification", message — текст уведомления, title — по
желанию, notification_type — permission_prompt | idle_prompt | auth_success | elicitation_dialog.

Что делает: `pantheon alert --from <окно> "окно <окно> ждёт вас: <message> (с ЧЧ:ММ)"` — без --critical. Строку
alerts.md Зевс получает в сводке новых тревог (ctx.py, hq_news), а карточку владельцу при ожидании дольше 5 мин заводит дежурный (watch.py wait_cards, metis-1122). Время в тексте
нужно потому, что alert() сливает одинаковые строки «ждёт вас» за сутки: второе ожидание того же окна за день иначе
пропало бы. Имя окна — PANTHEON_SESSION, без неё — PANTHEON_ROLE.

Молчит:
  - вне окон ролей (нет PANTHEON_ROLE) и в окне Зевса (PANTHEON_ROLE=hq): туда владелец смотрит сам. Проверку делает
    и оболочка в hooks.json (Python там не запускается), и сам скрипт;
  - на других notification_type (простой окна, вход, диалог MCP);
  - чаще раза в 2 минуты на окно: отметка STATE/ctx/wait-owner/<окно> — время последней тревоги. Отметка из будущего
    (часы ушли назад) окно не продлевает.
После успешного alert хук шлёт `pantheon notify` — уведомление macOS владельцу сразу, щелчок открывает доску; сбой
уведомления — строка в журнал, хук цел, предел «раз в 2 мин на окно» общий с alert (metis-0907).
Сбой `pantheon alert` (код не 0, нет файла, таймаут) — строка в STATE/logs/ctx-hooks.log, отметка не ставится:
следующий запрос разрешения попробует снова. Хук всегда выходит с кодом 0 и ничего не печатает в окно.
PANTHEON_NOW — подмена часов для тестов (секунды с эпохи), PANTHEON_STATE — папка состояния.
Python 3.11+: хуки запускает hooks/python.sh (metis-0571).
"""
import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
PLUGIN = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
EVERY = 120  # секунд между тревогами одного окна
MSG_MAX = 200
CMD_MAX = 300   # команда в вопросе Зевсу (PermissionRequest)
WHY_MAX = 160
DELAY = 3.0     # Notification ждёт, чтобы богатая тревога PermissionRequest легла первой
QUIET_ROLES = {"hq"}


def now():
    try:
        return float(os.environ.get("PANTHEON_NOW") or time.time())
    except ValueError:
        return time.time()


def log(text):
    try:
        os.makedirs(os.path.join(STATE, "logs"), exist_ok=True)
        with open(os.path.join(STATE, "logs", "ctx-hooks.log"), "a", encoding="utf-8") as fh:
            fh.write(f"wait-owner\t{text}\n")
    except OSError:
        pass


def mark_path(name):
    return os.path.join(STATE, "ctx", "wait-owner", re.sub(r"[^\w.-]", "_", name)[:80] or "none")


def recent(name, t):
    try:
        last = float(open(mark_path(name)).read().strip())
    except (OSError, ValueError):
        return False
    return last <= t < last + EVERY


def flat(v, n):
    return " ".join(str(v or "").split())[:n]


def lib(name):
    spec = importlib.util.spec_from_file_location(f"pantheon_{name}_wait", os.path.join(PLUGIN, "lib", f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def quoted(v, n):
    """Текст роли в вопрос Зевсу: секреты скрыты (denials.scrub), кавычки «» роли убраны — поле «Совет:» внутри
    кавычек не подделать (находка проверки безопасности 15.11). Сбой scrub — заглушка, а не сырой текст."""
    try:
        t = lib("denials").scrub(v, n)
    except Exception:  # noqa: BLE001 — без scrub сырой текст в тревогу не идёт
        t = "‹не показано›" if str(v or "").strip() else ""
    t = re.sub(r"(?i)(совет|зачем)\s*:", r"\1 —", t.replace("«", '"').replace("»", '"'))   # поля вопроса — только наши
    return f"«{t}»" if t else ""


def advice(cmd):
    """Совет Зевсу по маршрутам отказа (lib/handoff.py): у действия есть свой исполнитель — отклонить и передать ему;
    иначе — смотреть команду. Сбой загрузки — общий совет: подсказка не должна ломать тревогу."""
    try:
        key, who, _, _ = lib("handoff").route(cmd)
    except Exception:  # noqa: BLE001 — любой сбой разбора даёт общий совет
        key, who = "ask", ""
    if key != "ask":
        return f"отклонить — это делает {who}, роли передать туда"
    return "разрешить, если команда читает или пишет только в worktree роли; иначе отклонить"


def question(ev):
    """PermissionRequest (metis-0874): что просит окно — инструмент и команда, зачем — описание вызова, и совет."""
    tool = flat(ev.get("tool_name"), 60) or "инструмент"
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    raw = ti.get("command") or ti.get("file_path") or ti.get("path") or ti.get("url")
    cmd = quoted(raw, CMD_MAX) if raw else "поля: " + (", ".join(sorted(ti))[:CMD_MAX] if ti else "нет")
    why = quoted(ti.get("description") or ti.get("prompt"), WHY_MAX) or "окно не сказало"
    return f"{quoted(tool, 60)}: {cmd}. Зачем: {why}. Совет: {advice(tool + ' ' + str(raw or ''))}"


def main():
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(ev, dict):
        return 0
    kind = ev.get("hook_event_name")
    if kind != "PermissionRequest" and ev.get("notification_type") != "permission_prompt":
        return 0
    role = (os.environ.get("PANTHEON_ROLE") or "").strip()
    if not role or role in QUIET_ROLES:
        return 0
    name = " ".join((os.environ.get("PANTHEON_SESSION") or role).split())[:60]
    if kind != "PermissionRequest":   # хук асинхронный: даём PermissionRequest того же запроса лечь первым
        with contextlib.suppress(ValueError):
            time.sleep(min(10.0, float(os.environ.get("PANTHEON_WAIT_OWNER_DELAY") or DELAY)))
    t = now()
    if recent(name, t):
        return 0
    if kind == "PermissionRequest":
        msg = question(ev)
        text = f"окно {name} просит разрешение — {msg} (с {time.strftime('%H:%M', time.localtime(t))}; ответить — в окне)"
    else:
        msg = flat(ev.get("message") or ev.get("title") or "запрос разрешения", MSG_MAX)
        text = f"окно {name} ждёт вас: {msg} (с {time.strftime('%H:%M', time.localtime(t))})"
    try:
        r = subprocess.run([os.path.join(PLUGIN, "bin", "pantheon"), "alert", "--from", name, text],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"{name}\tpantheon alert: {type(e).__name__}: {e}")
        return 0
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        log(f"{name}\tpantheon alert: код {r.returncode}: {tail[0][:200]}")
        return 0
    p = mark_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(str(t))
    # уведомление macOS тем же путём, что у Пантеона (щелчок открывает доску); сбой его — в журнал, хук цел (metis-0907)
    try:
        r = subprocess.run([os.path.join(PLUGIN, "bin", "pantheon"), "notify", "--title", "Окно ждёт вас",
                            "--group", f"wait-owner-{name}", f"{name}: {msg}"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
            log(f"{name}\tpantheon notify: код {r.returncode}: {tail[0][:200]}")
    except (OSError, subprocess.SubprocessError) as e:
        log(f"{name}\tpantheon notify: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # сбой хука не мешает окну, но остаётся в журнале
        log(f"{type(e).__name__}: {e}")
        sys.exit(0)
