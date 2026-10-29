"""Пантеон: pantheon review — записи для шлюза слияния guard (P1-4, guard 0.5.4): test, accept, reject, talos,
begin, status.

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon (P.review_cmd и т. д.).
"""
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

__all__ = [
    "REVIEW_SHA", "REVIEW_REPO", "REVIEW_PR", "REVIEW_USAGE", "REVIEW_CHECKLIST", "OPUS_RAN", "RAN_MODEL",
    "review_accept_full", "review_accept_counts", "_review_verdict", "_review_git", "_review_state", "review_records",
    "review_tally", "REVIEW_PENDING_TTL", "_review_pending_path", "_record_epoch", "review_pending", "review_cmd",
    "REVIEW_AGENT", "review_find_transcripts", "review_last_report",
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
                "[те же флаги] | talos <owner/repo> <PR> <SHA> | begin <owner/repo> <PR> <SHA> | miss <owner/repo>#<PR> --by <argus> --text \"…\" | sample | "
                "status [<owner/repo> <PR>] | report <owner/repo> <PR> <agent8>[/<сессия8>] [--out ПУТЬ]")
# перечень проверенного в «принять» (Б6, guard 0.5.6): у accept все три поля обязательны и непусты, у reject — по
# желанию. Тот же разбор — в merge_gate.verdict_parse плагина guard (он и решает, будет ли запись)
REVIEW_CHECKLIST = {"opened": "открыл", "ran": "запустил", "unchecked": "не проверял"}
OPUS_RAN = re.compile(r"\s*модель:\s*claude-opus", re.I)   # как в шлюзе guard (metis-0176)
RAN_MODEL = re.compile(r"\s*модель:\s*(claude-[a-z0-9.-]*[a-z0-9])", re.I)  # ID модели из ran, как в шлюзе guard


def review_accept_full(r):
    """«Принять» с полным перечнем «открыл / запустил / не проверял» (Б6) — любая модель. Вне ядра шлюз guard считает
    такое «принять» (simplify п. 9); в PR ядра нужен ещё Opus — review_accept_counts."""
    c = r.get("checklist")
    return isinstance(c, dict) and all(isinstance(c.get(k), str) and c[k].strip() for k in REVIEW_CHECKLIST)


def review_accept_counts(r):
    """«Принять» в счёт шлюза ядра (metis-0176, Б6): полный перечень и --ran с «модель: claude-opus» в начале, а если хук
    guard записал модели из транскрипта argus (поле models) — все они claude-opus и среди них модель из ran (тот же ID
    или он с датой), как opus_problem шлюза guard. Поля models нет (models_note — транскрипта не было, или запись
    старше) — судим по ran. Одно правило для шлюза владельца (merge.gate) и итога `review status` (review_tally),
    чтобы они не разошлись (metis-0393). Шлюз ядра владельца — только для PR ядра, там Opus обязателен."""
    c = r.get("checklist")
    if not (review_accept_full(r) and OPUS_RAN.match(c["ran"])):
        return False
    if "models" not in r:
        return True
    seen = r["models"]
    if not isinstance(seen, list) or not all(isinstance(m, str) and m.startswith("claude-opus") for m in seen):
        return False   # пустой список отсеет any() ниже
    said = RAN_MODEL.match(c["ran"])
    said = said.group(1).lower() if said else ""
    return any(re.fullmatch(re.escape(said) + r"(-\d{8})?", m) for m in seen)


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
            if name not in REVIEW_CHECKLIST:
                return pos, {}, f"неизвестный флаг --{name}. Формат: {fmt}"
            if name in checklist:
                return pos, {}, f"--{name} указан дважды. Формат: {fmt}"
            if not eq:
                if i + 1 >= len(args):
                    return pos, {}, f"у --{name} нет значения. Формат: {fmt}"
                i += 1
                val = args[i]
            if val.strip().startswith("--"):  # `--opened --ran …`: имя флага — не значение
                return pos, {}, f"значение --{name} начинается с «--»: похоже, пропущено значение. Формат: {fmt}"
            checklist[name] = val.strip()
        else:
            pos.append(a)
        i += 1
    if len(pos) != 3 or not REVIEW_REPO.fullmatch(pos[0]) or not REVIEW_PR.fullmatch(pos[1]) \
            or not REVIEW_SHA.fullmatch(pos[2].lower()):
        return pos, {}, f"аргументы не в формате {fmt} (SHA — полный: gh pr view N --json headRefOid)"
    if sub == "accept":
        missing = [f"--{k}" for k in REVIEW_CHECKLIST if not checklist.get(k)]
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


