"""Пантеон: pantheon review — записи для шлюза слияния guard (P1-4, guard 0.5.4): test, accept, reject, talos,
begin, miss, sample, status, report (metis-0602: отчёт прежнего argus из его транскрипта), delta (metis-0784: какой
нужен круг argus — дельта от прошлого проверенного head или полный — и готов ли head). accept — только на head с
записью тестов шлюза или зелёным CI (review_ready, metis-0669): иначе код 1, и хук guard «принять» не пишет.

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon (P.review_cmd и т. д.).
"""
import glob
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime

__all__ = [
    "REVIEW_SHA", "REVIEW_REPO", "REVIEW_PR", "REVIEW_USAGE", "_review_verdict", "_review_git", "_review_state",
    "review_tally", "REVIEW_PENDING_TTL", "_review_pending_path", "_record_epoch", "review_pending", "review_cmd",
    "REVIEW_AGENT", "REVIEW_HEAD", "review_find_transcripts", "review_last_report", "NODE_MODULES_LINK", "tree_clean",
    "CRITERIA", "CRITERIA_FMT", "CRITERIA_STUB", "criteria_accepted", "review_criteria_ticks", "review_ready",
    "review_delta",
]


# --- review: записи для шлюза слияния guard (P1-4, guard 0.5.4) -------------------------------------------------
# Сама команда ничего не пишет: журнал STATE/merge-gate/records.jsonl пишет хук guard на PostToolUse по успешной
# простой команде `pantheon review …` и по agent_type сессии (accept, reject — argus, talos — talos). Поэтому
# запись нельзя сделать текстом команды от чужой роли, а сама команда только проверяет условия и формат.
REVIEW_SHA = re.compile(r"[0-9a-f]{40}")
REVIEW_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REVIEW_PR = re.compile(r"[1-9][0-9]{0,8}")
REVIEW_USAGE = ("pantheon review test -- <команда…> | accept <owner/repo> <PR> <SHA 40 знаков> --opened \"<что "
                "открыл>\" --ran \"<что запустил>\" --unchecked \"<что не проверял>\" | reject <owner/repo> <PR> <SHA> "
                "[те же флаги] (у accept и reject ещё --criteria \"<id>#<N> <хеш> да|нет <опора>\" на каждый проверенный "
                "пункт «Готово, когда»; пункт задачи не из Closes — если тело PR называет его «пункт N <id>») | talos <owner/repo> <PR> <SHA> | begin <owner/repo> <PR> <SHA> | miss "
                "<owner/repo>#<PR> --by <argus> --text \"…\" | sample | criteria <id задачи>… | status [<owner/repo> <PR>] "
                "| report <owner/repo> <PR> <agent8>[/<сессия8>] [--out ПУТЬ] | delta <owner/repo> <PR> (из клона: "
                "дельта-круг или полный, готов ли head к argus)")
# Правило засчитывания вердиктов (REVIEW_CHECKLIST, OPUS_RAN, RAN_MODEL, review_accept_full, review_accept_counts,
# review_records) — в lib/review_rules.py, ядре защит (metis-0858): здесь только P.<имя>, копии правила нет.

# metis-1193: и задачи не из Closes, если тело PR называет пункт «пункт N <id>» (autoclose.tick_named).
# metis-1004: вердикт argus по пункту «Готово, когда» задачи из Closes — `--criteria "<id>#<N> <хеш> да|нет <опора>"` у
# accept и reject, флаг на пункт (разбор — tasks.parse_criterion). Хеш — tasks.criterion_hash текста пункта: правка
# пункта после приёмки его меняет. Хук guard кладёт значения в запись полем "criteria", autoclose при слиянии PR
# отмечает пункты с «да» из засчитанных «принять» на head слияния (criteria_accepted). Готовые строки с хешами —
# `pantheon review criteria <id>`; в них опора — заглушка CRITERIA_STUB, её надо заменить.
CRITERIA = "criteria"
CRITERIA_FMT = '"<id задачи>#<номер пункта> <хеш 12 знаков> да|нет <опора: файл:строка или тест>"'
CRITERIA_STUB = "ОПОРА"


def _review_criteria_problem(sub, items):
    """Значения --criteria у accept|reject (metis-1004) → текст ошибки или None. Каждое — в формате CRITERIA_FMT, без
    повторов пункта; задача есть, пункт N в её «Готово, когда» есть и не заглушка, хеш — от его нынешнего текста;
    опора — не заглушка «ОПОРА». У accept «нет» — ошибка (пункт не выполнен — это «вернуть»); вердикт не по всем
    пунктам можно (ревью #401 Б1): пункты вне PR («часть») и проверяемые после слияния остаются без флага, и autoclose
    сам ставит задаче review «неотмечено N». Команда с кодом не 0 записи не даёт (хук пишет только успешную)."""
    T = P.tasks_mod()
    tasks = T.load_tasks(P.PANTHEON, T.WORK_TYPES)
    seen = {}
    for v in items:
        got = T.parse_criterion(v)
        if not got:
            return f"--{CRITERIA} «{v[:80]}» не в формате {CRITERIA_FMT}"
        tid, n, h, verdict, basis = got
        if basis == CRITERIA_STUB:
            return f"--{CRITERIA} {tid}#{n}: вместо «{CRITERIA_STUB}» — опора: файл:строка или тест"
        if n in seen.get(tid, ()):
            return f"--{CRITERIA} {tid}#{n} указан дважды"
        if sub == "accept" and verdict == "нет":
            return (f"--{CRITERIA} {tid}#{n} «нет» в «принять»: пункт не выполнен — это «вернуть». Запиши `pantheon "
                    f"review reject …` с теми же --{CRITERIA}")
        if tid not in tasks:
            return f"--{CRITERIA} {tid}#{n}: задачи {tid} нет (или её шапка не проходит проверку)"
        crit = T.done_criteria(tasks[tid][2])
        if not 1 <= n <= len(crit) or T._is_stub(crit[n - 1][1]):
            return f"--{CRITERIA} {tid}#{n}: в «Готово, когда» задачи {tid} нет пункта {n} (пунктов {len(crit)})"
        if T.criterion_hash(crit[n - 1][1]) != h:
            return (f"--{CRITERIA} {tid}#{n}: хеш {h} не от нынешнего текста пункта — пункт изменён или номер не тот; "
                    f"строки с хешами — `pantheon review criteria {tid}`")
        seen.setdefault(tid, set()).add(n)
    return None


