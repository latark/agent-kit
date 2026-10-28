#!/usr/bin/env python3
"""Тесты .github/scripts/release.py и .github/workflows/release.yml (metis-0512): номер версии поднимает Action на
main после слияния, PR его не трогают.

Запуск: python3 -I .github/scripts/test_release.py  (код 0 — все прошли; Python 3.11+, как все тесты
agent-kit, metis-0571). Каждый случай — временный репозиторий с голым origin;
настоящий репозиторий и ~/.gitconfig не трогаются (HOME — временная папка).
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_ROOT = tempfile.mkdtemp(prefix="release-root-")
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(HERE, "release.py")
WORKFLOWS = os.path.join(REPO, ".github", "workflows")
PANTHEON_LIB = os.path.join(REPO, "plugins", "pantheon", "lib")
HOME = os.path.join(_ROOT, "home")
os.makedirs(HOME)
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(HOME=HOME, TMPDIR=_ROOT, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@e", GIT_CONFIG_NOSYSTEM="1")
with open(os.path.join(HOME, ".gitconfig"), "w") as fh:
    fh.write("[user]\n\tname = t\n\temail = t@e\n[init]\n\tdefaultBranch = main\n")
PJ = "plugins/{}/.claude-plugin/plugin.json"
REL = ".claude-plugin/releases.json"
fails = []
count = 0

sys.path.insert(0, HERE)
import release as R  # noqa: E402


def g(d, *args, check=True):
    r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=ENV)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def put(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def manifest(name, ver, desc="d"):
    return '{\n  "name": "%s",\n  "version": "%s",\n  "description": "%s"\n}\n' % (name, ver, desc)


def version(d, name):
    with open(os.path.join(d, PJ.format(name)), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def check(name, cond, info=""):
    global count
    count += 1
    if not cond:
        fails.append(f"{name}: {info}")


def repo():
    """Голый origin с main (guard 0.5.17, pantheon 0.11.84) и рабочий клон на main → (work, origin)."""
    base = tempfile.mkdtemp(prefix="rel-")
    seed, origin, work = (os.path.join(base, n) for n in ("seed", "origin.git", "work"))
    subprocess.run(["git", "init", "-q", "-b", "main", seed], check=True, env=ENV)
    put(seed, PJ.format("guard"), manifest("guard", "0.5.17"))
    put(seed, PJ.format("pantheon"), manifest("pantheon", "0.11.84"))
    put(seed, "plugins/guard/hooks/a.py", "a = 1\n")
    put(seed, "plugins/pantheon/lib/b.py", "b = 1\n")
    put(seed, "README.md", "r\n")
    g(seed, "add", "-A")
    g(seed, "commit", "-qm", "init")
    subprocess.run(["git", "clone", "-q", "--bare", seed, origin], check=True, env=ENV)
    subprocess.run(["git", "clone", "-q", origin, work], check=True, env=ENV)
    return work, origin


def merge_pr(work, files, msg="pr"):
    """Слияние PR в main клона (--no-ff, как gh pr merge --merge): ветка от main, коммит, merge."""
    g(work, "checkout", "-q", "-b", "pr-" + str(abs(hash((msg, tuple(files)))) % 10 ** 8), "main")
    for rel, text in files.items():
        put(work, rel, text)
    g(work, "add", "-A")
    g(work, "commit", "-qm", msg)
    br = g(work, "rev-parse", "--abbrev-ref", "HEAD")
    g(work, "checkout", "-q", "main")
    g(work, "merge", "-q", "--no-ff", "-m", f"Merge pull request ({msg})", br)


def run(work, *args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, *args], cwd=work, capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout + r.stderr


def released(work):
    with open(os.path.join(work, REL), encoding="utf-8") as fh:
        return json.load(fh)


def t_first_and_bump():
    w, _o = repo()
    rc, out = run(w)
    check("первый запуск: только запись releases.json, номера те же", rc == 0 and version(w, "guard") == "0.5.17"
          and g(w, "log", "-1", "--format=%s") == f"выпуск: запись {REL}", out)
    rec = released(w)
    check("releases.json: версия и счёт дерева каждого плагина",
          rec["v"] == 1 and rec["plugins"]["guard"] == {"version": "0.5.17",
                                                       "tree": R.tree_hash(os.path.join(w, "plugins/guard"))}
          and set(rec["plugins"]) == {"guard", "pantheon"}, rec)
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 2\n"})
    rc, out = run(w)
    check("слит PR в guard: guard +1, pantheon тот же", rc == 0 and version(w, "guard") == "0.5.18"
          and version(w, "pantheon") == "0.11.84", out)
    check("коммит выпуска: только plugin.json guard и releases.json",
          sorted(g(w, "diff", "--name-only", "HEAD~1", "HEAD").split()) == sorted([PJ.format("guard"), REL]), out)
    check("коммит выпуска: сообщение и автор", g(w, "log", "-1", "--format=%s|%an")
          == "выпуск: guard 0.5.18|github-actions[bot]", g(w, "log", "-1", "--format=%s|%an"))
    diff = g(w, "diff", "-U0", "HEAD~1", "HEAD", "--", PJ.format("guard"))
    check("в plugin.json изменена одна строка version", diff.count("\n+  ") == 1 and diff.count("\n-  ") == 1
          and '"version": "0.5.18"' in diff, diff)
    check("запись guard — дерево после подъёма", released(w)["plugins"]["guard"]
          == {"version": "0.5.18", "tree": R.tree_hash(os.path.join(w, "plugins/guard"))}, released(w))
    head = g(w, "rev-parse", "HEAD")
    rc, out = run(w)
    check("повтор: поднимать нечего, без коммита", rc == 0 and "поднимать нечего" in out
          and g(w, "rev-parse", "HEAD") == head, out)
    merge_pr(w, {"README.md": "r2\n"}, "docs")
    head = g(w, "rev-parse", "HEAD")
    rc, out = run(w)
    check("слит PR без плагинов: выпуска нет", rc == 0 and g(w, "rev-parse", "HEAD") == head, out)
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 3\n"}, "second")
    rc, out = run(w)
    check("второе слияние подряд — следующий номер", rc == 0 and version(w, "guard") == "0.5.19", out)


def t_rules():
    w, _o = repo()
    run(w)
    merge_pr(w, {PJ.format("pantheon"): manifest("pantheon", "0.11.84", desc="new")}, "desc")
    rc, out = run(w)
    check("правка plugin.json кроме version — выпуск", rc == 0 and version(w, "pantheon") == "0.11.85"
          and json.load(open(os.path.join(w, PJ.format("pantheon"))))["description"] == "new", out)
    # PR старого порядка: поднял номер сам вместе с кодом — слияние и есть выпуск
    merge_pr(w, {"plugins/pantheon/lib/b.py": "b = 2\n", PJ.format("pantheon"): manifest("pantheon", "0.11.90", "new")},
             "legacy")
    rc, out = run(w)
    check("слияние, поднявшее номер само, — выпуск: номер не трогается", rc == 0 and version(w, "pantheon") == "0.11.90"
          and released(w)["plugins"]["pantheon"]["version"] == "0.11.90", out)
    # правка и откат: дерево как на выпуске — поднимать нечего
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 9\n"}, "x")
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 1\n"}, "revert x")
    head = g(w, "rev-parse", "HEAD")
    rc, out = run(w)
    check("правка и её откат — выпуска нет", rc == 0 and version(w, "guard") == "0.5.17"
          and g(w, "rev-parse", "HEAD") == head, out)
    # соседняя папка с общим началом имени не трогает плагин
    merge_pr(w, {"plugins/guardian/x.py": "x\n"}, "guardian")
    rc, out = run(w)
    check("plugins/guardian без plugin.json — guard не тронут", rc == 0 and version(w, "guard") == "0.5.17", out)
    # releases.json правили руками (битый) — перезаписывается без подъёма номеров
    put(w, REL, "{не json")
    g(w, "commit", "-qam", "broken")
    rc, out = run(w)
    check("битый releases.json перезаписан, номера те же", rc == 0 and released(w)["plugins"]["guard"]["version"]
          == "0.5.17" and version(w, "pantheon") == "0.11.90", out)


def t_refuse():
    w, _o = repo()
    put(w, "plugins/guard/hooks/a.py", "dirty\n")
    rc, out = run(w)
    check("грязное дерево — код 1, причина последней строкой", rc == 1 and out.strip().splitlines()[-1].startswith(
        "release: дерево не чистое"), out)
    g(w, "checkout", "-q", "--", ".")
    merge_pr(w, {PJ.format("guard"): manifest("guard", "x.y"), "plugins/guard/hooks/a.py": "a = 5\n"}, "bad")
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 6\n"}, "after bad")
    rc, out = run(w)
    check("version не числа — код 1", rc == 1 and "не разобрать" in out.strip().splitlines()[-1], out)
    w, _o = repo()
    merge_pr(w, {PJ.format("guard"): '{"name": "guard", "version": "0.5.17", "x": {"version": "1"}}\n',
                 "plugins/guard/hooks/a.py": "a = 7\n"}, "two")
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 8\n"}, "two-after")
    rc, out = run(w)
    check("две строки version — код 1, без коммита", rc == 1 and "не одна строка version" in out
          and g(w, "status", "--porcelain") == "", out)
    w, _o = repo()
    merge_pr(w, {PJ.format("guard"): '{"name": "guard", "version": "0.5.17", "name": "g"}\n',
                 "plugins/guard/hooks/a.py": "a = 7\n"}, "dup")
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 8\n"}, "dup-after")
    rc, out = run(w)
    check("повторный ключ в plugin.json — код 1", rc == 1 and "повторный ключ" in out, out)
    rc, out = run(w, "--nope")
    check("неверный вызов — код 2", rc == 2, out)
    # не тот репозиторий: плагинов нет — отказ без коммита, а не пустой releases.json
    empty = tempfile.mkdtemp(prefix="rel-empty-")
    subprocess.run(["git", "init", "-q", "-b", "main", empty], check=True, env=ENV)
    put(empty, "README.md", "r\n")
    g(empty, "add", "-A")
    g(empty, "commit", "-qm", "init")
    rc, out = run(empty)
    check("репозиторий без плагинов — код 1, без коммита и releases.json", rc == 1
          and "нет ни одного plugin.json" in out.strip().splitlines()[-1]
          and g(empty, "rev-list", "--count", "HEAD") == "1" and not os.path.exists(os.path.join(empty, REL)), out)


def t_push_race():
    """Второе слияние приходит между fetch и push: push отказан, пересчёт на свежем main покрывает оба."""
    w, origin = repo()
    run(w, "--push")
    other = os.path.join(os.path.dirname(w), "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, env=ENV)
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 2\n"}, "first")
    g(w, "push", "-q", "origin", "main")
    marker = os.path.join(os.path.dirname(w), "raced")
    hook = os.path.join(w, ".git", "hooks", "pre-push")
    with open(hook, "w") as fh:
        fh.write("#!/bin/sh\n[ -f %s ] && exit 0\ntouch %s\nunset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE\n"
                 "cd %s && git pull -q origin main && echo 'b = 2' > plugins/pantheon/lib/b.py && "
                 "git commit -qam second && git push -q origin HEAD:main\nexit 0\n" % (marker, marker, other))
    os.chmod(hook, 0o755)
    rc, out = run(w, "--push")
    check("гонка: код 0 после повтора", rc == 0 and "попытка 1 не прошла" in out, out)
    g(w, "fetch", "-q", "origin")
    check("гонка: на origin/main выпуск поверх второго слияния, оба плагина подняты",
          g(w, "log", "-1", "--format=%s", "origin/main") == "выпуск: guard 0.5.18, pantheon 0.11.85"
          and g(w, "log", "-1", "--format=%s", "origin/main~1") == "second", g(w, "log", "--oneline", "-4", "origin/main"))
    os.remove(hook)
    # origin отказывает всегда — три попытки и код 1
    with open(os.path.join(origin, "hooks", "pre-receive"), "w") as fh:
        fh.write("#!/bin/sh\necho nope >&2\nexit 1\n")
    os.chmod(os.path.join(origin, "hooks", "pre-receive"), 0o755)
    g(w, "checkout", "-q", "main")
    g(w, "reset", "-q", "--hard", "origin/main")
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 3\n"}, "third")
    # третьего слияния на origin нет (push отказан), поэтому выпуск считает от origin/main — правку берём через origin
    os.remove(os.path.join(origin, "hooks", "pre-receive"))
    g(w, "push", "-q", "origin", "main")
    with open(os.path.join(origin, "hooks", "pre-receive"), "w") as fh:
        fh.write("#!/bin/sh\necho nope >&2\nexit 1\n")
    os.chmod(os.path.join(origin, "hooks", "pre-receive"), 0o755)
    rc, out = run(w, "--push")
    check("push отказан всегда — код 1 после трёх попыток, причина последней строкой", rc == 1
          and out.count("не прошла") == 3 and out.strip().splitlines()[-1].startswith("release: push в origin/main не "
                                                                                       "прошёл за 3"), out)


def t_reconcile():
    """Сверка перед коммитом: лишний файл или правка plugin.json не только в version — отказ без коммита."""
    w, _o = repo()
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 9\n"}, "code")
    head = g(w, "rev-parse", "HEAD")
    orig_records, orig_plan = R.records, R.plan

    def stray_records(root):
        put(root, "plugins/guard/hooks/stray.py", "s\n")
        return orig_records(root)

    def wide_plan(root):
        return [(n, o, v, fixed.replace('"description": "d"', '"description": "changed"'))
                for n, o, v, fixed in orig_plan(root)]

    for label, attr, fake, want in (("лишний файл", "records", stray_records, "изменено лишнее"),
                                    ("plugin.json не только version", "plan", wide_plan, "задела не только version")):
        setattr(R, attr, fake)
        try:
            R.release_once(w)
            got = "без отказа"
        except R.Refuse as e:
            got = str(e)
        finally:
            setattr(R, attr, orig_records if attr == "records" else orig_plan)
        check(f"сверка: {label} — отказ, коммита нет", want in got and g(w, "rev-parse", "HEAD") == head, got)
        g(w, "checkout", "-q", "--", ".")
        g(w, "clean", "-qfd")


def t_first_parent():
    """Прошлый выпуск — по первой родительской линии: PR старого порядка поднял номер в своём коммите, а за ним шёл
    ещё коммит кода. Слияние такого PR — уже выпуск: номер второй раз не поднимается."""
    w, _o = repo()
    g(w, "checkout", "-q", "-b", "legacy", "main")
    put(w, PJ.format("guard"), manifest("guard", "0.5.18"))
    g(w, "commit", "-qam", "bump in branch")
    put(w, "plugins/guard/hooks/a.py", "a = 10\n")
    g(w, "commit", "-qam", "code after bump")
    g(w, "checkout", "-q", "main")
    g(w, "merge", "-q", "--no-ff", "-m", "Merge pull request (legacy)", "legacy")
    rc, out = run(w)
    check("PR старого порядка с кодом после подъёма — guard остаётся 0.5.18", rc == 0 and version(w, "guard") == "0.5.18"
          and released(w)["plugins"]["guard"]["version"] == "0.5.18", out)


def t_tree_hash_matches_pantheon():
    """Счёт дерева скрипта выпуска = pantheon._tree_hash: иначе плановый проход ни одной версии не поставит."""
    d = tempfile.mkdtemp(prefix="tree-")
    put(d, ".claude-plugin/plugin.json", "{}")
    put(d, ".hidden", "skip")
    put(d, "a/b.txt", "b")
    put(d, "a/.keep", "nested dot")
    put(d, "a/__pycache__/x.pyc", "skip")
    put(d, "z/.git/HEAD", "skip")
    os.symlink("a/b.txt", os.path.join(d, "link"))
    py = sys.executable
    env = dict(ENV, PANTHEON_HOME=os.path.join(_ROOT, "ph"), PANTHEON_STATE=os.path.join(_ROOT, "ps"),
               PANTHEON_NO_NOTIFY="1")
    r = subprocess.run([py, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pantheon as P; "
                        "print(P._tree_hash(sys.argv[2]))", PANTHEON_LIB, d], capture_output=True, text=True, env=env)
    got = r.stdout.strip()
    check("счёт дерева совпадает с pantheon._tree_hash", r.returncode == 0 and got == R.tree_hash(d),
          f"{py}: {got!r} vs {R.tree_hash(d)!r} {r.stderr[-300:]}")
    put(d, "a/b.txt", "changed")
    check("счёт дерева меняется от содержимого", R.tree_hash(d) != got)


def t_workflows():
    """Право contents: write — только у release.yml; сторонние Action только по полному SHA; запуск — main."""
    names = sorted(n for n in os.listdir(WORKFLOWS) if n.endswith((".yml", ".yaml")))
    write = [n for n in names if re.search(r"^\s*[a-z-]+:\s*write\b", open(os.path.join(WORKFLOWS, n)).read(), re.M)]
    check("право на запись — только release.yml", write == ["release.yml"], write)
    text = open(os.path.join(WORKFLOWS, "release.yml")).read()
    uses = re.findall(r"uses:\s*(\S+)", text)
    check("release.yml: Action только actions/checkout по 40 знакам SHA",
          uses and all(re.fullmatch(r"actions/checkout@[0-9a-f]{40}", u) for u in uses), uses)
    check("release.yml: общий permissions пуст, запись только у job", re.search(r"^permissions: \{\}$", text, re.M)
          and re.findall(r"^\s*contents:\s*write", text, re.M) == ["      contents: write"], text)
    check("release.yml: concurrency без отмены идущего", "group: release-main" in text
          and re.search(r"cancel-in-progress:\s*false", text), text)
    check("release.yml: только push в main и ручной запуск, job — только на main",
          re.search(r"push:\n\s+branches: \[main\]", text) and "pull_request" not in text
          and "if: github.ref == 'refs/heads/main'" in text, text)
    check("release.yml: запускает скрипт ядра --push", "python3 -I .github/scripts/release.py --push" in text, text)
    check("release.yml: ${{ }} не в run (инъекция)", not re.search(r"run:.*\$\{\{", text), text)
    # п. 8 (27.10): тесты до слияния — tests.yml; тик ставит выпуск без своего прогона, красный CI и есть «не ставить»
    text = open(os.path.join(WORKFLOWS, "tests.yml")).read()
    uses = re.findall(r"uses:\s*(\S+)", text)
    check("tests.yml: Action только checkout и setup-python по 40 знакам SHA",
          uses and all(re.fullmatch(r"actions/(checkout|setup-python)@[0-9a-f]{40}", u) for u in uses), uses)
    check("tests.yml: только чтение, PR в main, macOS, Python 3.14",
          re.search(r"^permissions:\n  contents: read$", text, re.M) and re.search(r"pull_request:\n\s+branches: \[main\]", text)
          and re.search(r"runs-on: macos-", text) and 'python-version: "3.14"' in text
          and "persist-credentials: false" in text, text)
    run = text.split("run: |", 1)[-1]
    check("tests.yml: раннер run-tests.py по всем трём плагинам, ${{ }} не в run",
          "plugins/pantheon/scripts/run-tests.py" in run and all(f"plugins/{p}" in run.split("run-tests.py", 1)[-1]
                                                                 for p in ("guard", "pantheon", "project-tools"))
          and "${{" not in run, run)


for t in (t_first_and_bump, t_rules, t_refuse, t_push_race, t_reconcile, t_first_parent, t_tree_hash_matches_pantheon,
          t_workflows):
    try:
        t()
    except Exception as e:  # noqa: BLE001 — падение случая — провал, остальные идут
        fails.append(f"{t.__name__}: {type(e).__name__} {e}")
for f in fails:
    print("FAIL", f)
print(f"проверок {count}, провалов {len(fails)}")
sys.exit(1 if fails else 0)
