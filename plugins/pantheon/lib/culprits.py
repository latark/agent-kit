"""Виновники памяти (metis-0568): кто держит память, когда Mac в красной зоне, и уборка брошенного.

  проверка дежурного «виновники памяти» (lib/watch.py, раз в 5 мин)
      Красная зона — своп выше swap_alert_gb (порог дежурного), давление памяти не «норма» или нагрузка (load за
      1 мин) выше load_red_per_cpu × число ядер. Тогда — процессы claude, node, tsx, next, vitest, pnpm и сироты
      Python multiprocessing (resource_tracker, spawn_main с ppid 1 — остатки прогонов тестов) старше
      CULPRIT_HOURS: чей (сессия, направление, worktree и задача по ветке), сколько памяти (top: память и сжатая,
      иначе RSS), возраст. Одна строка в alerts.md с таблицей «процесс → чей → память → возраст» на эпизод красной
      зоны: следующая — после EPISODE_GAP без красной зоны или через EPISODE_REPEAT, если зона держится (своп выше
      порога бывает сутками: до metis-0617 эпизод продлевался каждым проходом, и 30.10 строки не было вовсе). Без
      виновников строки нет (своп и так в тревоге). Language server (pyright-langserver, typescript-language-server,
      tsserver) — свой вид lsp: по исполняемому файлу (lsp_name), а не по слову в командной строке.
  pantheon reap [--apply] [--pid N …]
      Без флагов — сухой прогон: тот же список и что с кем будет. --apply гасит только точно брошенное: процесс (не
      claude) с cwd или путём в команде под .claude/worktrees/ репозитория направления, когда копии больше нет или
      все задачи её ветки закрыты (done, dropped), и сироту multiprocessing с cwd в папках Пантеона (в том числе
      ~/.local/state/pantheon и кэш плагинов agent-kit). Остальное своё — строка вопроса «[<id>] …» для окна вопросов Зевса.
      --apply --pid N … — после «да» владельца: только процессы Пантеона из списка (worktree, папки направлений,
      ~/ai/pantheon, мастерская), не claude; из окна Гестии — только pid из вопроса, на который владелец ответил «да»:
      свежая метка `<state>/hestia-consent/<id задачи>.reap`, её пишет `pantheon consent <id>` (метка push не годится).
      Чужое (вне папок Пантеона) не гасится никогда. Гашение — SIGTERM, через REAP_WAIT с — SIGKILL; строка в
      alerts.md. Коды: 0 — сделано; 1 — что-то не погашено или отказано; 2 — ошибка вызова или нет согласия;
      3 — список процессов не прочитан.
      Остаток (модель угроз guard): окно Гестии узнаём по PANTHEON_ROLE из окружения — команда с подменённой
      переменной проходит мимо проверки согласия. Это намеренный обход, граница — песочница окна.
  pantheon reap --auto   (metis-0617) задача планового прохода раз в 30 мин, без красной зоны и без вопроса: гасит
      только точно брошенное старше AUTO_MINUTES (auto_verdict) — сироту multiprocessing (ppid 1) в папках Пантеона,
      процесс в удалённой worktree или копии с закрытыми задачами, language server без живого родителя-claude (по
      цепочке ppid до launchd — только запускалки LAUNCHERS по точному имени или другой language server; сервер и его
      дети — одной семьёй, _lsp_family: щадим одного — щадим всех), сироту
      (ppid 1) в песочнице окна (~/Library/Caches/pantheon-sandbox; записи кэша убирает дежурный, sandbox_sweep).
      Отказ закрытый (проверка безопасности 04.11, два круга): вид — по исполняемому файлу или скрипту node
      (exec_kind), а не по слову в строке; чьё — только по cwd из lsof (cwd не прочитан — не гасим); выше по цепочке
      ppid живая claude, сессия из `claude agents`, задача launchd или идущая проверка вне окна (`run.py outside`,
      outside_like) — не гасим; другой процесс той же группы (pgid) под живым хозяином — не гасим (сирота прогона
      outside); цепочку не пройти до launchd — не гасим; сам процесс — задача launchd (`launchctl list`) — не гасим;
      сирота в песочнице окна, у которого есть
      живая сессия, — не гасим; language server прямо под launchd — только в удалённой копии или копии с закрытыми
      задачами. `claude agents` (строго: код 0 и разобранный список) или `launchctl list` не прочитаны — проход
      пропущен с кодом 3.
      Остаток (модель угроз guard): процесс Пантеона может подделать свою командную строку и cwd, а окно песочницы
      узнаём по имени сессии (из `claude agents`, реестра имён ~/.claude/sessions и `--name` claude; zeus → hq), её
      файлу settings/run/<имя>.json, `--settings` claude и `claude -p --agent <роль>` для окон job-*;
      сессию, которой нет ни в `claude agents`, ни в этих признаках, reap --auto не видит. Граница — песочница окна. Не трогает claude,
      процессы из пакетов /Applications/*.app (браузеры, редакторы, приложения) и всё вне папок Пантеона. Каждое
      гашение — строка «погашено: что, чьё, почему, МБ» в alerts.md. Коды: 0 — нечего или погашено; 1 — что-то не
      погашено; 2 — --auto не один; 3 — список процессов или сессий не прочитан. Строка для schedule.toml:
      name = "reap", command = "pantheon reap --auto",
      every = 30, class = "light", hosts = "all", timeout = 300, notify = false.

Подмены для тестов: PANTHEON_FAKE_PROCS — список процессов JSON ([{pid, ppid, pgid, age (с), rss (КБ), args, cwd, mem и
cmprs (МБ, необязательно)}]); PANTHEON_FAKE_LOAD — нагрузка; PANTHEON_FAKE_KILL_LOG — файл, куда пишется «pid сигнал»
вместо настоящего kill. Под подменой свопа или давления (PANTHEON_FAKE_SWAP, PANTHEON_FAKE_PRESSURE) настоящие ps и
нагрузка Mac не читаются: иначе тесты видели бы процессы и load владельца.
"""
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


