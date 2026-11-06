"""Выпуск без Actions (metis-0880): плановый проход сам запускает `.github/scripts/release.py --push`, когда workflow
release на main не запустился — кончились минуты Actions (решение владельца 06.11: денег не тратим, руками не
запускаем). Обычный путь — Action после слияния (AGENTS.md, «Выпуск»); этот — запасной, без модели и без окна роли.

Тик основного Mac зовёт tick(t). Проверка — не чаще раза в CHECK_EVERY (15 мин), её время пишется до работы: сбой
тоже не повторяется чаще. Репозиторий — agent-kit из [merge_repos] metis-pantheon (merge.allowed_repos).

Код release.py исполняется только из своей копии на свежем origin/main (класс metis-0902: код не из main не
исполнять). Копия — клон STATE/release/<имя>: fetch main, checkout --detach на sha FETCH_HEAD, reset --hard, clean
-ffdx. Рабочую копию владельца, папки ролей и ветки PR проход не трогает. Помощник учётных данных клона — `gh auth
git-credential` (push под входом gh владельца).

Запуск — только если выполнены все три условия:
1. На первой родительской линии origin/main после последнего коммита «выпуск: …» есть слияние, и самое новое из них
   (head main) старше MERGE_AGE (15 мин): запуск Actions на свежем head мог ещё не появиться.
2. У workflow release (.github/workflows/release.yml) на этом sha запуска нет совсем, либо все его запуски завершены с
   failure и хоть у одного job нет раннера и шагов или аннотация лимита минут (merge.CI_BILLING). Запуск идёт,
   прошёл, отменён или ответ gh неполон — не запускает.
3. Копия чистая: `git status --porcelain --untracked-files=all` пуст и HEAD — sha origin/main.
Затем `python3 -I .github/scripts/release.py --push` с рабочей папкой копии. Код 0 — sha запоминается, второй раз на
нём проход release.py не зовёт (поднимать было нечего — коммита выпуска нет, а условие 1 осталось).

Итог — одна строка `<время> release-tick: …` в logs/tick.log, когда итог сменился или был запуск. Сбой (клон, fetch,
gh, код release.py не 0) — тревога alert_once без critical, одна на состояние; удачная проверка её снимает.
PANTHEON_DRYRUN=1 (тесты тика) — ничего не делает.
"""
import os
import re
import subprocess
import sys

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

CHECK_EVERY = 15 * 60
MERGE_AGE = 15 * 60
RELEASE_PREFIX = "выпуск: "  # тема коммита release.py
RELEASE_SCRIPT = os.path.join(".github", "scripts", "release.py")
RELEASE_WORKFLOW = ".github/workflows/release.yml"
REPO_NAMES = ("agent-kit",)  # имя репозитория без владельца: у него есть release.py
URL = "https://github.com/{repo}.git"  # тесты подменяют на локальный голый репозиторий
LOG_DEPTH = 200
SHA_RE = re.compile(r"[0-9a-f]{40}")
GIT_TIMEOUT = 300
GH_TIMEOUT = 60
RELEASE_TIMEOUT = 600
ALERT_KEY = "release-tick"
WHO = "pantheon-tick"


def set_core(mod):
    global P
    P = mod


def state_file():
    return P.path("release-tick.json")


def copy_dir(repo):
    return P.path("release", repo.rsplit("/", 1)[-1])


def repos():
    return sorted(r for r in P.merge_mod().allowed_repos() if r.rsplit("/", 1)[-1] in REPO_NAMES)


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=P.HOME, PATH=P.merge_mod().SAFE_PATH, GIT_TERMINAL_PROMPT="0")
    return env


def git(d, *args, timeout=GIT_TIMEOUT):
    """→ (код, вывод). git не запустился или завис — (None, причина)."""
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=timeout, env=_env())
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"git {args[0]} не запустился: {type(e).__name__}"
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip()


