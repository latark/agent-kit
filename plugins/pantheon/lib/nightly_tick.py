"""Ночной полный набор тестов на main — итог из GitHub Actions (metis-1115, решение владельца 13.11: на Mac тесты
agent-kit не идут; до этого набор гонял сам плановый проход, metis-1050). На PR — затронутые и полный набор в CI, а
раз в сутки workflow tests (.github/workflows/tests.yml) по расписанию гонит полный набор частями full-shard на
macos-15 на main. Плановый проход набор не запускает: он только читает итог запуска через gh и при красном заводит
задачу и тревогу. Слияний это не держит.

Тик основного Mac зовёт tick(t). Проверка — не чаще раза в CHECK_EVERY (30 мин), в любое время суток. Репозиторий —
agent-kit из [merge_repos] (merge.allowed_repos). Запуски — `gh api repos/<repo>/actions/workflows/tests.yml/runs
?branch=main`, в счёт идут только события schedule и workflow_dispatch (на PR — свой итог, его держит шлюз). Берётся
самый новый завершённый запуск; уже разобранный (id и номер попытки — в STATE/nightly-tick.json) второй раз не
разбирается. Идущий запуск — ждать, локально ничего не гонять.

Разбор запуска: job частей full-shard (`full-shard (K/N)`) и их логи (`gh api …/actions/jobs/<id>/logs`, строки с
меткой времени GitHub в начале — она срезается). Упавшие файлы — строки раннера `FAIL <метка>`; файлы карантина
(run-tests.py QUARANTINE) — строки `карантин <метка>`: раннер с ними выходит с кодом 0, задачи они не дают (у каждого
она уже есть), но называются в строке журнала и в тревоге — падения в карантине видны.
- success — зелёный: тревога снята; но только если все части full-shard стартовали, логи прочитаны и в каждом есть
  строка «итого» раннера, иначе — «итога нет» (Д2 argus #430).
- failure — на каждый упавший файл не из карантина задача «Ночной полный набор: <метка> красный на main», если
  открытой с тем же заголовком нет; тревога alert_once без critical с именами файлов. Красный без строк FAIL (части не
  стартовали — лимит или сбой Actions, таймаут, сбой установки, лог не прочитан) — тревога с причиной и ссылкой.
- cancelled, skipped и прочее — только строка журнала, тревога не меняется: итога нет.
Свежесть: запуска на main с итогом (success с итогом частей или failure) нет дольше STALE (48 ч; отсчёт — от
created_at последнего такого запуска, cancelled и прочие без итога его не сбрасывают, Д1 argus #430) — отдельная тревога STALE_KEY (расписание выключено:
GitHub гасит schedule публичного репозитория после 60 дней без активности; Actions недоступны; gh не отвечает).
Свежий итог её снимает.

Итог — строка `nightly-tick:` в logs/tick.log, когда разобран новый запуск или сменилось состояние (ошибка gh,
устаревание). PANTHEON_DRYRUN=1 (тесты тика) — ничего не делает.
"""
import os
import re
import subprocess
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

CHECK_EVERY = 30 * 60
STALE = 48 * 3600
GH_TIMEOUT = 90
WORKFLOW = "tests.yml"
EVENTS = ("schedule", "workflow_dispatch")
SHARD = "full-shard ("
REPO_NAMES = ("agent-kit",)
DIRECTION = "metis-pantheon"
ALERT_KEY = "nightly-tick"
STALE_KEY = "nightly-tick-stale"
WHO = "pantheon-tick"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
STAMP_RE = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?", re.M)
FAIL_RE = re.compile(r"^FAIL ([\w.-]+/test_[\w.-]+\.py) ·", re.M)
QUAR_RE = re.compile(r"^карантин ([\w.-]+/test_[\w.-]+\.py) ·", re.M)
TOTAL_RE = re.compile(r"^итого: .*$", re.M)
TITLE = "Ночной полный набор: {label} красный на main"
CLOSED = ("done", "dropped", "cancelled")


def set_core(mod):
    global P
    P = mod


def state_file():
    return P.path("nightly-tick.json")


def repos():
    return sorted(r for r in P.merge_mod().allowed_repos() if r.rsplit("/", 1)[-1] in REPO_NAMES)


def parse(out):
    """Вывод раннера (лог job GitHub или голый) → (упавшие метки, метки карантина, [строки итога])."""
    out = STAMP_RE.sub("", ANSI_RE.sub("", (out or "").replace("\ufeff", "").replace("\r\n", "\n")))
    return (sorted(set(FAIL_RE.findall(out))), sorted(set(QUAR_RE.findall(out))),
            [x.strip() for x in TOTAL_RE.findall(out)])


# --- gh ----------------------------------------------------------------------------------------------------------

def gh_api(endpoint):
    """GET REST через gh → (данные JSON, None) или (None, причина). Тесты подменяют."""
    return P.release_tick_mod().gh_api(endpoint)


