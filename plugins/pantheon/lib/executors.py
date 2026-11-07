"""Исполнители кода Пантеона: Claude всегда, Codex — дополнение (решение 175, metis-0166 вариант А, 0173 Б).

Что здесь:
  - набор исполнителей `[executors] set` в STATE/config.toml (через pconfig): нет записи — ["claude"]; Claude из
    набора не удаляется;
  - доступность Codex: в наборе, `[codex] enabled`, `disabled_until` не наступил, codex на PATH;
  - `check_codex()` — проверка окружения: codex на PATH → вход есть (`codex login status` с CODEX_HOME роли) →
    hello-проба 45 с; итог — в `[codex]`;
  - `add_codex()` — шаг `pantheon-setup --add codex` и `pantheon executors --add codex`;
  - `pick(head, kind)` — кто пишет задачу (roles/_parts/executor.part);
  - `exec_codex()` — обёртка `pantheon exec codex <worktree> <файл поручения>` по образцу Paperclip codex_local
    (доклад prometheus 16.10, `research-2026-10-16-paperclip-codex-parity.md`, и поправки 17.10).

CODEX_HOME роли codex-dev — STATE/codex-dev (0700, свой вход `codex login --device-auth`), общий ~/.codex не трогаем.
Пути — от env PANTHEON_STATE и HOME на каждый вызов: тесты подменяют их временными папками.
Переопределения для тестов: PANTHEON_NOW — «сейчас»; PANTHEON_CODEX_IDLE_S (тишина, по умолчанию 1800),
PANTHEON_CODEX_TIMEOUT_S (общий предел, 7200), PANTHEON_CODEX_HELLO_S (hello-проба, 45), PANTHEON_CODEX_GRACE_S
(SIGTERM → SIGKILL, 5).
"""
import ast
import fnmatch
import importlib.util
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

try:
    import fcntl
except ImportError:  # pragma: no cover — только macOS
    fcntl = None

LIB = os.path.dirname(os.path.realpath(__file__))
PLUGIN = os.path.dirname(LIB)
PROBE = os.path.join(PLUGIN, "scripts", "live-probe-codex-nested.sh")

KINDS = {"mechanics": "dev-haiku", "code": "dev-sonnet", "hard": "dev-opus"}
KNOWN = ("claude", "codex")
FALLBACK = "dev-sonnet"   # executor.part: Codex недоступен → та же задача dev-sonnet
UNAVAILABLE = 3           # код «Codex недоступен»: задачи идут на dev-*
BUSY = 4                  # другой запуск держит CODEX_HOME роли

# Флаги запуска (доклад prometheus, разд. 1 и 4; решение Зевса 16.10 — без network_access и без bypass).
EXEC_FLAGS = ["exec", "--json", "--ephemeral", "--sandbox", "workspace-write",
              "-c", "features.shell_snapshot=false"]
HELLO_TEXT = "Respond with hello."
HELLO_FLAGS = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
               "-c", "features.plugins=false", "-c", "features.remote_plugin=false", "-c", "project_doc_max_bytes=0"]

ENV_KEEP = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR")
SECRET_NAME = re.compile(r"key|secret|token", re.I)

# Признаки «нужен новый вход» (Paperclip parse.ts:162-175): отказ без повторов, Codex выключен.
AUTH_RE = re.compile(r"refresh_token_reused|invalid_grant|refresh token has expired|401 Unauthorized", re.I)
LIMIT_RE = re.compile(r"usage limit", re.I)
AGAIN_RE = re.compile(r"try again at\s+(.+?)(?:\.\s|\.$|$)", re.I | re.S)
DEMAND_RE = re.compile(r"high demand|at capacity", re.I)
DEMAND_PAUSE_MIN = 30     # высокий спрос без времени — та же квота у Paperclip; Codex отдыхает полчаса
LIMIT_PAUSE_MIN = 60      # лимит без разборчивого времени
STDERR_NOISE = re.compile(r"^(YOLO mode is enabled|\[paperclip\])|state db missing rollout path", re.I)

# Защищённые пути (roles/_parts/protected.part; тест сверяет список с частью роли). Одно имя — на любой глубине,
# путь из нескольких частей — от корня репозитория.
PROTECTED_ANY = (".claude/", ".codex/", "agents/", "policy.toml", "settings*.json", ".mcp.json", "AGENTS.md",
                 "CLAUDE.md", ".pantheon-verify", ".claude-plugin/")
PROTECTED_ROOT = (".github/workflows/", ".github/scripts/", "plugins/guard/", "plugins/*/hooks/", "plugins/pantheon/roles/",
                  "plugins/pantheon/lib/merge.py", "plugins/pantheon/lib/window_rules.py",
                  "plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/plugins-by-role.toml")
# песочница и правила окон в pantheon.py (sandbox_build и всё, что он записывает): защищены строки диффа с этими словами
WINDOW_FILE = "plugins/pantheon/lib/pantheon.py"
WINDOW_WORDS = re.compile(r"autoMode|permissions|allowWrite|denyWrite|denyRead|allowRead|defaultMode|"
                          r"sandbox_build|excludedCommands|[A-Z]+_EXCLUDED\b|additionalDirectories|disallowedTools|"
                          r"allowedTools")


