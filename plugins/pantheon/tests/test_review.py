#!/usr/bin/env python3
"""pantheon review (запор слияния guard 0.5.4): test — только в чистом дереве git, без оболочки, после неё
HEAD и дерево те же, выход с её кодом и SHA; accept|reject|talos — проверка формата, код 0, у accept — перечень
проверенного Б6 (guard 0.5.6); status — журнал с перечнем.
Сама команда в журнал не пишет. Временный HOME, PANTHEON_HOME и PANTHEON_STATE; всё убирается в конце."""
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение,
# выход из подпроцесса); TMPDIR — для подпроцессов, которые тоже создают временные папки (как в 9587c02).
import atexit as _atexit
_ROOT = tempfile.mkdtemp(prefix="review-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
SHA = "a" * 40
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="review-test-"))
    try:
        run_all(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


def run_all(tmp):
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "TMPDIR": tmp, "PANTHEON_NO_NOTIFY": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def pantheon(*args, cwd=tmp, extra=None):
        return subprocess.run([sys.executable, "-I", RUN_PY, *args], capture_output=True, text=True,
                              env=dict(env, **(extra or {})), cwd=cwd)

    def git(*args, cwd):
        return subprocess.run(["git", *args], capture_output=True, text=True, env=env, cwd=cwd)

    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git("init", "-q", cwd=repo)
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("a\n")
    git("add", "a.txt", cwd=repo)
    git("commit", "-q", "-m", "init", cwd=repo)
    head = git("rev-parse", "HEAD", cwd=repo).stdout.strip()

    r = pantheon("review", "test", "--", "true", cwd=repo)
    check("test в чистом дереве — код команды 0 и SHA HEAD", r.returncode == 0 and head in r.stdout)
    r = pantheon("review", "test", "--", "false", cwd=repo)
    check("test — код упавшей команды", r.returncode == 1)
    # команда без оболочки: «;» — это слово, а не разделитель
    r = pantheon("review", "test", "--", "echo", "x;", "touch", "y", cwd=repo)
    check("test — команда без оболочки", r.returncode == 0 and not os.path.exists(os.path.join(repo, "y")))
    r = pantheon("review", "test", "--", "touch", "new.txt", cwd=repo)
    check("test — команда испачкала дерево: код 3", r.returncode == 3)
    os.remove(os.path.join(repo, "new.txt"))
    r = pantheon("review", "test", "--", "git", "commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
    check("test — команда сменила HEAD: код 3", r.returncode == 3)
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("b\n")
    r = pantheon("review", "test", "--", "true", cwd=repo)
    check("test — грязное дерево: код 2, команда не запускалась", r.returncode == 2 and "не чистое" in r.stderr)
    git("checkout", "-q", "a.txt", cwd=repo)
    # ссылка node_modules (metis-0721): в корне не мешает, папка с файлом — мешает
    os.symlink("/nonexistent-target", os.path.join(repo, "node_modules"))
    r = pantheon("review", "test", "--", "true", cwd=repo)
    check("test — симлинк node_modules в корне: чисто, код 0", r.returncode == 0, r.stderr)
    os.remove(os.path.join(repo, "node_modules"))
    os.makedirs(os.path.join(repo, "node_modules"))
    with open(os.path.join(repo, "node_modules", "f"), "w") as fh:
        fh.write("x")
    r = pantheon("review", "test", "--", "true", cwd=repo)
    check("test — папка node_modules с файлом: код 2", r.returncode == 2 and "не чистое" in r.stderr)
    shutil.rmtree(os.path.join(repo, "node_modules"))
    r = pantheon("review", "test", "--", "true", cwd=tmp)
    check("test — не git: код 2", r.returncode == 2)
    r = pantheon("review", "test", "true", cwd=repo)
    check("test без -- : код 2", r.returncode == 2)

    cl = ["--opened", "merge_gate.py, README", "--ran", 'heavy python3 -I tests/x.py "84 из 84"', "--unchecked", "gh"]
    for kind, extra in (("accept", cl), ("reject", []), ("talos", [])):
        r = pantheon("review", kind, "latark/agent-kit", "17", SHA, *extra)
        check(f"{kind} — код 0 и «записано хуком guard»", r.returncode == 0 and "хуком guard" in r.stdout)
    r = pantheon("review", "accept", "latark/agent-kit", "17", SHA, *cl)
    check("accept — перечень напечатан, кавычки и пробелы в поле целы",
          "открыл: merge_gate.py, README" in r.stdout and 'запустил: heavy python3 -I tests/x.py "84 из 84"' in r.stdout
          and "не проверял: gh" in r.stdout)
    r = pantheon("review", "accept", "--opened=a", "latark/agent-kit", "--ran=b c", "17", SHA, "--unchecked=d")
    check("accept — форма --x=V и флаги в любом месте: код 0", r.returncode == 0 and "запустил: b c" in r.stdout)
    for extra, why in (([], "без перечня"), (cl[:4], "пусто --unchecked"), (["--opened", "", *cl[2:]], "пусто --opened"),
                       (["--opened", "  ", *cl[2:]], "пусто --opened"), ([*cl, "--foo", "x"], "неизвестный флаг"),
                       ([*cl, "--opened", "b"], "дважды"), ([*cl[:5]], "нет значения"),
                       (["--opened", "--ran", "--ran", "--unchecked", "--unchecked", "--opened"], "начинается с «--»"),
                       (["--opened=--ran", *cl[2:]], "начинается с «--»")):
        r = pantheon("review", "accept", "latark/agent-kit", "17", SHA, *extra)
        check(f"accept {' '.join(extra)[:40] or '(без полей)'} — код 2, «{why}»",
              r.returncode == 2 and why in r.stderr and "Б6" in r.stderr if why == "без перечня"
              else r.returncode == 2 and why in r.stderr)
    r = pantheon("review", "reject", "latark/agent-kit", "17", SHA, "--opened", "a.py")
    check("reject — поля по желанию: код 0, поле напечатано", r.returncode == 0 and "открыл: a.py" in r.stdout)
    r = pantheon("review", "talos", "latark/agent-kit", "17", SHA, "--opened", "a.py")
    check("talos — флагов нет: код 2", r.returncode == 2)
    for bad in (["latark/agent-kit", "17", SHA[:39]], ["latark", "17", SHA], ["latark/agent-kit", "0", SHA],
                ["latark/agent-kit", "x", SHA], ["latark/agent-kit", "17"], ["latark/agent-kit", "17", SHA, "x"]):
        r = pantheon("review", "accept", *bad, *cl)
        check(f"accept {' '.join(bad)[:40]} — плохой формат, код 2", r.returncode == 2 and "формате" in r.stderr)
    check("неизвестный вид — код 2", pantheon("review", "approve", "x").returncode == 2)
    check("без вида — код 2", pantheon("review").returncode == 2)
    check("сама команда журнал не пишет", not os.path.exists(os.path.join(state, "merge-gate")))

    os.makedirs(os.path.join(state, "merge-gate"))
    rec = {"v": 1, "kind": "accept", "repo": ["latark/agent-kit"], "pr": 17, "sha": SHA,
           "by": {"agent_type": "argus", "agent_id": "x", "session_id": "s"}, "time": "2026-10-15T20:00:00"}
    full = dict(rec, pr=18, checklist={"opened": "a.py, README", "ran": "heavy pytest", "unchecked": "живой gh"})
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "w") as fh:
        fh.write("битая строка\n" + json.dumps(rec) + "\n" + json.dumps(full) + "\n")
    r = pantheon("review", "status", "latark/agent-kit", "17")
    check("status — запись видна, битая строка пропущена", r.returncode == 0 and "accept" in r.stdout)
    check("status — accept старого формата помечен «без перечня»", "без перечня проверенного (Б6)" in r.stdout)
    r = pantheon("review", "status", "latark/agent-kit", "18")
    check("status — перечень accept показан", r.returncode == 0 and "открыл: a.py, README" in r.stdout
          and "запустил: heavy pytest" in r.stdout and "не проверял: живой gh" in r.stdout
          and "без перечня" not in r.stdout)
    r = pantheon("review", "status", "latark/other", "17")
    check("status — фильтр по репозиторию", r.returncode == 0 and "записей нет" in r.stdout)

    # metis-0735: запись tests зелёного дозапуска — в status видно, что это дозапуск
    trec = {"v": 1, "kind": "tests", "repo": ["latark/agent-kit"], "pr": 19, "sha": SHA, "cmd": "x",
            "by": {"agent_type": "pantheon-outside"}, "time": "2026-10-15T20:00:00", "rerun_of": "20261103-000001-abcdef",
            "files": ["kit/test_a.py", "kit/test_b.py"], "map": "m"}
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "a") as fh:
        fh.write(json.dumps(trec) + "\n" + json.dumps(dict(trec, pr=20, rerun_of=None)) + "\n")
    r = pantheon("review", "status", "latark/agent-kit", "19")
    check("status: запись tests с rerun_of — «дозапуск от <id>, файлов 2»",
          r.returncode == 0 and "дозапуск от 20261103-000001-abcdef, файлов 2" in r.stdout, r.stdout)
    r = pantheon("review", "status", "latark/agent-kit", "20")
    check("status: запись tests без rerun_of — строки дозапуска нет", r.returncode == 0 and "дозапуск" not in r.stdout
          and "tests" in r.stdout, r.stdout)

    # metis-0393: итог по head — последний вердикт каждого argus (рецензент — сессия и agent_id, как у шлюза)
    opus = dict(full["checklist"], ran="модель: claude-opus-5-5, heavy pytest")

    def v(kind, sha, aid, sid="s", pr=40, who="argus", cl=opus):
        return dict(rec, kind=kind, sha=sha, pr=pr, by={"agent_type": who, "agent_id": aid, "session_id": sid},
                    checklist=cl)
    S2, S3, S4, S5 = "b" * 40, "c" * 40, "d" * 40, "e" * 40
    sonnet = dict(opus, ran="модель: claude-sonnet-4-6, heavy pytest")
    tally = [v("reject", SHA, "aaaaaaaa11"), v("accept", SHA, "aaaaaaaa11"),  # вернул и сам же снял
             v("reject", SHA, "bbbbbbbb22"),                                   # вернул, не снял
             v("accept", SHA, "bbbbbbbb22", sid="s2"),                         # тот же agent_id, другая сессия
             v("accept", SHA, "cccccccc33", pr=41), v("talos", SHA, "dddddddd44", who="talos"),
             v("accept", SHA, "eeeeeeee55", pr=None),            # без PR: review_records его пропускает, шлюз — нет
             v("accept", SHA, "ffffffff66", who="dev-opus"),     # «принять» не от argus шлюз не считает
             v("accept", S2, "aaaaaaaa11"), v("accept", S2, "bbbbbbbb22"),
             # «принять» не на Opus не в счёт, как у шлюза (metis-0176): и «вернуть» того же рецензента не снимает
             v("accept", S3, "aaaaaaaa11"), v("accept", S3, "gggggggg77", cl=sonnet),
             v("accept", S3, "gggggggg78", cl=dict(opus, ran="heavy pytest, модель: claude-opus-5-5")),
             v("reject", S3, "iiiiiiii99"), v("accept", S3, "iiiiiiii99", cl=sonnet),
             # «принять» без полного перечня (Б6) не в счёт
             v("accept", S4, "aaaaaaaa11"), v("accept", S4, "hhhhhhhh88", cl=None),
             v("accept", S4, "hhhhhhhh89", cl=dict(opus, unchecked=" ")),
             # metis-0393: модели транскрипта argus (поле models от хука guard) — как у шлюза merge.gate: «модель:
             # claude-opus» в --ran, а по транскрипту Sonnet — не в счёт; models_note (транскрипта не было) — по --ran
             dict(v("accept", S5, "jjjjjjjj01"), models=["claude-sonnet-4-6"]),
             dict(v("accept", S5, "jjjjjjjj02"), models=["claude-opus-5-5-20261001"]),
             dict(v("accept", S5, "jjjjjjjj03"), models_note="транскрипт argus не найден"),
             dict(v("accept", S5, "jjjjjjjj04", cl=sonnet), models_note="транскрипт argus не найден"),
             # metis-0413: транскрипт найден, моделей нет (models: []) — не в счёт, как в шлюзе guard
             dict(v("accept", S5, "jjjjjjjj05"), models=[],
                  models_note="транскрипт argus найден, но моделей в нём нет — модель не подтвердить")]
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "w") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in tally))
    r = pantheon("review", "status", "latark/agent-kit", "40")
    out = r.stdout.splitlines()
    check("status: итог на head — «вернуть» снимает только тот же рецензент; другой PR, без PR и не argus не в счёт",
          f"итог на {SHA[:12]}: принять 2, вернуть 1 — последний вердикт каждого argus" in out, r.stdout)
    check("status: итог на другом head — свой", f"итог на {S2[:12]}: принять 2, вернуть 0 — последний вердикт "
          "каждого argus" in out, r.stdout)
    check("status: «принять» на Sonnet и с «модель: claude-opus» не в начале --ran в счёт (вне ядра хватает любой "
          "модели) и снимает «вернуть» того же рецензента; строка «для PR ядра» считает только Opus и «вернуть» держит",
          f"итог на {S3[:12]}: принять 4, вернуть 0 — последний вердикт каждого argus" in out
          and f"итог на {S3[:12]}: принять 4, вернуть 0 — последний вердикт каждого argus" in out
          and out[out.index(f"итог на {S3[:12]}: принять 4, вернуть 0 — последний вердикт каждого argus") + 1]
          == "  для PR ядра (в счёт только «принять» на Opus): принять 1, вернуть 1", r.stdout)
    check("status: «принять» без перечня или с пустым полем не в счёт",
          f"итог на {S4[:12]}: принять 1, вернуть 0 — последний вердикт каждого argus" in out, r.stdout)
    check("status: «принять» не на Opus помечено в журнале",
          sum("не на Opus (--ran без «модель: claude-opus» в начале) — для PR ядра не в счёт" in ln for ln in out) == 4, r.stdout)
    check("status: Sonnet по транскрипту argus в счёт вне ядра, для ядра — нет; models_note — по --ran",
          f"итог на {S5[:12]}: принять 5, вернуть 0 — последний вердикт каждого argus" in out
          and "  для PR ядра (в счёт только «принять» на Opus): принять 2, вернуть 0" in out, r.stdout)
    check("status: расхождение --ran с транскриптом помечено своей строкой",
          sum("не на Opus по транскрипту argus" in ln for ln in out) == 1, r.stdout)
    check("status: транскрипт без моделей (models: []) помечен своей строкой, а не «по --ran»",
          sum("транскрипт argus найден, но моделей в нём нет" in ln for ln in out) == 1, r.stdout)
    # репозиторий продукта в [merge_repos] (не metis-pantheon): ядра там нет — без строк про Opus (app#20, 28.10)
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"), exist_ok=True)
    with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[merge_repos]\nathena-x = ["acme/app"]\nmetis-pantheon = ["latark/agent-kit"]\n')
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "a") as fh:
        fh.write(json.dumps(dict(v("accept", S5, "kkkkkkkk01", pr=20, cl=sonnet), repo=["acme/app"],
                                 models=["claude-sonnet-5-5"])) + "\n")
    r = pantheon("review", "status", "acme/app", "20")
    check("status: продукт — Sonnet в счёт, без «не на Opus» и без строки «для PR ядра»",
          f"итог на {S5[:12]}: принять 1, вернуть 0 — последний вердикт каждого argus" in r.stdout
          and "Opus" not in r.stdout, r.stdout)
    r = pantheon("review", "status", "latark/agent-kit", "40")
    check("status: репозиторий metis-pantheon в [merge_repos] — строка «для PR ядра» на месте",
          "  для PR ядра (в счёт только «принять» на Opus): принять 2, вернуть 0" in r.stdout, r.stdout)
    os.remove(os.path.join(tmp, ".claude", "pantheon", "policy.toml"))
    # тот же журнал — шлюз владельца merge.gate (общее правило review_accept_counts): Sonnet по транскрипту не в счёт
    import importlib.util as _ilu
    import types as _types

    def _load(name, path):
        spec = _ilu.spec_from_file_location(name, path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    _M = _load("merge_for_test", os.path.join(os.path.dirname(LIB), "merge.py"))
    _P = _types.SimpleNamespace(review_records=lambda repo: [x for x in tally if x["sha"] == S5],
                                review_accept_counts=_load("pantheon_for_test", LIB).review_accept_counts)
    _M.P = _P
    # запуски Actions (metis-0633) — подмена вместо настоящего gh: тест в сеть не ходит; обязательные agent-kit зелёные;
    # fork — голова PR из форка (metis-0649), у этого PR её нет
    _M.ci_runs_fetch = lambda repo, pr, sha, fork=None: [
        {"workflowName": w, "name": j, "status": "COMPLETED", "conclusion": "SUCCESS", "event": "pull_request"}
        for w, j in (("tests", "affected"), ("check-traces", "traces"))] if (repo, pr, sha) == (
            "latark/agent-kit", 40, S5) and fork is None else None
    view = {"state": "OPEN", "isDraft": False, "headRefOid": S5, "baseRefName": "main",
            "statusCheckRollup": [{"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]}
    st, why = _M.gate("latark/agent-kit", 40, S5, view)
    check("merge.gate на том же журнале: Sonnet по транскрипту не в счёт, models_note — по --ran", st == "fail"
          and "нет записи тестов" in why, (st, why))
    tests_rec = dict(rec, kind="tests", pr=None, sha=S5)
    _P.review_records = lambda repo: [tests_rec] + [x for x in tally if x["sha"] == S5]
    st, why = _M.gate("latark/agent-kit", 40, S5, view)
    check("merge.gate: «принять» ×2 (Opus по транскрипту и models_note), Sonnet по транскрипту отсеян",
          st == "ok" and "argus ×2" in why, (st, why))
    _P.review_records = lambda repo: [tests_rec] + [x for x in tally if x["sha"] == S5
                                                     and x["by"]["agent_id"] in ("jjjjjjjj01", "jjjjjjjj02")]
    st, why = _M.gate("latark/agent-kit", 40, S5, view)
    check("merge.gate: Opus в --ran и Sonnet по транскрипту — «1 из 2»", st == "fail" and "1 из 2" in why, (st, why))
    check("status: у вердикта виден рецензент (agent_id/сессия по 8 знаков)",
          any(ln.endswith("argus bbbbbbbb/s2") for ln in out) and any(ln.endswith("argus aaaaaaaa/s") for ln in out),
          r.stdout)
    r = pantheon("review", "status")
    check("status без PR — итога нет (он по одному PR)", r.returncode == 0 and "итог на" not in r.stdout, r.stdout)

    # metis-0158: метка «ревью идёт»
    import time as _time

    def at(t, *args):
        return subprocess.run([sys.executable, "-I", RUN_PY, *args], capture_output=True, text=True,
                              env=dict(env, PANTHEON_NOW=str(t), PANTHEON_SESSION="hephaestus-x"), cwd=tmp)

    T = 1_800_000_000
    S2 = "b" * 40
    gate = os.path.join(state, "merge-gate", "records.jsonl")
    gate_before = open(gate, "rb").read()
    r = at(T, "review", "begin", "latark/Agent-Kit", "30", SHA)
    pf = os.path.join(state, "review-pending", "latark__agent-kit__30.json")
    d = json.load(open(pf)) if os.path.exists(pf) else {}
    check("begin: метка в review-pending (sha, время, кто), журнал guard не тронут",
          r.returncode == 0 and d.get("sha") == SHA and d.get("by") == "hephaestus-x" and d.get("t") == T
          and open(gate, "rb").read() == gate_before, (r.stdout, r.stderr, d))
    check("begin: в справке — не вердикт и не согласие", "НЕ вердикт и НЕ согласие" in at(T, "help").stdout)
    r = at(T + 600, "review", "status", "latark/agent-kit", "30")
    hhmm = _time.strftime("%H:%M", _time.localtime(T))
    check("status: «ревью идёт с HH:MM (head sha8)»", f"ревью идёт с {hhmm}" in r.stdout and SHA[:8] in r.stdout
          and "второго argus не звать" in r.stdout, r.stdout)
    r = at(T + 600, "review", "status")
    check("status без аргументов тоже показывает метку", "ревью идёт" in r.stdout, r.stdout)
    r = at(T + 7201, "review", "status", "latark/agent-kit", "30")
    check("status: через 2 часа метка не показывается", "ревью идёт" not in r.stdout, r.stdout)
    r = at(T + 600, "review", "status", "latark/agent-kit", "31")
    check("status: на другой PR метки нет", "ревью идёт" not in r.stdout)
    # вердикт на этот PR после метки гасит; до метки — нет
    old = dict(rec, pr=30, time=_time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime(T - 100)))
    with open(gate, "a") as fh:
        fh.write(json.dumps(old) + "\n")
    check("старый вердикт (до метки) её не гасит",
          "ревью идёт" in at(T + 600, "review", "status", "latark/agent-kit", "30").stdout)
    new = dict(rec, pr=30, time=_time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime(T + 300)))
    with open(gate, "a") as fh:
        fh.write(json.dumps(new) + "\n")
    check("вердикт на тот же sha после метки гасит её",
          "ревью идёт" not in at(T + 600, "review", "status", "latark/agent-kit", "30").stdout)
    at(T + 700, "review", "begin", "latark/agent-kit", "30", S2)
    r = at(T + 800, "review", "status", "latark/agent-kit", "30")
    check("новая метка на новый sha перезаписывает и показывается",
          "head " + S2[:8] in r.stdout and SHA[:8] not in r.stdout.split("\n")[0], r.stdout)
    for bad in (["latark/agent-kit", "30"], ["latark/agent-kit", "30", "abc"], ["x", "30", SHA]):
        check(f"begin {' '.join(bad)[:30]}: плохой формат — код 2", at(T, "review", "begin", *bad).returncode == 2)
    report_tests(tmp, pantheon)


def report_tests(tmp, pantheon):
    """review report (metis-0602): отчёт прежнего argus из транскрипта субагента; HOME — временный. Пара и последний
    head берутся из журнала шлюза, «Head:» отчёта должен равняться head последнего вердикта пары."""
    ref = "o/r-report"
    sess, agent = "5e55" * 16, "ab12cd34" + "0" * 24
    H1, H2 = "1" * 40, "2" * 40
    gate = os.path.join(tmp, "state", "merge-gate")
    os.makedirs(gate, exist_ok=True)

    def verdict(kind, sha, a=agent, ss=sess, pr=204, typ="argus"):
        with open(os.path.join(gate, "records.jsonl"), "a") as fh:
            fh.write(json.dumps({"v": 1, "kind": kind, "repo": [ref], "pr": pr, "sha": sha, "time": "2026-10-30T10:00:00",
                                 "by": {"agent_type": typ, "agent_id": a, "session_id": ss}}) + "\n")
    verdict("reject", H1)
    verdict("accept", H2)  # последний вердикт пары — на H2
    sdir = os.path.join(tmp, ".claude", "projects", "-x-proj", sess, "subagents")
    os.makedirs(sdir)

    def line(blocks):
        return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": blocks}}) + "\n"

    def hb(text):
        return {"type": "tool_use", "name": "SubagentHandback", "input": {"message": text}}
    fp = os.path.join(sdir, f"agent-{agent}.jsonl")
    with open(fp, "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
        fh.write("битая строка\n")
        fh.write(line([hb(f"Head: {H1}\nПЕРВЫЙ {ref}#204")]))
        fh.write(line([hb(f"Head: {H2}\nВТОРОЙ-СТАРЫЙ {ref} 204")]))
        fh.write(line([{"type": "text", "text": "длинный текст после отчёта " + "т" * 500}]))
        fh.write(line([hb(f"Head: {H2}\nИТОГОВЫЙ {ref} 204 {H2}")]))  # PR без «#», два Handback на одном Head
    r = pantheon("review", "report", ref, "204", "ab12cd34/5e555e55")
    check("report: последний Handback (PR без «#»), не длинный text и не ранний", r.returncode == 0
          and "ИТОГОВЫЙ" in r.stdout and "ПЕРВЫЙ" not in r.stdout and "СТАРЫЙ" not in r.stdout
          and "длинный текст" not in r.stdout, r.stdout + r.stderr)
    check("report: сессия необязательна", pantheon("review", "report", ref, "204", "ab12cd34").returncode == 0)
    r = pantheon("review", "report", ref, "205", "ab12cd34")
    check("report: на этом PR вердикта пары нет — код 1 и «полным кругом»", r.returncode == 1
          and "полным кругом" in r.stderr and not r.stdout, r.stdout + r.stderr)
    r = pantheon("review", "report", ref, "204", "ffffffff")
    check("report: пары нет в журнале — код 1", r.returncode == 1 and "нет вердикта" in r.stderr, r.stderr)
    r = pantheon("review", "report", ref, "204", "ab12cd34/dead")
    check("report: сессия не та — код 1", r.returncode == 1, r.stderr)
    out = os.path.join(tmp, "rep.md")
    r = pantheon("review", "report", ref, "204", "ab12cd34", "--out", out)
    body = open(out).read() if os.path.exists(out) else ""
    check("report --out: файл записан, 0600", r.returncode == 0 and "ИТОГОВЫЙ" in body
          and oct(os.stat(out).st_mode & 0o777) == "0o600", r.stdout + r.stderr)
    r = pantheon("review", "report", ref, "204", "ab12cd34", "--out", out)
    check("report --out: файл уже есть — код 1, не затёрт", r.returncode == 1 and open(out).read() == body, r.stderr)
    victim = os.path.join(tmp, "victim.txt")
    open(victim, "w").write("жертва")
    link = os.path.join(tmp, "link.md")
    os.symlink(victim, link)
    r = pantheon("review", "report", ref, "204", "ab12cd34", "--out", link)
    check("report --out в симлинк — код 1, цель не тронута", r.returncode == 1 and open(victim).read() == "жертва",
          r.stderr)
    r = pantheon("review", "report", ref, "204", "ab12cd34", "--out", os.path.join(tmp, "a.md"), "--out",
                 os.path.join(tmp, "b.md"))
    check("report: --out дважды — код 2, файлов нет", r.returncode == 2 and not os.path.exists(os.path.join(tmp, "a.md")),
          r.stderr)
    # metis-0634: домашняя папка — из базы пользователей, а не ~: run-tests даёт файлу HOME под своим TMPDIR, а под
    # проходом outside тот лежит в /private/tmp — и «~/x-report.md» законно проходит как «под /private/tmp».
    r = pantheon("review", "report", ref, "204", "ab12cd34", "--out",
                 os.path.join(pwd.getpwuid(os.getuid()).pw_dir, "x-report.md"))
    r2 = pantheon("review", "report", ref, "204", "ab12cd34", "--out", "/etc/x-report.md")
    check("report --out вне $TMPDIR и /private/tmp — код 2", r.returncode == 2 and r2.returncode == 2
          and not os.path.exists("/etc/x-report.md"), r.stderr + r2.stderr)
    # «Head:» отчёта не равен head последнего вердикта — отчёт не тот
    verdict("reject", H1)
    r = pantheon("review", "report", ref, "204", "ab12cd34")
    check("report: Head отчёта ≠ head последнего вердикта пары — код 1", r.returncode == 1 and "не равен" in r.stderr,
          r.stdout + r.stderr)
    verdict("accept", H2)
    # вердикт не argus и чужого PR пару не создаёт
    verdict("accept", H2, a="ab12cd99" + "0" * 24, typ="talos")
    verdict("accept", H2, a="ab12cd88" + "0" * 24, pr=999)
    r = pantheon("review", "report", ref, "204", "ab12cd")
    check("report: talos и чужой PR не считаются парой — совпадение одно", r.returncode == 0, r.stderr)
    # транскрипт — симлинк: не читается
    a2 = "c0de0000" + "0" * 24
    verdict("accept", H2, a=a2)
    real = os.path.join(tmp, "real.jsonl")
    with open(real, "w") as fh:
        fh.write(line([hb(f"Head: {H2}\nОТЧЁТ {ref}#204")]))
    os.symlink(real, os.path.join(sdir, f"agent-{a2}.jsonl"))
    r = pantheon("review", "report", ref, "204", "c0de0000")
    check("report: транскрипт — симлинк, код 1", r.returncode == 1 and not r.stdout and "не найден" in r.stderr, r.stderr)
    # две пары под один префикс — отказ
    verdict("accept", H2, a="ab12cd35" + "0" * 24)
    r = pantheon("review", "report", ref, "204", "ab12cd")
    check("report: две пары под префикс — код 1", r.returncode == 1 and "несколько" in r.stderr, r.stderr)
    # транскрипт в подпапке workflows
    sess3, a3 = "7" * 64, "beef0000" + "0" * 24
    verdict("accept", H2, a=a3, ss=sess3)
    d3 = os.path.join(tmp, ".claude", "projects", "-y", sess3, "subagents", "workflows", "run1")
    os.makedirs(d3)
    with open(os.path.join(d3, f"agent-{a3}.jsonl"), "w") as fh:
        fh.write(line([hb(f"Head: {H2}\nWF {ref}#204")]))
    r = pantheon("review", "report", ref, "204", "beef0000")
    check("report: подпапка workflows", r.returncode == 0 and "WF" in r.stdout, r.stderr)
    # без Handback — последний длинный text; без отчёта — код 1
    a4, a5 = "cafe0000" + "0" * 24, "dead0000" + "0" * 24
    verdict("accept", H2, a=a4)
    verdict("accept", H2, a=a5)
    with open(os.path.join(sdir, f"agent-{a4}.jsonl"), "w") as fh:
        fh.write(line([{"type": "text", "text": f"Head: {H2} Статус: готово. " + "т" * 500}]))
        fh.write(line([{"type": "text", "text": "коротко"}]))
    r = pantheon("review", "report", ref, "204", "cafe0000")
    check("report: нет Handback — длинный text", r.returncode == 0 and "Статус: готово" in r.stdout, r.stderr)
    with open(os.path.join(sdir, f"agent-{a5}.jsonl"), "w") as fh:
        fh.write(line([{"type": "text", "text": "нет отчёта"}]))
    r = pantheon("review", "report", ref, "204", "dead0000")
    check("report: в транскрипте отчёта нет — код 1", r.returncode == 1 and "нет итогового отчёта" in r.stderr, r.stderr)
    # только user-запись с длинным текстом и «#N» — не отчёт (фильтр type=assistant)
    a6 = "f00d0000" + "0" * 24
    verdict("accept", H2, a=a6)
    with open(os.path.join(sdir, f"agent-{a6}.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": f"Head: {H2} {ref}#204 " + "т" * 500}]}}) + "\n")
    r = pantheon("review", "report", ref, "204", "f00d0000")
    check("report: длинный text из user-записи — не отчёт, код 1", r.returncode == 1 and not r.stdout, r.stdout + r.stderr)
    # один транскрипт в двух папках проектов — несколько файлов, код 1
    sdir_b = os.path.join(tmp, ".claude", "projects", "-w-proj", sess, "subagents")
    os.makedirs(sdir_b)
    shutil.copy(fp, sdir_b)
    r = pantheon("review", "report", ref, "204", "ab12cd34/5e55")
    check("report: один agent_id+сессия в двух папках — код 1 со списком", r.returncode == 1 and "несколько раз" in r.stderr
          and not r.stdout, r.stderr)
    shutil.rmtree(sdir_b)
    # вердикт без номера PR (pr: null) пару не создаёт
    verdict("accept", H2, a="ab12cd77" + "0" * 24, pr=None)
    r = pantheon("review", "report", ref, "204", "ab12cd7")
    check("report: вердикт с pr null не создаёт пару — код 1", r.returncode == 1 and "нет вердикта" in r.stderr, r.stderr)
    # соседняя папка с тем же началом имени, что $TMPDIR, — не «под $TMPDIR». metis-0634: $TMPDIR здесь — вне
    # /private/tmp (у run-tests под проходом outside временные папки лежат там, и любая соседняя прошла бы как «под
    # /private/tmp»). Папок не создаём: отказ — до записи и до чтения журнала, realpath несуществующего пути — по тексту.
    fake_tmp = os.path.join("/var/empty", "review-tmp")
    sib = fake_tmp + "-sib"
    r = pantheon("review", "report", ref, "204", "ab12cd34", "--out", os.path.join(sib, "x.md"),
                 extra={"TMPDIR": fake_tmp})
    check("report --out в соседней папке с общим префиксом $TMPDIR — код 2", r.returncode == 2
          and "только под $TMPDIR" in r.stderr and not os.path.exists(os.path.join(sib, "x.md")), r.stderr)
    for bad in (["x", "204", "ab12cd34"], [ref, "0", "ab12cd34"], [ref, "204", "zz"], [ref, "204"],
                [ref, "204", "ab12cd34", "--out"], [ref, "204", "ab12cd34", "--x"]):
        check(f"report {' '.join(bad)[:30]}: плохой формат — код 2", pantheon("review", "report", *bad).returncode == 2)


if __name__ == "__main__":
    sys.exit(main())
