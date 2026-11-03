#!/usr/bin/env python3
"""Вход хука guard (metis-0148): короткий файл, а правила — модуль guard_rules.py рядом (его шапка — все правила).

Скрипт Python компилируется заново на каждый запуск, модуль — один раз в hooks/__pycache__: у guard_rules.py (4000
строк) компиляция была больше половины времени вызова, а guard запускается на каждый вызов инструмента. Папка кэша не
пишется — Python молча компилирует в памяти, как раньше. Тот же приём — у pantheon (lib/run.py).

Хуки зовут именно этот файл: `/bin/sh hooks/python.sh hooks/guard.py [--managed|--strict]` (плагин, управляемые
настройки, окна ролей). Вход читает событие и решает, молчать ли копии плагина, не загружая правил. Молчит только хук плагина (без аргумента); управляемая копия
(--managed) и строгая (--strict) проверяют всегда: управляемая — опора доверия, её ничто в файлах не выключает.
  1. хук плагина при управляемых настройках с guard --managed — как раньше (managed_guard_active в guard_rules.py),
     кроме Agent, Task и Skill: их управляемые настройки guard не передают;
  2. хук плагина в окне роли — если строгий guard (--strict) этой же сессии уже проверял этот инструмент. Строгий
     guard на PreToolUse пишет метку ~/.local/state/pantheon/guard-strict/<session_id>: строка
     «<окно>\\t<инструмент>». Хук плагина молчит, только когда в метке есть строка с его окном (PANTHEON_WINDOW) и
     инструментом. Строгий guard стоит в настройках окна с onFailure: "block" (сбой, таймаут и пропавший файл — отказ)
     и проверяет те же правила тем же кодом из проверенного дерева. Так Agent, Task и Skill в окне (их управляемые не
     проверяют) и все инструменты на установке без управляемых настроек проверяются один раз, а не дважды. Первый
     вызов инструмента в сессии проверяют все копии: метки ещё нет. Сессии без строгого guard (ваша, вложенный
     claude, `claude -r` без окна) метки своей сессии не имеют. Метку строгий guard обновляет на каждом вызове; не
     обновлял STRICT_FRESH (10 мин) — хук плагина снова проверяет сам.
Сбой этого решения (метку не прочесть, не записать) — не молчать: полная проверка, как раньше.

Сбой загрузки правил (нет guard_rules.py, protect_config.py или merge_gate.py, ошибка в модуле) — код 2 с причиной, на
Stop — 0 (metis-0094), строка в ~/.local/state/pantheon/logs/guard-failures.log. merge_gate.py грузится при первом
обращении (metis-0330): ошибка внутри него — отказ того вызова, которому он нужен. Контекст вызова — configure(). Свой срок DEADLINE — и на чтение события и
загрузку. На Python старше 3.11 (управляемые настройки и окна, собранные раньше, зовут голый python3) вход
перезапускается запускателем hooks/python.sh (metis-0571); файл поэтому разбирается и старым Python.
"""
import json
import os
import re
import signal
import sys
import time

if sys.version_info < (3, 11) and __name__ == "__main__":
    # metis-0571: хуки зовут guard через hooks/python.sh (Python 3.11+). Голым python3 его зовут только настройки,
    # собранные раньше: управляемые (ставятся через sudo, README «Управляемые настройки») и окна до пересборки. Там
    # python3 бывает системным 3.9 — перезапуск тем же запускателем; нет 3.11+ — он сам откажет на PreToolUse.
    # GUARD_PY_REEXEC — защита от круга, если запускатель вдруг вернул старый Python.
    if os.environ.get("GUARD_PY_REEXEC"):
        sys.stderr.write("guard: нужен Python 3.11+, запускатель hooks/python.sh дал %d.%d — действие остановлено.\n"
                         % sys.version_info[:2])
        os._exit(2)
    os.environ["GUARD_PY_REEXEC"] = "1"
    _me = os.path.realpath(__file__)
    os.execv("/bin/sh", ["/bin/sh", os.path.join(os.path.dirname(_me), "python.sh"), _me] + sys.argv[1:])