# --- окружение ------------------------------------------------------------------------------------------------

def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def state():
    return os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(home(), ".local", "state", "pantheon"))


def codex_home():
    return os.path.join(state(), "codex-dev")


def lock_path():
    return os.path.join(state(), "locks", "codex-dev.lock")


def now():
    return float(os.environ.get("PANTHEON_NOW") or time.time())


def stamp(t=None):
    return datetime.fromtimestamp(now() if t is None else t).strftime("%Y-%m-%dT%H:%M")


def _num(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return float(default)


_PCONFIG = None


def pconfig():
    """lib/pconfig.py по пути: python3 -I не кладёт lib в путь импорта."""
    global _PCONFIG
    if _PCONFIG is None:
        spec = importlib.util.spec_from_file_location("pantheon_pconfig", os.path.join(LIB, "pconfig.py"))
        _PCONFIG = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PCONFIG)
    return _PCONFIG


def codex_bin():
    return shutil.which("codex")


def role_env(base=None):
    """Окружение Codex: белый список, CODEX_HOME роли, пустой OPENAI_API_KEY; CODEX_API_KEY — только если задан у
    вызова; прочие имена с key|secret|token не проходят, даже если попали в список."""
    base = os.environ if base is None else base
    env = {}
    for k, v in base.items():
        if (k in ENV_KEEP or k.startswith("LC_")) and not SECRET_NAME.search(k):
            env[k] = v
    env["CODEX_HOME"] = codex_home()
    env["OPENAI_API_KEY"] = ""
    if base.get("CODEX_API_KEY"):
        env["CODEX_API_KEY"] = base["CODEX_API_KEY"]
    return env


def ensure_home():
    """CODEX_HOME роли: папка 0700, config.toml в ней 0600 (общий ~/.codex не копируем и не трогаем)."""
    h = codex_home()
    os.makedirs(h, mode=0o700, exist_ok=True)
    os.chmod(h, 0o700)
    cfg = os.path.join(h, "config.toml")
    if not os.path.exists(cfg):
        fd = os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("# CODEX_HOME роли codex-dev (pantheon). Вход — свой: codex login --device-auth с этим CODEX_HOME.\n")
    os.chmod(cfg, 0o600)
    return h


# --- набор и доступность ----------------------------------------------------------------------------------------

def load():
    return pconfig().load()


def executor_set(cfg=None):
    cfg = load() if cfg is None else cfg
    got = (cfg.get("executors") or {}).get("set")
    got = [x for x in got if isinstance(x, str)] if isinstance(got, list) else []
    return ["claude"] + [x for x in dict.fromkeys(got) if x != "claude"]


def _write_set(names):
    names = ["claude"] + [x for x in dict.fromkeys(names) if x != "claude"]
    pconfig().update({"set": names}, "executors")
    return names


def remove(name):
    """→ (код, текст). Claude не удаляется (решение 175)."""
    if name == "claude":
        return 2, ("Claude из набора исполнителей не удаляется: он исполнитель по умолчанию и запасной для Codex "
                   "(решение 175). Убрать можно только Codex: pantheon executors --remove codex")
    if name not in KNOWN:
        return 2, f"исполнителя «{name}» нет; известны: {', '.join(KNOWN)}"
    cur = executor_set()
    if name not in cur:
        return 0, f"{name} и так не в наборе: {', '.join(cur)}"
    return 0, "набор: " + ", ".join(_write_set([x for x in cur if x != name]))


def _until_ts(s):
    try:
        return datetime.strptime(str(s)[:16], "%Y-%m-%dT%H:%M").timestamp()
    except ValueError:
        return None


def codex_status(cfg=None):
    """→ (доступен ли Codex, причина «почему нет» или «»)."""
    cfg = load() if cfg is None else cfg
    cx = cfg.get("codex") or {}
    if "codex" not in executor_set(cfg):
        return False, "Codex не в наборе исполнителей (pantheon executors --add codex)"
    if not cx.get("enabled"):
        return False, "Codex выключен: " + (cx.get("reason") or "не проверен")
    until = _until_ts(cx.get("disabled_until") or "")
    if until is not None and now() < until:
        return False, f"Codex выключен до {cx.get('disabled_until')}: {cx.get('reason') or 'лимит'}"
    if not codex_bin():
        return False, "codex нет на PATH"
    return True, ""


def codex_available(cfg=None):
    return codex_status(cfg)[0]


def _disable(reason, until=None):
    ch = {"reason": reason, "checked": stamp()}
    if until:
        ch["disabled_until"] = until
    else:
        ch["enabled"] = False
    pconfig().update(ch, "codex")


# --- выбор исполнителя ----------------------------------------------------------------------------------------