def prepare(repo, copy):
    """Копия на свежем origin/main → (sha, None) или (None, причина). Клона нет — клон; затем fetch и сброс."""
    if not os.path.isdir(os.path.join(copy, ".git")):
        os.makedirs(os.path.dirname(copy), exist_ok=True)
        code, out = git(os.path.dirname(copy), "clone", "-q", "--no-tags", URL.format(repo=repo), copy)
        if code != 0:
            return None, f"клон {repo} не создан: {out[-200:]}"
    gh = P.merge_mod().gh_path()
    git(copy, "config", "--local", "--unset-all", "credential.helper")
    for value in ("", f"!{gh} auth git-credential"):
        git(copy, "config", "--local", "--add", "credential.helper", value)
    code, out = git(copy, "fetch", "-q", "--no-tags", "origin", "main")
    if code != 0:
        return None, f"fetch origin main: {out[-200:]}"
    code, sha = git(copy, "rev-parse", "FETCH_HEAD")
    if code != 0 or not SHA_RE.fullmatch(sha):
        return None, f"sha origin/main не получен: {sha[-200:]}"
    for args in (("checkout", "-q", "-f", "--detach", sha), ("reset", "-q", "--hard", sha), ("clean", "-q", "-ffdx")):
        code, out = git(copy, *args)
        if code != 0:
            return None, f"git {args[0]}: {out[-200:]}"
    return sha, None


def merge_pending(copy, sha, t):
    """Условие 1 → (True, None) или (False, почему нет)."""
    code, out = git(copy, "log", "--first-parent", f"-n{LOG_DEPTH}", "--format=%H %ct %s", sha)
    if code != 0:
        return False, f"git log: {out[-200:]}"
    rows = [ln.split(" ", 2) for ln in out.splitlines()]
    after = []
    for row in rows:
        if len(row) == 3 and row[2].startswith(RELEASE_PREFIX):
            break
        after.append(row)
    else:
        return False, f"коммита «{RELEASE_PREFIX}…» нет в {LOG_DEPTH} последних"
    if not after:
        return False, f"main {sha[:7]} — коммит выпуска, слияний после него нет"
    try:
        head_time = int(after[0][1])
    except (IndexError, ValueError):
        return False, f"время коммита {sha[:7]} не разобрано"
    if t - head_time < MERGE_AGE:
        return False, f"слияние {sha[:7]} моложе {MERGE_AGE // 60} мин"
    return True, None


def copy_clean(copy, sha):
    """Условие 3 → (True, None) или (False, почему нет)."""
    code, head = git(copy, "rev-parse", "HEAD")
    if code != 0 or head != sha:
        return False, f"копия не на {sha[:7]} (HEAD {head[:12]})"
    code, out = git(copy, "status", "--porcelain", "--untracked-files=all")
    if code != 0 or out:
        return False, f"копия не чистая: {out[:120]}"
    return True, None


def gh_api(endpoint):
    """GET REST через gh → (данные, None) или (None, причина)."""
    import json
    try:
        r = subprocess.run([P.merge_mod().gh_path(), "api", endpoint], capture_output=True, text=True,
                           timeout=GH_TIMEOUT, env=P.merge_mod().gh_env())
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"gh не запустился: {type(e).__name__}"
    if r.returncode != 0:
        return None, f"gh api {endpoint.split('?')[0]}: {(r.stderr or r.stdout).strip()[:160]}"
    try:
        return json.loads(r.stdout or "null"), None
    except ValueError:
        return None, "gh вернул не JSON"


def _workflow(run):
    return str(run.get("path") or "").split("@", 1)[0] if isinstance(run, dict) else ""


