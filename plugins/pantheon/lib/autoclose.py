"""Автозакрытие задач при слиянии их PR (metis-0308). Для всех направлений, без участия ролей.

Два прохода. fetch (`pantheon autoclose fetch`, отдельная задача расписания, с пределом времени FETCH_BUDGET на весь
проход) спрашивает gh про слитые и открытые PR репозиториев из [merge_repos] policy.toml и пишет кэш STATE/autoclose-prs.json.
В кэше же — бывшие head ещё открытых PR (old_heads, former_heads, metis-0726): по ним `pantheon outside` не гоняет
тесты на коммит, который уже не head своего PR.
run (лёгкий тик) читает только кэш, в сеть не ходит. Задачу (`<префикс>-NNNN`) закрывает только PR из репозитория её
направления, и только если её номер в имени ветки или после «Closes/Fixes» в теле — там и списком: «Closes metis-0522,
metis-0534 и 0535» закрывает все три (metis-0583); упоминание («См. также») не считается.
Второй путь (metis-0583, close_checked): задача doing/review, у которой все пункты «Готово, когда» отмечены, а PR из её
журнала («PR #N») слит в репозитории её направления, — done той же записью: PR под общей веткой без Closes не оставляет её висеть.
Слитый PR закрывает такую задачу: status done, closed —
день слияния, release — «PR #N → коммит» (версия плагина, если PR поднял plugin.json), actual — из учёта по задачам
(metrics/tasks.jsonl, metis-0294), нет замера — «нет замера»; в журнал задачи — строка с CLOSED_BY_MERGE.
В теле PR «часть <id>» или «часть №<номер>» — PR закрывает только часть задачи: его задачи не закрываются (и close_checked,
metis-0660). Слово «часть» без номера рядом («личная часть карты») не в счёт (metis-1193, PART_RE).
Неотмеченные пункты «Готово, когда» (задачи с T.CRITERIA_FROM, metis-0503): слитый PR без «часть» ставит review и
строку «слит, неотмечено N (пункты …)», а не done — хвосты не теряются; закрыть — отметить пункты, `pantheon task split` или --force.
Перед этим (metis-1004) слитый PR с Closes отмечает сам пункты, которые argus принял на head слияния: `accepted(repo,
строка кэша)` → {id: {номер: хеш}} (review.review_criteria_ticks — засчитанные «принять» с --criteria «да»); пункт
отмечается, только если хеш его нынешнего текста тот же (T.criteria_tick). Отмечены все — done, как обычно. Пункты
задачи не из Closes (metis-1193, tick_named) — так же, если тело PR их называет: «пункт 3 metis-1050». Для этого
fetch кладёт в строку слитого PR head (headRefOid), base (baseRefName) и core (задето ли ядро, merged_core). Ядро по
обоим путям переименования; переименование без старого пути и список файлов, обрезанный gh (больше 100), — ядро.
Открытый PR, который так же закрывает задачу (без «часть»), ставит задаче todo/doing/waiting её направления review — один
раз на PR (строка REVIEW_MARK в журнале); PR без Closes — задачам doing/waiting, названным в его ветке или теле (metis-0615).
Обработанные PR отмечены в STATE/autoclose.json; задачу, уже закрытую этим PR (строка в журнале), второй раз не трогаем. Заодно проход запоминает, у каких
задач есть открытый PR: без него «review больше суток» на доске — повод для внимания.

Модуль без обращения к pantheon.py: тесты зовут его напрямую.
"""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime

ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")
# «часть» — только отдельным словом рядом с номером задачи: «часть metis-1051», «часть 1051», «часть задачи metis-1051»,
# «часть: metis-1051» (metis-1193). Номер — id с префиксом или цифры после № / # / «задачи» («часть №1051», «часть
# задачи 1051»); голое число («часть 100 строк», «часть 2026 года») — не номер. Между словом и номером — пробелы, знаки
# разметки (* _ ` ( [ # №, двоеточие, тире) и перед id не больше одного слова («часть работы metis-1051»). Слово в
# обычной фразе («личная часть карты», #441) PR частичным не делает.
_PART_GAP = r"[\s*_`(\[#№:—–-]*"
_PART_NUM = r"(?:[#№]|задачи" + _PART_GAP + r")\s*\d{3,}(?!\w)"
PART_RE = re.compile(r"(?<![^\W_])часть(?![^\W_])" + _PART_GAP + r"(?:(?:[^\W\d_]+" + _PART_GAP + r")?" + ID_RE.pattern
                     + r"|" + _PART_NUM + r")", re.I)
FETCH_BUDGET = 240     # секунд на весь сетевой проход (fetch): дольше не ждём, остаток репозиториев — в следующий раз
REPO_BUDGET = 75       # секунд на один репозиторий (metis-0808): fetch иногда 100-350 с против обычных 40 — завислый gh не съедает весь проход
FIRST_LOOKBACK = 48 * 3600  # первый проход (нет состояния) смотрит назад на столько: старые упоминания задач не трогаем
KEEP = 500             # отметок обработанных PR в состоянии
LIMIT = 100
NO_METRIC = "нет замера"
REVIEW_MARK = "открыт → review"  # строка журнала задачи, которой открытый PR поставил review (тот же текст в boardstatus.py)
VERSION_RE = re.compile(r'^\+\s*"version"\s*:\s*"([^"]+)"')
DIFF_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)")


def find_ids(*texts):
    """Номера задач в порядке появления, без повторов."""
    out = []
    for text in texts:
        for m in ID_RE.finditer(text or ""):
            if m.group(0) not in out:
                out.append(m.group(0))
    return out


CLOSE_RE = re.compile(r"(?<!\w)(?i:close[sd]?|fix(?:es|ed)?|resolve[sd]?|закрыва(?:ет|ю)|закры(?:л|ла|ли|то)|исправля(?:ет|ю)|исправил[аи]?)"
                      r"\s*[:\-]?\s+(" + ID_RE.pattern + ")")
# перед глаголом отрицание («не закрывает», «пока не закрываю», «doesn't fix», «not closing») — PR задачу не закрывает
NEG_BEFORE_RE = re.compile(r"(?:(?<!\w)(?:не|нет|not|never|no)|n['’]t)\s+(?:\w+\s+)?$", re.I)


