#!/usr/bin/env python3
"""pantheon review (запор слияния guard 0.5.4): test — только в чистом дереве git, без оболочки, после неё
HEAD и дерево те же, выход с её кодом и SHA; accept|reject|talos — проверка формата, код 0, у accept — перечень
проверенного Б6 (guard 0.5.6); status — журнал с перечнем.
Сама команда в журнал не пишет. Временный HOME, PANTHEON_HOME и PANTHEON_STATE; всё убирается в конце."""
import json
import os
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
SHA = "a" * 40
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))


def main():
    if sys.version_info < (3, 11):  # pantheon.py сам требует 3.11 (tomllib): на 3.9 он отвечал бы отказом на всё
        print("ok   пропуск: pantheon review требует Python 3.11+ (здесь %d.%d)" % sys.version_info[:2])
        return 0
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
           "PANTHEON_STATE": state, "PANTHEON_NO_NOTIFY": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def pantheon(*args, cwd=tmp):
        return subprocess.run([sys.executable, "-I", LIB, *args], capture_output=True, text=True, env=env, cwd=cwd)

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
    view = {"state": "OPEN", "isDraft": False, "headRefOid": S5,
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
    import shutil as _sh

    def at(t, *args):
        return subprocess.run([sys.executable, "-I", LIB, *args], capture_output=True, text=True,
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


if __name__ == "__main__":
    sys.exit(main())
