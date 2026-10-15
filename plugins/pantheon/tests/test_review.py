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


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


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


if __name__ == "__main__":
    sys.exit(main())