def pick(head, kind=None, cfg=None):
    """→ (роль, предупреждение или None). kind — mechanics|code|hard (по умолчанию code)."""
    kind = kind or "code"
    if kind not in KINDS:
        raise ValueError(f"вид задачи «{kind}» — не из {', '.join(KINDS)}")
    ex = (head or {}).get("executor") or "auto"
    dev = KINDS[kind]
    if ex == "claude":
        return dev, None
    ok, why = codex_status(cfg)
    if ex == "codex":
        if ok:
            return "codex-dev", None
        return FALLBACK, f"задача закреплена за Codex, но он недоступен ({why}) — исполнитель {FALLBACK}"
    if ex != "auto":
        raise ValueError(f"executor «{ex}» — не из auto, claude, codex")
    if ok and kind in ("mechanics", "code"):
        return "codex-dev", None
    return dev, None


# --- запуск процесса с монитором тишины ------------------------------------------------------------------------

def _kill_group(p, grace):
    """SIGTERM всей группе Codex, через grace — SIGKILL тому, кто в группе остался (и дочерним после выхода главного)."""
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


def run_codex(argv, cwd, env, stdin_text, log, idle_s, total_s, grace=None):
    """Запуск в своей группе процессов; stdout → log (JSONL), stderr → log + '.stderr'. Нет вывода idle_s — SIGTERM
    группе, через grace — SIGKILL; то же по общему пределу total_s. → (код, строки stdout, строки stderr, killed)."""
    grace = _num("PANTHEON_CODEX_GRACE_S", 5) if grace is None else grace
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    sel = selectors.DefaultSelector()
    try:
        try:
            p.stdin.write(stdin_text.encode("utf-8"))
            p.stdin.close()
        except BrokenPipeError:
            pass
        sel.register(p.stdout, selectors.EVENT_READ, "out")
        sel.register(p.stderr, selectors.EVENT_READ, "err")
        return _pump(p, sel, log, idle_s, total_s, grace)
    except Interrupted:  # обёртку остановили (SIGTERM/SIGHUP/SIGINT) — Codex не должен работать дальше без неё
        _kill_group(p, grace)
        raise
    finally:
        sel.close()
        for f in (p.stdout, p.stderr):
            try:
                f.close()
            except OSError:
                pass


class Interrupted(BaseException):  # как KeyboardInterrupt: широкие except Exception его не глотают
    pass