CULPRIT_HOURS = 2          # процесс старше — кандидат в виновники
LOAD_RED_PER_CPU = 4.0     # нагрузка выше этого × число ядер — красная зона (28.10: load 108 на 8 ядрах)
EPISODE_GAP = 3600         # красной зоны не было столько — следующая красная зона считается новым эпизодом
EPISODE_REPEAT = 6 * 3600  # красная зона держится — повтор таблицы не реже (metis-0617: своп выше порога сутками)
AUTO_MINUTES = 30          # reap --auto: процесс моложе не трогаем
TABLE_MAX = 8              # строк таблицы в тревоге
REAP_WAIT = 3.0            # после SIGTERM ждём столько, затем SIGKILL
CLOSED = ("done", "dropped")
KIND_RE = re.compile(r"(?:^|[\s/])(vitest|next-server|next|tsx|pnpm)(?=[\s/.@(]|$)")
SCRIPT_RE = re.compile(r"\.(?:[cm]?[jt]sx?)$")
MP_RE = re.compile(r"multiprocessing\.(?:resource_tracker|spawn)\b.*\b(?:main|spawn_main)\(")
WT_RE = re.compile(r"(/\S*?)/\.claude/worktrees/([^/\s]+)")
ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")  # как boardstatus.ID_RE
# language server, который запускает claude (плагины LSP): живёт, пока жив родитель; без него — мусор. Имя сверяем
# с исполняемым файлом или скриптом node, а не ищем в строке: `SCREEN -dmS tsserver` — не сервер (lsp_name)
LSP_FILE_RE = re.compile(r"^(pyright-langserver|typescript-language-server|tsserver)(?:\.[cm]?js)?$")
NODE_RE = re.compile(r"^node(?:\d+(?:\.\d+)*)?$")
# claude: исполняемый файл claude или node с cli.js пакета @anthropic-ai/claude-code — его дети не трогаем
CLAUDE_CLI_RE = re.compile(r"@anthropic-ai/claude-code/cli\.[cm]?js(?=\s|$)")
# процесс из пакета приложения в /Applications, ~/Applications, /System/Applications — браузер, редактор, приложение
# владельца: не трогаем. Не любой .app: у Python с python.org и Homebrew дети multiprocessing идут из
# …/Python.framework/…/Python.app/Contents/MacOS/Python (проба 04.11) — их сироты гасить нужно
APP_RE = re.compile(r"(?:^|[\s/])Applications/[^/]+\.app/Contents/")
# Родители language server, через которые цепочка идёт дальше вверх: короткоживущие запускалки по точному имени
# исполняемого файла. Не node: долгоживущий node (сервер, редактор, claude) — живой хозяин, а не запускалка
LAUNCHERS = {"sh", "bash", "zsh", "dash", "env", "npm", "npx", "pnpm"}
PY_RE = re.compile(r"^[Pp]ython(?:\d+(?:\.\d+)*)?$")
# окно сессии, запущенной без файла settings/run/<имя>.json: Зевс — `--settings settings/hq.json` (sessions.py: start
# zeus и свежий старт fresh_target), а его окно песочницы — hq (metis-0805, Д1)
SESSION_WINDOW = {"zeus": "hq"}


def lsp_name(args):
    """Имя language server или None. Сервер — basename argv[0] (pyright-langserver, typescript-language-server, tsserver)
    или argv[0] — node, а первый аргумент без «-» — скрипт сервера (…/pyright-langserver, …/tsserver.js,
    …/pyright/langserver.index.js). Слово в другом месте строки сервером не делает."""
    toks = args.split()
    if not toks:
        return None
    m = LSP_FILE_RE.match(os.path.basename(toks[0]))
    if m:
        return m.group(1)
    if not NODE_RE.match(os.path.basename(toks[0])):
        return None
    script = next((t for t in toks[1:] if not t.startswith("-")), "")
    if script.endswith("/pyright/langserver.index.js"):
        return "pyright-langserver"
    m = LSP_FILE_RE.match(os.path.basename(script))
    return m.group(1) if m else None


def claude_like(args):
    """Процесс claude: исполняемый файл claude или node с cli.js пакета Claude Code."""
    toks = args.split()
    return bool(toks) and (os.path.basename(toks[0]) == "claude" or bool(CLAUDE_CLI_RE.search(args)))


def outside_like(args):
    """Идущая проверка вне окна: python …/run.py outside … (`pantheon outside test|serve`, проход `outside run`) —
    держатель, как claude: её тесты и сервер идут в копии роли, в том числе закрытой задачи (metis-0805, Д3)."""
    toks = args.split()
    if not toks or not PY_RE.match(os.path.basename(toks[0])):
        return False
    rest = [t for t in toks[1:] if not t.startswith("-")]
    return len(rest) >= 2 and os.path.basename(rest[0]) == "run.py" and rest[1] == "outside"


def _faked():
    return any(os.environ.get(k) is not None for k in ("PANTHEON_FAKE_SWAP", "PANTHEON_FAKE_PRESSURE"))


# --- красная зона -----------------------------------------------------------------------