# после «Closes <id>» — список (metis-0583): «, <id>», «и <id>», «and <id>», «; <id>», «& <id>». Номер без префикса
# («Closes metis-0522, 0534 и 0535») берёт префикс прошлого id, если в нём столько же цифр и за ним конец, знак или «и»
LIST_NEXT_RE = re.compile(r"\s*(?:,|;|&|\s(?:и|and)(?=\s))\s*(?:(" + ID_RE.pattern + r")|(?<![\w-])(\d{3,})(?=$|[\s,;.()&]))", re.I)
BARE_END_RE = re.compile(r"\s*(?:$|[,;.()&—–-]|(?:и|and)\s)", re.I)


def _id_list(text, pos, first):
    """Номера после первого id списка «Closes a-1, a-2 и 0003» → [a-2, a-0003]; pos — конец первого id."""
    out, prev = [], first
    while True:
        m = LIST_NEXT_RE.match(text, pos)
        if not m:
            return out
        if m.group(1):
            prev = m.group(1)
        else:
            pre, num = prev.rsplit("-", 1)
            if len(m.group(2)) != len(num) or not BARE_END_RE.match(text, m.end()):
                return out  # «Closes metis-0522, 100 тестов» — число, а не номер задачи
            prev = f"{pre}-{m.group(2)}"
        out.append(prev)
        pos = m.end()


def closing_ids(branch, body):
    """Номера задач, которые PR закрывает: id в имени ветки или «Closes/Fixes <id>» в теле, со списком после него
    («Closes metis-0522, metis-0534 и 0535» — все три, metis-0583). Простое упоминание («См. также», «зависит от»,
    «часть») — нет."""
    body = body or ""
    ids = []
    for m in CLOSE_RE.finditer(body):
        if not NEG_BEFORE_RE.search(body[:m.start()]):
            ids += [m.group(1)] + _id_list(body, m.end(1), m.group(1))
    return find_ids(branch, *ids)


def is_part(body):
    return bool(PART_RE.search(body or ""))


def gh_exe(env=None):
    """gh: PANTHEON_GH (тесты подставляют поддельный) или первый в PATH."""
    e = env if env is not None else os.environ
    return e.get("PANTHEON_GH") or shutil.which("gh", path=e.get("PATH"))


def gh_json(args, env=None, timeout=90):
    """→ (данные, ошибка). gh нет или он упал — (None, текст)."""
    exe = gh_exe(env)
    if not exe:
        return None, "gh не найден в PATH"
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"gh не запустился: {type(e).__name__}"
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or f"код {r.returncode}").strip()[:200]
    try:
        return json.loads(r.stdout or "null"), None
    except ValueError:
        return None, "gh вернул не JSON"


def gh_text(args, env=None, timeout=90):
    exe = gh_exe(env)
    if not exe:
        return None
    try:
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def merged_day(iso):
    """'2026-10-19T21:05:00Z' → '2026-10-20' (день слияния по часам этого Mac). Не разобрать — None."""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d.astimezone() if d.tzinfo else d).strftime("%Y-%m-%d")


def merged_ts(iso):
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else d.astimezone().timestamp()


def plugin_versions(diff_text):
    """Диф PR → {плагин: новая версия} по строкам `+ "version": …` в .claude-plugin/plugin.json."""
    out, cur = {}, None
    for ln in (diff_text or "").splitlines():
        m = DIFF_RE.match(ln)
        if m:
            parts = m.group(2).split("/")
            cur = parts[-3] if m.group(2).endswith(".claude-plugin/plugin.json") and len(parts) >= 3 else None
            continue
        if cur:
            v = VERSION_RE.match(ln)
            if v:
                out[cur] = v.group(1)
    return out


def release_text(repo, pr):
    """release закрытой задачи: «PR #N → коммит»; PR поднял plugin.json — версия плагина (её собрал проход fetch)."""
    n = pr.get("number")
    sha = (pr.get("oid") or "")[:7]
    base = f"PR #{n} → {sha}" if sha else f"PR #{n}"
    vers = pr.get("versions")
    if isinstance(vers, dict) and vers:
        return "; ".join(f"{k} {v}" for k, v in sorted(vers.items())) + f" ({base})"
    return base


def actual_text(row):
    """Строка учёта по задаче (metrics/tasks.jsonl) → «$1.23 · 450k токенов · 2.1 ч»; пусто или нули — «нет замера»."""
    if not isinstance(row, dict):
        return NO_METRIC
    usd, tok, hours = row.get("usd") or 0, row.get("tokens_total") or 0, row.get("hours")
    if not usd and not tok:
        return NO_METRIC
    parts = []
    if usd:
        parts.append(f"${usd:.2f}")
    if tok:
        parts.append(f"{tok / 1000:.0f}k токенов" if tok >= 1000 else f"{tok} токенов")
    if hours:
        parts.append(f"{hours} ч")
    return " · ".join(parts) + (" (оценка)" if row.get("estimate") else "")