def _review_state():
    """(HEAD, дерево чистое) текущей папки; HEAD None — не git или коммитов нет."""
    head = (_review_git("rev-parse", "HEAD") or "").strip().lower()
    status = _review_git("status", "--porcelain")
    return (head if REVIEW_SHA.fullmatch(head) else None), (status is not None and not status.strip())


REVIEW_AGENT = re.compile(r"([0-9a-f]{4,64})(?:/([0-9a-f]{4,64}))?", re.I)  # agent8[/сессия8], как в `review status`


def review_find_transcripts(agent, session=None):
    """Файлы субагента ~/.claude/projects/*/<сессия>*/subagents/[workflows/<run>/]agent-<agent>*.jsonl (путь шлюза
    guard: agent_models) по началу agent_id и сессии. Транскрипт прежнего argus переживает /clear, а SendMessage к
    нему уже нет (No transcript found) — отчёт читается из файла (metis-0602)."""
    base = glob.escape(os.path.join(P.HOME, ".claude", "projects"))
    sess = glob.escape(session) if session else ""
    out = set()
    for sub in ((), ("*",), ("*", "*")):
        out.update(glob.glob(os.path.join(base, "*", sess + "*", "subagents", *sub, f"agent-{glob.escape(agent)}*.jsonl")))
    return sorted(p for p in out if os.path.isfile(p) and not os.path.islink(p))


def review_last_report(path, pr):
    """Последний финальный отчёт субагента в транскрипте, где назван этот PR: сообщение tool_use *Handback (поле
    input.message), а если такого блока нет — последний длинный text. None — отчёта по PR нет."""
    pr_re = re.compile(r"(?:#|/pull/|PR\s*)%s(?!\d)" % int(pr), re.I)
    handback, texts = [], []
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
                    handback.append(inp["message"])
                elif b.get("type") == "text" and isinstance(b.get("text"), str) and len(b["text"]) >= 400:
                    texts.append(b["text"])
    for text in reversed(handback or texts):
        if pr_re.search(text):
            return text
    return None


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
    repo, pr, agent, session = pos[0], pos[1], m.group(1).lower(), (m.group(2) or "").lower() or None
    files = review_find_transcripts(agent, session)
    if not files:
        print(f"pantheon review report: транскрипта субагента agent-{agent}*.jsonl"
              + (f" в сессии {session}*" if session else "") + " нет в ~/.claude/projects — сверь пару с "
              f"`pantheon review status {repo} {pr}`; отчёта нет — новый argus идёт полным кругом", file=sys.stderr)
        return 1
    if len(files) > 1:
        print("pantheon review report: под пару подходит несколько транскриптов — укажи сессию (agent8/сессия8) или "
              "длиннее agent_id:\n" + "\n".join("  " + f for f in files), file=sys.stderr)
        return 1
    text = review_last_report(files[0], pr)
    if text is None:
        print(f"pantheon review report: в {files[0]} нет итогового отчёта по {repo}#{pr} (блок *Handback с "
              "полем message или длинный текст с номером PR) — новый argus идёт полным кругом", file=sys.stderr)
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