def review_criteria_cmd(ids):
    """pantheon review criteria <id>… (metis-1004): пункты «Готово, когда» задач с номером, отметкой и готовой строкой
    --criteria с хешем; argus меняет «да» на «нет», если пункт не выполнен, и «ОПОРА» — на файл:строка или тест."""
    T = P.tasks_mod()
    if not ids or any(not T.ID_RE.fullmatch(i) for i in ids):
        print("pantheon review criteria <id задачи>…", file=sys.stderr)
        return 2
    tasks = T.load_tasks(P.PANTHEON, T.WORK_TYPES)
    for tid in ids:
        if tid not in tasks:
            print(f"pantheon review criteria: задачи {tid} нет (или её шапка не проходит проверку)", file=sys.stderr)
            return 1
        items = [(i, ok, x) for i, (ok, x) in enumerate(T.done_criteria(tasks[tid][2]), 1) if not T._is_stub(x)]
        if not items:
            print(f"{tid}: пунктов «Готово, когда» нет — --{CRITERIA} не нужен")
        for i, ok, x in items:
            print(f"{tid}#{i} [{'x' if ok else ' '}] {x}")
            print(f'  --{CRITERIA} "{tid}#{i} {T.criterion_hash(x)} да {CRITERIA_STUB}"')
    return 0


def criteria_accepted(recs, pr, head, base, core):
    """Пункты, которые argus принял на head слияния PR (metis-1004) → {id задачи: {номер пункта: хеш}}. recs — журнал
    шлюза по PR (review_records). В счёт — «принять» argus на этот PR и ровно этот head, как у шлюза: последний вердикт
    своего рецензента (пара session_id, agent_id), полный перечень, а у PR ядра (core) ещё Opus (review_accept_counts),
    base записи — base PR (base_counts), без лживого поля «вернули» (returned_lie), позже каждого «вернуть» PR, кроме
    снятого «принять» того же рецензента на том же head (как _floor шлюза). Последний вердикт какого-нибудь
    рецензента на head — «вернуть» — не в счёт ничего. Пункт принят, если в засчитанных «принять» он есть, у всех —
    «да» и один хеш. Переносов «принять» с прошлого head нет: запись другого head не отмечает ничего."""
    T, rules = P.tasks_mod(), P.merge_mod()
    ok = P.review_accept_counts if core else P.review_accept_full
    head = str(head or "").lower()
    if not REVIEW_SHA.fullmatch(head):
        return {}
    verdicts = [r for r in recs if r.get("kind") in ("accept", "reject") and r.get("pr") == pr
                and isinstance(r.get("by"), dict) and r["by"].get("agent_type") == "argus"
                and isinstance(r.get("sha"), str)]

    def who(r):
        return (r["by"].get("session_id") or "", r["by"].get("agent_id") or "")

    floor = -1
    for i, r in enumerate(verdicts):
        if r["kind"] == "reject" and not any(a["kind"] == "accept" and who(a) == who(r) and a["sha"].lower() ==
                                             r["sha"].lower() and P.review_accept_full(a) for a in verdicts[i + 1:]):
            floor = i
    last = {}
    for i, r in enumerate(verdicts):
        if r["sha"].lower() == head:
            last[who(r)] = (i, r)
    if any(r["kind"] == "reject" for _, r in last.values()):
        return {}
    votes = {}
    for i, r in sorted(last.values(), key=lambda x: x[0]):
        if i <= floor or not ok(r) or not rules.base_counts(r, {"baseRefName": base}) or rules.returned_lie(r, verdicts):
            continue
        for v in r.get("criteria") if isinstance(r.get("criteria"), list) else []:
            got = T.parse_criterion(v)
            if got:
                votes.setdefault((got[0], got[1]), []).append((got[2], got[3]))
    out = {}
    for (tid, n), vs in sorted(votes.items()):
        if all(v == "да" for _, v in vs) and len({h for h, _ in vs}) == 1:
            out.setdefault(tid, {})[n] = vs[0][0]
    return out


def review_criteria_ticks(repo, row):
    """Для autoclose (metis-1004): строка кэша слитого PR (number, head, base, core) → criteria_accepted по журналу
    шлюза. Нет head в строке (кэш до metis-1004) — пусто; нет core — как ядро (строже)."""
    n, head = row.get("number"), str(row.get("head") or "").lower()
    if not isinstance(n, int) or isinstance(n, bool) or not REVIEW_SHA.fullmatch(head):
        return {}
    return criteria_accepted(P.review_records(repo, n), n, head, row.get("base"), row.get("core") is not False)


def _review_verdict(sub, args):
    """accept|reject|talos: → (позиционные [repo, PR, SHA], перечень {поле: значение}, None) или (…, текст ошибки)."""
    flags = sub in ("accept", "reject")
    fmt = f"pantheon review {sub} <owner/repo> <номер PR> <SHA 40 знаков>" + (
        ' --opened "<что открыл>" --ran "<что запустил>" --unchecked "<что не проверял>"' if sub == "accept"
        else " [--opened … --ran … --unchecked …]" if flags else "")
    pos, checklist, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if flags and a.startswith("--") and len(a) > 2:
            name, eq, val = a[2:].partition("=")
            if name not in P.REVIEW_CHECKLIST and name != CRITERIA:
                return pos, {}, f"неизвестный флаг --{name}. Формат: {fmt}"
            if name in checklist and name != CRITERIA:
                return pos, {}, f"--{name} указан дважды. Формат: {fmt}"
            if not eq:
                if i + 1 >= len(args):
                    return pos, {}, f"у --{name} нет значения. Формат: {fmt}"
                i += 1
                val = args[i]
            if val.strip().startswith("--"):  # `--opened --ran …`: имя флага — не значение
                return pos, {}, f"значение --{name} начинается с «--»: похоже, пропущено значение. Формат: {fmt}"
            if name == CRITERIA:  # metis-1004: по флагу на пункт, как в merge_gate.verdict_parse
                if not val.strip():
                    return pos, {}, f"--{CRITERIA} пустой. Формат пункта: {CRITERIA_FMT}"
                checklist.setdefault(CRITERIA, []).append(val.strip())
            else:
                checklist[name] = val.strip()
        else:
            pos.append(a)
        i += 1
    if len(pos) != 3 or not REVIEW_REPO.fullmatch(pos[0]) or not REVIEW_PR.fullmatch(pos[1]) \
            or not REVIEW_SHA.fullmatch(pos[2].lower()):
        return pos, {}, f"аргументы не в формате {fmt} (SHA — полный: gh pr view N --json headRefOid)"
    if sub == "accept":
        missing = [f"--{k}" for k in P.REVIEW_CHECKLIST if not checklist.get(k)]
        if missing:
            return pos, {}, (f"«принять» без перечня проверенного (Б6): нет или пусто {', '.join(missing)}. Формат: "
                             f"{fmt}. Шлюз слияния guard пускает только «принять», где сказано, что открыто, что "
                             "запущено и чего не проверял")
    return pos, {k: v for k, v in checklist.items() if v}, None