def load_state(p):
    try:
        with open(p, encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(p, st):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def pr_index(cache):
    """PR задач по кэшу fetch (metis-0501 [zeus-pr-link]) → {id: [{"repo", "number", "sha", "merged", "branch"}]}: слитые — по
    ветке и «Closes» (и с «часть»: PR всё равно её), открытые — по closes. Карточка задачи берёт отсюда ссылки на GitHub;
    упоминания в журнале дополняет tasks.work_links. branch — ветка PR (headRefName слитого, branch открытого); у PR из
    форка (isCrossRepository, поле cross кэша) и у строки кэша без поля cross branch пуст. PR пачки по ветке batch/<id>
    ищет не индекс, а batch_prs (одно правило для карточки, board-auto и check, metis-0810)."""
    out = {}
    cache = cache if isinstance(cache, dict) else {}
    for key, merged in (("merged", True), ("open_prs", False)):
        rows_by = cache.get(key) if isinstance(cache.get(key), dict) else {}
        for repo, rows in sorted(rows_by.items()):
            for pr in rows if isinstance(rows, list) else []:
                if not isinstance(pr, dict) or not isinstance(pr.get("number"), int) or isinstance(pr.get("number"), bool):
                    continue
                if merged:
                    if any(not isinstance(pr.get(k), (str, type(None))) for k in ("body", "headRefName")):
                        continue
                    ids = closing_ids(pr.get("headRefName"), pr.get("body"))
                else:
                    ids = [i for i in pr.get("closes") or [] if isinstance(i, str)] if isinstance(pr.get("closes"), list) else []
                sha = str(pr.get("oid") or "") if merged else ""
                branch = pr.get("headRefName") if merged else pr.get("branch")
                # ветку для PR пачки (batch/<id>) — только у PR из самого репозитория: форк назовёт ветку как угодно;
                # строка кэша без cross (до metis-0799) — тоже не PR пачки, кэш пересоберёт следующий fetch
                branch = branch if isinstance(branch, str) and pr.get("cross") is False else ""
                for tid in ids:
                    out.setdefault(tid, []).append({"repo": repo, "number": pr["number"],
                                                    "sha": sha if re.fullmatch(r"[0-9a-f]{7,40}", sha) else "",
                                                    "merged": merged, "branch": branch,
                                                    "day": (merged_day(pr.get("mergedAt")) or "") if merged else ""})
    return out


BATCH_HEAD_RE = re.compile(r"batch/([a-z][a-z0-9]{1,11}-\d{3,})")  # ветка пачки batch/<story-id> (tasks.BATCH_BRANCH)


def batch_prs(cache):
    """Одно правило «PR пачки» (metis-0810) — для карточки пачки (tasks.batch_pr), board-auto (boardtext.batch_branch_prs)
    и check (pantheon.batch_outside). PR пачки <id> — строка кэша fetch с веткой ровно batch/<id> (слитый — headRefName,
    открытый — branch), не из форка (cross is False: форк назовёт ветку как угодно, строка без cross — тоже нет), номер —
    целое больше нуля. «часть» в теле PR не мешает ему быть PR пачки (карточка и доска его показывают), но закрывает он
    тогда ничего: closes пуст, «вне состава» по нему нет — как у autoclose. Репозитории направления пачки (own) — выбор
    batch_pick. → {id пачки: [(репозиторий в нижнем регистре, номер, слит, [id задач, которые PR закрывает, кроме самой
    пачки])]}, лучший первым: открытый важнее слитого, из одинаковых — больший номер."""
    out = {}
    cache = cache if isinstance(cache, dict) else {}
    for key, branch_key in (("merged", "headRefName"), ("open_prs", "branch")):
        by_repo = cache.get(key) if isinstance(cache.get(key), dict) else {}
        for repo, rows in by_repo.items():
            for pr in rows if isinstance(rows, list) and isinstance(repo, str) else []:
                if not isinstance(pr, dict) or not isinstance(pr.get(branch_key), str) or pr.get("cross") is not False:
                    continue
                m = BATCH_HEAD_RE.fullmatch(pr[branch_key])
                n = pr.get("number")
                if not m or not isinstance(n, int) or isinstance(n, bool) or n <= 0:
                    continue
                sid = m.group(1)
                if key == "merged":
                    body = pr.get("body") if isinstance(pr.get("body"), str) else ""
                    ids = [] if is_part(body) else closing_ids(pr[branch_key], body)
                else:
                    ids = [i for i in pr.get("closes") or [] if isinstance(i, str)] \
                        if isinstance(pr.get("closes"), list) and not pr.get("part") else []
                out.setdefault(sid, []).append((repo.lower(), n, key == "merged", [i for i in ids if i != sid]))
    for rows in out.values():
        rows.sort(key=lambda r: (not r[2], r[1]), reverse=True)
    return out


def batch_pick(rows, own=None):
    """Лучший PR пачки (строка batch_prs) из репозиториев её направления: own — их имена в нижнем регистре, None — любые.
    Нет такого — None. Тот же выбор — tasks.batch_pr (модуль без autoclose; равенство держит test_board_sync)."""
    return next((r for r in rows or [] if own is None or r[0] in own), None)


def open_pr_tasks(state_file):
    """id задач с открытым PR по последнему проходу; нет состояния — None (неизвестно)."""
    st = load_state(state_file)
    return set(st["open"]) if isinstance(st.get("open"), list) else None


def _path_ok(path):
    """Путь файла открытого PR для кэша (metis-0665): строка до 400 знаков без управляющих знаков и переводов строк —
    чужой PR не вставит строки в вывод `pantheon task overlap`. Та же граница — tasks.overlap_path_ok."""
    return (isinstance(path, str) and 0 < len(path) <= 400
            and not any(ord(c) < 32 or c in "\x7f\x85\u2028\u2029" for c in path))


_GATE = []


def load_gate():
    """Шлюз слияния guard (merge_gate.py) — единственный источник признака «ядро» (metis-0686): рядом в репозитории
    (plugins/guard/hooks) или в клоне маркетплейса. Нет файла или не загрузился — None (вызывающий считает ядром)."""
    if _GATE:
        return _GATE[0]
    import importlib.util
    import sys
    home = os.environ.get("HOME") or ""
    for d in (os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "guard", "hooks"),
              os.path.join(home, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard", "hooks")):
        f = os.path.join(d, "merge_gate.py")
        if not os.path.isfile(f):
            continue
        saved = list(sys.path)
        try:
            sys.path.insert(0, d)
            spec = importlib.util.spec_from_file_location("merge_gate_for_board", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001 — любой сбой загрузки шлюза: не ядро по пути не значит «не ядро»
            continue
        finally:
            sys.path[:] = saved
        _GATE.append(mod)
        return mod
    return None


def base_tip(repo, branch, env=None, gate=None, timeout=90):
    """Живая вершина ветки branch в repo (gh api repos/<repo>/ref heads/<branch>) — SHA коммита или None. Как _base_tip
    шлюза, но gh берётся тем же путём, что у остального прохода (PANTHEON_GH, env прохода), а не из PATH (metis-0711, С1):
    у плана PATH может быть без gh. Формат имени ветки и SHA — константы шлюза."""
    gate = gate or load_gate()
    if gate is None or not isinstance(branch, str) or not gate.BRANCH_RE.fullmatch(branch):
        return None
    got, _ = gh_json(["api", f"repos/{repo}/git/ref/heads/{branch}"], env, timeout=timeout)
    ref = got if isinstance(got, dict) else {}
    obj = ref.get("object") if isinstance(ref.get("object"), dict) else {}
    sha = obj.get("sha")
    if ref.get("ref") != "refs/heads/" + branch or obj.get("type") != "commit" or not isinstance(sha, str) \
            or not gate.SHA_RE.fullmatch(sha.lower()):
        return None
    return sha.lower()


def _norm_path(path):
    p = str(path or "").strip("/").casefold()
    while p.startswith("./"):
        p = p[2:].lstrip("/")
    return p


def sandbox_core(repo, p, env=None, gate=None, left=None):
    """Открытый PR (строка gh pr list с files, headRefOid, baseRefOid, baseRefName) правит pantheon.py → задевает ли он
    сборку окон — тем же sandbox_build_changes, что шлюз guard (metis-0404, 0686). Не получить файлы, шлюз или
    разобрать — True, как у шлюза: ядро. Файла pantheon.py в PR нет — False без запросов. Переименование — ядро, как у
    шлюза (metis-0711, Д2): старое имя в previous_filename или файл с changeType RENAMED/COPIED, у которого старый путь
    gh pr list не отдаёт. left — остаток бюджета прохода, сек (fetch): каждый вызов gh ждёт не больше min(90, left()),
    остаток не больше секунды — ядро (Д1)."""
    gate = gate or load_gate()
    if gate is None:
        return True
    # файлы сборки и запуска окон шлюза (metis-0552: и sessions.py) — у старого шлюза только pantheon.py
    wants = list(getattr(gate, "BUILD_ROOTS", None) or [gate.SANDBOX_BUILD_FILE])
    files = [f for f in p.get("files") or [] if isinstance(f, dict)]
    for f in files:
        moved = str(f.get("changeType") or "").upper() in ("RENAMED", "COPIED") or f.get("previous_filename") is not None
        if moved and (f.get("previous_filename") is None
                      or {_norm_path(f.get("path")), _norm_path(f.get("previous_filename"))} & set(wants)):
            return True  # старый путь неизвестен или это файл сборки: переименование — ядро
    paths = [_norm_path(f.get("path")) for f in files]
    wants = [w for w in wants if w in paths]
    if not wants:
        return False
    if not all(any(f.get("path") == w for f in files) for w in wants):
        return True  # другой регистр, как у шлюза
    head, base = (str(p.get(k) or "").lower() for k in ("headRefOid", "baseRefOid"))
    sha_re = re.compile(r"[0-9a-f]{40}")
    if not sha_re.fullmatch(head) or not sha_re.fullmatch(base):
        return True

    def room():
        return 90 if left is None else min(90, left())

    def text(args):
        to = room()
        return gh_text(args, env, timeout=to) if to > 1 else None

    mb = (text(["api", f"repos/{repo}/compare/{base}...{head}", "--jq", ".merge_base_commit.sha"]) or "").strip()
    if room() <= 1:
        return True
    tip = base_tip(repo, str(p.get("baseRefName") or ""), env, gate, timeout=room())
    if not sha_re.fullmatch(mb) or tip is None:
        return True

    def blob(ref, want):
        return text(["api", f"repos/{repo}/contents/{want}?ref={ref}", "-H", "Accept: application/vnd.github.raw"])

    for want in wants:
        old, new = blob(mb, want), blob(head, want)
        tips = [blob(r, want) for r in dict.fromkeys((base, tip)) if r != mb]
        if old is None or new is None or any(x is None for x in tips):
            return True
        kw = {"path": want} if hasattr(gate, "BUILD_ROOTS") else {}
        got = gate.sandbox_build_changes(old, new, *tips, **kw)
        if got is None or got:
            return True
    return False


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def fetch(cache_file, state_file, t, repos, env=None, budget=FETCH_BUDGET, core=None, sandbox=None, repo_budget=REPO_BUDGET):
    """Сетевой проход: gh по репозиториям → кэш cache_file. Только он зовёт gh; лёгкий тик (run) читает кэш.
    budget — секунд на весь проход, repo_budget — на один репозиторий (metis-0808: один завислый репозиторий не съедает
    весь проход): на каждый вызов gh остаётся не больше, чем осталось; не успел — ошибка по репозиторию. Порядок —
    от давнего успеха к свежему: репозиторий, которому не хватило времени, в следующий раз идёт первым.
    Ошибка gh по репозиторию (401, TLS, EOF, время) не стирает его прошлые строки (merged, open, open_prs): они остаются
    в кэше, а stale[repo] — время последнего успешного ответа по нему (repo_ok); читатели доски пишут «данные от HH:MM».
    core — путь → ядро ли (merge.is_core): открытые PR в кэше (open_prs) несут пометку «задето ядро» для автоблока
    board.md (metis-0397); sandbox — (repo, строка PR) → задевает ли PR сборку окон в pantheon.py (sandbox_core, metis-0686):
    зовётся, только если по путям не ядро. → ошибки по репозиториям {repo: текст}."""
    end = time.monotonic() + budget
    prev = load_state(cache_file)
    prev_ok = prev.get("repo_ok") if isinstance(prev.get("repo_ok"), dict) else {}

    def prev_at(r):
        """Время последнего успешного ответа gh по репозиторию; кэш до metis-0808 — время всего прохода, если строки были; иначе 0."""
        if r in prev_ok:
            return _num(prev_ok[r])
        had = any(isinstance(prev.get(k), dict) and isinstance(prev[k].get(r), list) for k in ("merged", "open_prs"))
        return _num(prev.get("fetched")) if had else 0

    def left():
        return end - time.monotonic()

    def keep_prev(repo, part, errors_text):
        """Прошлые строки репозитория part ('all' | 'open') — в новый кэш; → есть ли что сохранять."""
        for key, dst in (("merged", merged), ("open", opened), ("open_prs", open_prs)):
            if key == "merged" and part == "open":
                continue
            old = prev.get(key) if isinstance(prev.get(key), dict) else {}
            if isinstance(old.get(repo), list):
                dst[repo] = old[repo]
        errors[repo] = errors_text
        stale[repo] = prev_at(repo)
        if stale[repo] > 0:  # кэш до metis-0808 без repo_ok: время фиксируем, чтобы следующий сбой не сдвинул его к fetched
            repo_ok.setdefault(repo, stale[repo])

    done = load_state(state_file).get("done")
    done = done if isinstance(done, dict) else {}
    merged, opened, open_prs, errors, stale = {}, {}, {}, {}, {}
    repo_ok = {r: v for r, v in prev_ok.items() if r in repos}
    for repo in sorted(set(repos), key=lambda r: (prev_at(r), r)):
        rend = min(end, time.monotonic() + repo_budget)

        def rleft(rend=rend):
            return rend - time.monotonic()
        if rleft() <= 1:
            keep_prev(repo, "all", "не хватило времени прохода")
            continue
        data, err = gh_json(["pr", "list", "--repo", repo, "--state", "merged", "--limit", str(LIMIT), "--json",
                             "number,headRefName,headRefOid,baseRefName,body,mergedAt,mergeCommit,files,changedFiles,"
                             "isCrossRepository"],
                            env, timeout=min(90, rleft()))
        if err or not isinstance(data, list):
            keep_prev(repo, "all", err or "ответ gh — не список")
            continue
        rows = []
        for pr in data:
            if not isinstance(pr, dict):
                continue
            row = {"number": pr.get("number"), "headRefName": pr.get("headRefName") or "", "body": (pr.get("body") or "")[:4000],
                   "mergedAt": pr.get("mergedAt"), "oid": ((pr.get("mergeCommit") or {}).get("oid") or ""),
                   "cross": pr.get("isCrossRepository") is not False}  # PR из форка (или gh не сказал) — не PR пачки
            # path null у файла слитого PR — пропустить, а не упасть на endswith (metis-0674)
            files = [f["path"] for f in pr.get("files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str)]
            head = str(pr.get("headRefOid") or "").lower()  # metis-1004: head слияния и base — для отметки пунктов
            row.update(head=head if re.fullmatch(r"[0-9a-f]{40}", head) else "",
                       base=pr.get("baseRefName") if isinstance(pr.get("baseRefName"), str) else "",
                       core=merged_core(pr.get("files"), core, pr.get("changedFiles")))
            if f"{repo}#{pr.get('number')}" not in done and any(x.endswith(".claude-plugin/plugin.json") for x in files):
                if rleft() <= 1:
                    errors[f"{repo}#{pr.get('number')}"] = "не хватило времени на diff"
                    continue  # без версии PR не отдаём: закрытие подождёт следующего прохода
                row["versions"] = plugin_versions(gh_text(["pr", "diff", str(pr.get("number")), "--repo", repo], env,
                                                          timeout=min(90, rleft())))
            rows.append(row)
        merged[repo] = rows
        o, oerr = (gh_json(["pr", "list", "--repo", repo, "--state", "open", "--limit", str(LIMIT), "--json",
                            "number,headRefName,headRefOid,baseRefOid,baseRefName,body,files,isCrossRepository"], env,
                           timeout=min(90, rleft())) if rleft() > 1 else (None, "не хватило времени прохода"))
        if isinstance(o, list):
            opened[repo] = sorted({i for p in o if isinstance(p, dict) for i in find_ids(p.get("headRefName"), p.get("body"))})
            # branch и files — сверке пересечения `pantheon task overlap` (metis-0665), когда gh в окне не отвечает
            open_prs[repo] = [{"number": p.get("number"), "head": str(p.get("headRefOid") or "")[:40],
                               "branch": str(p.get("headRefName") or "")[:200],
                               "cross": p.get("isCrossRepository") is not False,
                               "files": [f.get("path") for f in p.get("files") or []
                                         if isinstance(f, dict) and _path_ok(f.get("path"))],
                               "ids": find_ids(p.get("headRefName"), p.get("body")),
                               "closes": closing_ids(p.get("headRefName"), p.get("body")),
                               "part": is_part(p.get("body")),
                               "core": open_core(repo, p, core, sandbox, rleft)}
                              for p in o if isinstance(p, dict) and isinstance(p.get("number"), int)]
            repo_ok[repo] = t
        else:  # слитые свежие, открытые — прошлые: без этого «Открытых PR нет» при открытых PR
            keep_prev(repo, "open", "открытые PR: " + (oerr or "ответ gh — не список"))
    old_heads = former_heads(prev, open_prs)
    save_state(cache_file, {"fetched": t, "merged": merged, "open": opened, "open_prs": open_prs, "errors": errors,
                            "old_heads": old_heads, "repo_ok": repo_ok, "stale": stale})
    return errors


OLD_HEADS_KEEP = 200   # бывших head на репозиторий в кэше: больше — самые старые уходят


def former_heads(prev, open_prs):
    """{repo: {sha: номер PR}} — бывшие head ещё открытых PR (metis-0726): прошлый кэш (его old_heads и head его
    open_prs) минус нынешние head. По ним `pantheon outside` снимает заявку test на коммит, который уже не head своего
    PR. PR закрыт или слит — его бывшие head уходят; репозиторий, про который gh не ответил (нет в open_prs), держит
    прошлые. Порядок — от старых к новым, не больше OLD_HEADS_KEEP на репозиторий."""
    prev = prev if isinstance(prev, dict) else {}
    p_old = prev.get("old_heads") if isinstance(prev.get("old_heads"), dict) else {}
    p_open = prev.get("open_prs") if isinstance(prev.get("open_prs"), dict) else {}
    out = {r: v for r, v in p_old.items() if r not in open_prs and isinstance(v, dict)}
    for repo, prs in open_prs.items():
        cur = {p["number"]: p.get("head") for p in prs}
        keep = {}
        seen = list((p_old.get(repo) or {}).items()) if isinstance(p_old.get(repo), dict) else []
        seen += [(p.get("head"), p.get("number")) for p in p_open.get(repo) or [] if isinstance(p, dict)]
        for sha, num in seen:
            if isinstance(sha, str) and sha and num in cur and cur[num] != sha:
                keep.pop(sha, None)
                keep[sha] = num
        if keep:
            out[repo] = dict(list(keep.items())[-OLD_HEADS_KEEP:])
    return out


FILES_CAP = 100   # gh pr list отдаёт не больше 100 файлов PR (files(first: 100) в GraphQL)


def merged_core(files, core, changed=None):
    """Задето ли ядро слитым PR (metis-1004): files — поле files строки gh pr list (path, changeType), changed — его
    changedFiles. По путям (core) или правкой файлов сборки и запуска окон шлюза (BUILD_ROOTS: pantheon.py, sessions.py)
    — сборку окон в них без сети не сверить, поэтому как ядро.
    У переименования и копии — оба пути (previous_filename), а без старого пути (gh pr list его не отдаёт) — ядро,
    как у шлюза: старое имя могло быть ядром. Список неполон — файлов changed больше полученных, а без changed
    получено FILES_CAP и больше (обрезка gh) — ядро; файл без пути — тоже. core нет или шлюз не загрузился — ядро
    (строже: в счёт только «принять» на Opus)."""
    gate = load_gate()
    if core is None or gate is None or not isinstance(files, list):
        return True
    rows = [f for f in files if isinstance(f, dict)]
    known = isinstance(changed, int) and not isinstance(changed, bool)
    if len(rows) != len(files) or (changed != len(rows) if known else len(rows) >= FILES_CAP):
        return True
    paths = []
    for f in rows:
        old = f.get("previous_filename")
        if str(f.get("changeType") or "").upper() in ("RENAMED", "COPIED") and old is None:
            return True
        paths += [f.get("path")] + ([old] if old is not None else [])
    if not all(isinstance(p, str) and p for p in paths):
        return True
    wants = set(getattr(gate, "BUILD_ROOTS", None) or [gate.SANDBOX_BUILD_FILE])  # как sandbox_core (metis-0552)
    return any(core(p) or _norm_path(p) in wants for p in paths)


def open_core(repo, p, core, sandbox, left=None):
    """Задето ли ядро открытым PR: по путям (core) или сборкой окон в pantheon.py (sandbox)."""
    if core and any(core(f.get("path") or "") for f in p.get("files") or [] if isinstance(f, dict)):
        return True
    if not sandbox:
        return False
    return bool(sandbox(repo, p) if left is None else sandbox(repo, p, left))


def journal_has(path, T, needle):
    return needle in (T.read(path)[1] or "")


def run(pantheon, state_file, cache_file, t, repo_dirs, T, actual_for=None, accepted=None):
    """Один проход по кэшу fetch, без сети. repo_dirs — {"владелец/репозиторий": {направления}}: задачу закрывает
    только PR из репозитория её направления. T — модуль tasks.py, actual_for(tid) → строка actual или None,
    accepted(repo, строка слитого PR) → {id: {номер пункта: хеш}} принятых argus пунктов (metis-1004) или None.
    → (строки журнала, ошибки). Тот же кэш второй раз не читается."""
    cache = load_state(cache_file)
    st = load_state(state_file)
    if cache.get("fetched") is None or st.get("seen") == cache.get("fetched"):
        return [], {}
    done = st.get("done") if isinstance(st.get("done"), dict) else {}
    since = float(st["since"]) if st.get("since") is not None else t - FIRST_LOOKBACK
    log, open_ids, finished = [], set(), False
    errors = dict(cache.get("errors") or {})
    merged = cache.get("merged") if isinstance(cache.get("merged"), dict) else {}
    try:
        for repo in sorted(repo_dirs):
            for pr in sorted(merged.get(repo) or [], key=lambda p: str(p.get("mergedAt") or "")):
                key = f"{repo}#{pr.get('number')}"
                ts = merged_ts(pr.get("mergedAt"))
                if key in done or ts is None or ts < since:
                    continue
                if close_pr(pantheon, t, repo, pr, repo_dirs[repo], T, actual_for, log, errors, accepted):
                    done[key] = T.now_iso(t)
            open_ids.update((cache.get("open") or {}).get(repo) or [])
        for repo in sorted(repo_dirs):
            for pr in (cache.get("open_prs") or {}).get(repo) or []:
                if isinstance(pr, dict):
                    review_pr(pantheon, t, repo, pr, repo_dirs[repo], T, log, errors)
        close_checked(pantheon, t, merged, repo_dirs, T, actual_for, log, errors, open_ids)
        finished = True
    finally:  # сбой посреди прохода (не только ValueError): отметки уже обработанных PR не теряем, кэш прочтём заново
        keep = dict(sorted(done.items(), key=lambda kv: kv[1])[-KEEP:])
        st.update(done=keep, since=since, open=sorted(open_ids) if not errors else (st.get("open") or sorted(open_ids)))
        if finished:
            st["seen"] = cache.get("fetched")
        save_state(state_file, st)
    return log, errors


REVIEW_FROM = ("todo", "doing", "waiting")   # открытый PR с Closes ставит review из этих статусов
REVIEW_FROM_MENTION = ("doing", "waiting")   # PR без Closes — только начатую работу: todo по упоминанию не трогаем
BRANCH_NUM_RE = re.compile(r"(?<!\d)\d{3,}(?!\d)")   # номер задачи в имени ветки без префикса: landing-claims-0275


def branch_named(branch, ids):
    """PR без Closes (metis-0615, argus #341 Б1): из id тела — только те, чей номер есть в имени ветки (BA #38: ветка
    …-0184 и athena-0184 в теле). Простое упоминание («после metis-0201», «зависит от athena-0274» в PR ветки …-0275)
    задачу не трогает. Номера сравниваются числом: 0184 и 184 — один."""
    nums = {int(x) for x in BRANCH_NUM_RE.findall(branch)} if isinstance(branch, str) else set()
    return [i for i in ids if isinstance(i, str) and (m := re.search(r"-(\d+)$", i)) and int(m.group(1)) in nums]


def review_pr(pantheon, t, repo, pr, dirs, T, log, errors):
    """Открытый PR, который закрывает задачу (id в ветке или «Closes» в теле, без «часть»), → задача todo/doing/waiting
    его направления в review (metis-0397, п. 7). PR без Closes и без id в ветке (closes пуст) — задачи из тела (ids),
    чей номер есть в имени ветки (branch_named), и только doing/waiting (metis-0615, случай athena-0184 и PR BA #38: задача
    в waiting с открытым PR висела мимо review); простое упоминание в теле не в счёт. waiting владельца (waiting_on human,
    колонка «Нужен ответ») не трогаем: вопрос не теряется; прежний waiting_on — в строке журнала (task_set его стирает).
    Строка REVIEW_MARK в журнале: этим PR уже ставили — второй раз не трогаем (владелец вернул задачу —
    тревога у прохода доски, lib/boardstatus.py)."""
    n = pr.get("number")
    if not isinstance(n, int) or pr.get("part") or not isinstance(pr.get("closes"), list):
        return
    ids, allowed = [i for i in pr["closes"] if isinstance(i, str)], REVIEW_FROM
    if not ids:
        ids = branch_named(pr.get("branch"), pr["ids"]) if isinstance(pr.get("ids"), list) else []
        allowed = REVIEW_FROM_MENTION
    if not ids:
        return
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    note = f"PR #{n} ({repo}) {REVIEW_MARK}"
    for tid in ids:
        path, head, _ = tasks.get(tid, ("", {}, ""))
        if head.get("type") != "task" or head.get("direction") not in dirs or head.get("status") not in allowed:
            continue
        if head.get("status") == "waiting" and head.get("waiting_on") == "human":
            continue
        if journal_has(path, T, note):
            continue
        try:
            was = head.get("waiting_on") if head.get("status") == "waiting" else None
            T.task_set(pantheon, t, tid, {"status": "review"}, actor="плановый проход",
                       note=note + (f"; был waiting_on {was}" if was else ""))
            log.append(f"{tid}: review — открыт PR #{n} ({repo})")
        except ValueError as e:
            errors[f"{repo}#{n}"] = f"{tid}: {e}"


def tick_accepted(pantheon, t, repo, pr, tid, task, T, accepted, log):
    """Пункты «Готово, когда» задачи, которые argus принял на head слияния (metis-1004): accepted → {номер: хеш},
    T.criteria_tick отмечает только пункты с тем же хешем текста. → (путь, шапка, тело) задачи после отметки."""
    want = (accepted(repo, pr) or {}).get(tid) if accepted else None
    if not want:
        return task
    head = str(pr.get("head") or "")[:12]
    got = T.criteria_tick(pantheon, t, tid, want, "плановый проход",
                          f"PR #{pr.get('number')} ({repo}) слит: argus принял пункты на head {head}")
    if not got:
        return task
    log.append(f"{tid}: PR #{pr.get('number')} слит — отмечены пункты {', '.join(map(str, got))} по приёмке argus")
    h, b = T.read(task[0])
    return (task[0], h, b) if h else task


# metis-1193: пункт задачи X, сделанный PR другой задачи (или проверяемый фактом после слияния — его принимают на
# следующем PR), argus принимает тем же --criteria на этом PR, а тело PR называет его: «пункт 3 metis-1050», «пункты
# 1, 2 и 4 metis-1117», «пункты 1, 2, и 4 metis-1117», «пункт 3 задачи metis-1050». Не «часть metis-X»: «часть» в теле оставляет открытыми и задачи из Closes (is_part).
ITEM_RE = re.compile(r"(?<!\w)пункт(?:ы|ов|ах)?\s+(\d{1,3}(?:\s*(?:,\s*и|,|и)\s*\d{1,3})*)\s+(?:задачи\s+)?("
                     + ID_RE.pattern + r")", re.I)


def named_items(body):
    """Пункты чужих задач, названные в теле PR (metis-1193) → {id: {номера}}."""
    out = {}
    for m in ITEM_RE.finditer(body or ""):
        out.setdefault(m.group(2), set()).update(int(x) for x in re.findall(r"\d+", m.group(1)))
    return out


def tick_named(pantheon, t, repo, pr, dirs, skip, T, accepted, log, errors):
    """Пункты задач вне Closes (metis-1193): отмечаются только те, что и названы в теле PR (named_items), и приняты
    argus на head слияния (accepted, как в tick_accepted) — с той же сверкой хеша в T.criteria_tick. Одно название без
    приёмки argus не отмечает ничего: тело PR пишет роль, запись приёмки — только хук guard. Задача — своего
    направления, не done/dropped. → False при сбое отметки (PR повторим)."""
    named = {tid: nums for tid, nums in named_items(pr.get("body")).items() if tid not in skip}
    if not named or not accepted:
        return True
    ok, n = True, pr.get("number")
    try:
        got_all = accepted(repo, pr) or {}
    except Exception as e:  # noqa: BLE001 — журнал шлюза не прочитан: PR повторим, тревога
        errors[f"{repo}#{n}"] = f"приёмка argus для пунктов {', '.join(sorted(named))}: {type(e).__name__}: {e}"
        return False
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    for tid, nums in sorted(named.items()):
        head = tasks.get(tid, ("", {}, ""))[1]
        want = {k: h for k, h in (got_all.get(tid) or {}).items() if k in nums}
        if not want or head.get("type") != "task" or head.get("direction") not in dirs \
                or head.get("status") not in ("todo", "doing", "waiting", "review"):
            continue
        try:
            got = T.criteria_tick(pantheon, t, tid, want, "плановый проход",
                                  f"PR #{n} ({repo}) слит: argus принял пункты на head {str(pr.get('head') or '')[:12]}"
                                  " (пункты названы в теле PR другой задачи)")
        except Exception as e:  # noqa: BLE001 — сбой отметки не роняет проход: PR повторим, тревога
            ok = False
            errors[f"{repo}#{n}"] = f"{tid}: отметка пунктов по приёмке argus: {type(e).__name__}: {e}"
            continue
        if got:
            log.append(f"{tid}: PR #{n} слит — отмечены пункты {', '.join(map(str, got))} по приёмке argus (не Closes)")
    return ok


def close_pr(pantheon, t, repo, pr, dirs, T, actual_for, log, errors, accepted=None):
    """Слитый PR → закрытие его задач. → True, если PR обработан целиком (можно отметить), False — повторить.
    accepted — как в run: до подсчёта неотмеченных пункты, принятые argus на head слияния, отмечаются (metis-1004)."""
    n = pr.get("number")
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    ids = [i for i in closing_ids(pr.get("headRefName"), pr.get("body")) if i in tasks
           and tasks[i][1].get("type") == "task" and tasks[i][1].get("direction") in dirs
           and tasks[i][1].get("status") in ("todo", "doing", "waiting", "review")]
    part = is_part(pr.get("body"))
    ok = True
    for tid in ids:
        head = tasks[tid][1]
        try:
            if part:
                note = f"PR #{n} ({repo}) слит, в теле «часть» — задача не закрыта"
                if not journal_has(tasks[tid][0], T, note):
                    T.task_set(pantheon, t, tid, {}, actor="плановый проход", note=note)
                    log.append(f"{tid}: PR #{n} слит, «часть» — не закрыта")
                continue
            try:
                tasks[tid] = tick_accepted(pantheon, t, repo, pr, tid, tasks[tid], T, accepted, log)
            except Exception as e:  # noqa: BLE001 — сбой отметки не роняет весь проход: эту задачу повторим, тревога
                ok = False
                errors[f"{repo}#{n}"] = f"{tid}: отметка пунктов по приёмке argus: {type(e).__name__}: {e}"
                continue
            head = tasks[tid][1]
            left = T.unchecked_criteria(head, tasks[tid][2])
            if left:  # хвосты «Готово, когда» не теряем (metis-0503): слитый PR без «часть» — на проверку, не в done
                nums = ", ".join(map(str, T.unchecked_numbers(head, tasks[tid][2])))
                note = f"PR #{n} ({repo}) слит, неотмечено {left} (пункты {nums})"
                if head.get("status") != "review" or not journal_has(tasks[tid][0], T, note):
                    T.task_set(pantheon, t, tid, {"status": "review"}, actor="плановый проход", note=note)
                    log.append(f"{tid}: PR #{n} слит, неотмечено {left} — review")
                continue
            if close_done(pantheon, t, tid, tasks[tid], repo, pr, T, actual_for):
                log.append(f"{tid}: закрыта по слиянию PR #{n} ({repo})")
        except ValueError as e:  # задача изменилась или шапка не прошла проверку — PR не отмечаем, повторим
            ok = False
            errors[f"{repo}#{n}"] = f"{tid}: {e}"
    return tick_named(pantheon, t, repo, pr, dirs, set(ids), T, accepted, log, errors) and ok


def close_done(pantheon, t, tid, task, repo, pr, T, actual_for, why=""):
    """Задача → done по слитому PR: closed — день слияния, release, actual, строка CLOSED_BY_MERGE в журнал.
    → False, если этим PR её уже закрывали (владелец вернул в работу — второй раз не трогаем)."""
    path, head, _ = task
    mark = f"PR #{pr.get('number')} ({repo}) →"
    if journal_has(path, T, T.CLOSED_BY_MERGE + " " + mark):
        return False
    day = merged_day(pr.get("mergedAt")) or T.now_iso(t)[:10]
    changes = {"status": "done", "closed": day}
    if not head.get("release"):
        changes["release"] = release_text(repo, pr)
    T.task_set(pantheon, t, tid, changes, actor="плановый проход",
               note=f"{T.CLOSED_BY_MERGE} {mark} {(pr.get('oid') or '')[:7]}, closed {day}{why}")
    if not head.get("actual"):
        val = None
        try:
            val = actual_for(tid) if actual_for else None
        except Exception:  # noqa: BLE001 — учёт не должен мешать закрытию
            val = None
        T.task_set(pantheon, t, tid, {"actual": val or NO_METRIC}, actor="плановый проход")
    return True


# PR в журнале задачи (metis-0583): «PR #163», «PR 163», «…/pull/163», «owner/repo#163»
JOURNAL_PR_RE = re.compile(r"(?:\bPR\s*#?|/pull/|(?<=[\w.-])#)(\d{1,6})\b")
CHECKED_WHY = ", все пункты «Готово, когда» отмечены"


def close_checked(pantheon, t, merged, repo_dirs, T, actual_for, log, errors, open_ids=()):
    """Задача doing/review, у которой все пункты «Готово, когда» отмечены (хотя бы один), а PR из её журнала слит
    (кэш fetch, репозиторий её направления), → done той же записью, что и по Closes (metis-0583). PR без Closes и под
    общей веткой (simplify-*) иначе оставляли задачу висеть в doing после слияния. Без пунктов «Готово, когда» не
    закрываем: «всё отмечено» нечем доказать; задачу с открытым PR (open_ids) — тоже: работа ещё идёт. Из нескольких
    слитых PR журнала — последний по времени слияния; «часть» в его теле — задача остаётся открытой."""
    by_num = {}
    for repo, rows in sorted(merged.items()):
        if repo not in repo_dirs:
            continue
        for pr in rows if isinstance(rows, list) else []:
            if isinstance(pr, dict) and isinstance(pr.get("number"), int) and merged_ts(pr.get("mergedAt")) is not None:
                by_num.setdefault(pr["number"], []).append((repo, pr))
    if not by_num:
        return
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    for tid, (path, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") not in ("doing", "review") or tid in open_ids:
            continue
        crit = T.done_criteria(body)
        if not crit or not all(ok for ok, _ in crit):
            continue
        nums = {int(n) for x in T._journal(body) for n in JOURNAL_PR_RE.findall(x[2])}
        found = [(merged_ts(pr.get("mergedAt")), repo, pr) for n in nums for repo, pr in by_num.get(n, [])
                 if head.get("direction") in repo_dirs[repo]]
        if not found:
            continue
        _, repo, pr = max(found, key=lambda x: (x[0], x[1]))
        try:
            if is_part(pr.get("body")):  # «часть» в теле: PR делает не всю задачу — как в close_pr, не закрываем
                note = f"PR #{pr['number']} ({repo}) слит, в теле «часть» — задача не закрыта"
                if not journal_has(path, T, note):
                    T.task_set(pantheon, t, tid, {}, actor="плановый проход", note=note)
                    log.append(f"{tid}: PR #{pr['number']} слит, «часть» — не закрыта")
                continue
            if close_done(pantheon, t, tid, (path, head, body), repo, pr, T, actual_for, CHECKED_WHY):
                log.append(f"{tid}: закрыта — все пункты отмечены, PR #{pr['number']} ({repo}) слит")
        except ValueError as e:
            errors[f"{repo}#{pr['number']}"] = f"{tid}: {e}"