def review_records(repo=None, pr=None):
    """Записи журнала шлюза слияния (битые строки пропускаются); файл — симлинк или не читается — пусто."""
    try:
        fd = os.open(os.path.join(P.STATE, "merge-gate", "records.jsonl"), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(rec, dict) or not isinstance(rec.get("repo"), list):
                continue
            if repo and repo.lower() not in [str(x).lower() for x in rec["repo"]]:
                continue
            if pr is not None and rec.get("pr") not in (pr, None):
                continue
            out.append(rec)
    return out


def review_tally(recs, pr, opus_only=False):
    """Итог argus по head PR (metis-0393): {sha: (принять, вернуть)} по последнему вердикту каждого рецензента.
    Рецензент — пара (session_id, agent_id), как у шлюза слияния guard: «вернуть» снимает только «принять» того же
    вызова. По итогу прошлого head лид и argus решают, допустим ли узкий повтор, — не по отчётам и словам лида.
    «Принять» без полного перечня не в счёт: «вернуть» того же рецензента оно не снимает. Модель не смотрим — вне
    ядра шлюз guard считает «принять» на любой модели (simplify п. 9, 27.10); opus_only=True — как для PR ядра:
    ещё и на Opus (по --ran и по моделям транскрипта argus, review_accept_counts)."""
    ok = review_accept_counts if opus_only else review_accept_full
    last = {}
    for r in recs:
        by = r.get("by")
        if (r.get("kind") in ("accept", "reject") and r.get("pr") == pr and isinstance(by, dict)
                and by.get("agent_type") == "argus" and isinstance(r.get("sha"), str)):
            if r["kind"] == "accept" and not ok(r):
                continue
            last.setdefault(r["sha"].lower(), {})[(by.get("session_id") or "", by.get("agent_id") or "")] = r["kind"]
    return {sha: (sum(k == "accept" for k in v.values()), sum(k == "reject" for k in v.values()))
            for sha, v in last.items()}


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
        try:
            rc = subprocess.run(rest[2:]).returncode
        except OSError as e:
            print(f"pantheon review test: команда не запустилась: {e}", file=sys.stderr)
            return 127
        head2, clean2 = _review_state()
        if head2 != head or not clean2:
            print(f"pantheon review test: команда изменила HEAD или дерево (было {head}, стало {head2 or '?'}, "
                  f"чистое: {'да' if clean2 else 'нет'}) — запись не делается", file=sys.stderr)
            return 3
        print(head)
        print(f"pantheon review test: код {rc} на {head}" + (" — запись тестов сделает хук guard" if rc == 0 else
                                                             " — тесты не прошли, записи не будет"))
        return rc
    if sub in ("accept", "reject", "talos"):
        args, checklist, why = _review_verdict(sub, rest[1:])
        if why:
            print(f"pantheon review {sub}: {why}", file=sys.stderr)
            return 2
        who = "argus" if sub != "talos" else "talos"
        print(f"pantheon review {sub}: {args[0].lower()}#{args[1]} @ {args[2].lower()} — записано хуком guard, "
              f"если роль подходит ({who})")
        for k, v in checklist.items():
            print(f"  {REVIEW_CHECKLIST[k]}: {v}")
        return 0
    if sub == "report":
        return review_report(rest[1:])
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
            cl = r.get("checklist") if isinstance(r.get("checklist"), dict) else {}
            if r.get("kind") == "accept" and not all(isinstance(cl.get(k), str) and cl[k].strip()
                                                     for k in REVIEW_CHECKLIST):
                print("    без перечня проверенного (Б6) — шлюз слияния такое «принять» не пускает")
            elif r.get("kind") == "accept" and not core_repo:
                pass
            elif r.get("kind") == "accept" and not OPUS_RAN.match(cl["ran"]):
                print("    не на Opus (--ran без «модель: claude-opus» в начале) — для PR ядра не в счёт; вне ядра "
                      "шлюз его считает")
            elif r.get("kind") == "accept" and r.get("models") == []:  # metis-0413: транскрипт найден, моделей нет
                print("    транскрипт argus найден, но моделей в нём нет — для PR ядра не в счёт; вне ядра шлюз его "
                      "считает")
            elif r.get("kind") == "accept" and not review_accept_counts(r):
                print("    не на Opus по транскрипту argus (поле models не сходится с --ran) — для PR ядра не в счёт; "
                      "вне ядра шлюз его считает")
            for k, label in REVIEW_CHECKLIST.items():
                if isinstance(cl.get(k), str) and cl[k].strip():
                    print(f"    {label}: {cl[k]}")
        if args:
            strict = review_tally(recs, int(args[1]), opus_only=True)
            for sha, (acc, rej) in review_tally(recs, int(args[1])).items():
                print(f"итог на {sha[:12]}: принять {acc}, вернуть {rej} — последний вердикт каждого argus")
                if core_repo and strict.get(sha, (0, 0)) != (acc, rej):   # для PR ядра — только «принять» на Opus
                    print(f"  для PR ядра (в счёт только «принять» на Opus): принять {strict.get(sha, (0, 0))[0]}, "
                          f"вернуть {strict.get(sha, (0, 0))[1]}")
        return 0
    print(f"pantheon review: {REVIEW_USAGE}", file=sys.stderr)
    return 2