def load_avg():
    fake = os.environ.get("PANTHEON_FAKE_LOAD")
    if fake is not None:
        try:
            return float(fake)
        except ValueError:
            return None
    if _faked():
        return None
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def red_reasons():
    """Причины красной зоны строками; пусто — зона не красная."""
    w = P.watch_mod()
    out = []
    gb = None
    with contextlib.suppress(Exception):
        gb = w.swap_gb()
    limit = w.threshold("swap_alert_gb", w.SWAP_ALERT_GB)
    if gb is not None and gb > limit:
        out.append(f"своп {gb:.1f} ГБ > {limit:g} ГБ")
    pr = P._memory_pressure()
    if pr is not None and pr >= 2:
        out.append(f"давление памяти {'критичное' if pr >= 4 else 'предупреждение'}")
    la, cpus = load_avg(), os.cpu_count() or 1
    per = w.threshold("load_red_per_cpu", LOAD_RED_PER_CPU)
    if la is not None and la > per * cpus:
        out.append(f"нагрузка {la:.0f} > {per * cpus:g} ({cpus} ядер)")
    return out


# --- процессы ---------------------------------------------------------------------------

def _etime(s):
    """ps etime «[[дд-]чч:]мм:сс» → секунды или None."""
    m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", s.strip())
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + se


def _mb(s):
    """Поле top «1235M», «12K», «2G+» → МБ или None."""
    m = re.fullmatch(r"([\d.]+)([KMGB]?)[+-]?", s.strip())
    if not m:
        return None
    return float(m.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024, "B": 1 / 1048576, "": 1 / 1048576}[m.group(2)]


def kind_of(args, ppid=None):
    """Вид процесса по командной строке: claude, vitest, next, tsx, pnpm, node, python-mp (сирота multiprocessing:
    resource_tracker или spawn_main с ppid 1 — остаток прогона тестов, чей родитель умер) — или None (не наш вид)."""
    toks = args.split()
    if not toks:
        return None
    if MP_RE.search(args):
        return "python-mp" if ppid == 1 else None
    base = os.path.basename(toks[0])
    if base == "claude":
        return "claude"
    if lsp_name(args):
        return "lsp"
    m = KIND_RE.search(args)
    if m:
        return "next" if m.group(1) == "next-server" else m.group(1)
    if base == "node" or base.startswith("node"):
        return "node"
    if base in ("npm", "npx"):
        return None
    return None


def label(p):
    if p["kind"] == "python-mp":
        return "python " + ("resource_tracker" if "resource_tracker" in p["args"] else "spawn_main")
    if p["kind"] == "lsp":
        return "lsp " + (lsp_name(p["args"]) or "?")
    script = next((os.path.basename(t) for t in reversed(p["args"].split())
                   if SCRIPT_RE.search(t) and "node_modules" not in t), "")
    return p["kind"] + (f" {script}" if script else "")


def ps_all():
    """Все процессы — [dict(pid, ppid, pgid, age, rss КБ, args, cwd, mem и cmprs МБ или None)]; None — не прочитать."""
    raw = os.environ.get("PANTHEON_FAKE_PROCS")
    if raw is not None:
        try:
            lst = json.loads(raw) if raw.strip() else []
        except ValueError:
            return None
        procs = [dict(pid=int(x["pid"]), ppid=x.get("ppid"), pgid=x.get("pgid"), age=float(x.get("age") or 0),
                      rss=int(x.get("rss") or 0),
                      args=str(x.get("args") or ""), cwd=x.get("cwd"), mem=x.get("mem"), cmprs=x.get("cmprs"))
                 for x in lst]
    elif _faked():
        return []
    else:
        try:
            r = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,pgid=,etime=,rss=,args="], capture_output=True,
                               text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0:
            return None
        procs = []
        for ln in r.stdout.splitlines():
            m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s+(.*)$", ln)
            if m and _etime(m.group(4)) is not None:
                procs.append(dict(pid=int(m.group(1)), ppid=int(m.group(2)), pgid=int(m.group(3)),
                                  age=_etime(m.group(4)), rss=int(m.group(5)), args=m.group(6).strip(), cwd=None,
                                  mem=None, cmprs=None))
    return procs


def collect(procs=None):
    """[процесс] из ps_all() (или переданного списка) — только наших видов, с полем kind; None — не прочитать."""
    if procs is None:
        procs = ps_all()
    if procs is None:
        return None
    out = []
    for p in procs:
        p["kind"] = kind_of(p["args"], p.get("ppid"))
        if p["kind"] and p["pid"] != os.getpid():
            out.append(p)
    return out


def _details(procs):
    """cwd (lsof) и память со сжатой (top) — только для кандидатов, одним вызовом каждого; сбой — поле пустое."""
    pids = [p["pid"] for p in procs if p.get("cwd") is None]
    if pids and os.environ.get("PANTHEON_FAKE_PROCS") is None:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            r = subprocess.run(["lsof", "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fn"],
                               capture_output=True, text=True, timeout=20)
            cur, cwd = None, {}
            for ln in r.stdout.splitlines():
                if ln.startswith("p") and ln[1:].isdigit():
                    cur = int(ln[1:])
                elif ln.startswith("n") and cur is not None:
                    cwd[cur] = ln[1:]
            for p in procs:
                p["cwd"] = p.get("cwd") or cwd.get(p["pid"])
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            argv = ["top", "-l", "1", "-stats", "pid,mem,cmprs"]
            for pid in pids:
                argv += ["-pid", str(pid)]
            r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
            mem = {}
            for ln in r.stdout.splitlines():
                m = re.match(r"\s*(\d+)\s+(\S+)\s+(\S+)\s*$", ln)
                if m:
                    mem[int(m.group(1))] = (_mb(m.group(2)), _mb(m.group(3)))
            for p in procs:
                if p["pid"] in mem:
                    p["mem"], p["cmprs"] = mem[p["pid"]]
    return procs


