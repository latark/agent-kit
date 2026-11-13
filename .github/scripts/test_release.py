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
    g(w, "checkout", "-q", "main")  # скрипт HEAD отвязывает и main не двигает (metis-0814) — подтягиваем сами
    g(w, "reset", "-q", "--hard", "origin/main")
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


def t_push_detach():
    """metis-0814: --push во второй worktree не двигает локальную ветку main, открытую в первой."""
    w, origin = repo()
    second = os.path.join(os.path.dirname(w), "second")
    g(w, "worktree", "add", "-q", "--detach", second, "main")  # w держит main; second отвязана
    merge_pr(w, {"plugins/guard/hooks/a.py": "a = 2\n"}, "pr")
    g(w, "push", "-q", "origin", "main")
    main_before = g(w, "rev-parse", "main")
    rc, out = run(second, "--push")
    check("detach: код 0", rc == 0, out)
    check("detach: локальная main первой worktree не сдвинулась", g(w, "rev-parse", "main") == main_before
          and g(w, "rev-parse", "HEAD") == main_before and g(w, "status", "--porcelain") == "", g(w, "status", "-sb"))
    g(w, "fetch", "-q", "origin")
    check("detach: выпуск ушёл на origin/main", g(w, "log", "-1", "--format=%s", "origin/main").startswith("выпуск: ")
          and g(w, "rev-parse", "origin/main") == g(second, "rev-parse", "HEAD"), g(w, "log", "--oneline", "-3", "origin/main"))
    check("detach: HEAD второй worktree отвязан", g(second, "symbolic-ref", "-q", "HEAD", check=False) == "")


