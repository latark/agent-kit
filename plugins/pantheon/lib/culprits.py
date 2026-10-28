"""Виновники памяти (metis-0568): кто держит память, когда Mac в красной зоне, и уборка брошенного.

  проверка дежурного «виновники памяти» (lib/watch.py, раз в 5 мин)
      Красная зона — своп выше swap_alert_gb (порог дежурного), давление памяти не «норма» или нагрузка (load за
      1 мин) выше load_red_per_cpu × число ядер. Тогда — процессы claude, node, tsx, next, vitest, pnpm и сироты
      Python multiprocessing (resource_tracker, spawn_main с ppid 1 — остатки прогонов тестов) старше
      CULPRIT_HOURS: чей (сессия, направление, worktree и задача по ветке), сколько памяти (top: память и сжатая,
      иначе RSS), возраст. Одна строка в alerts.md с таблицей «процесс → чей → память → возраст» на эпизод красной
      зоны: следующая — только после EPISODE_GAP без красной зоны. Без виновников строки нет (своп и так в тревоге).
  pantheon reap [--apply] [--pid N …]
      Без флагов — сухой прогон: тот же список и что с кем будет. --apply гасит только точно брошенное: процесс (не
      claude) с cwd или путём в команде под .claude/worktrees/ репозитория направления, когда копии больше нет или
      все задачи её ветки закрыты (done, dropped), и сироту multiprocessing с cwd в папках Пантеона (в том числе
      ~/.local/state/pantheon и кэш плагинов agent-kit). Остальное своё — строка вопроса «[<id>] …» для окна вопросов Зевса.
      --apply --pid N … — после «да» владельца: только процессы Пантеона из списка (worktree, папки направлений,
      ~/ai/pantheon, мастерская), не claude; из окна Гестии — только при свежей метке `pantheon consent <id задачи>`.
      Чужое (вне папок Пантеона) не гасится никогда. Гашение — SIGTERM, через REAP_WAIT с — SIGKILL; строка в
      alerts.md. Коды: 0 — сделано; 1 — что-то не погашено или отказано; 2 — ошибка вызова или нет согласия;
      3 — список процессов не прочитан.

Подмены для тестов: PANTHEON_FAKE_PROCS — список процессов JSON ([{pid, ppid, age (с), rss (КБ), args, cwd, mem и cmprs
(МБ, необязательно)}]); PANTHEON_FAKE_LOAD — нагрузка; PANTHEON_FAKE_KILL_LOG — файл, куда пишется «pid сигнал»
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
TABLE_MAX = 8              # строк таблицы в тревоге
REAP_WAIT = 3.0            # после SIGTERM ждём столько, затем SIGKILL
CLOSED = ("done", "dropped")
KIND_RE = re.compile(r"(?:^|[\s/])(vitest|next-server|next|tsx|pnpm)(?=[\s/.@(]|$)")
SCRIPT_RE = re.compile(r"\.(?:[cm]?[jt]sx?)$")
MP_RE = re.compile(r"multiprocessing\.(?:resource_tracker|spawn)\b.*\b(?:main|spawn_main)\(")
WT_RE = re.compile(r"(/\S*?)/\.claude/worktrees/([^/\s]+)")
ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")  # как boardstatus.ID_RE


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
    script = next((os.path.basename(t) for t in reversed(p["args"].split())
                   if SCRIPT_RE.search(t) and "node_modules" not in t), "")
    return p["kind"] + (f" {script}" if script else "")


def collect():
    """[процесс] — dict(pid, age, rss КБ, args, cwd, mem и cmprs МБ или None, kind) только наших видов; None — не
    прочитать."""
    raw = os.environ.get("PANTHEON_FAKE_PROCS")
    if raw is not None:
        try:
            lst = json.loads(raw) if raw.strip() else []
        except ValueError:
            return None
        procs = [dict(pid=int(x["pid"]), ppid=x.get("ppid"), age=float(x.get("age") or 0), rss=int(x.get("rss") or 0),
                      args=str(x.get("args") or ""), cwd=x.get("cwd"), mem=x.get("mem"), cmprs=x.get("cmprs"))
                 for x in lst]
    elif _faked():
        return []
    else:
        try:
            r = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,etime=,rss=,args="], capture_output=True, text=True,
                               timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0:
            return None
        procs = []
        for ln in r.stdout.splitlines():
            m = re.match(r"\s*(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s+(.*)$", ln)
            if m and _etime(m.group(3)) is not None:
                procs.append(dict(pid=int(m.group(1)), ppid=int(m.group(2)), age=_etime(m.group(3)),
                                  rss=int(m.group(4)), args=m.group(5).strip(), cwd=None, mem=None, cmprs=None))
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
    mark = P.path("culprits-last")
    try:
        last = float(open(mark).read().strip())
    except (OSError, ValueError):
        last = 0.0
    if last <= t <= last + EPISODE_GAP:  # тот же эпизод: тревога уже была — только продлить
        P.write_atomic(mark, f"{t}\n")
        return
    procs = collect()
    if procs is None:
        raise RuntimeError("список процессов (ps) не прочитан")
    rs = rows(candidates(procs), context(agents))
    if not rs:
        return
    table = "; ".join(f"{label(p)} (pid {p['pid']}) → {who} → {fmt_mem(p)} → {fmt_age(p['age'])}"
                      for p, who, _, _ in rs[:TABLE_MAX])
    more = f"; и ещё {len(rs) - TABLE_MAX}" if len(rs) > TABLE_MAX else ""
    n_ab = sum(1 for r in rs if r[2] == "abandoned")
    n_ask = sum(1 for r in rs if r[2] == "ask")
    P.alert(f"виновники памяти ({'; '.join(reasons)}), процессы старше {CULPRIT_HOURS} ч — процесс → чей → память → "
            f"возраст: {table}{more}. Брошено: {n_ab}, своё живое: {n_ask}. Зевсу: задача и `pantheon wake hestia "
            "--task <id>` — Гестия погасит брошенное (`pantheon reap --apply`), об остальном спросит вас", "watch")
    P.write_atomic(mark, f"{t}\n")


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


def _consent_ok():
    """Окно Гестии: свежая метка `pantheon consent <задача окна>` (как правило hestia в guard: 2 ч)."""
    task = os.environ.get("PANTHEON_TASK") or ""
    if not P.CONSENT_ID.fullmatch(task):
        return False
    try:
        st = os.lstat(os.path.join(P.STATE, "hestia-consent", task))
    except OSError:
        return False
    import stat as _st
    return _st.S_ISREG(st.st_mode) and 0 <= time.time() - st.st_mtime <= 2 * 3600


USAGE = "pantheon reap [--apply] [--pid N …] — без --apply только показать"


def reap(rest):
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
    if pids and os.environ.get("PANTHEON_ROLE") == "hestia" and not _consent_ok():
        print(f"pantheon reap --pid: нет свежего «да» владельца — сначала `pantheon consent "
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
            if r is None:
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
