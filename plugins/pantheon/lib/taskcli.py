"""Пантеон: pantheon task … — разбор флагов и подкоманды задач (new, set, show, ready, claim, split, attach,
migrate-*). Сами задачи и доска — lib/tasks.py.

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import os
import sys

__all__ = [
    "TASK_NEW_VALUE_FLAGS", "TASK_NEW_BOOL_FLAGS", "TASK_SPLIT_VALUE_FLAGS", "TASK_SET_VALUE_FLAGS",
    "TASK_REPEATABLE_FLAGS", "TASK_FLAG_ALIASES", "task_repeat_error", "task_flag_error", "task_body_arg",
    "_read_or_empty", "task_new_notify", "overlap_open_prs", "ready_overlap_lines", "overlap_lines", "task_cmd",
]


# Флаги `task new` (metis-0402): неизвестный флаг — отказ с его именем, а не молчаливо потерянное поле.
TASK_NEW_VALUE_FLAGS = {"--direction", "--title", "--project", "--text", "--body", "--body-file", "--type", "--status",
                        "--priority", "--due", "--next", "--owner", "--release", "--wave", "--batch", "--mode", "--mode-why",
                        "--touches", "--night", "--estimate", "--actual", "--acceptance", "--waiting-on", "--question",
                        "--why", "--recommend", "--if-no-answer", "--option", "--depends-on", "--executor", "--parent",
                        "--from", "--source", "--done-when"}
TASK_NEW_BOOL_FLAGS = {"--risky"}
TASK_SPLIT_VALUE_FLAGS = {"--title", "--done-when", "--text", "--mode", "--mode-why"}
TASK_SET_VALUE_FLAGS = {"--note", "--option", "--body", "--body-file", "--force"}
# Повторяемые флаги — списки; любой другой повторённый флаг — отказ (argus b, круг 2): `opt()` берёт последнее
# значение, и `--body "Цель" --body "Готово, когда"` молча терял бы первую часть. --wave — прежнее имя --release.
TASK_REPEATABLE_FLAGS = {"--option", "--touches", "--depends-on", "--done-when"}
TASK_FLAG_ALIASES = {"--wave": "--release"}


def task_repeat_error(sub, a, seen):
    """Отказ, если одиночный флаг `a` уже был (seen пополняется), иначе None."""
    key = TASK_FLAG_ALIASES.get(a, a)
    if key in TASK_REPEATABLE_FLAGS:
        return None
    if key in seen:
        return (f"pantheon task {sub}: флаг {a} повторён — он одиночный, значения не склеиваются; весь текст — одним "
                f"флагом (длинный — --body-file <путь>), повторяются только {', '.join(sorted(TASK_REPEATABLE_FLAGS))}"
                " — ничего не записано")
    seen.add(key)
    return None


def task_flag_error(sub, args, value_flags, bool_flags=()):
    """Первая ошибка во флагах `--…` (неизвестный, без значения, повтор одиночного, лишнее слово) или None. Значение
    флага пропускается."""
    i, seen = 0, set()
    while i < len(args):
        a = args[i]
        if a in bool_flags:
            err = task_repeat_error(sub, a, seen)
            if err:
                return err
            i += 1
        elif a in value_flags:
            if i + 1 >= len(args):
                return f"pantheon task {sub}: у флага {a} нет значения"
            err = task_repeat_error(sub, a, seen)
            if err:
                return err
            i += 2
        elif a.split("=", 1)[0] in value_flags | set(bool_flags):
            return f"pantheon task {sub}: пишите «{a.split('=', 1)[0]} значение» через пробел, не «{a[:40]}» — ничего не записано"
        elif a.startswith("--"):
            return f"pantheon task {sub}: неизвестный флаг {a.split('=', 1)[0]} — ничего не записано"
        else:
            return f"pantheon task {sub}: лишнее «{a}» — значения идут после своего флага"
    return None


def task_body_arg(sub, opt):
    """Текст из --text, --body, --body-file (в этом порядке, через пустую строку) → (текст или None, ошибка или None)."""
    parts = [opt("--text"), opt("--body")]
    bf = opt("--body-file")
    if bf:
        try:
            with open(bf, encoding="utf-8") as fh:
                parts.append(fh.read())
        except (OSError, UnicodeDecodeError) as e:
            return None, f"pantheon task {sub}: --body-file {bf} не читается ({getattr(e, 'strerror', None) or e})"
    parts = [x for x in parts if x and x.strip()]
    return ("\n\n".join(x.strip() for x in parts) if parts else None), None


def _read_or_empty(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def task_new_notify(T, tid, direction, title, text):
    """Уведомление координатору направления (metis-0402 в): файл в directions/<направление>/inbox/ — входящие он
    разбирает при старте и по ним его будит передача задания. Тот же канал, что находки. Сбой записи не отменяет
    задачу: строка в stderr и тревога."""
    if direction == "inbox" or os.environ.get("PANTHEON_SESSION") == direction:  # свою задачу координатор знает
        return
    ib = os.path.join(P.PANTHEON, "directions", direction, "inbox")
    fname = f"{P.stamp()[:10]}-{P.stamp()[11:13]}{P.stamp()[14:16]}-task-{tid}.md"
    # без переменных роли — «агент»: «владелец» подписывает только owner-log, а не тот, кто вызвал команду (argus b)
    who = os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "агент"
    try:
        os.makedirs(ib, exist_ok=True)
        P.write_atomic(os.path.join(ib, fname),
                     f"# Новая задача {tid}: {' '.join(title.split())[:120]}\n\nОт: {who}\n\n"
                     f"{T.NOTICE_MARK} задача уже заведена (`pantheon task show {tid}`), заводить её заново не нужно. "
                     f"Возьми её в работу и перенеси этот файл в `inbox/done/`.\n")
    except OSError as e:
        print(f"предупреждение · уведомление координатору {direction} не записано: {e.strerror or e}", file=sys.stderr)
        P.alert(f"новая задача {tid} ({direction}): уведомление в inbox не записано — {e.strerror or e}", "task-new")


OVERLAP_GH_TIMEOUT = 30  # секунд на репозиторий: `task set status=doing` не должен висеть на сети


def _merge_repos(direction):
    """Репозитории направления из [merge_repos] policy.toml (как у автозакрытия) → (список, ошибка или None)."""
    p = os.path.join(P.HOME, ".claude", "pantheon", "policy.toml")
    try:
        with open(p, "rb") as fh:
            pol = P.tomllib.load(fh)
    except FileNotFoundError:
        return [], f"нет {p} — репозитории направления неизвестны, открытые PR не проверены"
    except (OSError, ValueError) as e:
        return [], f"{p} не читается ({type(e).__name__}) — открытые PR не проверены"
    repos = (pol.get("merge_repos") or {}).get(direction) if isinstance(pol.get("merge_repos"), dict) else None
    repos = [r for r in repos if isinstance(r, str) and r.strip()] if isinstance(repos, list) else []
    T = P.tasks_mod()
    ok = [r for r in repos if T.overlap_name_ok(r, T.OVERLAP_REPO_RE)]
    if len(ok) < len(repos):  # имя не owner/name — в команды и вывод не идёт; само имя не печатаем
        return ok, (f"в [merge_repos] {p} у {direction} отклонено имён не owner/name: {len(repos) - len(ok)} — "
                    "их открытые PR не проверены")
    return repos, None if repos else f"у {direction} нет репозиториев в [merge_repos] {p} — открытые PR не проверены"


def _pr_files(T, raw):
    """Пути файлов PR → (годные, сколько отброшено): путь с управляющим знаком, переводом строки или длиннее
    T.OVERLAP_PATH_MAX в вывод не идёт — чужой PR не вставит строки в предупреждение."""
    paths = [f for f in raw if isinstance(f, str)]
    good = [f for f in paths if T.overlap_path_ok(f)]
    return good, len(paths) - len(good)


def _pr_row(A, T, repo, pr, raw_files, branch):
    files, dropped = _pr_files(T, raw_files)
    return {"repo": repo, "number": pr.get("number"), "branch": branch, "files": files, "dropped": dropped,
            "ids": A.find_ids(branch, _body(pr)), "closes": A.closing_ids(branch, _body(pr))}


def _body(pr):
    body = pr.get("body")
    return body if isinstance(body, str) else ""


def _one_line(text):
    """Ответ gh об ошибке — в одну строку без управляющих знаков."""
    return " ".join("".join(c if c.isprintable() else " " for c in str(text)).split())[:200]


def overlap_open_prs(direction):
    """Открытые PR репозиториев направления с файлами (metis-0665) → (prs, notes). Сначала gh; не ответил — кэш
    планового прохода autoclose-prs.json (open_prs с files и branch) и строка, что взят кэш и почему; нет и кэша —
    строка «не проверено». Молча PR не пропускаются: notes уходят в вывод."""
    A, T = P.autoclose_mod(), P.tasks_mod()
    repos, err = _merge_repos(direction)
    if not repos:
        return [], [err]
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    cache = P.read_json(P.path("autoclose-prs.json"), {})
    cache = cache if isinstance(cache, dict) else {}  # кэш не словарь — как нет кэша
    cached = cache.get("open_prs") if isinstance(cache.get("open_prs"), dict) else {}
    fetched = cache.get("fetched")
    prs, notes = [], [err] if err else []
    for repo in repos:
        data, gerr = A.gh_json(["pr", "list", "-R", repo, "--state", "open", "--limit", str(A.LIMIT), "--json",
                                "number,headRefName,body,files"], env, timeout=OVERLAP_GH_TIMEOUT)
        if not gerr and isinstance(data, list):
            for pr in data:
                if isinstance(pr, dict) and isinstance(pr.get("number"), int):
                    files = [f.get("path") for f in pr.get("files") or [] if isinstance(f, dict)]
                    prs.append(_pr_row(A, T, repo, pr, files, str(pr.get("headRefName") or "")))
            continue
        why = _one_line(gerr or "ответ gh — не список")
        rows = cached.get(repo.lower())
        if not isinstance(rows, list) or not isinstance(fetched, (int, float)):
            notes.append(f"{repo}: gh не ответил ({why}), кэша планового прохода нет — проверь вручную: "
                         f"gh pr list -R {repo} --state open --json number,headRefName,files")
            continue
        when = P.datetime.fromtimestamp(fetched).strftime("%d.%m %H:%M")
        nofiles = [r.get("number") for r in rows if isinstance(r, dict) and not isinstance(r.get("files"), list)]
        notes.append(f"{repo}: gh не ответил ({why}) — открытые PR из кэша планового прохода от {when}"
                     + (f"; без списка файлов: {', '.join('#' + str(n) for n in nofiles)}" if nofiles else ""))
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("number"), int) and isinstance(r.get("files"), list):
                files, dropped = _pr_files(T, r["files"])
                prs.append({"repo": repo, "number": r["number"], "branch": str(r.get("branch") or ""),
                            "files": files, "dropped": dropped,
                            "ids": [i for i in r.get("ids") or [] if isinstance(i, str) and A.ID_RE.fullmatch(i)],
                            "closes": [i for i in r.get("closes") or [] if isinstance(i, str) and A.ID_RE.fullmatch(i)]})
    return prs, notes


def overlap_lines(T, tid, quiet_clean=False):
    """Строки предупреждения о пересечении задачи tid (metis-0665). quiet_clean — для `task set status=doing`: без
    touches — одна короткая строка-подсказка, а не весь разбор."""
    tasks = T.load_tasks(P.PANTHEON, T.WORK_TYPES)
    head = tasks[tid][1]
    if not head.get("touches"):
        return T.overlap_text(tid, head, [], []) if not quiet_clean else [
            f"у {tid} нет touches — пересечение с соседними задачами и открытыми PR не проверено "
            f"(pantheon task overlap {tid} после touches=…)"]
    prs, notes = overlap_open_prs(head.get("direction"))
    return T.overlap_text(tid, head, T.overlap_tasks(tasks, tid), T.overlap_prs(tid, head, prs), notes)


def _warn_overlap(T, tid):
    """После взятия в работу — предупреждение в stderr; сбой сверки задачу не отменяет."""
    try:
        lines = overlap_lines(T, tid, quiet_clean=True)
    except Exception as e:  # noqa: BLE001 — сверка — подсказка, запись уже сделана
        lines = [f"сверка пересечения не прошла ({type(e).__name__}: {e}) — повтори pantheon task overlap {tid}"]
    for ln in lines:
        print(ln if ln.startswith((" ", "-")) else f"предупреждение · {ln}", file=sys.stderr)


def ready_overlap_lines(T, rows):
    """Для `task ready` (metis-0667): по строке на готовую задачу с touches, чьи области пересекаются с открытым PR →
    "TID: пересечение с PR #N (файлы …)". Нет пересечений — пусто. Открытые PR берутся один раз на направление; нет
    touches ни у кого — gh не зовётся. Строки «не проверено» (gh не ответил, нет policy) — один раз на направление."""
    out, per_dir = [], {}
    for tid, h in rows:
        if not h.get("touches"):
            continue
        d = h.get("direction")
        if d not in per_dir:
            per_dir[d] = overlap_open_prs(d)
            out += [f"не проверено: {n}" for n in per_dir[d][1]]
        for pr, common in T.overlap_prs(tid, h, per_dir[d][0]):
            more = f" и ещё {len(common) - 6}" if len(common) > 6 else ""
            out.append(f"{tid}: пересечение с PR #{pr.get('number')} (файлы {', '.join(common[:6])}{more}) — "
                       f"до взятия: pantheon task overlap {tid}")
    return out


def task_cmd(rest):
    T = P.tasks_mod()
    if not rest:
        print("pantheon task new|set|show|ready|claim|overlap — справка: pantheon help", file=sys.stderr)
        return 2
    sub, args = rest[0], rest[1:]

    def opt(name, many=False):
        vals = [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]
        return vals if many else (vals[-1] if vals else None)

    try:
        if sub == "new":
            err = task_flag_error("new", args, TASK_NEW_VALUE_FLAGS, TASK_NEW_BOOL_FLAGS)
            if err:
                print(err, file=sys.stderr)
                return 2
            body_text, err = task_body_arg("new", opt)
            if err:
                print(err, file=sys.stderr)
                return 2
            if body_text is None and opt("--question") and not T.is_full_question(
                    {"question": opt("--question"), "why": opt("--why"), "options": opt("--option", True)}):
                # metis-0402, argus a: без текста суть карточки вопроса — в её полях, поэтому они должны быть полными
                print("pantheon task new: вопрос без текста задачи — нужны --why и не меньше двух --option "
                      "(или текст --text/--body/--body-file); ничего не записано", file=sys.stderr)
                return 2
            if body_text is not None and opt("--question") and not T.is_full_question(
                    {"question": opt("--question"), "why": opt("--why"), "options": opt("--option", True)}):
                print("предупреждение · вопрос владельцу без --why или без двух непустых --option: карточка выйдет "
                      "неполной (writing.part — суть, причина и варианты всегда)", file=sys.stderr)
            if body_text is None and not opt("--question"):
                print("pantheon task new: нужен текст задачи — --text, --body или --body-file <путь> (цель и «готово, когда»); "
                      "задача без описания не создаётся (вопрос владельцу — с --question, --why и вариантами)", file=sys.stderr)
                return 2
            fields = {"status": opt("--status"), "priority": int(opt("--priority")) if opt("--priority") else None,
                      "due": opt("--due"), "next": opt("--next"), "owner": opt("--owner"),
                      "release": opt("--release") or opt("--wave"), "batch": opt("--batch"),
                      "mode": opt("--mode"), "mode_why": opt("--mode-why"), "touches": opt("--touches", True) or None,
                      "night": opt("--night"), "estimate": opt("--estimate"), "actual": opt("--actual"),
                      "acceptance": opt("--acceptance"),
                      "waiting_on": opt("--waiting-on"), "question": opt("--question"), "why": opt("--why"),
                      "recommend": opt("--recommend"), "if_no_answer": opt("--if-no-answer"),
                      "options": opt("--option", True) or None, "depends_on": opt("--depends-on", True) or None,
                      "risky": True if "--risky" in args else None, "executor": opt("--executor"), "parent": opt("--parent"),
                      "from": opt("--from"), "source": opt("--source")}
            if not opt("--direction") or not opt("--title"):
                print("pantheon task new: нужны --direction и --title", file=sys.stderr)
                return 2
            if opt("--direction") == "inbox":
                print("pantheon task new: входящие создаёт только доска владельца; Зевс заводит задачу сразу в направлении",
                      file=sys.stderr)
                return 2
            if (opt("--type") or "task") not in T.WORK_TYPES:
                print(f"pantheon task new: --type {opt('--type')} — только {' или '.join(T.WORK_TYPES)}", file=sys.stderr)
                return 2
            tid, p = T.task_new(P.PANTHEON, P.now(), opt("--direction"), opt("--title"), project=opt("--project"),
                                text=body_text, kind=opt("--type") or "task", done_when=opt("--done-when", True) or None, **fields)
            print(f"{tid} {os.path.relpath(p, P.PANTHEON)}")
            task_new_notify(T, tid, opt("--direction"), opt("--title"), body_text)
            for w in T.option_warns(fields):
                print(f"предупреждение · {w}", file=sys.stderr)
        elif sub == "set" and args:
            tid, changes, note, i, seen, force = args[0], {}, None, 1, set(), None
            # --wave — прежнее имя --release (metis-0069): выпуск строкой «pantheon 0.11.50»
            night_flags = {"--release": "release", "--wave": "release", "--batch": "batch", "--night": "night", "--estimate": "estimate",
                           "--actual": "actual", "--acceptance": "acceptance", "--mode": "mode", "--mode-why": "mode_why"}  # ночной цикл: флаги как у --due
            j = 1  # повтор одиночного флага — отказ до чтения --body-file и до записи; шаг — как в разборе ниже
            while j < len(args):
                if args[j] in TASK_SET_VALUE_FLAGS | set(night_flags) and j + 1 < len(args):
                    err = task_repeat_error("set", args[j], seen)
                    if err:
                        print(err, file=sys.stderr)
                        return 2
                    j += 2
                else:
                    j += 1
            new_body, err = task_body_arg("set", opt)
            if err:
                print(err, file=sys.stderr)
                return 2
            if new_body is None and (opt("--body") is not None or opt("--body-file") is not None):
                print("pantheon task set: --body/--body-file пусты — текст не заменён; ничего не записано", file=sys.stderr)
                return 2
            while i < len(args):
                if args[i] in ("--body", "--body-file") and i + 1 < len(args):  # тело уже взято task_body_arg
                    i += 2
                    continue
                if args[i] == "--note" and i + 1 < len(args):
                    note, i = args[i + 1], i + 2
                    continue
                if args[i] == "--force" and i + 1 < len(args):  # причина закрытия с неотмеченными пунктами (metis-0503)
                    force, i = args[i + 1], i + 2
                    continue
                if args[i] == "--option" and i + 1 < len(args):  # варианты с запятыми и кавычками (metis-0037)
                    changes["options"] = (changes.get("options") or []) + [args[i + 1]]  # и после options= (argus)
                    i += 2
                    continue
                if args[i].startswith("--") and not (args[i] in night_flags and i + 1 < len(args)):
                    # metis-0402: неизвестный флаг или флаг без значения — отказ с его именем, не «поле=значение»
                    known, name = {"--note", "--option", "--body", "--body-file", "--force", *night_flags}, args[i].split("=", 1)[0]
                    print("pantheon task set: " + (f"у флага {args[i]} нет значения" if args[i] in known
                          else f"пишите «{name} значение» через пробел, не «{args[i][:40]}»" if name in known
                          else f"неизвестный флаг {name}") + " — ничего не записано", file=sys.stderr)
                    return 2
                if args[i] in night_flags and i + 1 < len(args):
                    k, v, eq, step = night_flags[args[i]], args[i + 1], "=", 2
                else:
                    k, eq, v = args[i].partition("=")
                    k = T.LEGACY_KEYS.get(k, k)
                    step = 1
                if not eq:
                    print(f"pantheon task set: «{args[i]}» — нужно поле=значение", file=sys.stderr)
                    return 2
                if k in T.OWNER_ONLY_FIELDS:
                    print(f"pantheon task set: поле {k} ставит только доска владельца", file=sys.stderr)
                    return 2
                if k == "options" and v not in ("", "null"):
                    print("pantheon task set: варианты — повторяемым --option \"…\" (в тексте бывают запятые); "
                          "options= только чтобы очистить", file=sys.stderr)
                    return 2
                kind = T.FIELDS.get(k, ("str",))[0]
                changes[k] = None if v in ("", "null") else int(v) if kind == "int" else (v == "true") if kind == "bool" else \
                    [x.strip() for x in v.split(",") if x.strip()] if kind == "list" else v
                i += step
            p, head = T.task_set(P.PANTHEON, P.now(), tid, changes, note=note, body=new_body, force=force)
            print(f"{tid}: {head.get('status')} · {os.path.relpath(p, P.PANTHEON)}")
            if head.get("status") == "waiting":  # metis-0714: строка для проверяющей модели цели окна (WAITING_GOAL)
                print(f"{tid}: {T.GOAL_OUT} — ждёт " + ("ответа владельца на вопрос" if head.get("waiting_on") == "human"
                                                       else f"задачу {head.get('waiting_on')}")
                      if T.goal_released(head, T.load_tasks(P.PANTHEON, T.WORK_TYPES))
                      else f"{tid}: {T.GOAL_IN} — «ждёт» снимает задачу с цели, только если waiting_on=human с question "
                           f"или waiting_on=<id другой задачи>, которая есть, не done/dropped и, если сама ждёт, "
                           f"снята с цели")
            if changes.get("status") == "doing" and head.get("status") == "doing":
                _warn_overlap(T, tid)
            if changes.get("status") in ("done", "dropped"):
                P.metrics_on_close(T, tid)
            for w in T.option_warns({"options": changes.get("options")}):
                print(f"предупреждение · {w}", file=sys.stderr)
        elif sub == "show" and args:
            tasks = T.load_tasks(P.PANTHEON, T.WORK_TYPES)
            if args[0] not in tasks:
                print(f"нет задачи {args[0]}", file=sys.stderr)
                return 1
            print(open(tasks[args[0]][0], encoding="utf-8").read())
            if tasks[args[0]][1].get("type") == "story":
                print("## Состав пачки\n\n" + T.story_text(args[0], tasks) + "\n")
            words = T.owner_words(P.path("owner-log", "board.jsonl"), args[0])
            print("## Слова владельца (журнал владельца — только это подтверждает его решение)\n")
            for w in words or [{"time": "—", "kind": "нет записей"}]:
                print(f"- {w.get('time', '')[:16].replace('T', ' ')} · {w.get('kind')} · "
                      f"{w.get('dst') or w.get('answer') or w.get('text') or w.get('title') or ''}")
        elif sub == "split" and args and not args[0].startswith("--"):
            err = task_flag_error("split", args[1:], TASK_SPLIT_VALUE_FLAGS)
            if err:
                print(err, file=sys.stderr)
                return 2
            tid0 = args[0]
            args = args[1:]
            if not opt("--title"):
                print("pantheon task split: нужен --title — название остатка; ничего не записано", file=sys.stderr)
                return 2
            tid, p = T.task_split(P.PANTHEON, P.now(), tid0, opt("--title"), done_when=opt("--done-when", True) or None,
                                  text=opt("--text"), mode=opt("--mode"), mode_why=opt("--mode-why"))
            print(f"{tid} {os.path.relpath(p, P.PANTHEON)} (остаток {tid0})")
            task_new_notify(T, tid, T.read(p)[0].get("direction"), opt("--title"), opt("--text"))
        elif sub == "attach" and len(args) == 2:
            old = T.task_attach(P.PANTHEON, P.now(), args[0], args[1])
            print(f"{args[0]} → пачка {args[1]}" + (f" (была в {old})" if old else ""))
        elif sub == "migrate-batches":
            if any(a != "--dry-run" for a in args):
                print(f"pantheon task migrate-batches: не понял «{' '.join(args)}» — допустим только --dry-run", file=sys.stderr)
                return 2
            dry = "--dry-run" in args
            plan = T.migrate_batches(P.PANTHEON, P.now(), dry_run=dry)
            print("\n".join(plan) if plan else "переносить нечего")
            if dry and plan:
                print("(--dry-run: ничего не записано)")
        elif sub == "migrate-mode":
            if any(a != "--dry-run" for a in args):
                print(f"pantheon task migrate-mode: не понял «{' '.join(args)}» — допустим только --dry-run", file=sys.stderr)
                return 2
            dry = "--dry-run" in args
            plan, failed = T.migrate_modes(P.PANTHEON, P.now(), dry_run=dry)
            print("\n".join(plan) if plan else "переносить нечего")
            if dry and plan:
                print("(--dry-run: ничего не записано)")
            if failed:
                print(f"pantheon task migrate-mode: не записано {failed} — строки «не записано» выше", file=sys.stderr)
                return 1
        elif sub == "migrate-project":
            if any(a != "--write" for a in args):
                print(f"pantheon task migrate-project: не понял «{' '.join(args)}» — допустим только --write", file=sys.stderr)
                return 2
            dirs = T.load_directions(P.PANTHEON)
            if dirs is None:
                print("pantheon task migrate-project: нет читаемого directions.toml", file=sys.stderr)
                return 1
            plan, failed = T.migrate_projects(P.PANTHEON, P.now(), dirs, dry_run="--write" not in args)
            print("\n".join(plan) if plan else "переносить нечего")
            if plan and "--write" not in args:
                print(f"(сухой прогон: {len(plan)} карточек, ничего не записано; запись — с --write)")
            if failed:
                print(f"не перенесено: {failed}", file=sys.stderr)
                return 1
        elif sub == "detach" and len(args) == 1:
            sid = T.task_detach(P.PANTHEON, P.now(), args[0])
            print(f"{args[0]}: откреплена от пачки {sid}")
        elif sub == "ready":
            rows = T.ready(P.PANTHEON, P.now(), opt("--direction"), opt("--owner"))
            for tid, h in rows:
                print(f"{tid}\t{T.PRIORITY.get(h.get('priority', 2), '')}\t{h.get('due') or '—'}\t{h.get('title')}")
            try:  # сверка — подсказка в stderr: список задач и код выхода она не меняет
                warns = ready_overlap_lines(T, [r for r in rows if r[1].get("type", "task") == "task"])
            except Exception as e:  # noqa: BLE001
                warns = [f"не проверено: сверка с открытыми PR не прошла ({type(e).__name__}: {e})"]
            for ln in warns:
                print(f"предупреждение · {ln}", file=sys.stderr)
        elif sub == "claim" and args and opt("--by"):
            p, head = T.task_claim(P.PANTHEON, P.now(), args[0], opt("--by"), float(opt("--hours") or 1))
            print(f"{args[0]}: взята {opt('--by')} до {head.get('claimed_until')}")
            if head.get("status") == "doing":
                _warn_overlap(T, args[0])
        elif sub == "overlap" and len(args) == 1 and not args[0].startswith("--"):
            tasks = T.load_tasks(P.PANTHEON, T.WORK_TYPES)
            if args[0] not in tasks or tasks[args[0]][1].get("type", "task") != "task":
                print(f"pantheon task overlap: нет задачи {args[0]}", file=sys.stderr)
                return 1
            lines = overlap_lines(T, args[0])
            print("\n".join(lines) if lines else f"{args[0]}: пересечений с живыми задачами направления и открытыми PR нет")
        else:
            print(f"pantheon task: не понял «{' '.join(rest)}»", file=sys.stderr)
            return 2
    except ValueError as e:
        print(f"pantheon task: {e}", file=sys.stderr)
        return 1
    return 0