def configure():
    """Контекст вызова (metis-0330): HOME и пути от него — из os.environ здесь, а не в строках модуля (STRICT_DIR —
    метки строгого guard: <session_id> → строки «окно\tинструмент»). Заново — set_context."""
    global HOME, STATE, FAIL_LOG, STRICT_DIR, MARKET_GUARD
    HOME = os.path.expanduser("~")
    STATE = os.path.join(HOME, ".local", "state", "pantheon")
    FAIL_LOG = os.path.join(STATE, "logs", "guard-failures.log")
    STRICT_DIR = os.path.join(STATE, "guard-strict")
    MARKET_GUARD = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard", "hooks",
                                "guard.py")


def set_context(argv, environ):
    """Контекст другого вызова в этом процессе (демон хуков, тест test_context): sys.argv — этот файл и argv,
    os.environ — ровно environ, затем configure() входа и загруженных guard_rules и taint. Их имена берутся при
    проверке из глобальных модулей, поэтому решение — как у нового процесса с этими argv и окружением."""
    sys.argv = [os.path.realpath(__file__)] + list(argv)
    os.environ.clear()
    os.environ.update(environ)
    configure()
    for name in ("guard_rules", "taint"):
        if name in sys.modules:
            sys.modules[name].configure()


STRICT_TTL = 2 * 86400  # с: старше — метка удаляется при создании новой (сессия окна её пересоздаст сама)
STRICT_FRESH = 600  # с: метка глушит хук плагина, только если строгий guard обновлял её за это время (жив в сессии)
# те же, что в guard_rules.py (тест test_entry сверяет): управляемые настройки, клон маркетплейса, инструменты окна
MANAGED_FILE = "/Library/Application Support/ClaudeCode/managed-settings.json"  # MARKET_GUARD — в configure()
WINDOW_ONLY_TOOLS = frozenset({"Agent", "Task", "Skill"})
DEADLINE = 8  # с, как в guard_rules.py: таймаут хука — 10 с, а таймаут Claude Code пропускает вызов
SESSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z_-]{7,127}")
NAME_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,127}")


def mode_of(argv):
    return "strict" if "--strict" in argv else "managed" if "--managed" in argv else "plugin"


def parse(raw):
    """Событие хука из байтов stdin (та же расшифровка, что у json.load(sys.stdin)) или None: тогда решает
    guard_rules — и даёт код 2 на плохом входе."""
    try:
        ev = json.loads(raw.decode(sys.stdin.encoding or "utf-8", sys.stdin.errors or "strict"))
    except Exception:
        return None
    if isinstance(ev, dict) and isinstance(ev.get("hook_event_name"), str):
        return ev
    return None


