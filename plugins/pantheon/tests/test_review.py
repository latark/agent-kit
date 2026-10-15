#!/usr/bin/env python3
"""pantheon review (запор слияния guard 0.5.4): test — только в чистом дереве git, команда без оболочки, после неё
HEAD и дерево те же, выход с её кодом и SHA; accept|reject|talos — проверка формата, код 0; status — журнал.
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

    for kind in ("accept", "reject", "talos"):
        r = pantheon("review", kind, "latark/agent-kit", "17", SHA)
        check(f"{kind} — код 0 и «записано хуком guard»", r.returncode == 0 and "хуком guard" in r.stdout)
    for bad in (["latark/agent-kit", "17", SHA[:39]], ["latark", "17", SHA], ["latark/agent-kit", "0", SHA],
                ["latark/agent-kit", "x", SHA], ["latark/agent-kit", "17"], ["latark/agent-kit", "17", SHA, "x"]):
        r = pantheon("review", "accept", *bad)
        check(f"accept {' '.join(bad)[:40]} — плохой формат, код 2", r.returncode == 2)
    check("неизвестный вид — код 2", pantheon("review", "approve", "x").returncode == 2)
    check("без вида — код 2", pantheon("review").returncode == 2)
    check("сама команда журнал не пишет", not os.path.exists(os.path.join(state, "merge-gate")))

    os.makedirs(os.path.join(state, "merge-gate"))
    rec = {"v": 1, "kind": "accept", "repo": ["latark/agent-kit"], "pr": 17, "sha": SHA,
           "by": {"agent_type": "argus", "agent_id": "x", "session_id": "s"}, "time": "2026-10-15T20:00:00"}
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "w") as fh:
        fh.write("битая строка\n" + json.dumps(rec) + "\n")
    r = pantheon("review", "status", "latark/agent-kit", "17")
    check("status — запись видна, битая строка пропущена", r.returncode == 0 and "accept" in r.stdout)
    r = pantheon("review", "status", "latark/other", "17")
    check("status — фильтр по репозиторию", r.returncode == 0 and "записей нет" in r.stdout)


if __name__ == "__main__":
    sys.exit(main())