def candidates(procs, hours=None):
    lim = (CULPRIT_HOURS if hours is None else hours) * 3600
    return _details([p for p in procs if p["age"] >= lim])


# --- чей процесс ------------------------------------------------------------------------

def _under(p, root):
    return p == root or p.startswith(root.rstrip("/") + "/")


def _real(p):
    return os.path.realpath(os.path.expanduser(p))


def context(agents=None):
    """Что нужно для «чей»: корни направлений, статусы задач, pid живых сессий."""
    roots = {}
    for name, folders in (P.watch_mod().domains() or {}).items():
        for f in folders if isinstance(folders, list) else []:
            if isinstance(f, str):
                roots.setdefault(_real(f), name)
    tasks = {}
    with contextlib.suppress(Exception):
        tasks = {tid: (h or {}).get("status") for tid, (_, h, _) in P.tasks_mod().load_tasks(P.PANTHEON).items()}
    sessions = {int(a["pid"]): a.get("name") or a.get("id") or "?" for a in agents or []
                if isinstance(a, dict) and str(a.get("pid") or "").isdigit()}
    return {"roots": roots, "tasks": tasks, "sessions": sessions}


def _branch(wt):
    """Ветка копии по файлам (.git → gitdir → HEAD), без запуска git; None — не прочитать."""
    with contextlib.suppress(OSError, UnicodeDecodeError):
        with open(os.path.join(wt, ".git"), encoding="utf-8") as fh:
            m = re.match(r"gitdir:\s*(.+)", fh.read(4096))
        if m:
            gd = m.group(1).strip()
            gd = gd if os.path.isabs(gd) else os.path.join(wt, gd)
            with open(os.path.join(gd, "HEAD"), encoding="utf-8") as fh:
                m = re.match(r"ref: refs/heads/(\S+)", fh.read(4096))
            return m.group(1) if m else None
    return None


SANDBOX_WHY = "песочница окна Пантеона"


def sandbox_root():
    """Кэш песочниц окон Пантеона (его TMPDIR — PANTHEON_TMP; уборка записей — lib/watch.py sandbox_sweep)."""
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def owner(p, ctx):
    """Как place_owner; сирота multiprocessing в папках Пантеона — всегда брошена (родителя нет, ждать некого)."""
    who, verdict, why = place_owner(p, ctx)
    if p["kind"] == "python-mp" and verdict in ("ask", "abandoned"):
        return who, "abandoned", "сирота multiprocessing (ppid 1), родитель умер"
    return who, verdict, why


def place_owner(p, ctx):
    """→ (чей — строка, вердикт, почему): вердикт session (живая сессия), abandoned (точно брошено), ask (своё,
    спросить владельца) или foreign (чужое — не трогать)."""
    if p["pid"] in ctx["sessions"]:
        return f"сессия {ctx['sessions'][p['pid']]}", "session", "живая сессия — pantheon stop"
    cwd = p.get("cwd") or ""
    places = [cwd] if cwd else []
    m = WT_RE.search(cwd + " ") if cwd else None
    if not m:
        m = WT_RE.search(p["args"])
    if m:
        root, name = _real(m.group(1)), m.group(2)
        wt = os.path.join(root, ".claude", "worktrees", name)
        d = ctx["roots"].get(root)
        if d:
            who = f"{d}, worktree {name}"
            if not os.path.isdir(wt):
                verdict, why = "abandoned", "worktree удалён"
            else:
                ids = list(dict.fromkeys(ID_RE.findall(_branch(wt) or "") + ID_RE.findall(name)))
                known = [i for i in ids if i in ctx["tasks"]]
                if ids:
                    who += ", задача " + ", ".join(ids)
                if known and all(ctx["tasks"][i] in CLOSED for i in known):
                    verdict, why = "abandoned", "задача закрыта (" + ", ".join(
                        f"{i} {ctx['tasks'][i]}" for i in known) + ")"
                else:
                    verdict, why = "ask", "копия жива, задача не закрыта" if known else "копия жива, задачи не найти"
            if verdict == "abandoned" and p["kind"] == "claude":
                verdict, why = "ask", why + "; claude сам не гашу"
            return who, verdict, why
        places.append(m.group(0))
    for place in places:
        rp = _real(place)
        for root, d in sorted(ctx["roots"].items(), key=lambda x: -len(x[0])):
            if _under(rp, root):
                return f"{d}, папка направления", "ask", "папка направления — может быть ваше"
        if _under(rp, P.PANTHEON):
            rel = os.path.relpath(rp, P.PANTHEON).split(os.sep)
            who = rel[1] if rel[:1] == ["directions"] and len(rel) > 1 else "Пританей"
            return f"{who}, ~/ai/pantheon", "ask", "папка Пантеона"
        if _under(rp, _real(P.WORKSHOP)):
            rel = os.path.relpath(rp, _real(P.WORKSHOP)).split(os.sep)
            return f"мастерская {rel[0]}", "ask", "мастерская"
        if _under(rp, _real(sandbox_root())):
            return f"песочница окна, {place.replace(P.HOME, '~')}", "ask", SANDBOX_WHY
        for root, who in ((P.STATE, "состояние Пантеона"),
                          (os.path.join(P.HOME, ".claude", "plugins", "cache", "agent-kit"), "плагины agent-kit")):
            if _under(rp, _real(root)):
                return f"{who}, {place.replace(P.HOME, '~')}", "ask", "служебная папка Пантеона"
    return (cwd.replace(P.HOME, "~") or "cwd не прочитан"), "foreign", "вне папок Пантеона"