def gh_text(endpoint):
    """GET REST через gh, ответ — текст (лог job) → (текст, None) или (None, причина). Тесты подменяют."""
    M = P.merge_mod()
    try:
        # --allow-escape-sequences: в логах job GitHub есть ANSI-коды (`\x1b[36;1m`), без флага gh 2.103 отказывает с
        # кодом 1 «the response contains terminal escape sequences» (Б1 argus #430); коды снимает parse()
        r = subprocess.run([M.gh_path(), "api", "--allow-escape-sequences", endpoint], capture_output=True, text=True, timeout=GH_TIMEOUT,
                           env=M.gh_env())
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"gh не запустился: {type(e).__name__}"
    if r.returncode != 0:
        return None, f"gh api {endpoint}: {(r.stderr or r.stdout).strip()[:160]}"
    return r.stdout, None


def _ts(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def main_runs(repo):
    """Запуски tests.yml на main по расписанию и вручную, новые первыми → ([run], None) или (None, причина)."""
    data, err = gh_api(f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=30")
    if err:
        return None, err
    try:
        runs = [r for r in data["workflow_runs"] if r.get("event") in EVENTS and r.get("head_branch") == "main"]
    except (TypeError, KeyError):
        return None, "ответ gh о запусках не разобран"
    return sorted(runs, key=lambda r: _ts(r.get("created_at")) or 0, reverse=True), None


def run_key(run):
    return f"{run.get('id')}/{run.get('run_attempt') or 1}"


def run_result(repo, run):
    """Запуск → итог: {repo, sha, night, url, conclusion, fails, quarantine, total, why}. why — почему итог неполон."""
    res = {"repo": repo, "sha": str(run.get("head_sha") or ""), "night": str(run.get("created_at") or "")[:10],
           "url": run.get("html_url") or "", "conclusion": run.get("conclusion"), "fails": [], "quarantine": [],
           "total": [], "why": None}
    data, err = gh_api(f"repos/{repo}/actions/runs/{run.get('id')}/jobs?per_page=100")
    if err:
        res["why"] = f"job запуска не прочитать: {err}"
        return res
    try:
        jobs = [j for j in data["jobs"] if str(j.get("name") or "").startswith(SHARD)]
    except (TypeError, KeyError):
        res["why"] = "ответ gh о job не разобран"
        return res
    if not jobs:
        res["why"] = "частей full-shard в запуске нет"
        return res
    unstarted = [j["name"] for j in jobs if not j.get("steps")]
    if unstarted:
        res["why"] = (f"части не стартовали ({', '.join(sorted(unstarted))}): Actions не запустились — лимит минут или "
                      "сбой GitHub")
    fails, quar, total, lost, untotal = set(), set(), [], [], []
    for j in jobs:
        if not j.get("steps"):
            continue
        text, err = gh_text(f"repos/{repo}/actions/jobs/{j.get('id')}/logs")
        if err:
            lost.append(f"{j.get('name')}: {err}")
            continue
        f, q, tot = parse(text)
        fails.update(f)
        quar.update(q)
        total += tot
        if not tot:
            untotal.append(str(j.get("name")))
    if lost and not res["why"]:
        res["why"] = "лог части не прочитать — " + "; ".join(lost)
    if untotal and not res["why"]:
        res["why"] = f"в логе части нет строки «итого» ({', '.join(sorted(untotal))}): раннер не дошёл до конца"
    res.update(fails=sorted(fails), quarantine=sorted(quar), total=total)
    return res


# --- итог --------------------------------------------------------------------------------------------------------

def _open_titles():
    return {head.get("title"): tid for tid, (_, head, _) in P.tasks_mod().load_tasks(P.PANTHEON).items()
            if head.get("status") not in CLOSED}


def file_tasks(res):
    """Задача на каждый упавший файл не из карантина, если открытой с тем же заголовком нет → [id]."""
    if not res.get("fails"):
        return []
    try:
        have = _open_titles()
    except Exception:  # noqa: BLE001 — список задач не прочитать: лучше дубль, чем потерять красный файл
        have = {}
    total = " | ".join(res.get("total") or []) or "нет строки итога"
    out = []
    for label in res["fails"]:
        title = TITLE.format(label=label)
        if title in have:
            out.append(have[title])
            continue
        try:
            tid, _ = P.tasks_mod().task_new(
                P.PANTHEON, P.now(), DIRECTION, title, owner=DIRECTION, actor="плановый проход", priority=1,
                text=(f"Ночной полный набор в GitHub Actions ({res.get('night')}) на {res.get('repo')} main "
                      f"{str(res.get('sha'))[:12]} упал в файле {label}. Итог частей: {total}. Запуск и логи — "
                      f"{res.get('url')}. Слияний это не держит (metis-1050); падает только на раннере и зелёный "
                      "отдельно — в карантин run-tests.py (QUARANTINE) с этой задачей, иначе чинить."))
            out.append(tid)
        except Exception:  # noqa: BLE001 — карточку не завести: тревога всё равно назовёт файл
            continue
    return out


def summarize(res):
    """Итог запуска → (строка журнала, текст тревоги или None, менять ли тревогу)."""
    head = f"{res.get('repo')} {str(res.get('sha'))[:7]} ({res.get('night')}, {res.get('url')})"
    quar = f"; карантин упал: {', '.join(res['quarantine'])}" if res.get("quarantine") else ""
    total = f"; {' | '.join(res['total'])}" if res.get("total") else ""
    concl = res.get("conclusion")
    if concl == "success" and not res.get("why") and res.get("total"):
        return f"{head}: зелёный{quar}{total}", None, True
    if concl == "success":   # Д2 argus #430: success без стартовавших частей или строк итога — не зелёный
        return (f"{head}: запуск success, но итога нет — {res.get('why') or 'строк «итого» в логах частей нет'}; жду "
                "следующего"), None, False
    if concl != "failure":
        return f"{head}: запуск {concl} — итога нет, жду следующего", None, False
    if res.get("fails"):
        tids = file_tasks(res)
        why = (f"{head}: красный — {', '.join(res['fails'])}" + (f" (задачи {', '.join(tids)})" if tids else "")
               + quar + total)
        return why, why, True
    why = f"{head}: красный без строк FAIL — {res.get('why') or 'сбой части вне тестов (установка, таймаут)'}{quar}{total}"
    return why, why, True


# --- тик ---------------------------------------------------------------------------------------------------------

def log(t, text):
    os.makedirs(P.path("logs"), exist_ok=True)
    with open(P.path("logs", "tick.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{P.stamp(t)} nightly-tick: {' '.join(text.split())}\n")


def _changed(st, repo, text):
    """Строка журнала — только если сменилась с прошлой для repo."""
    last = st.setdefault("last", {})
    if last.get(repo) == text:
        return None
    last[repo] = text
    return text


def _stale_text(repo, t, since, why):
    """Нет итога дольше STALE → тревога STALE_KEY и её текст; иначе тревога снята, None."""
    if t - since > STALE:
        text = (f"{repo}: итога ночного набора в Actions нет с {P.stamp(since)} — {why} (расписание tests.yml выключено? "
                "Actions недоступны?)")
        P.alert_once(STALE_KEY, f"{repo} {int(since)}", "ночной полный набор: " + text[:300], WHO)
        return text
    P.clear_once(STALE_KEY)
    return None


def _stale(st, repo, t, since, why):
    """Нет свежего итога дольше STALE → тревога STALE_KEY; иначе снять. → строка журнала при смене или None."""
    return _changed(st, repo, _stale_text(repo, t, since, why) or f"{repo}: {why}")


def check(repo, t, st):
    """Проверка репозитория → строка журнала или None (ничего нового)."""
    done = st.setdefault("done", {})
    prev = done.get(repo) if isinstance(done.get(repo), dict) else {}
    # отсчёт свежести — от последнего запуска с итогом (Д1 argus #430); "created" — состояние до этой правки
    since = prev.get("final", prev.get("created")) or st["first"]
    runs, err = main_runs(repo)
    if err:
        return _stale(st, repo, t, since, f"запуски {WORKFLOW} не прочитать: {err}")
    completed = [r for r in runs if r.get("status") == "completed"]
    newest = completed[0] if completed else None
    if newest is None:
        return _stale(st, repo, t, since, "завершённых запусков на main нет")
    created = _ts(newest.get("created_at")) or t
    if run_key(newest) == prev.get("key"):
        going = " (идёт новый)" if runs and runs[0].get("status") != "completed" else ""
        return _stale(st, repo, t, since, f"новых итогов нет{going}")
    res = run_result(repo, newest)
    text, fail, final = summarize(res)
    if final:
        since = created
    done[repo] = {"key": run_key(newest), "created": created, "final": since, "sha": res["sha"],
                  "conclusion": res["conclusion"]}
    if final:
        _alert(fail)
        P.clear_once(STALE_KEY)
    else:
        stale = _stale_text(repo, t, since, "последний запуск без итога")
        text = f"{text}; {stale}" if stale else text
    st.setdefault("last", {})[repo] = text
    return text


def tick(t):
    """Проход тика: не чаще CHECK_EVERY читает итог ночного запуска в Actions. → строка журнала или None."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return None
    st = P.read_json(state_file(), {})
    last = st.get("checked")
    if isinstance(last, (int, float)) and 0 <= t - last < CHECK_EVERY:
        return None
    st["checked"] = t
    if not isinstance(st.get("first"), (int, float)):
        st["first"] = t
    for old in ("running", "result"):  # от локального набора (metis-1050): работника больше нет
        st.pop(old, None)
    texts = [x for x in (check(repo, t, st) for repo in repos()) if x]
    P.write_json(state_file(), st)
    if not texts:
        return None
    text = "; ".join(texts)
    log(t, text)
    return text


def _alert(fail):
    if fail:
        P.alert_once(ALERT_KEY, fail[:300], "ночной полный набор: " + fail[:300], WHO)
    else:
        P.clear_once(ALERT_KEY)