def managed_guard_active():
    """Управляемые настройки сами вызывают guard (--managed), и его файл на месте: хуку плагина молчать. Копия
    одноимённой функции guard_rules.py (тест test_entry сверяет ответы): вход не грузит правил ради этого ответа."""
    try:
        with open(MANAGED_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    if not os.path.isfile(MARKET_GUARD):
        return False
    for group in ((data.get("hooks") or {}).get("PreToolUse") or []):
        for h in group.get("hooks") or []:
            cmd = h.get("command") or ""
            if "guard.py" in cmd and "--managed" in cmd:
                return True
    return False


def _strict_key(event):
    """(файл метки, строка метки) для PreToolUse окна роли или None: сессия, окно и инструмент — только простые имена."""
    if event.get("hook_event_name") != "PreToolUse":
        return None
    sid, tool, window = event.get("session_id"), event.get("tool_name"), os.environ.get("PANTHEON_WINDOW") or ""
    if not (isinstance(sid, str) and SESSION_RE.fullmatch(sid) and isinstance(tool, str) and NAME_RE.fullmatch(tool)
            and NAME_RE.fullmatch(window)):
        return None
    return os.path.join(STRICT_DIR, sid), f"{window}\t{tool}"


def _read_marker(path, fresh=None):
    """Строки метки: не ссылка (O_NOFOLLOW), не больше 64 КБ. Нет файла или (с fresh) метка старше fresh с — пусто.
    Папка на месте метки — исключение у fdopen, его ловит run: полная проверка."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return set()
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if fresh is not None and st.st_mtime < time.time() - fresh:
            return set()
        return set(fh.read(65536).decode("utf-8", "replace").splitlines())


def note_strict(event):
    """Строгий guard: запомнить, что он проверяет этот инструмент в этой сессии окна. Метку он обновляет на каждом
    вызове: строгий хук пропал из настроек живой сессии — через STRICT_FRESH хук плагина снова проверяет сам."""
    key = _strict_key(event)
    if key is None:
        return
    path, line = key
    if line in _read_marker(path):
        os.utime(path, follow_symlinks=False)
        return
    os.makedirs(STRICT_DIR, mode=0o700, exist_ok=True)
    new = not os.path.lexists(path)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    if new:  # уборка старых меток — раз на сессию
        cutoff = time.time() - STRICT_TTL
        for e in os.scandir(STRICT_DIR):
            try:
                if e.is_file(follow_symlinks=False) and e.stat(follow_symlinks=False).st_mtime < cutoff:
                    os.unlink(e.path)
            except OSError:
                pass


def strict_covers(event):
    """Строгий guard этой сессии окна уже проверял этот инструмент и жив (метка свежее STRICT_FRESH) — хук плагина
    молчит."""
    key = _strict_key(event)
    return key is not None and key[1] in _read_marker(key[0], STRICT_FRESH)


def quiet(event, mode):
    """Хуку плагина молчать (код 0 без проверки): его проверку делает другая копия. Управляемая копия (--managed) и
    строгая (--strict) не молчат никогда."""
    if mode != "plugin":
        return False
    name = event.get("hook_event_name")
    tool = event.get("tool_name") if name == "PreToolUse" else None
    if name != "PostToolUse" and tool not in WINDOW_ONLY_TOOLS and managed_guard_active():
        return True  # условие то же, что в guard_rules.main; PostToolUse — журнал запора слияния, его пишет плагин
    return name == "PreToolUse" and strict_covers(event)


def _log_load(mode, e):
    try:
        tb, line = e.__traceback__, 0
        while tb is not None:
            line, tb = tb.tb_lineno, tb.tb_next
        os.makedirs(os.path.dirname(FAIL_LOG), exist_ok=True)
        with open(FAIL_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{mode}\tload\t{type(e).__name__}:{line}\n")
    except Exception:
        pass


def _stop(event):
    return 0 if event is not None and event.get("hook_event_name") == "Stop" else 2


def run(argv):
    """Вход хука. Не возвращается: молчание — код 0, иначе guard_rules.run_hook (свой код и причина)."""
    mode, event = mode_of(argv), None

    def out_of_time(signum, frame):
        sys.stderr.write(f"guard: проверка не уложилась в {DEADLINE} с — действие остановлено. Повтори проще или "
                         "сообщи координатору.\n")
        sys.stderr.flush()
        os._exit(_stop(event))

    signal.signal(signal.SIGALRM, out_of_time)
    signal.setitimer(signal.ITIMER_REAL, DEADLINE)
    raw = sys.stdin.buffer.read()
    event = parse(raw)
    if event is not None:
        try:
            if mode == "strict":
                note_strict(event)
            elif quiet(event, mode):
                os._exit(0)
        except Exception:
            pass  # не решилось — полная проверка, как раньше
    try:
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import guard_rules
    except BaseException as e:  # noqa: B036 — сбой загрузки защиты: отказ с причиной, а не трассировка с кодом 1
        _log_load(mode, e)
        sys.stderr.write(f"guard: сбой загрузки guard ({type(e).__name__}) — действие остановлено. Сообщи "
                         "координатору или владельцу: защита не загрузилась.\n")
        sys.stderr.flush()
        os._exit(_stop(event))
    guard_rules.run_hook(raw)


configure()

if __name__ == "__main__":
    run(sys.argv[1:])