def fmt_mem(p):
    mb = p["mem"] if p.get("mem") is not None else p["rss"] / 1024
    s = f"{mb / 1024:.1f} ГБ" if mb >= 1024 else f"{mb:.0f} МБ"
    if p.get("cmprs"):
        c = p["cmprs"]
        s += f" (сжато {c / 1024:.1f} ГБ)" if c >= 1024 else f" (сжато {c:.0f} МБ)"
    return s


def fmt_age(sec):
    h = sec / 3600
    return f"{h / 24:.0f} дн." if h >= 48 else f"{h:.0f} ч"


def rows(procs, ctx):
    """[(процесс, чей, вердикт, почему)] — по памяти, больше первыми."""
    out = [(p, *owner(p, ctx)) for p in procs]
    out.sort(key=lambda r: -(r[0]["mem"] if r[0].get("mem") is not None else r[0]["rss"] / 1024))
    return out


# --- проверка дежурного -----------------------------------------------------------------

def watch_check(agents, t):
    """Красная зона → одна строка в alerts.md с виновниками на эпизод (см. шапку)."""
    reasons = red_reasons()
    if not reasons:
        return
    # метка: «последний красный проход» и «последняя тревога». Раньше была одна — последний красный проход, и эпизод
    # продлевался каждым проходом: своп выше порога держался с 28.10 сутками, и тревога была только после сна Mac
    # дольше часа — 30.10 (своп 9,7 ГБ) строки виновников не было (metis-0617). Старая метка из одного числа —
    # тревоги в ней нет: первая же красная проверка после выпуска даёт строку.
    mark = P.path("culprits-last")
    try:
        vals = [float(x) for x in open(mark).read().split()]
    except (OSError, ValueError):
        vals = []
    last = vals[0] if vals else 0.0
    alerted = vals[1] if len(vals) > 1 else 0.0
    same = last <= t <= last + EPISODE_GAP
    if same and alerted <= t < alerted + EPISODE_REPEAT:  # тот же эпизод, тревога свежая — только продлить
        P.write_atomic(mark, f"{t} {alerted}\n")
        return
    procs = collect()
    if procs is None:
        raise RuntimeError("список процессов (ps) не прочитан")
    rs = rows(candidates(procs), context(agents))
    if not rs:
        P.write_atomic(mark, f"{t} {alerted if same else 0.0}\n")
        return
    table = "; ".join(f"{label(p)} (pid {p['pid']}) → {who} → {fmt_mem(p)} → {fmt_age(p['age'])}"
                      for p, who, _, _ in rs[:TABLE_MAX])
    more = f"; и ещё {len(rs) - TABLE_MAX}" if len(rs) > TABLE_MAX else ""
    n_ab = sum(1 for r in rs if r[2] == "abandoned")
    n_ask = sum(1 for r in rs if r[2] == "ask")
    held = f", красная зона держится {fmt_age(t - alerted)} с прошлой строки" if same and alerted else ""
    P.alert(f"виновники памяти ({'; '.join(reasons)}{held}), процессы старше {CULPRIT_HOURS} ч — процесс → чей → память → "
            f"возраст: {table}{more}. Брошено: {n_ab}, своё живое: {n_ask}. Брошенное гасит плановый проход "
            "(`pantheon reap --auto`, раз в 30 мин); сразу или об остальном — Зевсу: задача и `pantheon wake hestia "
            "--task <id>` — Гестия погасит брошенное (`pantheon reap --apply`), об остальном спросит вас", "watch")
    P.write_atomic(mark, f"{t} {t}\n")


# --- pantheon reap ----------------------------------------------------------------------