def _pump(p, sel, log, idle_s, total_s, grace):
    bufs = {"out": b"", "err": b""}
    lines = {"out": [], "err": []}
    start = last = time.monotonic()
    killed = None
    with open(log, "ab") as lo, open(log + ".stderr", "ab") as le:
        while sel.get_map():
            t = time.monotonic()
            if t - last > idle_s:
                killed = f"нет вывода {int(idle_s)} с — остановлен (тишина)"
            elif t - start > total_s:
                killed = f"общий предел {int(total_s)} с — остановлен"
            if killed:
                _kill_group(p, grace)
                break
            for key, _ in sel.select(timeout=min(1.0, max(0.05, idle_s / 10))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                last = time.monotonic()
                (lo if key.data == "out" else le).write(chunk)
                (lo if key.data == "out" else le).flush()
                bufs[key.data] += chunk
                *done, bufs[key.data] = bufs[key.data].split(b"\n")
                lines[key.data] += [x.decode("utf-8", "replace") for x in done]
    for k in bufs:
        if bufs[k]:
            lines[k].append(bufs[k].decode("utf-8", "replace"))
    try:
        rc = p.wait(timeout=grace + 5)
    except subprocess.TimeoutExpired:
        _kill_group(p, grace)
        rc = p.wait()
    return rc, lines["out"], lines["err"], killed


def parse_events(out_lines):
    """JSONL Codex → dict: events, answer (последний agent_message), failure (текст turn.failed/error),
    terminal (было ли конечное событие), completed, thread."""
    events, answer, failure, terminal, completed, thread = [], None, None, False, False, None
    for ln in out_lines:
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        events.append(ev)
        ty = ev.get("type")
        if ty == "thread.started":
            thread = ev.get("thread_id")
        elif ty == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                answer = item["text"]
        elif ty == "turn.completed":
            terminal = completed = True
        elif ty == "turn.failed":
            terminal = True
            err = ev.get("error") or {}
            failure = (err.get("message") if isinstance(err, dict) else str(err)) or "turn.failed"
        elif ty == "error":
            terminal = True
            failure = ev.get("message") or "error"
    return {"events": events, "answer": answer, "failure": failure, "terminal": terminal, "completed": completed,
            "thread": thread}


def stderr_reason(err_lines):
    for ln in err_lines:
        s = ln.strip()
        if s and not STDERR_NOISE.search(s):
            return s
    return ""


def _again_at(text):
    """Время из «try again at 11:31 PM» → «ГГГГ-ММ-ДДTЧЧ:ММ» (местное; пояс в скобках не учитываем)."""
    m = AGAIN_RE.search(text)
    if not m:
        return None
    tail = m.group(1)
    tm = re.search(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", tail)
    if not tm:
        return None
    hh, mm = int(tm.group(1)), int(tm.group(2))
    if tm.group(3):
        hh = hh % 12 + (12 if tm.group(3).lower() == "pm" else 0)
    if hh > 23 or mm > 59:
        return None
    base = datetime.fromtimestamp(now())
    dm = re.search(r"([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", tail)
    if dm:
        try:
            day = datetime.strptime(f"{dm.group(1)} {dm.group(2)} {dm.group(3)}", "%b %d %Y")
            return day.replace(hour=hh, minute=mm).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            pass
    at = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if at <= base:
        at += timedelta(days=1)
    return at.strftime("%Y-%m-%dT%H:%M")


def classify(rc, parsed, err_lines, killed):
    """→ (вид, текст): ok | auth | limit | demand | crash | failed | hang."""
    text = "\n".join(x for x in [parsed["failure"] or ""] + err_lines if x)
    if killed:
        return "hang", killed
    if AUTH_RE.search(text):
        return "auth", (parsed["failure"] or stderr_reason(err_lines) or "нужен вход")
    if LIMIT_RE.search(text):
        return "limit", (parsed["failure"] or stderr_reason(err_lines))
    if DEMAND_RE.search(text):
        return "demand", (parsed["failure"] or stderr_reason(err_lines))
    if parsed["failure"]:
        return "failed", parsed["failure"]
    if parsed["completed"] and rc == 0:
        return "ok", ""
    if parsed["events"] and not parsed["terminal"] and rc != 0:
        return "crash", stderr_reason(err_lines) or f"Codex упал посреди хода (код {rc})"
    if rc != 0:
        return "failed", stderr_reason(err_lines) or f"Codex вышел с кодом {rc}"
    return "failed", "Codex завершился без конечного события (turn.completed)"


# --- проверка окружения -----------------------------------------------------------------------------------------

def codex_version(env=None):
    exe = codex_bin()
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20,
                           env=env or role_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    s = (r.stdout or "").strip().splitlines()
    m = re.match(r"^codex-cli\s+(\S+)$", s[0]) if s else None
    return m.group(1) if m else (s[0].split()[-1] if s and s[0].split() else "")


def hello_probe(env):
    """→ (исход, подробность): passed | unexpected_output | timed_out | auth_required | failed."""
    exe = codex_bin()
    tmp = tempfile.mkdtemp(prefix="tmp-codex-hello-", dir=os.environ.get("TMPDIR") or None)
    log = os.path.join(tmp, "hello.jsonl")
    try:
        t = _num("PANTHEON_CODEX_HELLO_S", 45)
        rc, out, err, killed = run_codex([exe, *HELLO_FLAGS, "-"], tmp, env, HELLO_TEXT + "\n", log, t, t)
        parsed = parse_events(out)
        kind, why = classify(rc, parsed, err, killed)
        if kind == "hang":
            return "timed_out", f"нет ответа за {int(t)} с"
        if kind == "auth":
            return "auth_required", why
        if kind == "ok":
            if parsed["answer"] and "hello" in parsed["answer"].lower():
                return "passed", ""
            return "unexpected_output", (parsed["answer"] or "")[:200]
        return "failed", why[:300]
    finally:
        shutil.rmtree(tmp, True)


def check_codex(out=None):
    """codex на PATH → вход (`codex login status`) → hello-проба. Итог — в [codex]. → (код, текст)."""
    out = out or (lambda s: print(s))
    exe = codex_bin()
    if not exe:
        _disable("нет на PATH")
        return UNAVAILABLE, "Codex недоступен: codex нет на PATH — задачи идут на dev-*"
    ensure_home()
    env = role_env()
    ver = codex_version(env)
    pconfig().update({"home": codex_home(), "version": ver, "checked": stamp()}, "codex")
    try:
        r = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=30, env=env,
                           stdin=subprocess.DEVNULL)
        logged = r.returncode == 0
        detail = (r.stdout + r.stderr).strip().splitlines()
    except (OSError, subprocess.TimeoutExpired) as e:
        logged, detail = False, [str(e)]
    if not logged:
        _disable("нет входа")
        return UNAVAILABLE, ("Codex недоступен: нет входа в CODEX_HOME роли (" + codex_home() + ")"
                             + (f": {detail[0]}" if detail else "") + " — задачи идут на dev-*. Вход: "
                             "pantheon-setup --add codex")
    res, why = hello_probe(env)
    if res != "passed":
        _disable("нужен вход" if res == "auth_required" else f"hello-проба: {res}")
        return UNAVAILABLE, f"Codex недоступен: hello-проба — {res}" + (f" ({why})" if why else "") + \
            " — задачи идут на dev-*"
    pconfig().update({"enabled": True, "reason": "", "disabled_until": "", "checked": stamp()}, "codex")
    return 0, f"Codex доступен: версия {ver or '?'}, вход есть, hello-проба прошла"


INSTALL_HINT = ("Codex не найден на PATH. Поставить: `npm install -g @openai/codex` (или `brew install --cask codex`), "
                "затем снова `pantheon-setup --add codex`. Codex не добавлен; установка идёт дальше, задачи — на Claude.")
CONNECTORS_HINT = ("Проверьте подключённые приложения и коннекторы аккаунта Codex роли (chatgpt.com → Настройки → "
                   "Приложения/Connectors): песочница CLI не ограничивает права аккаунта (GHSA-gqqj). Лишнее — отключите.")


def run_live_probe(env, out):
    """scripts/live-probe-codex-nested.sh с CODEX_HOME роли → (код, строка итога)."""
    try:
        r = subprocess.run(["bash", PROBE], capture_output=True, text=True, env=env, timeout=1800,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"живая проба не прошла: {e}"
    for ln in (r.stdout + r.stderr).splitlines():
        out("  " + ln)
    m = re.search(r"итог:\s*N=(\d+)\s+W=(\d+)\s+D=(\d+)", r.stdout)
    if not m:
        return 1, "живая проба: нет строки итога"
    line = f"итог: N={m.group(1)} W={m.group(2)} D={m.group(3)}"
    # обёртка запускает Codex с workspace-write внутри окна — нужны N=0 (Codex работает) и W=0 (вложенный Seatbelt)
    return (0 if m.group(1) == "0" and m.group(2) == "0" else 1), line


def add_codex(interactive=False, live_probe=False, out=None):
    """Добавить Codex к набору (pantheon-setup --add codex, pantheon executors --add codex).
    interactive — `codex login --device-auth` с CODEX_HOME роли; live_probe — живая проба вложенной песочницы.
    → 0 — добавлен, 3 — не добавлен (понятный текст уже выведен, установка идёт дальше)."""
    out = out or (lambda s: print(s))
    exe = codex_bin()
    if not exe:
        _disable("нет на PATH")
        out(INSTALL_HINT)
        return UNAVAILABLE
    ensure_home()
    env = role_env()
    if interactive:
        out(f"Вход Codex для роли codex-dev (CODEX_HOME={codex_home()}): откроется код для входа на устройстве.")
        try:
            rc = subprocess.run([exe, "login", "--device-auth"], env=env).returncode
        except OSError as e:
            out(f"codex login не запустился: {e}")
            rc = 1
        if rc != 0:
            _disable("нет входа")
            out(f"Codex не добавлен: вход не выполнен (код {rc}). Повторить: pantheon-setup --add codex")
            return UNAVAILABLE
    code, text = check_codex(out)
    out(text)
    if code != 0:
        out("Codex не добавлен.")
        return UNAVAILABLE
    if live_probe:
        pc, line = run_live_probe(env, out)
        out(line)
        if pc != 0:
            _disable("живая проба вложенной песочницы")
            out("Codex не добавлен: живая проба не прошла (нужны N=0 и W=0). Итог — Зевсу.")
            return UNAVAILABLE
    out(CONNECTORS_HINT)
    names = _write_set(executor_set() + ["codex"])
    out("набор: " + ", ".join(names))
    return 0


# --- обёртка pantheon exec codex -------------------------------------------------------------------------------

def _git(wt, *args, check=False):
    r = subprocess.run(["git", "-C", wt, *args], capture_output=True, text=True, timeout=120,
                       stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r


def snapshot(wt):
    """HEAD и вид дерева: путь → (код состояния, размер, mtime). --ignored -uall: игнорируемое тоже видно."""
    head = _git(wt, "rev-parse", "HEAD").stdout.strip()
    r = _git(wt, "status", "--porcelain=v1", "-z", "--ignored", "-uall")
    items, parts, i = {}, r.stdout.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, p = e[:2], e[3:]
        names = [p]
        if xy[0] in "RC" and i < len(parts):
            names.append(parts[i])  # у переименования и копии второй путь — старое имя: считаются оба
            i += 1
        for n in names:
            try:
                st = os.lstat(os.path.join(wt, n))
                sig = (st.st_size, st.st_mtime_ns)
            except OSError:
                sig = None
            items[n] = (xy, sig)
    return head, items


def _diff_names(wt, *revs):
    """Имена путей диффа без склейки переименований: у git mv — и старое, и новое имя."""
    r = _git(wt, "diff", "--name-only", "--no-renames", "-z", *revs)
    return {x for x in r.stdout.split("\0") if x}


def changed_paths(wt, before, after):
    """Что изменилось за ход: сверка снимков статуса (вместе с неотслеживаемым и игнорируемым), свои коммиты Codex
    (снимок..HEAD) и рабочее дерево против снимка HEAD — всё без склейки переименований. Запуск идёт только из
    чистого дерева (dirty_paths), поэтому любой дифф против снимка HEAD — работа Codex."""
    head0, it0 = before
    head1, it1 = after
    paths = {p for p in set(it0) | set(it1) if it0.get(p) != it1.get(p)}
    if head0 and head1 and head0 != head1:
        paths |= _diff_names(wt, head0, head1)
    if head0:
        paths |= _diff_names(wt, head0)
    return sorted(paths)


def dirty_paths(snap):
    """Изменённое в отслеживаемых и неотслеживаемое по снимку; игнорируемое («!!»: node_modules, .venv) — не грязь."""
    return sorted(p for p, (xy, _sig) in snap[1].items() if xy != "!!")


def protected_hit(p):
    p = p.replace(os.sep, "/")
    segs = p.split("/")
    for pat in PROTECTED_ANY:
        if pat.endswith("/"):
            if pat[:-1] in segs[:-1] or (p.endswith("/") and pat[:-1] in segs):
                return True
        elif fnmatch.fnmatchcase(segs[-1], pat):
            return True
    for pat in PROTECTED_ROOT:
        n = pat.rstrip("/").count("/") + 1
        if len(segs) >= n + (1 if pat.endswith("/") else 0) and fnmatch.fnmatchcase("/".join(segs[:n]), pat.rstrip("/")):
            return True
    return False


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


_BODY_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")


def _stmt_head(st):
    """Строки (первая, последняя) заголовка инструкции st: у составной (if, for, with, def, class, try, match) — от
    декораторов до конца условия, аргументов, баз; у инструкции без тела — она вся."""
    if not any(getattr(st, f, None) for f in _BODY_FIELDS):
        return st.lineno, st.end_lineno
    first = last = st.lineno
    for field, value in ast.iter_fields(st):
        if field in _BODY_FIELDS:
            continue
        for n in value if isinstance(value, list) else [value]:
            if isinstance(n, ast.AST) and getattr(n, "lineno", None) is not None:
                first, last = min(first, n.lineno), max(last, n.end_lineno)
    return first, last


def _stmt_hits(src, lines, sign):
    """Строки продолжения (metis-0411): инструкция, в которой есть задетая строка lines (номера с 1), а слово
    WINDOW_WORDS — на другой её строке. Без тела (присваивание, выражение, return) — слово где угодно в ней, например
    элемент многострочного списка `HQ_EXCLUDED = [` … `]`. Составная (if, for, with, def, match) — слово в её
    заголовке, а задета строка заголовка или тела: многострочное условие `if (… or` / `"permissions" in d):` и правка
    тела `if "permissions" in data:` (Д3 argus R2-1, Д4 argus R2-2 PR #394). → первая строка каждой такой инструкции со
    знаком sign. Не разобрать — пусто: тогда остаются построчные совпадения."""
    if not lines or src is None:
        return []
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    text = src.splitlines()
    out = []
    for st in ast.walk(tree):
        if not isinstance(st, ast.stmt):
            continue
        first, last = _stmt_head(st)
        hit = [n for n in lines if first <= n <= st.end_lineno]
        # однострочная инструкция или задет только однострочный заголовок — его видит построчное совпадение
        if not hit or all(n == first == last for n in hit) or \
                not WINDOW_WORDS.search("\n".join(text[first - 1:last])):
            continue
        out.append(f"{sign}{text[st.lineno - 1]}  # строки {st.lineno}-{st.end_lineno}")
    return out


def window_rules_hit(wt, base):
    """Строки диффа pantheon.py (против base, вместе с незакоммиченным), задевающие правила окон: со словом
    WINDOW_WORDS — и строки продолжения многострочной инструкции, где это слово стоит на другой строке (metis-0411)."""
    r = _git(wt, "diff", "--unified=0", base, "--", WINDOW_FILE)
    hits = [ln for ln in r.stdout.splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---")) and WINDOW_WORDS.search(ln)]
    old_lines, new_lines = set(), set()
    for ln in r.stdout.splitlines():
        m = HUNK.match(ln)
        if m:
            a, b = int(m[1]), int(m[2] if m[2] is not None else 1)
            c, d = int(m[3]), int(m[4] if m[4] is not None else 1)
            old_lines.update(range(a, a + b))
            new_lines.update(range(c, c + d))
    p = os.path.join(wt, WINDOW_FILE)
    if old_lines:
        old = _git(wt, "show", f"{base}:{WINDOW_FILE}")
        hits += _stmt_hits(old.stdout if old.returncode == 0 else None, old_lines, "-")
    if new_lines:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                hits += _stmt_hits(fh.read(), new_lines, "+")
        except OSError:
            pass
    if os.path.isfile(p) and not _git(wt, "ls-files", "--", WINDOW_FILE).stdout.strip():
        try:  # файл новый и не в индексе — git diff его не видит, смотрим целиком
            with open(p, encoding="utf-8", errors="replace") as fh:
                hits += ["+" + ln.rstrip("\n") for ln in fh if WINDOW_WORDS.search(ln)]
        except OSError:
            pass
    return hits


def _branch_dir(wt):
    br = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "detached"
    safe = re.sub(r"[^\w.-]+", "-", br).strip("-") or "branch"
    d = os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), f"tmp-codex-{safe}")
    os.makedirs(d, exist_ok=True)
    return d


def _subject(brief):
    line = next((x.strip().lstrip("#").strip() for x in brief.splitlines() if x.strip()), "") or "поручение"
    return ("codex: " + line)[:72]


def commit_result(wt, base_head, brief):
    """Коммит в worktree с трейлером `Executor: codex`. Свои коммиты Codex сводятся в один (reset --soft к снимку):
    так трейлер есть на всём, что сделал Codex, а их заголовки — в теле. → (sha или None, текст)."""
    head = _git(wt, "rev-parse", "HEAD").stdout.strip()
    own = []
    if head != base_head:
        if _git(wt, "merge-base", "--is-ancestor", base_head, head).returncode != 0:
            return None, "Codex переписал историю ветки (снимок до запуска не предок HEAD) — не коммичу"
        own = _git(wt, "log", "--format=%s", f"{base_head}..{head}").stdout.strip().splitlines()
        _git(wt, "reset", "--soft", base_head, check=True)
    _git(wt, "add", "-A", check=True)
    if _git(wt, "diff", "--cached", "--quiet").returncode == 0:
        return None, "Codex ничего не изменил"
    body = ("Коммиты Codex:\n" + "\n".join("- " + s for s in own)) if own else ""
    args = ["commit", "--no-verify", "-q", "-m", _subject(brief)]
    if body:
        args += ["-m", body]
    args += ["-m", "Executor: codex"]
    _git(wt, *args, check=True)
    return _git(wt, "rev-parse", "HEAD").stdout.strip(), ""


class Busy(Exception):
    pass


def _take_lock():
    p = lock_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fh = open(p, "a")
    if fcntl:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise Busy(p)
    return fh


def exec_codex(worktree, brief_path, out=None, err=None):
    """pantheon exec codex <worktree> <файл поручения>. Коды: 0 — коммит есть; 1 — отказ (ошибка хода, защищённые
    пути, нет изменений); 2 — неверный вызов или worktree не чистый; 3 — Codex недоступен (задачу на dev-*); 4 — занят."""
    out = out or (lambda s: print(s, flush=True))
    err = err or (lambda s: print(s, file=sys.stderr, flush=True))
    ok, why = codex_status()
    if not ok:
        err(f"Codex недоступен: {why} — задачу на dev-*")
        return UNAVAILABLE
    wt = os.path.realpath(worktree)
    if not os.path.isdir(wt) or _git(wt, "rev-parse", "--show-toplevel").returncode != 0:
        err(f"pantheon exec codex: {worktree} — не папка git (worktree)")
        return 2
    try:
        brief = open(brief_path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError) as e:
        err(f"pantheon exec codex: поручение не читается: {e}")
        return 2
    if not brief.strip():
        err("pantheon exec codex: поручение пустое")
        return 2
    try:
        lk = _take_lock()
    except Busy as e:
        err(f"Codex занят: другой запуск держит {e} — один процесс на CODEX_HOME роли")
        return BUSY
    old = _trap_signals()
    try:
        return _exec_locked(wt, brief, out, err)
    except Interrupted as e:
        err(f"прервано ({e}): Codex остановлен, изменения не закоммичены — проверь worktree {wt}")
        return 1
    finally:
        _restore_signals(old)
        lk.close()  # замок снимается и при прерывании


STOP_SIGNALS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGHUP", "SIGINT") if hasattr(signal, n))


def _trap_signals():
    """SIGTERM/SIGHUP/SIGINT обёртке → исключение Interrupted: run_codex гасит группу Codex, замок снимается.
    Повторный сигнал во время остановки не мешает: после первого обработчики игнорируют остальные."""
    import threading
    if threading.current_thread() is not threading.main_thread():
        return None

    def on_signal(signum, _frame):
        for s in STOP_SIGNALS:
            signal.signal(s, signal.SIG_IGN)
        raise Interrupted(signal.Signals(signum).name)
    old = {s: signal.getsignal(s) for s in STOP_SIGNALS}
    for s in STOP_SIGNALS:
        signal.signal(s, on_signal)
    return old


def _restore_signals(old):
    for s, h in (old or {}).items():
        signal.signal(s, h if h is not None else signal.SIG_DFL)


def _exec_locked(wt, brief, out, err):
    before = snapshot(wt)  # снимок под замком, до любого вызова codex
    dirty = dirty_paths(before)
    if dirty:  # чужие правки не должны попасть в коммит под трейлером Executor: codex
        more = f" и ещё {len(dirty) - 5}" if len(dirty) > 5 else ""
        err(f"worktree не чистый: {', '.join(dirty[:5])}{more} — закоммить или убери до запуска Codex")
        return 2
    ensure_home()
    env = role_env()
    exe = codex_bin()
    ver = codex_version(env) or (load().get("codex") or {}).get("version") or "?"
    d = _branch_dir(wt)
    tag = datetime.fromtimestamp(time.time()).strftime("%Y%m%d-%H%M%S")
    report = os.path.join(d, f"report-{tag}.md")
    argv = [exe, *EXEC_FLAGS, "-"]
    idle, total = _num("PANTHEON_CODEX_IDLE_S", 1800), _num("PANTHEON_CODEX_TIMEOUT_S", 7200)
    logs, kind, text, parsed = [], "failed", "", None
    for attempt in (1, 2):
        log = os.path.join(d, f"codex-{tag}-{attempt}.jsonl")
        logs.append(log)
        rc, o, e, killed = run_codex(argv, wt, env, brief, log, idle, total)
        parsed = parse_events(o)
        kind, text = classify(rc, parsed, e, killed)
        if kind != "crash" or attempt == 2:
            break
        err(f"Codex упал посреди хода ({text}) — один повтор")
    out(f"исполнитель: codex {ver}, лог: {logs[-1]}")
    if len(logs) > 1:
        out(f"первая попытка: {logs[0]}")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write((parsed["answer"] or "") if kind == "ok" else f"Codex: {kind}\n\n{text}\n\n{parsed['answer'] or ''}")
    out(f"отчёт: {report}")
    after = snapshot(wt)
    changed = changed_paths(wt, before, after)
    hits = [p for p in changed if protected_hit(p)]
    wr = window_rules_hit(wt, before[0])
    if hits or wr:
        err("Codex задел защищённые пути — не коммичу и не откатываю:")
        for p in hits:
            err(f"  {p}")
        if wr:
            err(f"  {WINDOW_FILE}: правила окон (autoMode/permissions) — {len(wr)} строк диффа")
        return 1
    if kind == "auth":
        _disable("нужен вход")
        err(f"Codex недоступен: нужен вход ({text}) — Codex выключен, задачу на dev-*. Вход: pantheon-setup --add codex")
        return UNAVAILABLE
    if kind in ("limit", "demand"):
        until = (_again_at(text) if kind == "limit" else None) or \
            stamp(now() + 60 * (LIMIT_PAUSE_MIN if kind == "limit" else DEMAND_PAUSE_MIN))
        _disable("лимит" if kind == "limit" else "высокая нагрузка", until=until)
        err(f"Codex недоступен до {until}: {text} — задачу на dev-*")
        return UNAVAILABLE
    if kind != "ok":
        err(f"Codex: отказ ({kind}): {text}")
        if changed:
            err("изменено и не закоммичено: " + ", ".join(changed[:20]))
        return 1
    try:
        sha, why = commit_result(wt, before[0], brief)
    except RuntimeError as e:
        err(f"коммит не удался: {e}")
        return 1
    if not sha:
        err(why)
        return 1
    out(f"коммит: {sha}")
    return 0


# --- CLI --------------------------------------------------------------------------------------------------------

def show():
    cfg = load()
    cx = cfg.get("codex") or {}
    ok, why = codex_status(cfg)
    lines = ["исполнители: " + ", ".join(executor_set(cfg))]
    if "codex" in executor_set(cfg) or cx:
        lines.append("Codex: " + ("включён" if ok else why))
        extra = [f"{k}={cx[k]}" for k in ("version", "checked", "disabled_until", "home") if cx.get(k)]
        if extra:
            lines.append("  " + ", ".join(extra))
    return "\n".join(lines)


def cli(rest, task_head=None):
    """pantheon executors [check | --add codex | --remove <имя> | pick <id> [--kind …]]."""
    try:
        if not rest:
            print(show())
            return 0
        if rest == ["check"]:
            code, text = check_codex()
            print(text, file=sys.stderr if code else sys.stdout)
            return code
        if rest[:1] == ["--add"] and len(rest) == 2:
            if rest[1] == "claude":
                print("Claude в наборе всегда")
                return 0
            if rest[1] != "codex":
                print(f"исполнителя «{rest[1]}» нет; известны: {', '.join(KNOWN)}", file=sys.stderr)
                return 2
            return add_codex(interactive=False, live_probe=False)
        if rest[:1] == ["--remove"] and len(rest) == 2:
            code, text = remove(rest[1])
            print(text, file=sys.stderr if code else sys.stdout)
            return code
        if rest[:1] == ["pick"] and len(rest) in (2, 4):
            kind = None
            if len(rest) == 4:
                if rest[2] != "--kind":
                    raise ValueError("pick <id задачи> [--kind mechanics|code|hard]")
                kind = rest[3]
            head = task_head(rest[1]) if task_head else None
            if head is None:
                print(f"нет задачи {rest[1]}", file=sys.stderr)
                return 1
            role, warn = pick(head, kind)
            if warn:
                print(f"предупреждение: {warn}", file=sys.stderr)
            print(role)
            return 0
    except ValueError as e:
        print(f"pantheon executors: {e}", file=sys.stderr)
        return 2
    print("pantheon executors [check | --add codex | --remove <имя> | pick <id задачи> [--kind mechanics|code|hard]]",
          file=sys.stderr)
    return 2


def exec_cli(rest):
    if len(rest) != 3 or rest[0] != "codex":
        print("pantheon exec codex <папка worktree> <файл поручения>", file=sys.stderr)
        return 2
    try:
        return exec_codex(rest[1], rest[2])
    except ValueError as e:  # битый config.toml
        print(f"pantheon exec codex: {e}", file=sys.stderr)
        return 2
