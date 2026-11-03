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
    """Самотест разбора: формы, которые регулярка пропустила бы, обязаны быть пойманы (мутант forbidden=set() убит)."""
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
    # п. 8 (27.10) + гибрид 03.11 (metis-0688): на GitHub — только PR с затронутым на Linux; полный набор — локально через
    # `pantheon outside test` (запись FULL_TESTS). macOS на GitHub нет (квота Free, минута macOS ×10), полного набора на push нет.
    text = open(os.path.join(wfdir, "tests.yml")).read()
    tst, why = wf_parse(os.path.join(wfdir, "tests.yml"))
    uses = tst["uses"] if tst else None
    check("tests.yml: Action только checkout и setup-python по 40 знакам SHA",
          uses and all(re.fullmatch(r"actions/(checkout|setup-python)@[0-9a-f]{40}", u) for u in uses), uses if tst else why)
    jobs = re.split(r"^jobs:\n", text, flags=re.M)[-1]
    parts = re.split(r"^  (?=[a-z]+:\n)", jobs, flags=re.M)
    job = {m.group(1): part for part in parts if (m := re.match(r"([a-z]+):\n", part))}
    aff = job.get("affected", "")
    check("tests.yml: только чтение, запуск только на PR в main, Python 3.14, без токена в checkout",
          re.search(r"^permissions:\n  contents: read$", text, re.M) and re.search(r"pull_request:\n\s+branches: \[main\]", text)
          and re.search(r"^on:\n  pull_request:\n    branches: \[main\]\n  workflow_dispatch:\n\npermissions:", text, re.M)
          and text.count('python-version: "3.14"') == 2 and text.count("persist-credentials: false") == 2, text)
    # гибрид без macOS (03.11, metis-0688): macOS на GitHub выключен во всех workflow, полный набор на push не идёт
    macos = [n for n in names if re.search(r"macos", re.sub(r"(?m)^\s*#.*$", "", open(os.path.join(wfdir, n)).read()), re.I)]
    check("workflows: ни одного runs-on: macos (квота Free, минута macOS ×10)", not macos, macos)
    # полный набор тестов (run-tests.py без --affected, прямой запуск tests/test_*.py в обход раннера) — только в job с
    # `if: github.event_name == 'workflow_dispatch'`, и только если workflow не запускается на push/schedule/_target; на
    # pull_request такой job SKIPPED (шлюз держит его в OPTIONAL_CHECKS). Комментарии отрезаются до проверки; смотрим все файлы.
    nocomment = lambda t: "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in t.splitlines())
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
            if not re.search(r"^    if: github\.event_name == 'workflow_dispatch'$", part, re.M):
                full_bad.append((n, "полный набор в job без if: workflow_dispatch", jname))
            if re.search(r"\b(push|schedule|pull_request_target)\b", won):
                full_bad.append((n, "workflow с полным набором запускается на push/schedule", jname))
    check("полный набор тестов — только в job с if: github.event_name == 'workflow_dispatch' и в workflow без "
          "push/schedule (комментарии не в счёт, все файлы workflows)", not full_bad, full_bad)
    # runs-on — только закреплённый Linux (или ubuntu-latest у release и check-traces): выражение, список, matrix и
    # self-hosted не пускаем
    ro = [(n, m) for n in names for m in re.findall(r"^\s*runs-on:\s*(.*)$", nocomment(open(os.path.join(wfdir, n)).read()), re.M)
          if not re.fullmatch(r"ubuntu-(\d\d\.\d\d|latest)", m.strip())]
    check("workflows: runs-on — только ubuntu-NN.NN или ubuntu-latest (без выражений, списков, matrix)", not ro, ro)
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
    check("tests.yml: PR — job affected на закреплённом Linux, full — ручной на Linux (минута macOS ×10), полная история для merge-base",
          tst is not None and sorted(tst["jobs"]) == ["affected", "full"] and set(job) == {"affected", "full"}
          and re.search(r"^    if: github.event_name == 'pull_request'$", aff, re.M)
          and re.search(r"^    runs-on: ubuntu-\d\d\.\d\d$", aff, re.M) and "fetch-depth: 0" in aff
          and re.search(r"^    runs-on: ubuntu-\d\d\.\d\d$", job.get("full", ""), re.M), job.keys())

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
    ar = [ln for _, lines in asteps[1:] for ln in lines]
    check("tests.yml: affected — после ruff тесты скриптов выпуска, затем раннер --affected по трём плагинам; код 3 — успех, "
          "остальные коды — job красный (строки run целиком, без комментариев и лишних ветвей)",
          ar == ["python3 -I .github/scripts/test_release.py", "python3 --version", "code=0", call,
                 'if [ "$code" -eq 3 ]; then', 'echo "нечего гонять: изменения не задевают тесты"', "code=0", "fi",
                 'exit "$code"'], ar)
    fr = [ln for _, lines in runs(job.get("full", "")) for ln in lines]
    check("tests.yml: full — раннер по трём плагинам без --affected, код раннера — код job",
          fr == ["python3 --version", 'python3 -I plugins/pantheon/scripts/run-tests.py -j 3 --log-dir '
                 '"$RUNNER_TEMP/tests" plugins/guard plugins/pantheon plugins/project-tools'], fr)
    req = open(os.path.join(WORKFLOWS, "..", "ruff-requirements.txt"), encoding="utf-8").read()
    check("ruff-requirements.txt: ruff==<точная версия> и хеши sha256 колёс",
          re.search(r"^ruff==\d+\.\d+\.\d+ \\$", req, re.M) and len(re.findall(r"--hash=sha256:[0-9a-f]{64}", req)) >= 1, req)
    check("tests.yml: ${{ }} не в run (инъекция)", not any("${{" in ln for ln in ar + fr + lr), ar + fr + lr)