def _kill(pid, sig):
    log = os.environ.get("PANTHEON_FAKE_KILL_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"{pid} {int(sig)}\n")
        return
    os.kill(pid, sig)


def _alive(pid):
    if os.environ.get("PANTHEON_FAKE_KILL_LOG"):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop(pid):
    """SIGTERM, через REAP_WAIT — SIGKILL; → None или причина неудачи."""
    try:
        _kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except OSError as e:
        return f"{type(e).__name__}: {e}"
    end = time.monotonic() + REAP_WAIT
    while time.monotonic() < end and _alive(pid):
        time.sleep(0.1)
    if _alive(pid):
        try:
            _kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return None
        except OSError as e:
            return f"{type(e).__name__}: {e}"
    return None


def consent_pids():
    """Окно Гестии: pid из вопроса о гашении, на который владелец ответил «да» — свежая (2 ч, как у guard) метка
    `<state>/hestia-consent/<задача окна>.reap`, её пишет `pantheon consent`. Метка push (без .reap) не годится.
    None — метки нет или она устарела."""
    task = os.environ.get("PANTHEON_TASK") or ""
    if not P.CONSENT_ID.fullmatch(task):
        return None
    path = os.path.join(P.STATE, "hestia-consent", task + ".reap")
    try:
        st = os.lstat(path)
        import stat as _st
        if not _st.S_ISREG(st.st_mode) or not 0 <= time.time() - st.st_mtime <= 2 * 3600:
            return None
        m = re.search(r"^pids:([\d ]*)$", open(path, encoding="utf-8").read(), re.M)
    except (OSError, UnicodeDecodeError):
        return None
    return {int(x) for x in m.group(1).split()} if m else None


USAGE = "pantheon reap [--apply] [--pid N …] | --auto — без --apply и --auto только показать"


AUTO_KINDS = {"vitest": "vitest", "next": "next", "next-server": "next", "tsx": "tsx", "pnpm": "pnpm"}


def exec_kind(args):
    """Вид для reap --auto по исполняемому файлу, как lsp_name: basename argv[0] — python с кодом multiprocessing,
    language server, node, vitest, next-server, tsx, pnpm. Слово в остальных аргументах (`SCREEN -dmS next`,
    `tmux new -s pnpm`) вида не даёт: None."""
    toks = args.split()
    if not toks:
        return None
    base = os.path.basename(toks[0])
    if PY_RE.match(base) and MP_RE.search(args):
        return "python-mp"  # сирота ли (ppid 1) — решает owner
    if lsp_name(args):
        return "lsp"
    if NODE_RE.match(base):
        return "node"  # подпись строки «погашено» — по kind_of; вид здесь решает только «наш ли процесс»
    return AUTO_KINDS.get(base)


def agents_strict():
    """`claude agents --json --all` строго, для reap --auto: код выхода 0 и stdout, который разбирается в список
    (пустой и из пробелов не разбирается) → список после reconcile_agents; иначе None. P.agents_all мягче: пустой
    вывод там — пустой список, а для гашения это значит «живых сессий нет»."""
    try:
        r = subprocess.run([P.claude_bin(), "agents", "--json", "--all"], env=P.claude_env(), capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None
    data = data.get("agents") if isinstance(data, dict) else data
    return P.reconcile_agents(data) if isinstance(data, list) else None


def launchd_pids():
    """pid задач launchd пользователя (`launchctl list`, первая колонка) — их reap --auto не трогает; None — не
    прочитать (код не 0, нет launchctl). Тесты кладут поддельный launchctl первым в PATH."""
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return {int(m.group(1)) for m in (re.match(r"(\d+)\s", ln) for ln in r.stdout.splitlines()) if m}


def _run_window(path):
    """PANTHEON_WINDOW файла запуска settings/run/<имя>.json или None."""
    w = ((P.read_json(path, {}) or {}).get("env") or {}).get("PANTHEON_WINDOW")
    return w if isinstance(w, str) else None


def live_windows(ctx, table):
    """Окна песочницы (папки ~/Library/Caches/pantheon-sandbox/<окно>), у которых есть живая сессия. Имя живой
    сессии — из `claude agents`, из реестра имён ~/.claude/sessions (живой pid: интерактивная вкладка, которой нет в
    `claude agents`) и `--name` живого claude из ps; окно имени — само имя, PANTHEON_WINDOW его settings/run/<имя>.json
    и SESSION_WINDOW (zeus → hq: файла запуска у Зевса нет, metis-0805). У живого claude из ps ещё `--settings` (окно
    settings/<окно>.json или PANTHEON_WINDOW файла settings/run/<имя>.json) и job-<роль> по `--agent <роль>`."""
    wins, names = set(), list(ctx["sessions"].values())
    with contextlib.suppress(Exception):
        names += [r.get("name") for r in P.sessions_registry()]
    settings = _real(P.path("settings"))
    for q in table.values():
        a = str(q.get("args") or "")
        if not claude_like(a):
            continue
        m = re.search(r"\s--agent[=\s]+(\S+)", a)
        if m:
            wins.add("job-" + m.group(1))
        m = re.search(r"\s--name[=\s]+(\S+)", a)
        if m:
            names.append(m.group(1))
        m = re.search(r"\s--settings[=\s]+(\S+\.json)(?=\s|$)", a)
        if m:
            f = _real(m.group(1))
            if os.path.dirname(f) == settings:
                wins.add(os.path.basename(f)[:-5])
            elif os.path.dirname(f) == os.path.join(settings, "run"):
                wins.add(_run_window(f) or "")
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[\w.-]+", name):
            continue
        wins.add(name)
        wins.add(SESSION_WINDOW.get(name) or "")
        wins.add(_run_window(P.path("settings", "run", name + ".json")) or "")
    wins.discard("")
    return wins


def _chain(p, table):
    """Предки процесса по ppid до launchd (без него) — [процесс]; None — цепочку не пройти до launchd: родителя нет в
    списке ps, петля, ppid не число. Тогда доказать брошенность нечем — не гасим."""
    out, pid, seen = [], p.get("ppid"), {p["pid"]}
    while pid != 1:
        if not isinstance(pid, int) or pid <= 0 or pid in seen or pid not in table:
            return None
        seen.add(pid)
        out.append(table[pid])
        pid = table[pid].get("ppid")
    return out


def _holder(q, ctx):
    """Живой хозяин: claude (исполняемый claude или node с cli.js Claude Code), идущая проверка вне окна
    (outside_like), сессия из `claude agents` или задача launchd."""
    a = str(q.get("args") or "")
    return q["pid"] in ctx["sessions"] or q["pid"] in ctx.get("launchd", ()) or claude_like(a) or outside_like(a)


def _held(chain, ctx):
    """Процесс держит живой хозяин → True (не гасить): предок — _holder; цепочки нет (_chain → None) — тоже True."""
    return chain is None or any(_holder(q, ctx) for q in chain)


def _group_held(p, ctx, table):
    """Группа процессов p (pgid) жива → True: другой её процесс — хозяин или под хозяином (_held его цепочки). Сирота
    с ppid 1 остаётся в группе прогона: outside test и serve ставят группу каждому прогону (start_new_session), и
    ребёнок, ушедший к launchd, пока прогон идёт, не брошен (metis-0805, Д3). pgid нет или он 0–1 — False."""
    g = p.get("pgid")
    if not isinstance(g, int) or g <= 1:
        return False
    return any(q.get("pgid") == g and q["pid"] != p["pid"] and (_holder(q, ctx) or _held(_chain(q, table), ctx))
               for q in table.values())


def _lsp_orphan(chain):
    """Language server, у которого до launchd только запускалки LAUNCHERS (точное имя argv[0]) и другие language
    server (typescript-language-server запускает tsserver) → почему гасить; любой другой предок — долгоживущий node,
    редактор, терминал, приложение — хозяин жив: None. claude и сессии отсекает _held раньше."""
    for q in chain:
        a = str(q.get("args") or "")
        toks = a.split()
        if APP_RE.search(a) or not ((os.path.basename(toks[0]) if toks else "") in LAUNCHERS or lsp_name(a)):
            return None
    return "language server без живого родителя-claude"


def _lsp_family(p, chain, table):
    """Language server и решаемые вместе с ним (metis-0805, Д2): корень — самый верхний предок в цепочке, о котором
    решает reap (exec_kind: другой language server, pnpm), иначе сам p; семья — корень и все language server под ним.
    Запускалки sh, env, npm в семью не входят: reap их не гасит, они уходят сами вместе с ребёнком."""
    root = next((q for q in reversed(chain) if exec_kind(str(q.get("args") or ""))), p)
    fam = [root]
    for q in table.values():
        if q is root or exec_kind(str(q.get("args") or "")) != "lsp":
            continue
        pid, seen = q.get("ppid"), {q["pid"]}
        while isinstance(pid, int) and pid > 1 and pid not in seen and pid in table:
            if pid == root["pid"]:
                fam.append(q)
                break
            seen.add(pid)
            pid = table[pid].get("ppid")
    return fam


def auto_verdict(p, ctx, table):
    """reap --auto: _auto_one; language server — только вместе с семьёй (_lsp_family, metis-0805 Д2): кого-то из неё
    reap щадит (моложе AUTO_MINUTES, прямо под launchd в живой копии, хозяин жив) — не гасим никого. Иначе родителя
    щадили бы, а ребёнка гасили: typescript-language-server прямо под launchd в живой копии жив, его tsserver погашен."""
    v = _auto_one(p, ctx, table)
    if v is None or exec_kind(p["args"]) != "lsp":
        return v
    for q in _lsp_family(p, _chain(p, table) or [], table):
        if q is not p and (q["age"] < AUTO_MINUTES * 60 or _auto_one(q, ctx, table) is None):
            return None
    return v


def _auto_one(p, ctx, table):
    """reap --auto, один процесс: → (чей, почему) — гасить; None — не трогать. Только точно брошенное и только старше AUTO_MINUTES:
      - сирота multiprocessing (ppid 1) в папках Пантеона;
      - процесс (не claude) в удалённой worktree или в копии, где все задачи ветки закрыты;
      - language server (pyright-langserver, typescript-language-server, tsserver) без живого родителя-claude;
      - сирота (ppid 1) с cwd в песочнице окна Пантеона (~/Library/Caches/pantheon-sandbox).
    Никогда: claude, процессы из пакетов приложений (/Applications/*.app — браузеры, редакторы), всё вне папок
    Пантеона. Отказ закрытый: чьё — только по cwd (lsof), а не по командной строке, которую процесс пишет сам (cwd
    нет — place_owner скажет «чужое»); сам процесс — живая сессия — не гасим (place_owner); выше по цепочке ppid
    живая claude, сессия или идущая проверка вне окна, или цепочка не прослежена до launchd — не гасим (_held); другой
    процесс той же группы под живым хозяином — не гасим (_group_held)."""
    a = p["args"]
    if p["kind"] == "claude" or claude_like(a) or APP_RE.search(a):  # возраст отсекает candidates(AUTO_MINUTES)
        return None
    kind = exec_kind(a)
    if kind is None or p["pid"] in ctx.get("launchd", ()):
        return None
    p = dict(p, kind=kind)
    chain = _chain(p, table)
    if _held(chain, ctx) or _group_held(p, ctx, table):
        return None
    who, verdict, why = owner(dict(p, args=""), ctx)  # args пусты — place_owner решает только по cwd
    if p["kind"] == "lsp":
        if verdict not in ("ask", "abandoned") or (not chain and verdict != "abandoned"):
            return None  # прямо под launchd — только в брошенной копии: одного ppid 1 мало
        lwhy = _lsp_orphan(chain)
        return (f"ничей language server, {who}", lwhy) if lwhy else None
    if verdict == "abandoned":
        return who, why
    win = os.path.relpath(_real(p["cwd"]), _real(sandbox_root())).split(os.sep)[0] if why == SANDBOX_WHY else None
    if verdict == "ask" and why == SANDBOX_WHY and p.get("ppid") == 1 and win not in ctx.get("windows", ()):
        return who, "сирота (ppid 1) в песочнице окна, родитель умер"
    return None


def _mb_of(p):
    return p["mem"] if p.get("mem") is not None else p["rss"] / 1024


def reap_auto():
    """pantheon reap --auto — задача планового прохода раз в 30 мин (metis-0617): гасит брошенное по auto_verdict без
    красной зоны и без вопроса. Каждое гашение — строка «погашено: что, чьё, почему, МБ» в alerts.md (одинаковые
    процессы одного владельца с той же причиной — одной строкой). Коды: 0 — нечего или всё погашено; 1 — что-то не
    погашено; 3 — список процессов, сессий или задач launchd не прочитан (ничего не гасим)."""
    raw = ps_all()
    if raw is None:
        print("pantheon reap --auto: список процессов не прочитан (ps) — гасить нечего", file=sys.stderr)
        return 3
    table = {q["pid"]: q for q in raw}
    procs = collect(raw)
    try:
        agents = agents_strict()
    except Exception as ex:  # noqa: BLE001 — любой сбой: без списка сессий не гасим
        agents = f"{type(ex).__name__}: {ex}"
    if not isinstance(agents, list):
        print("pantheon reap --auto: список сессий (claude agents) не прочитан — без него не гашу, проход пропущен"
              + (f" ({agents})" if isinstance(agents, str) else ""), file=sys.stderr)
        return 3
    jobs = launchd_pids()
    if jobs is None:
        print("pantheon reap --auto: список задач launchd (launchctl list) не прочитан — без него не гашу, проход "
              "пропущен", file=sys.stderr)
        return 3
    ctx = context(agents)
    ctx["launchd"] = jobs
    ctx["windows"] = live_windows(ctx, table)
    todo = []
    for p in candidates(procs, hours=AUTO_MINUTES / 60):
        v = auto_verdict(p, ctx, table)
        if v:
            todo.append((p, *v))
    if not todo:
        print(f"pantheon reap --auto: брошенного старше {AUTO_MINUTES} мин нет")
        return 0
    groups, failed = {}, []
    for p, who, why in todo:
        err = _stop(p["pid"])
        if err:
            failed.append(f"{label(p)} pid {p['pid']} ({who}): {err}")
            continue
        groups.setdefault((label(p), who, why), []).append(p)
    for (lb, who, why), ps in groups.items():
        mb = sum(_mb_of(x) for x in ps)
        what = (f"{lb} pid {ps[0]['pid']}" if len(ps) == 1 else
                f"{lb} ×{len(ps)} (pid {', '.join(str(x['pid']) for x in ps)})")
        line = f"погашено: {what}, чьё: {who}, почему: {why}, {mb:.0f} МБ"
        print(line)
        P.alert(line, "reap --auto")
    for s_ in failed:
        print("не погашен: " + s_)
    if failed:
        P.alert("reap --auto: не погашены — " + "; ".join(failed), "reap --auto")
    return 1 if failed else 0


def reap(rest):
    if "--auto" in rest:
        if rest != ["--auto"]:
            print(f"{USAGE}; --auto — только один, без --apply и --pid", file=sys.stderr)
            return 2
        return reap_auto()
    apply_, pids, bad = False, [], []
    it = iter(rest)
    for a in it:
        if a == "--apply":
            apply_ = True
        elif a == "--dry-run":
            pass
        elif a == "--pid":
            for b in it:
                if not b.isdigit():
                    bad.append(b)
                    break
                pids.append(int(b))
        else:
            bad.append(a)
    if bad or (pids and not apply_):
        print(f"{USAGE}; не понял: {' '.join(bad) or '--pid без --apply'}", file=sys.stderr)
        return 2
    allowed = consent_pids() if pids and os.environ.get("PANTHEON_ROLE") == "hestia" else None
    if pids and os.environ.get("PANTHEON_ROLE") == "hestia" and allowed is None:
        print(f"pantheon reap --pid: нет свежего «да» владельца на вопрос о гашении — сначала `pantheon consent "
              f"{os.environ.get('PANTHEON_TASK') or '<id задачи>'}` (код 0), затем повтор", file=sys.stderr)
        return 2
    procs = collect()
    if procs is None:
        print("pantheon reap: список процессов не прочитан (ps) — гасить нечего", file=sys.stderr)
        return 3
    agents = None
    with contextlib.suppress(Exception):
        agents = P.agents_all()
    rs = rows(candidates(procs, hours=0 if pids else None), context(agents))
    mark = {"abandoned": "брошен — погасить", "ask": "своё живое — спросить владельца", "session": "сессия — не трогаю",
            "foreign": "чужое — не трогаю"}
    if not rs:
        print(f"процессов claude/node/tsx/next/vitest/pnpm старше {CULPRIT_HOURS} ч нет")
    for p, who, verdict, why in rs:
        if not pids or p["pid"] in pids:
            print(f"pid {p['pid']}  {label(p)}  → {who} → {fmt_mem(p)} → {fmt_age(p['age'])}  [{mark[verdict]}: {why}]")
    if not apply_:
        return 0
    by_pid = {r[0]["pid"]: r for r in rs}
    if pids:
        todo, refused = [], []
        for pid in pids:
            r = by_pid.get(pid)
            if allowed is not None and pid not in allowed:
                refused.append(f"pid {pid} — не из вопроса, на который владелец ответил «да»")
            elif r is None:
                refused.append(f"pid {pid} — нет среди процессов claude/node/tsx/next/vitest/pnpm")
            elif r[2] not in ("abandoned", "ask") or r[0]["kind"] == "claude":
                refused.append(f"pid {pid} — {r[1]}: {mark[r[2]] if r[0]['kind'] != 'claude' else 'claude не гашу'}")
            else:
                todo.append(r)
    else:
        todo, refused = [r for r in rs if r[2] == "abandoned"], []
    done, failed = [], []
    for p, who, verdict, why in todo:
        err = _stop(p["pid"])
        (failed if err else done).append(f"{label(p)} pid {p['pid']} ({who}{'' if pids else ', ' + why})"
                                         + (f": {err}" if err else ""))
    for s in refused:
        print("отказ: " + s)
    for s in failed:
        print("не погашен: " + s)
    if done:
        print("погашены: " + "; ".join(done))
        by = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
        P.alert(("погашены по «да» владельца" if pids else "погашены брошенные процессы") + ": " + "; ".join(done),
                f"reap ({by})")
    ask = [r for r in rs if r[2] == "ask"] if not pids else []
    if ask:
        qid = os.environ.get("PANTHEON_TASK") or "<id задачи>"
        lst = ", ".join(f"pid {p['pid']} {label(p)} ({who}, {fmt_mem(p)}, {fmt_age(p['age'])})" for p, who, _, _ in ask)
        print(f"вопрос для окна вопросов Зевса: [{qid}] Погасить процессы Пантеона: {lst}?\n"
              f"варианты: Да — погасить | Нет\nпосле «да»: pantheon consent {qid}, затем pantheon reap --apply --pid "
              + " ".join(str(r[0]["pid"]) for r in ask))
    return 1 if failed or refused else 0