def t_push_from_main():
    """metis-0818 (мутант reset --hard FETCH_HEAD): --push из копии, где открыта main и она позади origin, — локальная
    main не сдвигается, HEAD отвязан, выпуск ушёл на origin/main."""
    w, origin = repo()
    main_before = g(w, "rev-parse", "main")
    other = os.path.join(os.path.dirname(w), "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, env=ENV)
    merge_pr(other, {"plugins/guard/hooks/a.py": "a = 3\n"}, "pr-other")
    g(other, "push", "-q", "origin", "main")
    check("main: до запуска копия на ветке main, и она позади origin", g(w, "symbolic-ref", "-q", "HEAD") == "refs/heads/main"
          and g(w, "rev-parse", "main") == main_before, g(w, "status", "-sb"))
    rc, out = run(w, "--push")
    check("main: код 0", rc == 0, out)
    check("main: локальная main не сдвинулась (не reset --hard)", g(w, "rev-parse", "main") == main_before,
          g(w, "status", "-sb"))
    check("main: HEAD отвязан, ветки нет", g(w, "symbolic-ref", "-q", "HEAD", check=False) == "")
    g(w, "fetch", "-q", "origin")
    check("main: выпуск ушёл на origin/main", g(w, "log", "-1", "--format=%s", "origin/main").startswith("выпуск: ")
          and g(w, "rev-parse", "origin/main") == g(w, "rev-parse", "HEAD"), g(w, "log", "--oneline", "-3", "origin/main"))


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


# Запрещённые в tests.yml ключи: подмена оболочки, окружения, каталога и сбоя прячет провал (metis-0597).
WF_FORBIDDEN = {"shell", "defaults", "env", "container", "services", "working-directory", "continue-on-error"}
_WF_WALK = (
    "def w(o, a) case o when Hash then o.each { |k, v| a << k.to_s; w(v, a) } when Array then o.each { |x| w(x, a) } end; a end; "
    "def v(o, key, a) case o when Hash then o.each { |k, x| a << x.to_s if k.to_s == key; v(x, key, a) } "
    "when Array then o.each { |x| v(x, key, a) } end; a end; "
    "d = begin YAML.load_file(ARGV[0], aliases: true) rescue ArgumentError; YAML.load_file(ARGV[0]) end; "
    "steps = []; if d.is_a?(Hash) && d['jobs'].is_a?(Hash) then d['jobs'].each_value { |j| "
    "steps.concat(j['steps']) if j.is_a?(Hash) && j['steps'].is_a?(Array) } end; "
    "steps = steps.select { |s| s.is_a?(Hash) }; "
    "puts JSON.generate({'keys' => w(d, []), 'refs' => v(d, 'ref', []), "
    "'uses' => v(d, 'uses', []), 'repos' => v(d, 'repository', []), "
    "'jobs' => (d.is_a?(Hash) && d['jobs'].is_a?(Hash) ? d['jobs'].keys.map(&:to_s) : []), "
    "'docs' => YAML.load_stream(File.read(ARGV[0])).size, "
    "'step_ifs' => steps.select { |s| s.key?('if') }.map { |s| s['if'].to_s }})"
)


def wf_parse(path):
    """Разбор workflow через ruby -ryaml: {'keys': все ключи mapping любого уровня (в т.ч. из escape, flow, merge-ключа
    `<<`), 'refs': значения ref любого уровня, 'uses': uses любого уровня (job и шаг), 'repos': repository, 'jobs': имена job, 'step_ifs': if шагов} или (None, причина)."""
    rb = shutil.which("ruby")
    if not rb:
        return None, "нет ruby"
    r = subprocess.run([rb, "-rjson", "-ryaml", "-e", _WF_WALK, path], capture_output=True, text=True)
    if r.returncode != 0:
        return None, f"ruby код {r.returncode}: {r.stderr.strip()[-400:] or '(stderr пуст)'}"
    data = json.loads(r.stdout)
    if data["docs"] != 1:
        return None, f"в файле {data['docs']} YAML-документов, нужен один"
    return data, ""


def wf_step_bad(data):
    """Шаг выключается через if или checkout берёт чужой ref — по разбору YAML."""
    return bool(data["step_ifs"] or data["refs"] or data["repos"])


def t_wf_parse_selftest():
    """Самотест разбора: формы, которые регулярка пропустила бы, обязаны быть пойманы (мутант forbidden=set() краснеет)."""
    cases = {
        "escape в ключе": ('jobs:\n  a:\n    "\\x65nv":\n      X: 1\n    steps: []\n', "env"),
        "continue-on-error во flow-шаге": ("jobs:\n  a:\n    steps:\n      - {name: x, run: y, continue-on-error: true}\n",
                                           "continue-on-error"),
        "merge-ключ <<": ("jobs:\n  a:\n    steps:\n      - run: y\n        <<: {env: {X: 1}}\n", "env"),
    }
    d = tempfile.mkdtemp(prefix="wfself-")
    for name, (text, want) in cases.items():
        path = put(d, name.replace(" ", "_") + ".yml", text) or os.path.join(d, name.replace(" ", "_") + ".yml")
        data, why = wf_parse(path)
        check(f"wf_parse: {name} — ключ {want} найден и запрещён",
              data is not None and want in data["keys"] and want in set(data["keys"]) & WF_FORBIDDEN, why or data)
    path = os.path.join(d, "ok.yml")
    put(d, "ok.yml", "jobs:\n  a:\n    if: x\n    steps:\n      - uses: a/b@1\n        with: {ref: main}\n"
        "      - run: z\n        if: y\n")
    data, why = wf_parse(path)
    check("wf_parse: uses, ref, if шага — из разбора, if job-а не в step_ifs",
          data == {"keys": data["keys"], "refs": ["main"], "uses": ["a/b@1"], "repos": [], "jobs": ["a"], "docs": 1, "step_ifs": ["y"]} if data else False,
          why or data)
    check("wf_step_bad: if шага и ref пойманы, чистый файл — нет",
          data is not None and wf_step_bad(data) and wf_step_bad({"step_ifs": [], "refs": ["x"], "repos": []})
          and wf_step_bad({"step_ifs": [], "refs": [], "repos": ["evil/r"]})
          and not wf_step_bad({"step_ifs": [], "refs": [], "repos": []}), data)
    put(d, "job.yml", "jobs:\n  evil-x:\n    uses: evil/repo/.github/workflows/x.yml@main\n    secrets: inherit\n")
    data, why = wf_parse(os.path.join(d, "job.yml"))
    check("wf_parse: uses на уровне job (reusable workflow) виден, имя job с дефисом тоже",
          data is not None and data["uses"] == ["evil/repo/.github/workflows/x.yml@main"] and data["jobs"] == ["evil-x"],
          why or data)
    put(d, "repo.yml", "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + "0" * 40 + "\n        with: {repository: evil/r}\n")
    data, why = wf_parse(os.path.join(d, "repo.yml"))
    check("wf_parse: with.repository виден", data is not None and data["repos"] == ["evil/r"], why or data)
    put(d, "multi.yml", "a: 1\n---\njobs: {}\n")
    data, why = wf_parse(os.path.join(d, "multi.yml"))
    check("wf_parse: два YAML-документа — провал с причиной", data is None and "документов" in why, why)
    bad = put(d, "bad.yml", "a: b: c\n") or os.path.join(d, "bad.yml")
    data, why = wf_parse(bad)
    check("wf_parse: битый YAML — None и причина из stderr ruby", data is None and "ruby код" in why and len(why) > 20, why)


# metis-1111: job full-shard (части полного набора) идёт на каждый PR и вручную — ровно эта строка if
FULL_IF = r"^    if: github\.event_name == 'pull_request' \|\| github\.event_name == 'workflow_dispatch'$"
# metis-1111: job tests.yml — части matrix и собирающие их итог с прежними именами (шлюз guard ищет affected и full)
SHARD_JOBS = ("affected-shard", "affected", "full-shard", "full")
# ${{ }} в run — только эти: их значения пишет сам GitHub (matrix из файла workflow, итог части), а не текст PR
RUN_EXPR_OK = {"${{ matrix.part }}", "${{ needs.affected-shard.result }}", "${{ needs.full-shard.result }}"}


def t_workflows(wfdir=WORKFLOWS):
    """Право contents: write — только у release.yml; сторонние Action только по полному SHA; запуск — main."""
    names = sorted(n for n in os.listdir(wfdir) if n.endswith((".yml", ".yaml")))
    write = [n for n in names if re.search(r"^\s*[a-z-]+:\s*write\b", open(os.path.join(wfdir, n)).read(), re.M)]
    check("право на запись — только release.yml", write == ["release.yml"], write)
    text = open(os.path.join(wfdir, "release.yml")).read()
    rel, why = wf_parse(os.path.join(wfdir, "release.yml"))
    uses = rel["uses"] if rel else None
    check("release.yml: Action только actions/checkout по 40 знакам SHA",
          uses and all(re.fullmatch(r"actions/checkout@[0-9a-f]{40}", u) for u in uses), uses if rel else why)
    check("release.yml: ровно один job release (имена из разбора YAML)", rel is not None and rel["jobs"] == ["release"],
          rel["jobs"] if rel else why)
    check("release.yml: checkout не берёт чужой репозиторий", rel is not None and not rel["repos"],
          rel if rel else why)
    check("release.yml: общий permissions пуст, запись только у job", re.search(r"^permissions: \{\}$", text, re.M)
          and re.findall(r"^\s*contents:\s*write", text, re.M) == ["      contents: write"], text)
    check("release.yml: concurrency без отмены идущего", "group: release-main" in text
          and re.search(r"cancel-in-progress:\s*false", text), text)
    check("release.yml: только push в main и ручной запуск, job — только на main",
          re.search(r"push:\n\s+branches: \[main\]", text) and "pull_request" not in text
          and "if: github.ref == 'refs/heads/main'" in text, text)
    check("release.yml: запускает скрипт ядра --push", "python3 -I .github/scripts/release.py --push" in text, text)
    check("release.yml: ${{ }} не в run (инъекция)", not re.search(r"run:.*\$\{\{", text), text)
    # п. 8 (27.10) + metis-1111 (13.11, репозиторий публичный): на каждый PR в main — affected на закреплённом Linux и
    # полный набор (job full) на macos-15; полного набора на push и по расписанию нет. Гибрид без macOS (metis-0688) снят.
    text = open(os.path.join(wfdir, "tests.yml")).read()
    tst, why = wf_parse(os.path.join(wfdir, "tests.yml"))
    uses = tst["uses"] if tst else None
    check("tests.yml: Action только checkout и setup-python по 40 знакам SHA",
          uses and all(re.fullmatch(r"actions/(checkout|setup-python)@[0-9a-f]{40}", u) for u in uses), uses if tst else why)
    jobs = re.split(r"^jobs:\n", text, flags=re.M)[-1]
    parts = re.split(r"^  (?=[a-z-]+:\n)", jobs, flags=re.M)
    job = {m.group(1): part for part in parts if (m := re.match(r"([a-z-]+):\n", part))}
    aff = job.get("affected", "")
    ash = job.get("affected-shard", "")
    fsh = job.get("full-shard", "")
    check("tests.yml: только чтение, запуск только на PR в main, Python 3.14, без токена в checkout",
          re.search(r"^permissions:\n  contents: read$", text, re.M) and re.search(r"pull_request:\n\s+branches: \[main\]", text)
          and re.search(r"^on:\n  pull_request:\n    branches: \[main\]\n  workflow_dispatch:\n\npermissions:", text, re.M)
          and text.count('python-version: "3.14"') == 3 and text.count("persist-credentials: false") == 3, text)
    nocomment = lambda t: "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in t.splitlines())
    # metis-1111: macOS — ровно одна строка `    runs-on: macos-15` в job full-shard (части полного набора) файла
    # tests.yml; любое другое упоминание macos вне комментариев (runs-on у affected, у собирающего full, release.yml,
    # matrix, другой образ) — провал
    macos = []
    for n in names:
        wtext = nocomment(open(os.path.join(wfdir, n)).read())
        if n == "tests.yml":
            parts = re.split(r"(?m)^(?=  [A-Za-z0-9_-]+:\s*$)", wtext)
            wtext = "".join(p.replace("    runs-on: macos-15\n", "", 1) if p.startswith("  full-shard:\n") else p
                            for p in parts)
        if re.search(r"macos", wtext, re.I):
            macos.append(n)
    check("workflows: macos — только `runs-on: macos-15` у job full-shard в tests.yml (affected, full и release — Linux)",
          not macos, macos)
    # полный набор тестов (run-tests.py без --affected, прямой запуск tests/test_*.py в обход раннера) — только в job
    # full-shard файла tests.yml с `if` на pull_request и workflow_dispatch, и только если workflow не запускается на
    # push/schedule/_target (tests/full в OPTIONAL_CHECKS шлюза, слияние не держит). Комментарии отрезаются до проверки; смотрим все файлы.
    full_bad = []
    for n in names:
        wtext = nocomment(open(os.path.join(wfdir, n)).read())
        won, _, wjobs = wtext.partition("\njobs:\n")
        for part in re.split(r"^  (?=[A-Za-z0-9_-]+:\s*$)", wjobs, flags=re.M):
            lines = part.splitlines()
            is_full = any(("run-tests.py" in ln and "--affected" not in ln)
                          or re.search(r"tests/|test_[\w*?\[\]]*\.py", ln.replace(".github/scripts/test_release.py", ""))
                          for ln in lines if re.match(r"\s+(- )?(run:|[^\s:]+ )|\s{8,}\S", ln) or "run:" in ln)
            if not is_full:
                continue
            jname = lines[0].strip() if lines else "?"
            if (n, jname) != ("tests.yml", "full-shard:"):
                full_bad.append((n, "полный набор вне job full-shard файла tests.yml", jname))
            if not re.search(FULL_IF, part, re.M):
                full_bad.append((n, "полный набор в job без if на pull_request и workflow_dispatch", jname))
            if re.search(r"\b(push|schedule|pull_request_target)\b", won):
                full_bad.append((n, "workflow с полным набором запускается на push/schedule", jname))
    check("полный набор тестов — только в job full-shard файла tests.yml с if на pull_request и workflow_dispatch и в "
          "workflow без push/schedule (комментарии не в счёт, все файлы workflows)", not full_bad, full_bad)
    # runs-on — только закреплённый Linux (или ubuntu-latest у release и check-traces) или macos-15 (где — проверка
    # macos выше): выражение, список, matrix и self-hosted не пускаем
    ro = [(n, m) for n in names for m in re.findall(r"^\s*runs-on:\s*(.*)$", nocomment(open(os.path.join(wfdir, n)).read()), re.M)
          if not re.fullmatch(r"ubuntu-(\d\d\.\d\d|latest)|macos-15", m.strip())]
    check("workflows: runs-on — только ubuntu-NN.NN, ubuntu-latest или macos-15 (без выражений, списков, matrix)", not ro, ro)
    # YAML с «: » в простом скаляре GitHub не разбирает — workflow не запускается вовсе (так было после #192)
    rb = shutil.which("ruby")
    load = "ARGV.each { |f| begin YAML.load_file(f, aliases: true) rescue ArgumentError; YAML.load_file(f) end }"
    bad = subprocess.run([rb, "-ryaml", "-e", load, *[os.path.join(wfdir, n) for n in names]],
        capture_output=True, text=True) if rb else None
    check("workflows: каждый .yml разбирается как YAML (ruby -ryaml)", bad is not None and bad.returncode == 0,
          bad.stderr[-300:] if bad else "нет ruby")
    # metis-0597 (долг argus B #198): ключи, if, ref, uses — из разбора YAML (wf_parse), а не регуляркой: экранированный
    # ("\x65nv"), flow ({env: x}), кавычки и merge-ключ дают тот же ключ после разбора. Все уровни, все mapping.
    keys = tst["keys"] if tst else None
    hit = sorted(set(keys) & WF_FORBIDDEN) if keys is not None else None
    check("tests.yml: continue-on-error, shell, defaults, env, container, services, working-directory нигде нет "
          "(ключи из разбора YAML, любой уровень): подмена оболочки, окружения, каталога и сбоя прячет провал",
          keys is not None and not hit, hit if hit is not None else f"разбор YAML не удался: {why}")
    check("tests.yml: ни один шаг не выключается (`if:` только на уровне job), checkout не берёт чужой ref",
          tst is not None and not wf_step_bad(tst), tst if tst else why)
    full = job.get("full", "")
    check("tests.yml: PR — job affected на закреплённом Linux, полная история для merge-base; full — на PR и вручную, "
          "macos-15, timeout-minutes 90 (metis-1111); части — affected-shard и full-shard, собирающие — affected и full",
          tst is not None and sorted(tst["jobs"]) == sorted(SHARD_JOBS) and set(job) == set(SHARD_JOBS)
          and re.search(r"^    if: github.event_name == 'pull_request'$", ash, re.M)
          and re.search(r"^    runs-on: ubuntu-\d\d\.\d\d$", ash, re.M) and "fetch-depth: 0" in ash
          and re.search(FULL_IF, fsh, re.M) and re.search(r"^    runs-on: macos-15$", fsh, re.M)
          and re.search(r"^    timeout-minutes: 90$", fsh, re.M)
          and re.search(r"^    runs-on: ubuntu-\d\d\.\d\d$", aff, re.M)
          and re.search(r"^    runs-on: ubuntu-\d\d\.\d\d$", full, re.M), job.keys())
    # metis-1111: части matrix — fail-fast false (красная часть не гасит соседние), part: [1..N], имя «<job> (K/N)», N
    # раннера (--shard …/N) то же; affected — 4 части, full на macOS — не больше 3 (лимит macOS — 5 job на все PR).
    # Собирающий job: needs — его части, идёт при красной части (!cancelled()), но не при отмене запуска
    nparts = {}
    for sj, cj, cond, cap in (("affected-shard", "affected", "github.event_name == 'pull_request'", (4, 4)),
                              ("full-shard", "full", "(github.event_name == 'pull_request' || "
                                                     "github.event_name == 'workflow_dispatch')", (1, 3))):
        part = job.get(sj, "")
        m = re.search(r"^    strategy:\n      fail-fast: false\n      matrix:\n        part: \[([\d, ]+)\]\n", part, re.M)
        got = [int(x) for x in m.group(1).split(",")] if m else []
        n = len(got)
        nparts[sj] = n
        check(f"tests.yml: {sj} — fail-fast: false, matrix part: [1..N], N от {cap[0]} до {cap[1]}, имя «{sj} (K/N)», "
              "раннер с --shard K/N того же N",
              m is not None and got == list(range(1, n + 1)) and cap[0] <= n <= cap[1]
              and re.search(rf"^    name: {re.escape(sj)} \(\$\{{\{{ matrix\.part \}}\}}/{n}\)$", part, re.M)
              and len(re.findall(r"--shard \$\{\{ matrix\.part \}\}/(\d+)", part)) == 1
              and re.search(rf"--shard \$\{{\{{ matrix\.part \}}\}}/{n} ", part)
              and part.count("matrix") == 3, part)
        coll = job.get(cj, "")
        check(f"tests.yml: собирающий {cj} — needs: {sj}, if: {cond} && !cancelled(), без strategy",
              re.search(rf"^    needs: {re.escape(sj)}$", coll, re.M)
              and re.search(rf"^    if: {re.escape(cond)} && !cancelled\(\)$", coll, re.M)
              and "strategy" not in coll and "matrix" not in coll, coll)

    def runs(part):
        """[(имя шага, [строки run, продолжения через обратную косую склеены])]: строки целиком, комментарий — отдельная строка."""
        out = []
        for st in re.split(r"^      - (?=name:|uses:)", part, flags=re.M)[1:]:
            name = re.search(r"name:\s*(.+)", st)
            m = re.search(r"^        run: (\|\n)?(.*(?:\n.*)*)", st, re.M)
            if not m:
                continue
            body = [ln.strip() for ln in m.group(2).split("\n") if ln.strip()] if m.group(1) else [m.group(2).strip()]
            lines, cur = [], ""
            for ln in body:
                cur += ln[:-1].rstrip() + " " if ln.endswith("\\") else ln
                if not ln.endswith("\\"):
                    lines.append(cur)
                    cur = ""
            out.append((name.group(1) if name else "", lines))
        return out

    call = ('python3 -I plugins/pantheon/scripts/run-tests.py --affected --base origin/main -j 3 '
            '--log-dir "$RUNNER_TEMP/tests" plugins/guard plugins/pantheon plugins/project-tools || code=$?')
    # metis-0265: первый шаг affected — ruff по закреплённой версии и хешам, провал не прячется
    asteps = runs(aff)
    lr = asteps[0][1] if asteps else []
    check("tests.yml: affected — первым шагом ruff: ставится по хешам из .github/ruff-requirements.txt, затем ровно "
          "`ruff check .` (без `|| true`, --exit-zero и других флагов)",
          lr == ["python3 -m pip install --disable-pip-version-check --require-hashes -r .github/ruff-requirements.txt",
                 "ruff check ."], asteps)
    # metis-0854: вторым шагом — храповик, ровно одна команда без флагов (--update и || true прятали бы рост)
    rt = asteps[1][1] if len(asteps) > 1 else []
    check("tests.yml: affected — вторым шагом храповик: ровно `python3 -I plugins/pantheon/scripts/lint_ratchet.py`",
          rt == ["python3 -I plugins/pantheon/scripts/lint_ratchet.py"], asteps)
    def gather(sj):
        """Строки run собирающего job: красный, если итог частей sj не success."""
        return [f'result="${{{{ needs.{sj}.result }}}}"', 'if [ "$result" != success ]; then',
                f'echo "части {sj}: $result — нужна success у каждой"', "exit 1", "fi", f'echo "части {sj}: success"']

    ar = [ln for _, lines in asteps[2:] for ln in lines]
    check("tests.yml: affected — после ruff и храповика тесты скриптов выпуска, затем итог частей affected-shard: "
          "красный, если хоть одна часть не success (строки run целиком, без комментариев и лишних ветвей)",
          ar == ["python3 -I .github/scripts/test_release.py", *gather("affected-shard")], ar)
    sr = [ln for _, lines in runs(ash) for ln in lines]
    call = call.replace("-j 3 ", f"-j 3 --shard ${{{{ matrix.part }}}}/{nparts.get('affected-shard')} ", 1)
    check("tests.yml: affected-shard — раннер --affected --shard K/N по трём плагинам; код 3 — успех, остальные коды — "
          "часть красная (строки run целиком)",
          sr == ["python3 --version", "code=0", call, 'if [ "$code" -eq 3 ]; then',
                 'echo "нечего гонять: изменения не задевают тесты"', "code=0", "fi", 'exit "$code"'], sr)
    fr = [ln for _, lines in runs(fsh) for ln in lines]
    # metis-1111: первым шагом full-shard ставит тот же ruff по хешам, иначе храповик в run-tests.py пропускается
    check("tests.yml: full-shard — ruff по хешам из .github/ruff-requirements.txt (храповик в раннере), затем раннер "
          "--shard K/N по трём плагинам без --affected, код раннера — код части",
          fr == ["python3 -m pip install --disable-pip-version-check --require-hashes -r .github/ruff-requirements.txt",
                 "python3 --version", "python3 -I plugins/pantheon/scripts/run-tests.py -j 3 --shard "
                 f"${{{{ matrix.part }}}}/{nparts.get('full-shard')} --log-dir "
                 '"$RUNNER_TEMP/tests" plugins/guard plugins/pantheon plugins/project-tools'], fr)
    gr = [ln for _, lines in runs(full) for ln in lines]
    check("tests.yml: full — только итог частей full-shard: красный, если хоть одна часть не success",
          gr == gather("full-shard") and "uses:" not in full, gr)
    req = open(os.path.join(WORKFLOWS, "..", "ruff-requirements.txt"), encoding="utf-8").read()
    check("ruff-requirements.txt: ruff==<точная версия> и хеши sha256 колёс",
          re.search(r"^ruff==\d+\.\d+\.\d+ \\$", req, re.M) and len(re.findall(r"--hash=sha256:[0-9a-f]{64}", req)) >= 1, req)
    allrun = [ln for p in job.values() for _, lines in runs(p) for ln in lines]
    exprs = sorted({e for ln in allrun for e in re.findall(r"\$\{\{.*?\}\}", ln)} - RUN_EXPR_OK)
    check("tests.yml: ${{ }} в run — только matrix.part и needs.<часть>.result (инъекция)",
          allrun and not exprs and not any(ln.count("${{") != len(re.findall(r"\$\{\{.*?\}\}", ln)) for ln in allrun),
          exprs)


def t_workflows_on_bad_copies():
    """Сами проверки t_workflows (не только wf_parse) краснеют на плохой копии workflows: мутант в месте вызова
    (`set(keys) & set()`, снятый wf_step_bad, подменённый список uses) выживать не должен."""
    global count
    real = open(os.path.join(WORKFLOWS, "tests.yml"), encoding="utf-8").read()
    rel_real = open(os.path.join(WORKFLOWS, "release.yml"), encoding="utf-8").read()
    tr_real = open(os.path.join(WORKFLOWS, "check-traces.yml"), encoding="utf-8").read()

    def run_on(tests=None, release=None, traces=None, extra=None):
        d = tempfile.mkdtemp(prefix="wfbad-")
        put(d, "tests.yml", tests if tests is not None else real)
        put(d, "release.yml", release if release is not None else rel_real)
        put(d, "check-traces.yml", traces if traces is not None else tr_real)
        for en, et in (extra or {}).items():
            put(d, en, et)
        saved, n = list(fails), count
        fails.clear()
        try:
            t_workflows(d)
            return list(fails)
        finally:
            fails[:] = saved
            globals()["count"] = n

    clean = run_on()
    check("t_workflows на нетронутой копии — зелёный", not clean, clean)
    ins = lambda text, old, new: text.replace(old, new, 1)
    cases = [
        ("env в job tests.yml", dict(tests=ins(real, "timeout-minutes: 30", "timeout-minutes: 30\n    env: {X: 1}")),
         "tests.yml: continue-on-error, shell"),
        ("if шага в кавычках", dict(tests=ins(real, "      - name: Тесты скриптов выпуска\n",
                                              "      - name: Тесты скриптов выпуска\n        \"if\": \"false\"\n")),
         "tests.yml: ни один шаг не выключается"),
        ("uses на уровне job в tests.yml", dict(tests=real.rstrip("\n") + "\n  evil-x:\n    uses: evil/r/.github/workflows/x.yml@main\n"),
         "tests.yml: Action только"),
        ("uses на уровне job в release.yml", dict(release=rel_real.rstrip("\n") + "\n  evil-x:\n    uses: evil/r/.github/workflows/x.yml@main\n"),
         "release.yml: Action только"),
        ("job с дефисом в tests.yml", dict(tests=real.rstrip("\n") + "\n  evil-x:\n    runs-on: ubuntu-24.04\n"),
         "tests.yml: PR — job affected"),
        ("repository у checkout в release.yml", dict(release=ins(rel_real, "ref: main", "ref: main\n          repository: evil/r")),
         "release.yml: checkout не берёт чужой репозиторий"),
        ("второй YAML-документ в tests.yml", dict(tests=real.rstrip("\n") + "\n---\na: 1\n"), "tests.yml: continue-on-error, shell"),
    ]
    nofull = real.split("\n  full-shard:\n")[0].rstrip("\n") + "\n"
    full_job = ("\n  full-shard:\n%s    runs-on: %s\n    timeout-minutes: 45\n    steps:\n      - uses: actions/checkout@"
                "11bd71901bbe5b1630ceea73d27597364c9af683\n      - run: python3 -I plugins/pantheon/scripts/run-tests.py -j 3 "
                "plugins/guard\n")
    disp = "    if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'\n"
    full_msg = "полный набор тестов — только в job"
    full_msg_all = "полный набор тестов — только в job"
    on_push_wf = ("name: full\non:\n  push:\n    branches: [main]\npermissions:\n  contents: read\njobs:\n  full:\n"
                  "    runs-on: %s\n    steps:\n      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683\n"
                  "      - run: %s\n")
    cases += [
        ("ruff с --exit-zero", dict(tests=ins(real, "          ruff check .", "          ruff check . --exit-zero")),
         "tests.yml: affected — первым шагом ruff"),
        ("ruff с || true", dict(tests=ins(real, "          ruff check .", "          ruff check . || true")),
         "tests.yml: affected — первым шагом ruff"),
        ("ruff без закреплённых хешей", dict(tests=ins(real, " --require-hashes", "")),
         "tests.yml: affected — первым шагом ruff"),
        ("шага ruff нет в affected", dict(tests=ins(real, "          ruff check .\n", "")),
         "tests.yml: affected — первым шагом ruff"),
        ("храповик с || true", dict(tests=ins(real, "lint_ratchet.py\n", "lint_ratchet.py || true\n")),
         "tests.yml: affected — вторым шагом храповик"),
        ("храповик с --update", dict(tests=ins(real, "lint_ratchet.py\n", "lint_ratchet.py --update\n")),
         "tests.yml: affected — вторым шагом храповик"),
        ("шага храповика нет в affected",
         dict(tests=ins(real, "        run: python3 -I plugins/pantheon/scripts/lint_ratchet.py\n", "        run: echo\n")),
         "tests.yml: affected — вторым шагом храповик"),
        ("ruff отдельным job lint (шлюз guard его не знает)",
         dict(tests=ins(real, "  affected:\n", "  lint:\n    if: github.event_name == 'pull_request'\n"
                                              "    runs-on: ubuntu-24.04\n    steps:\n      - run: ruff check .\n\n"
                                              "  affected:\n")),
         "tests.yml: PR — job affected"),
        ("job full на ubuntu-24.04 (не macOS)", dict(tests=ins(real, "runs-on: macos-15", "runs-on: ubuntu-24.04")),
         "tests.yml: PR — job affected"),
        ("job full на macos-latest", dict(tests=ins(real, "runs-on: macos-15", "runs-on: macos-latest")),
         "workflows: macos — только"),
        ("job full с timeout-minutes 60", dict(tests=ins(real, "timeout-minutes: 90", "timeout-minutes: 60")),
         "tests.yml: PR — job affected"),
        ("macos-15 в runs-on у affected", dict(tests=ins(real, "runs-on: ubuntu-24.04", "runs-on: macos-15")),
         "workflows: macos — только"),
        ("runs-on: macos-15 в release.yml", dict(release=ins(rel_real, "runs-on: ubuntu-latest", "runs-on: macos-15")),
         "workflows: macos — только"),
        ("runs-on: macos-15 в check-traces.yml", dict(traces=ins(tr_real, "runs-on: ubuntu-latest", "runs-on: macos-15")),
         "workflows: macos — только"),
        ("job full без if", dict(tests=nofull + full_job % ("", "macos-15")), full_msg),
        ("job full с if на push", dict(tests=nofull + full_job % ("    if: github.event_name == 'push'\n", "macos-15")),
         full_msg),
        ("job full только на workflow_dispatch (на PR не идёт)",
         dict(tests=nofull + full_job % ("    if: github.event_name == 'workflow_dispatch'\n", "macos-15")), full_msg),
        ("job full только на pull_request", dict(tests=nofull + full_job % ("    if: github.event_name == 'pull_request'\n",
                                                                           "macos-15")), full_msg),
        ("полный набор в job affected", dict(tests=ins(real, "        run: python3 -I .github/scripts/test_release.py\n",
                                                       "        run: python3 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard\n")),
         full_msg),
        ("push в main в tests.yml при job full", dict(tests=ins(real, "  workflow_dispatch:\n",
                                                               "  push:\n    branches: [main]\n  workflow_dispatch:\n")),
         full_msg),
        ("schedule в tests.yml при job full", dict(tests=ins(real, "  workflow_dispatch:\n",
                                                            "  schedule:\n    - cron: '0 3 * * *'\n  workflow_dispatch:\n")),
         full_msg),
        ("tests.yml без workflow_dispatch", dict(tests=ins(real, "  workflow_dispatch:\n", "")), "tests.yml: только чтение"),
        ("лишний триггер issues в on у tests.yml", dict(tests=ins(real, "  workflow_dispatch:\n", "  workflow_dispatch:\n  issues:\n")),
         "tests.yml: только чтение"),
        ("on: push с run-tests.py и '# --affected' в комментарии",
         dict(extra={"full.yml": on_push_wf % ("ubuntu-24.04", "python3 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard  # --affected")}),
         full_msg_all),
        ("on: push, обход раннера: python3 -I plugins/*/tests/test_*.py",
         dict(extra={"full.yml": on_push_wf % ("ubuntu-24.04", "for t in plugins/*/tests/test_*.py; do python3 -I $t; done")}),
         full_msg_all),
        ("полный набор в check-traces.yml на push",
         dict(traces=tr_real.replace("      - name: Личных следов нет\n", "      - run: python3 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard\n"
                                     "      - name: Личных следов нет\n", 1)), full_msg_all),
        ("schedule в check-traces.yml с полным набором (в job full с dispatch)",
         dict(traces=tr_real.replace("\njobs:\n", "\n  schedule:\n    - cron: '0 3 * * 1'\njobs:\n", 1).rstrip("\n") + "\n" + full_job.replace("\n  full:", "\n  full:", 1) % (disp, "ubuntu-24.04")),
         full_msg_all),
        ("runs-on: ${{ vars.RUNNER }}", dict(tests=ins(real, "runs-on: ubuntu-24.04", "runs-on: ${{ vars.RUNNER }}")),
         "workflows: runs-on — только"),
        ("matrix os: [macos-15]", dict(tests=ins(real, "    runs-on: ubuntu-24.04\n", "    strategy:\n      matrix:\n        os: [macos-15]\n    runs-on: ${{ matrix.os }}\n")),
         "workflows: macos — только"),
        ("runs-on: [self-hosted, linux]", dict(tests=ins(real, "runs-on: ubuntu-24.04", "runs-on: [self-hosted, linux]")),
         "workflows: runs-on — только"),
        ("второй job в release.yml", dict(release=rel_real.rstrip("\n") + "\n  evil-x:\n    runs-on: ubuntu-24.04\n"),
         "release.yml: ровно один job"),
    ]
    # metis-1111: части matrix и собирающие job
    ash_cut = real.split("\n  affected:\n")[0]
    cases += [
        ("fail-fast: true у affected-shard", dict(tests=ins(real, "\n      fail-fast: false", "\n      fail-fast: true")),
         "tests.yml: affected-shard — fail-fast"),
        ("fail-fast: true у full-shard", dict(tests=real[::-1].replace("fail-fast: false"[::-1], "fail-fast: true"[::-1], 1)[::-1]),
         "tests.yml: full-shard — fail-fast"),
        ("affected-shard: matrix из 3 частей при --shard …/4", dict(tests=ins(real, "part: [1, 2, 3, 4]", "part: [1, 2, 3]")),
         "tests.yml: affected-shard — fail-fast"),
        ("affected-shard: --shard …/3 при 4 частях", dict(tests=ins(real, "matrix.part }}/4 ", "matrix.part }}/3 ")),
         "tests.yml: affected-shard — fail-fast"),
        ("affected-shard без --shard (каждая часть гонит всё)", dict(tests=ins(real, " --shard ${{ matrix.part }}/4", "")),
         "tests.yml: affected-shard — fail-fast"),
        ("affected-shard: имя «affected (K/4)» (шлюз принял бы часть за обязательную affected)",
         dict(tests=ins(real, "name: affected-shard (", "name: affected (")), "tests.yml: affected-shard — fail-fast"),
        ("full-shard: 4 части на macOS (лимит 5 на все PR)",
         dict(tests=real.replace("part: [1, 2, 3]\n", "part: [1, 2, 3, 4]\n").replace("matrix.part }}/3", "matrix.part }}/4")),
         "tests.yml: full-shard — fail-fast"),
        ("full-shard: --shard …/2 при 3 частях", dict(tests=ins(real, "matrix.part }}/3 ", "matrix.part }}/2 ")),
         "tests.yml: full-shard — fail-fast"),
        ("собирающий affected без !cancelled() (при красной части не идёт — пропущенная обязательная)",
         dict(tests=ins(real, "if: github.event_name == 'pull_request' && !cancelled()", "if: github.event_name == 'pull_request'")),
         "tests.yml: собирающий affected"),
        ("собирающий affected на always() (идёт и при отмене запуска)",
         dict(tests=ins(real, "'pull_request' && !cancelled()", "'pull_request' && always()")), "tests.yml: собирающий affected"),
        ("собирающий affected без needs", dict(tests=ins(real, "    needs: affected-shard\n", "")), "tests.yml: собирающий affected"),
        ("собирающий full без needs", dict(tests=ins(real, "    needs: full-shard\n", "")), "tests.yml: собирающий full"),
        ("собирающий affected зелёный при красной части (exit 0)",
         dict(tests=ins(real, "части affected-shard: $result — нужна success у каждой\"\n            exit 1",
                        "части affected-shard: $result — нужна success у каждой\"\n            exit 0")),
         "tests.yml: affected — после ruff"),
        ("собирающий full зелёный при красной части (exit 0)",
         dict(tests=ins(real, "части full-shard: $result — нужна success у каждой\"\n            exit 1",
                        "части full-shard: $result — нужна success у каждой\"\n            exit 0")),
         "tests.yml: full — только итог"),
        ("собирающий affected смотрит не те части", dict(tests=ins(real, '"${{ needs.affected-shard.result }}"',
                                                                  '"${{ needs.full-shard.result }}"')),
         "tests.yml: affected — после ruff"),
        ("собирающий full на macos-15", dict(tests=ins(real, "!cancelled()\n    runs-on: ubuntu-24.04\n    timeout-minutes: 5",
                                                       "!cancelled()\n    runs-on: macos-15\n    timeout-minutes: 5")),
         "workflows: macos — только"),
        ("тесты в собирающем full", dict(tests=real.rstrip("\n") + "\n      - name: x\n        run: python3 -I "
                                         "plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard\n"),
         "полный набор тестов — только в job"),
        ("ruff check . убран из affected (красный ruff не красит обязательную)",
         dict(tests=ins(real, "          ruff check .\n", "          true\n")), "tests.yml: affected — первым шагом ruff"),
        ("${{ github.event.pull_request.title }} в run", dict(tests=ins(real, 'echo "части full-shard: success"',
                                                                       'echo "${{ github.event.pull_request.title }}"')),
         "tests.yml: ${{ }} в run"),
        ("части без собирающего full (job full убран)", dict(tests=real.split("\n  full:\n")[0].rstrip("\n") + "\n"),
         "tests.yml: PR — job affected"),
        ("affected-shard удалён (affected — одним job, как до частей)", dict(tests=real.replace(ash_cut, real.split("\n  affected-shard:\n")[0], 1)),
         "tests.yml: PR — job affected"),
    ]
    for name, kw, prefix in cases:
        got = run_on(**kw)
        check(f"t_workflows краснеет: {name}", any(f.startswith(prefix) for f in got), got)
    got = run_on(release="a: b: c\n")
    check("t_workflows: упавший разбор — причина ruby в сообщении проверки uses",
          any(f.startswith("release.yml: Action только") and "ruby код" in f for f in got), got)




for t in (t_first_and_bump, t_rules, t_refuse, t_push_race, t_push_detach, t_push_from_main, t_reconcile, t_first_parent, t_tree_hash_matches_pantheon,
          t_wf_parse_selftest, t_workflows, t_workflows_on_bad_copies):
    try:
        t()
    except Exception as e:  # noqa: BLE001 — падение случая — провал, остальные идут
        fails.append(f"{t.__name__}: {type(e).__name__} {e}")
for f in fails:
    print("FAIL", f)
print(f"проверок {count}, провалов {len(fails)}")
sys.exit(1 if fails else 0)