def _review_git(*args):
    """Вывод git в текущей папке (без переменных GIT_*); None — не репозиторий или сбой."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


# Ссылка node_modules, которую разработчик кладёт в worktree для pnpm (metis-0721): в корне и в apps/*, packages/*.
NODE_MODULES_LINK = re.compile(r"\?\? (?:(?:apps|packages)/[^/]+/)?node_modules")


def tree_clean(status, top, ok_prefix=()):
    """Дерево чистое по выводу `git status --porcelain` (общая для outside и review test, metis-0721). Строки с
    ok_prefix не грязь. Неотслеживаемая СИМЛИНК node_modules в корне top и в apps/*, packages/* — тоже не грязь:
    папка node_modules, файл с этим именем, ссылка глубже и ссылка с другим именем — грязь, как любая правка."""
    if status is None:
        return False
    for ln in status.splitlines():
        if not ln.strip() or ln.startswith(tuple(ok_prefix)):
            continue
        if NODE_MODULES_LINK.fullmatch(ln) and top and os.path.islink(os.path.join(top, ln[3:])):
            continue
        return False
    return True


def _review_state():
    """(HEAD, дерево чистое) текущей папки; HEAD None — не git или коммитов нет."""
    head = (_review_git("rev-parse", "HEAD") or "").strip().lower()
    status = _review_git("status", "--porcelain")
    top = (_review_git("rev-parse", "--show-toplevel") or "").strip()
    return (head if REVIEW_SHA.fullmatch(head) else None), tree_clean(status, top)


REVIEW_AGENT = re.compile(r"([0-9a-f]{4,64})(?:/([0-9a-f]{4,64}))?", re.I)  # agent8[/сессия8], как в `review status`


def review_find_transcripts(agent, session):
    """Файлы субагента ~/.claude/projects/*/<сессия>/subagents/[*/[*/]]agent-<agent>.jsonl (путь шлюза guard:
    agent_models) по полным agent_id и сессии из журнала шлюза. Транскрипт прежнего argus переживает /clear, а
    SendMessage к нему уже нет (No transcript found) — отчёт читается из файла (metis-0602). Симлинки отбрасываются."""
    base = glob.escape(os.path.join(P.HOME, ".claude", "projects"))
    out = set()
    for sub in ((), ("*",), ("*", "*")):
        out.update(glob.glob(os.path.join(base, "*", glob.escape(session), "subagents", *sub,
                                          f"agent-{glob.escape(agent)}.jsonl")))
    return sorted(p for p in out if os.path.isfile(p) and not os.path.islink(p))


REVIEW_HEAD = re.compile(r"Head:\s*\**\s*([0-9a-f]{40})", re.I)


def review_last_report(path):
    """Итоговый отчёт субагента: input.message последнего блока tool_use *Handback; блока нет — последний длинный
    text (от 400 знаков). None — отчёта в транскрипте нет."""
    handback, texts = None, None
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            blocks = msg.get("content") if isinstance(msg, dict) and rec.get("type") == "assistant" else None
            for b in blocks if isinstance(blocks, list) else []:
                if not isinstance(b, dict):
                    continue
                inp = b.get("input")
                if b.get("type") == "tool_use" and "Handback" in str(b.get("name")) and isinstance(inp, dict) \
                        and isinstance(inp.get("message"), str):
                    handback = inp["message"]
                elif b.get("type") == "text" and isinstance(b.get("text"), str) and len(b["text"]) >= 400:
                    texts = b["text"]
    return handback if handback is not None else texts


def _review_out_ok(out):
    """--out только под $TMPDIR (realpath) или /private/tmp: команду зовут роли, и писать им куда попало незачем."""
    roots = {os.path.realpath("/private/tmp")}
    if os.environ.get("TMPDIR"):
        roots.add(os.path.realpath(os.environ["TMPDIR"]))
    parent = os.path.realpath(os.path.dirname(os.path.abspath(out)))
    return any(parent == r or parent.startswith(r + os.sep) for r in roots)


def review_report(args):
    """pantheon review report <owner/repo> <PR> <agent8>[/<сессия8>] [--out ПУТЬ] (metis-0602)."""
    usage = "pantheon review report <owner/repo> <номер PR> <agent_id 8 знаков>[/<сессия 8 знаков>] [--out ПУТЬ]"
    out, pos, i = None, [], 0
    while i < len(args):
        if args[i] == "--out" or args[i].startswith("--out="):
            if out is not None:
                print(f"pantheon review report: --out указан дважды. Формат: {usage}", file=sys.stderr)
                return 2
            if args[i] == "--out":
                i += 1
                out = args[i] if i < len(args) else ""
            else:
                out = args[i][6:]
            if not out or out.startswith("--"):
                print(f"pantheon review report: у --out нет пути. Формат: {usage}", file=sys.stderr)
                return 2
        else:
            pos.append(args[i])
        i += 1
    m = REVIEW_AGENT.fullmatch(pos[2]) if len(pos) == 3 else None
    if not m or not REVIEW_REPO.fullmatch(pos[0]) or not REVIEW_PR.fullmatch(pos[1]):
        print(f"pantheon review report: аргументы не в формате {usage}", file=sys.stderr)
        return 2
    repo, pr, agent, session = pos[0], pos[1], m.group(1).lower(), (m.group(2) or "").lower()
    if out is not None and not _review_out_ok(out):
        print(f"pantheon review report: --out — только под $TMPDIR или /private/tmp, не {out}", file=sys.stderr)
        return 2
    # пара и последний head — из журнала шлюза: только argus, вынесший вердикт на этот PR, и только его последний head
    last, pairs = None, set()
    for r in P.review_records(repo, int(pr)):
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        a, ss = str(by.get("agent_id") or "").lower(), str(by.get("session_id") or "").lower()
        if (r.get("pr") == int(pr) and r.get("kind") in ("accept", "reject") and by.get("agent_type") == "argus"
                and a.startswith(agent) and ss.startswith(session) and isinstance(r.get("sha"), str)):
            pairs.add((a, ss))
            last = (a, ss, r["sha"].lower())
    if len(pairs) != 1:
        print(f"pantheon review report: в журнале {repo}#{pr} " + ("нет вердикта argus с такой парой" if not pairs else
              "под пару подходит несколько argus — укажи длиннее agent_id и сессию") + f" (`pantheon review status "
              f"{repo} {pr}`); отчёта нет — новый argus идёт полным кругом", file=sys.stderr)
        return 1
    files = review_find_transcripts(last[0], last[1])
    if len(files) != 1:
        print(f"pantheon review report: транскрипт agent-{last[0]}.jsonl сессии {last[1][:8]} "
              + ("не найден в ~/.claude/projects" if not files else "найден несколько раз:\n" + "\n".join(files))
              + "; отчёта нет — новый argus идёт полным кругом", file=sys.stderr)
        return 1
    text = review_last_report(files[0])
    if text is None:
        print(f"pantheon review report: в {files[0]} нет итогового отчёта (блок *Handback с полем message или длинный "
              "text) — новый argus идёт полным кругом", file=sys.stderr)
        return 1
    hm = REVIEW_HEAD.search(text)
    if not hm or hm.group(1).lower() != last[2]:
        print(f"pantheon review report: «Head:» отчёта ({hm.group(1)[:12] if hm else 'нет'}) не равен head последнего "
              f"вердикта этого argus в журнале ({last[2][:12]}) — отчёт не тот; новый argus идёт полным кругом",
              file=sys.stderr)
        return 1
    if out is None:
        print(text)
        return 0
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        print(f"pantheon review report: в {out} записать нельзя: {e.strerror or e} (файл уже есть — возьми новое имя)",
              file=sys.stderr)
        return 1
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    print(f"pantheon review report: отчёт {repo}#{pr} от {agent} из {files[0]} записан в {out}")
    return 0


def tally_base(recs, pr):
    """base PR для итога `review status` без gh: base последней записи вердикта PR с полем base (metis-0965) или None."""
    got = [r.get("base") for r in recs if r.get("kind") in ("accept", "reject") and r.get("pr") == pr
           and isinstance(r.get("base"), str) and r["base"]]
    return got[-1] if got else None


def review_tally(recs, pr, opus_only=False, base=None, light=False):
    """Итог argus по head PR (metis-0393): {sha: (принять, вернуть)} по последнему вердикту каждого рецензента.
    Рецензент — пара (session_id, agent_id), как у шлюза слияния guard: «вернуть» снимает только «принять» того же
    вызова. По итогу прошлого head лид и argus решают, допустим ли узкий повтор, — не по отчётам и словам лида.
    «Принять» без полного перечня не в счёт: «вернуть» того же рецензента оно не снимает. Модель не смотрим — вне
    ядра шлюз guard считает «принять» на любой модели (simplify п. 9, 27.10); opus_only=True — как для PR ядра:
    ещё и на Opus (по --ran и по моделям транскрипта argus, P.review_accept_counts). Как в шлюзах (Д6 долга #388):
    «принять» на другой base PR, чем base (base_counts, metis-0965; base None — неизвестна, не в счёт), и с полем
    «вернули», которое называет рецензента без «вернуть» на PR (returned_lie, metis-0497), не в счёт. light=True — как
    для лёгкого PR ядра (metis-1065): ещё и effort high по транскрипту argus (light_accept шлюза владельца)."""
    rules = P.merge_mod()

    def ok(r):
        if light:
            return P.review_accept_counts(r) and rules.light_accept(r)
        return P.review_accept_counts(r) if opus_only else P.review_accept_full(r)
    verdicts = [r for r in recs if r.get("kind") in ("accept", "reject") and r.get("pr") == pr
                and isinstance(r.get("by"), dict) and r["by"].get("agent_type") == "argus"
                and isinstance(r.get("sha"), str)]
    last = {r["sha"].lower(): {} for r in verdicts}  # head с вердиктами — в итоге и тогда, когда ни один не в счёт
    verdicts = [r for r in verdicts if r["kind"] == "reject" or ok(r) and rules.base_counts(r, {"baseRefName": base})]
    verdicts = [r for r in verdicts if not (r["kind"] == "accept" and rules.returned_lie(r, verdicts))]
    for r in verdicts:
        by = r["by"]
        last.setdefault(r["sha"].lower(), {})[(by.get("session_id") or "", by.get("agent_id") or "")] = r["kind"]
    return {sha: (sum(k == "accept" for k in v.values()), sum(k == "reject" for k in v.values()))
            for sha, v in last.items()}


def carry_lines(repo, pr):
    """Строки `review status` о записях carry.jsonl шлюза guard на PR (metis-0443): перенос «принять» шлюзом gh pr
    merge и решение о коде head при `pantheon merge request` (его читает шлюз владельца, merge.code_facts)."""
    out, decisions = [], P.review_decisions(repo, pr)
    for d in P.carry_records(repo, pr):
        sha, t = str(d.get("sha") or "")[:12], d.get("time", "?")
        if d.get("kind") == "carry" and isinstance(d.get("from"), list):
            src = ", ".join(str(x.get("sha") or "")[:12] for x in d["from"] if isinstance(x, dict))
            out.append(f"{t}  carry   шлюз guard перенёс «принять» с {src or '?'} на {sha} (тот же код)")
        elif d.get("kind") == "decision" and d in decisions:
            why = d.get("why") if isinstance(d.get("why"), list) else []
            out.append(f"{t}  decision  код {sha} (base {d.get('base')}): тот же — "
                       f"{', '.join(h[:12] for h in d['same']) or 'нет'}; другой — "
                       f"{', '.join(h[:12] for h in d['differs']) or 'нет'}"
                       + (f"; мелкая правка поверх (metis-0784) — {', '.join(str(h)[:12] for h in d['delta'])}"
                          if isinstance(d.get("delta"), list) and d["delta"] else "")
                       + (f"; не сверено: {'; '.join(map(str, why))}" if why else ""))
        elif d.get("kind") == "decision-miss":   # сверка не дошла до git (metis-1181)
            why = d.get("why") if isinstance(d.get("why"), list) else []
            out.append(f"{t}  decision  код {sha or '?'} не сверен: {'; '.join(map(str, why)) or '?'} — повтори "
                       "`pantheon merge request`")
    return out


# --- готовность к кругу argus и дельта-круг (metis-0669, 0784) -----------------------------------------------------
# argus смотрит PR только после зелёного CI или записи тестов шлюза на head (иначе ревью идёт по коду, который ещё
# упадёт). Полный круг — на свежем main (base не впереди head); повторный круг после мелкой правки поверх уже
# проверенного head — только дельта, без rebase: rebase рвёт дельту (прошлый head перестаёт быть предком), и круг
# снова полный. Правила дельты — merge.delta_problem (те же, что у шлюзов guard и владельца).

def _outside_test(base=None):
    """Команда записи тестов для подсказки роли. Узкая (`--affected`, от base, если задан) — только если проверка
    проекта (.pantheon-verify в корне git текущей папки) — run-tests.py: `outside test --affected` гоняет именно его,
    в репозитории без него узкой нет (Д2 argus #420). Иначе — полный набор."""
    top = (_review_git("rev-parse", "--show-toplevel") or "").strip()
    try:
        with open(os.path.join(top, ".pantheon-verify"), encoding="utf-8") as fh:
            runner = "run-tests.py" in fh.read()
    except (OSError, ValueError):
        runner = False
    if not top or not runner:
        return "pantheon outside test --wait 590"
    return "pantheon outside test --affected " + (f"--base {base} " if base else "") + "--wait 590"


def review_ready(repo, pr, sha, M, recs, view=False):
    """Можно ли argus «принять» head sha PR repo#pr (metis-0669) → None или почему нет: на sha есть запись tests шлюза
    (любая — узкая, полная; recs — записи журнала этого репозитория) или CI на head PR зелёный (gh pr view, если view
    не передан; M.ci_state по всем проверкам rollup). Сбой gh, PR на другом head, CI идёт или красный — причина."""
    if any(r.get("kind") == "tests" and r.get("sha") == sha for r in recs):
        return None
    view = M.pr_view(repo, pr) if view is False else view
    if not isinstance(view, dict):
        return f"на {sha[:12]} нет записи тестов шлюза, а gh pr view не ответил — CI не проверить"
    head = str(view.get("headRefOid") or "").lower()
    if head != sha:
        return f"у PR head {head[:12] or '?'}, а не {sha[:12]} — ревью на старом коммите"
    state, why, _ = M.ci_state(view.get("statusCheckRollup"))
    if state == "ok":
        return None
    return (f"на {sha[:12]} нет записи тестов шлюза, а CI не зелёный ({why}). argus — только после зелёного CI или "
            f"записи: `{_outside_test()}` из чистой копии на этом коммите (metis-0669)")


def _delta_rows(old, new):
    """git diff --numstat old new в текущей папке → [(путь, добавлено, удалено)] (у двоичного — None) или None."""
    out = _review_git("diff", "--numstat", "-z", "--no-renames", "--no-relative", "--ignore-submodules=none",
                      "--no-ext-diff", "--no-textconv", old, new)
    if out is None or out and not out.endswith("\0"):
        return None
    rows = []
    for part in out[:-1].split("\0") if out else []:
        bits = part.split("\t", 2)
        if len(bits) != 3 or not bits[2] or not all(b.isdigit() or b == "-" for b in bits[:2]):
            return None
        rows.append((bits[2], *(int(b) if b.isdigit() else None for b in bits[:2])))
    return rows


def _delta_round(M, repo, head, base_name, verdicts):
    """(прошлый head или None, почему круг полный или None, строк дельты, годится ли дельта тестам, base свежий) для
    дельта-круга: прошлый head — последний с вердиктом argus, кроме head; он — предок head в git текущей папки, дельта
    годится по merge.delta_problem с ядром окна (window_core), тестам — без ядра (только файлы шлюза). Полный круг — на
    свежем base: он не впереди head (gh compare, behind_by 0)."""
    prev = next((r["sha"] for r in reversed(verdicts) if r["sha"] != head), None)
    why = "первый круг" if prev is None else None
    rows = ren = None
    if prev and _review_git("merge-base", "--is-ancestor", prev, head) is None:
        why = (f"прошлый head {prev[:12]} не предок {head[:12]} (rebase или его нет в git папки — git fetch): дельту не "
               "посчитать")
    elif prev:
        ren = _review_git("diff", "-z", "--name-only", "--diff-filter=R", "-M", "--no-relative",
                          "--ignore-submodules=none", "--no-ext-diff", prev, head)
        ren = "дельту с прошлого head не посчитать" if ren is None else M.DELTA_RENAME if ren else None
        rows = _delta_rows(prev, head)
        why = ren or M.delta_problem(rows, core=M.window_core)
    lines = sum((a or 0) + (d or 0) for _, a, d in rows or [])
    tests_ok = rows is not None and not ren and M.delta_problem(rows) is None
    if why:
        try:
            r = subprocess.run([M.gh_path(), "api", f"repos/{repo}/compare/{base_name}...{head}", "--jq", ".behind_by"],
                               capture_output=True, text=True, timeout=M.GH_TIMEOUT, env=M.gh_env())
            behind = r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            behind = ""
        if behind != "0":
            why += (f"; полный круг — на свежем {base_name}: head отстаёт на {behind} коммитов — rebase на свежий "
                    f"{base_name} до круга" if behind.isdigit() else f"; свежесть {base_name} не проверить (gh)")
            return prev, why, lines, tests_ok, False
    return prev, why, lines, tests_ok, True


def _accept_unready(sub, args):
    """metis-0669: «принять» — только на head с записью тестов или зелёным CI → причина или None (не accept — None).
    Код не 0 у команды — хук guard «принять» не пишет."""
    if sub != "accept":
        return None
    repo = args[0].lower()
    return review_ready(repo, int(args[1]), args[2].lower(), P.merge_mod(), P.review_records(repo))


def review_delta(args):
    """`pantheon review delta <owner/repo> <PR>` из клона репозитория (metis-0784, 0669): какой нужен круг argus на
    нынешнем head PR — дельта от прошлого проверенного head или полный, — какой командой писать тесты и готов ли head к
    argus (запись тестов или зелёный CI, а для полного круга — свежий base). Код 0 — готов, 1 — нет, 2 — формат."""
    if len(args) != 2 or not REVIEW_REPO.fullmatch(args[0]) or not REVIEW_PR.fullmatch(args[1]):
        print("pantheon review delta <owner/repo> <номер PR> — из клона репозитория", file=sys.stderr)
        return 2
    repo, pr, M = args[0].lower(), int(args[1]), P.merge_mod()
    view = M.pr_view(repo, pr)
    head = str((view or {}).get("headRefOid") or "").lower()
    base_name = (view or {}).get("baseRefName")
    if not REVIEW_SHA.fullmatch(head) or not isinstance(base_name, str) or not base_name:
        print(f"pantheon review delta: gh pr view {pr} -R {repo} не дал head и base PR", file=sys.stderr)
        return 1
    recs = P.review_records(repo)
    verdicts = [r for r in recs if r.get("kind") in ("accept", "reject") and r.get("pr") == pr
                and isinstance(r.get("sha"), str) and isinstance(r.get("by"), dict)
                and r["by"].get("agent_type") == "argus"]
    prev, why, lines, tests_ok, fresh = _delta_round(M, repo, head, base_name, verdicts)
    if why:
        print(f"круг: полный на {head[:12]} — {why}")
    else:
        print(f"круг: дельта {prev[:12]}..{head[:12]} ({lines} строк, вне ядра) — argus смотрит только `git diff "
              f"{prev} {head}`; «принять» на {prev[:12]} шлюз владельца переносит, если на нём полный круг "
              f"({M.MIN_ACCEPTS} argus), на этом head есть «принять» argus, а каждый, кто вернул {prev[:12]}, принял "
              "этот head (решение при `pantheon merge request`)")
    has_prev = tests_ok and any(r.get("kind") == "tests" and r.get("sha") == prev for r in recs)
    cmd = _outside_test(prev if has_prev else None)
    print(f"тесты: из чистой копии на head `{cmd}`"
          + (" (дельта от прошлого head с записью тестов)" if "--base" in cmd else ""))
    latest = {}
    for r in verdicts:
        latest[M._reviewer(r)] = r
    for (sid, aid), r in latest.items():
        if r["kind"] == "reject":
            who = f"{aid[:8]}/{sid[:8]}" if aid else sid[:8]
            print(f"вернул: {who or '—'} на {r['sha'][:12]} — в поручение нового argus: "
                  f"`pantheon review report {repo} {pr} {who}`")
    ready = review_ready(repo, pr, head, M, recs, view)
    if ready or not fresh:
        print(f"pantheon review delta: head {head[:12]} не готов к argus — {ready or why}", file=sys.stderr)
        return 1
    print(f"готов к argus: head {head[:12]}")
    return 0


REVIEW_PENDING_TTL = 2 * 3600  # метка «ревью идёт» устаревает через 2 часа


def _review_pending_path(repo, pr):
    return P.path("review-pending", f"{repo.lower().replace('/', '__')}__{pr}.json")


def _record_epoch(rec):
    try:
        d = datetime.fromisoformat(str(rec.get("time")))
        return d.timestamp()  # без пояса — местное время, как пишет хук guard
    except ValueError:
        return None


def review_pending(repo, pr, recs=None):
    """Метка «ревью идёт» для (repo, PR) или None: нет метки, старше 2 ч, или после неё есть вердикт на этот PR."""
    d = P.read_json(_review_pending_path(repo, pr), None)
    if not isinstance(d, dict) or not isinstance(d.get("t"), (int, float)):
        return None
    if not 0 <= P.now() - d["t"] < REVIEW_PENDING_TTL:
        return None
    for r in P.review_records(repo, int(pr)) if recs is None else recs:
        if r.get("kind") in ("accept", "reject") and (_record_epoch(r) or 0) >= d["t"] - 1 \
                and repo.lower() in [str(x).lower() for x in r.get("repo") or []]:
            return None  # вердикт на тот же sha — ревью кончилось; на другой — head сменился, метка устарела
    return d


# metis-0513: запись tests пишет хук guard, когда команда вернулась. Инструмент Bash обрывает вызов на 600 с и хук не видит
# конца: ожидание места heavy (очередь) и сами тесты шли молча до обрыва, записи не было, причина не видна. Бюджет —
# меньше предела: ждать места heavy не дольше бюджета (HEAVY_WAIT_MAX — код 75 без запуска), а команда, не уложившаяся,
# гасится со строкой «для длинного набора — pantheon outside test». PANTHEON_REVIEW_TEST_BUDGET=<с> — свой бюджет
# (0 — без ограничения, как раньше).
REVIEW_TEST_BUDGET = 570


def _review_budget(env):
    try:
        return float(env.get("PANTHEON_REVIEW_TEST_BUDGET", REVIEW_TEST_BUDGET))
    except ValueError:
        return float(REVIEW_TEST_BUDGET)


def _gate_tests_cmd(cmd, M):
    """Команда — полный набор шлюза (merge.FULL_TESTS) или его узкий вариант от outside (`--affected`, `--base <ref>`)."""
    words = list(cmd)
    if "--affected" in words:
        words.remove("--affected")
        if "--base" in words:
            i = words.index("--base")
            del words[i:i + 2]
    line = shlex.join(words)
    return any(M.full_tests_record(name, {"cmd": line}) for name in M.FULL_TESTS)


def _review_test_run(cmd, M=None):
    """Команда `review test -- …` под бюджетом времени → (код, оборвана): 127 — не запустилась, 75 — не уложилась в
    бюджет; оборвана — запись и проверку HEAD после неё делать незачем."""
    env = dict(os.environ)
    # запасной путь «только CI» (metis-1174): heavy не отказывает тестам, только если команда — набор шлюза (полный
    # или узкий); любой другой команде переменная не ставится, и чужая HEAVY_LOCAL_TESTS снимается
    env.pop("HEAVY_LOCAL_TESTS", None)
    if M is not None and _gate_tests_cmd(cmd, M):
        env["HEAVY_LOCAL_TESTS"] = "1"
    budget = _review_budget(env)
    if budget > 0:
        try:
            own = float(env.get("HEAVY_WAIT_MAX") or 0)
        except ValueError:
            own = 0
        env["HEAVY_WAIT_MAX"] = str(int(min(own, budget) if own > 0 else budget))
    try:
        proc = subprocess.Popen(cmd, env=env)
    except OSError as e:
        print(f"pantheon review test: команда не запустилась: {e}", file=sys.stderr)
        return 127, True
    try:
        return proc.wait(timeout=budget if budget > 0 else None), False
    except subprocess.TimeoutExpired:
        proc.terminate()  # heavy и run-tests получают TERM и гасят дерево
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print(f"pantheon review test: команда не уложилась в {int(budget)} с (предел вызова Bash — 600 с, ожидание места "
              "heavy входит в него) — остановлена, записи не будет. Длинный набор — `pantheon outside test --wait 590` "
              "из корня чистой копии", file=sys.stderr)
        return 75, True


def _review_test_cmd(rest):
    if len(rest) < 3 or rest[1] != "--":
        print(f"pantheon review: {REVIEW_USAGE}", file=sys.stderr)
        return 2
    head, clean = _review_state()
    if head is None:
        print("pantheon review test: папка не репозиторий git или в нём нет коммитов", file=sys.stderr)
        return 2
    if not clean:
        print("pantheon review test: дерево не чистое — закоммить или убери правки: тесты пишутся на коммит, "
              "а не на незакоммиченное", file=sys.stderr)
        return 2
    rc, over = _review_test_run(rest[2:], P.merge_mod())
    if over:
        return rc
    head2, clean2 = _review_state()
    if head2 != head or not clean2:
        print(f"pantheon review test: команда изменила HEAD или дерево (было {head}, стало {head2 or '?'}, "
              f"чистое: {'да' if clean2 else 'нет'}) — запись не делается", file=sys.stderr)
        return 3
    print(head)
    print(f"pantheon review test: код {rc} на {head}" + (" — запись тестов сделает хук guard" if rc == 0 else
                                                         " — тесты не прошли, записи не будет"))
    return rc


def review_cmd(rest):
    sub = rest[0] if rest else ""
    if sub == "miss":
        m = re.fullmatch(r"(%s)#(%s)" % (REVIEW_REPO.pattern, REVIEW_PR.pattern), rest[1] if len(rest) > 1 else "")
        opts, i, bad = {}, 2, None
        while i < len(rest) and not bad:
            k = rest[i]
            if k not in ("--by", "--text", "--class") or k in opts or i + 1 >= len(rest) or rest[i + 1].startswith("--"):
                bad = f"лишнее или без значения: {k}"
            else:
                opts[k] = rest[i + 1].strip()
            i += 2
        if not m or bad or not opts.get("--by") or not opts.get("--text"):
            print(f"pantheon review miss: {bad + '. ' if bad else ''}формат: miss <owner/repo>#<PR> --by <argus> --text "
                  "\"<что пропустил>\" [--class защиты|ядро|вне ядра]", file=sys.stderr)
            return 2
        row, why = P.metrics_mod().add_miss(P.metrics_ctx(), m.group(1), int(m.group(2)), opts["--by"][:80],
                                          opts["--text"][:1000], opts.get("--class"))
        if why:
            print(f"pantheon review miss: {why}", file=sys.stderr)
            return 2
        print(f"pantheon review miss: {row['repo']}#{row['pr']} — пропуск argus записан (класс {row['class']}, "
              f"argus принявших: {row['argus']}); завести задачу «пропуск из PR #{row['pr']}», класс — строкой в "
              "agent-memory/argus")
        return 0
    if sub == "sample":
        res = P.metrics_mod().sample_pick(P.metrics_ctx())
        print(f"выборка недели {res['week']}: потолок {res['budget']} запуск(ов); узкий режим — дифф и тесты, "
              "модель и усилие как у argus вне ядра (medium)")
        if not res["targets"]:
            print(res["why"])
        for g in res["targets"]:
            print("  " + (" + ".join(f"{r}#{n}" for r, n in g)) + (" — суммарный дифф области" if len(g) > 1 else ""))
        return 0
    if sub == "begin":
        args, _, why = _review_verdict("talos", rest[1:])  # тот же разбор: repo, PR, SHA без флагов
        if why:
            print(f"pantheon review begin: {why.replace('review talos', 'review begin')}", file=sys.stderr)
            return 2
        repo, pr, sha = args[0].lower(), args[1], args[2].lower()
        who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]
        P.write_json(_review_pending_path(repo, pr), {"repo": repo, "pr": int(pr), "sha": sha, "t": P.now(),
                                                    "time": P.stamp(), "by": who or None})
        print(f"pantheon review begin: ревью {repo}#{pr} @ {sha[:8]} помечено «идёт» (не вердикт и не согласие; "
              f"шлюз метку не читает)")
        return 0
    if sub == "test":
        return _review_test_cmd(rest)
    if sub in ("accept", "reject", "talos"):
        args, checklist, why = _review_verdict(sub, rest[1:])
        crit = checklist.pop(CRITERIA, [])
        why = why or (_review_criteria_problem(sub, crit) if crit else None)
        if why:
            print(f"pantheon review {sub}: {why}", file=sys.stderr)
            return 2
        why = _accept_unready(sub, args)
        if why:
            print(f"pantheon review accept: не записано — {why}", file=sys.stderr)
            return 1
        who = "argus" if sub != "talos" else "talos"
        print(f"pantheon review {sub}: {args[0].lower()}#{args[1]} @ {args[2].lower()} — записано хуком guard, "
              f"если роль подходит ({who})")
        for k, v in checklist.items():
            print(f"  {P.REVIEW_CHECKLIST[k]}: {v}")
        for v in crit:
            print(f"  пункт: {v}")
        return 0
    if sub in ("criteria", "delta", "report"):
        return {"criteria": review_criteria_cmd, "delta": review_delta, "report": review_report}[sub](rest[1:])
    if sub == "status":
        args = rest[1:]
        if args and (len(args) != 2 or not REVIEW_REPO.fullmatch(args[0]) or not REVIEW_PR.fullmatch(args[1])):
            print("pantheon review status [<owner/repo> <номер PR>]", file=sys.stderr)
            return 2
        recs = P.review_records(args[0] if args else None, int(args[1]) if args else None)
        pend = []
        if args:
            pend = [review_pending(args[0], args[1])]
        else:
            for f in sorted(glob.glob(P.path("review-pending", "*.json"))):
                d = P.read_json(f, None)
                if isinstance(d, dict) and d.get("repo") and d.get("pr"):
                    pend.append(review_pending(d["repo"], d["pr"]))
        for d in (x for x in pend if x):
            print(f"ревью идёт с {P.stamp(d['t'])[11:]} ({d['repo']}#{d['pr']}, head {str(d['sha'])[:8]}"
                  + (f", {d['by']}" if d.get("by") else "") + ") — второго argus не звать")
        if not recs:
            print("pantheon review status: записей нет")
        # строки про Opus — только там, где бывает ядро: репозиторий metis-pantheon в [merge_repos] или неизвестный
        # (строже); у репозитория продукта шлюз считает «принять» на любой модели, и эти строки только путают
        dirs = P.autoclose_repo_dirs().get(args[0].lower()) if args else None
        core_repo = not dirs or "metis-pantheon" in dirs
        for r in recs:
            by = r.get("by") if isinstance(r.get("by"), dict) else {}
            pr = f"#{r['pr']}" if r.get("pr") else ""
            who = by.get("agent_type") or "—"
            if r.get("kind") in ("accept", "reject"):
                who += f" {str(by.get('agent_id') or '—')[:8]}/{str(by.get('session_id') or '—')[:8]}"
            print(f"{r.get('time', '?')}  {r.get('kind', '?'):<6}  {','.join(map(str, r['repo']))}{pr}  "
                  f"{str(r.get('sha', ''))[:12]}  {who}")
            if r.get("kind") == "tests" and r.get("rerun_of"):
                nf = len(r["files"]) if isinstance(r.get("files"), list) else 0
                print(f"    дозапуск от {r['rerun_of']}, файлов {nf}")
            cl = r.get("checklist") if isinstance(r.get("checklist"), dict) else {}
            if r.get("kind") == "accept" and not all(isinstance(cl.get(k), str) and cl[k].strip()
                                                     for k in P.REVIEW_CHECKLIST):
                print("    без перечня проверенного (Б6) — шлюз слияния такое «принять» не пускает")
            elif r.get("kind") == "accept" and not core_repo:
                pass
            elif r.get("kind") == "accept" and not P.OPUS_RAN.match(cl["ran"]):
                print("    не на Opus (--ran без «модель: claude-opus» в начале) — для PR ядра не в счёт; вне ядра "
                      "шлюз его считает")
            elif r.get("kind") == "accept" and r.get("models") == []:  # metis-0413: транскрипт найден, моделей нет
                print("    транскрипт argus найден, но моделей в нём нет — для PR ядра не в счёт; вне ядра шлюз его "
                      "считает")
            elif r.get("kind") == "accept" and "models" not in r and r.get("models_note") \
                    and (r.get("by") if isinstance(r.get("by"), dict) else {}).get("agent_id"):
                print("    транскрипт субагента argus не найден — модель не подтвердить: для PR ядра не в счёт "
                      "(metis-0489); вне ядра шлюз его считает")
            elif r.get("kind") == "accept" and not P.review_accept_counts(r):
                print("    не на Opus по транскрипту argus (поле models не сходится с --ran) — для PR ядра не в счёт; "
                      "вне ядра шлюз его считает")
            for k, label in P.REVIEW_CHECKLIST.items():
                if isinstance(cl.get(k), str) and cl[k].strip():
                    print(f"    {label}: {cl[k]}")
            for v in r.get("criteria") if isinstance(r.get("criteria"), list) else []:
                print(f"    пункт: {v}")
        if args:
            base = tally_base(recs, int(args[1]))
            # metis-0443: что шлюз guard решил о коде head — переносы «принять» и решения при `merge request`
            for line in carry_lines(args[0], int(args[1])):
                print(line)
            if any(r.get("kind") in ("accept", "reject") for r in recs):
                print(f"base PR для итога — {base or 'неизвестна (нет записи вердикта с base)'}: по последней записи "
                      "вердикта, gh не спрашиваем; «принять» на другой base или с полем «вернули» без «вернуть» на "
                      "PR не в счёт, как в шлюзе")
            strict = review_tally(recs, int(args[1]), opus_only=True, base=base)
            light = review_tally(recs, int(args[1]), base=base, light=True)
            for sha, (acc, rej) in review_tally(recs, int(args[1]), base=base).items():
                print(f"итог на {sha[:12]}: принять {acc}, вернуть {rej} — последний вердикт каждого argus")
                if core_repo and strict.get(sha, (0, 0)) != (acc, rej):   # для PR ядра — только «принять» на Opus
                    print(f"  для PR ядра (в счёт только «принять» на Opus): принять {strict.get(sha, (0, 0))[0]}, "
                          f"вернуть {strict.get(sha, (0, 0))[1]}")
                if core_repo and strict.get(sha, (0, 0))[0] == 1:   # metis-1065: одно «принять» — хватит ли его
                    print(f"  PR ядра: нужно 2 «принять» на Opus, лёгкому (шлюз по файлам PR: только добавленные "
                          f"строки тестов и README*.md, drafts/*.md) — 1 на Opus с effort high, таких "
                          f"{light.get(sha, (0, 0))[0]}")
        return 0
    print(f"pantheon review: {REVIEW_USAGE}", file=sys.stderr)
    return 2