def t_workflows_on_bad_copies():
    """Сами проверки t_workflows (не только wf_parse) ловят плохую копию workflows: мутант в месте вызова
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
    nofull = real.split("\n  full:\n")[0].rstrip("\n") + "\n"
    full_job = ("\n  full:\n%s    runs-on: %s\n    timeout-minutes: 45\n    steps:\n      - uses: actions/checkout@"
                "11bd71901bbe5b1630ceea73d27597364c9af683\n      - run: python3 -I plugins/pantheon/scripts/run-tests.py -j 3 "
                "plugins/guard\n")
    disp = "    if: github.event_name == 'workflow_dispatch'\n"
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
        ("ruff отдельным job lint (шлюз guard его не знает)",
         dict(tests=ins(real, "  affected:\n", "  lint:\n    if: github.event_name == 'pull_request'\n"
                                              "    runs-on: ubuntu-24.04\n    steps:\n      - run: ruff check .\n\n"
                                              "  affected:\n")),
         "tests.yml: PR — job affected"),
        ("job full на macos-15 в tests.yml", dict(tests=nofull + full_job % (disp, "macos-15")),
         "workflows: ни одного runs-on: macos"),
        ("macos-15 в runs-on у affected", dict(tests=ins(real, "runs-on: ubuntu-24.04", "runs-on: macos-15")),
         "workflows: ни одного runs-on: macos"),
        ("runs-on: macos-15 в release.yml", dict(release=ins(rel_real, "runs-on: ubuntu-latest", "runs-on: macos-15")),
         "workflows: ни одного runs-on: macos"),
        ("job full без if (идёт на PR)", dict(tests=nofull + full_job % ("", "ubuntu-24.04")), full_msg),
        ("job full с if на push", dict(tests=nofull + full_job % ("    if: github.event_name == 'push'\n", "ubuntu-24.04")),
         full_msg),
        ("job full с if на pull_request", dict(tests=nofull + full_job % ("    if: github.event_name == 'pull_request'\n",
                                                                         "ubuntu-24.04")), full_msg),
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
         "workflows: ни одного runs-on: macos"),
        ("runs-on: [self-hosted, linux]", dict(tests=ins(real, "runs-on: ubuntu-24.04", "runs-on: [self-hosted, linux]")),
         "workflows: runs-on — только"),
        ("второй job в release.yml", dict(release=rel_real.rstrip("\n") + "\n  evil-x:\n    runs-on: ubuntu-24.04\n"),
         "release.yml: ровно один job"),
    ]
    for name, kw, prefix in cases:
        got = run_on(**kw)
        check(f"t_workflows краснеет: {name}", any(f.startswith(prefix) for f in got), got)
    got = run_on(release="a: b: c\n")
    check("t_workflows: упавший разбор — причина ruby в сообщении проверки uses",
          any(f.startswith("release.yml: Action только") and "ruby код" in f for f in got), got)




for t in (t_first_and_bump, t_rules, t_refuse, t_push_race, t_reconcile, t_first_parent, t_tree_hash_matches_pantheon,
          t_wf_parse_selftest, t_workflows, t_workflows_on_bad_copies):
    try:
        t()
    except Exception as e:  # noqa: BLE001 — падение случая — провал, остальные идут
        fails.append(f"{t.__name__}: {type(e).__name__} {e}")
for f in fails:
    print("FAIL", f)
print(f"проверок {count}, провалов {len(fails)}")
sys.exit(1 if fails else 0)
