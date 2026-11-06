#!/usr/bin/env python3
"""Окно роли встало на запросе разрешения → строка в alerts.md, её видит Зевс (metis-0900).

Хук Notification с matcher permission_prompt (hooks.json). Claude Code шлёт его, когда окну нужно разрешение
владельца: правка защищённого файла, команда вне правил, окно доверия. Поля события (документация Claude Code,
Notification input): session_id, cwd, hook_event_name = "Notification", message — текст уведомления, title — по
желанию, notification_type — permission_prompt | idle_prompt | auth_success | elicitation_dialog.

Что делает: `pantheon alert --from <окно> "окно <окно> ждёт вас: <message> (с ЧЧ:ММ)"` — без --critical. Строку
alerts.md Зевс получает в сводке новых тревог (ctx.py, hq_news), а «ждёт вас» он переносит на доску. Время в тексте
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


def main():
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(ev, dict) or ev.get("notification_type") != "permission_prompt":
        return 0
    role = (os.environ.get("PANTHEON_ROLE") or "").strip()
    if not role or role in QUIET_ROLES:
        return 0
    name = " ".join((os.environ.get("PANTHEON_SESSION") or role).split())[:60]
    t = now()
    if recent(name, t):
        return 0
    msg = " ".join(str(ev.get("message") or ev.get("title") or "запрос разрешения").split())[:MSG_MAX]
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