def actions_skipped(repo, sha):
    """Условие 2 → (True, почему да) или (False, почему нет); ответ gh не получен — (None, причина)."""
    M = P.merge_mod()
    data, err = gh_api(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100")
    if err:
        return None, err
    try:
        runs = data["workflow_runs"]
        if data["total_count"] > len(runs):
            return False, f"неполный ответ gh: запусков {data['total_count']}, получено {len(runs)}"
        rel = [r for r in runs if _workflow(r) == RELEASE_WORKFLOW and r["head_sha"] == sha]
    except (TypeError, KeyError):
        return None, "ответ gh о запусках не разобран"
    if not rel:
        return True, "запуска release нет"
    for run in rel:
        status, concl = str(run.get("status") or ""), str(run.get("conclusion") or "")
        if status != "completed":
            return False, f"release на {sha[:7]} ещё идёт ({status or 'нет статуса'})"
        if concl != "failure":
            return False, f"release на {sha[:7]} завершён: {concl or 'нет итога'}"
    jobs = []
    for run in rel:
        data, err = gh_api(f"repos/{repo}/actions/runs/{run.get('id')}/jobs?per_page=100")
        if err:
            return None, err
        got = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(got, list):
            return None, "ответ gh о job не разобран"
        jobs += got
    if any(M.ci_job_unstarted(j) for j in jobs):
        return True, "job release без раннера и шагов"
    for job in jobs:
        if not isinstance(job, dict) or type(job.get("id")) is not int:
            continue
        notes, err = gh_api(f"repos/{repo}/check-runs/{job['id']}/annotations?per_page=100")
        if err:
            return None, err
        if isinstance(notes, list) and any(isinstance(a, dict) and a.get("annotation_level") == "failure"
                                           and str(a.get("message") or "").startswith(M.CI_BILLING) for a in notes):
            return True, "аннотация лимита минут Actions"
    return False, f"release на {sha[:7]} упал не из-за лимита минут"


def run_release(copy):
    """release.py --push из копии → (код, последняя строка вывода)."""
    script = os.path.join(copy, RELEASE_SCRIPT)
    try:
        r = subprocess.run([sys.executable, "-I", script, "--push"], cwd=copy, capture_output=True, text=True,
                           timeout=RELEASE_TIMEOUT, env=_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"не запустился: {type(e).__name__}"
    lines = [ln for ln in (r.stdout + "\n" + r.stderr).splitlines() if ln.strip()]
    return r.returncode, (lines[-1].strip() if lines else "")[:200]


def check(repo, t, st):
    """Одна проверка репозитория → (итог, сбой или None, запуск был). st — состояние, done_sha дописывается сюда."""
    copy = copy_dir(repo)
    sha, err = prepare(repo, copy)
    if err:
        return f"{repo}: {err}", err, False
    if st.get("done_sha") == sha:
        return f"{repo}: на {sha[:7]} release.py уже отработал", None, False
    ok, why = merge_pending(copy, sha, t)
    if not ok:
        return f"{repo}: не нужен — {why}", None, False
    ok, why = copy_clean(copy, sha)
    if not ok:
        return f"{repo}: не запускаю — {why}", why, False
    ok, why = actions_skipped(repo, sha)
    if ok is None:
        return f"{repo}: {why}", why, False
    if not ok:
        return f"{repo}: не нужен — {why}", None, False
    code, last = run_release(copy)
    if code != 0:
        fail = f"release.py --push на {sha[:7]} — код {code}: {last}"
        return f"{repo}: {fail}", fail, True
    st["done_sha"] = sha
    return f"{repo}: выпуск на {sha[:7]} ({why}) — {last}", None, True


def log(t, text):
    os.makedirs(P.path("logs"), exist_ok=True)
    with open(P.path("logs", "tick.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{P.stamp(t)} release-tick: {' '.join(text.split())}\n")


def tick(t):
    """Проход тика: не чаще CHECK_EVERY, по одному репозиторию из REPO_NAMES. → итог или None (пропуск)."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return None
    st = P.read_json(state_file(), {})
    last = st.get("checked")
    if isinstance(last, (int, float)) and 0 <= t - last < CHECK_EVERY:
        return None
    todo = repos()
    if not todo:
        return None
    st["checked"] = t
    P.write_json(state_file(), st)
    texts, fails, ran = [], [], False
    for repo in todo:
        text, fail, did = check(repo, t, st)
        texts.append(text)
        ran = ran or did
        if fail:
            fails.append(f"{repo}: {fail}")
    text = "; ".join(texts)
    if ran or text != st.get("last"):
        log(t, text)
    st["last"] = text
    P.write_json(state_file(), st)
    if fails:
        P.alert_once(ALERT_KEY, "; ".join(fails)[:300], "выпуск без Actions: " + "; ".join(fails)[:300], WHO)
    else:
        P.clear_once(ALERT_KEY)
    return text
