#!/usr/bin/env python3
"""Сверка guard с настоящей оболочкой: каждая команда выполняется в zsh и bash на временном HOME, и если
оболочка изменила ~/ai/pantheon (или ~/ai/pantheon-view), а guard команду пропустил, — это обход разбора.

Запуск: python3 -I plugins/guard/tests/test_shell_diff.py [--verbose]   (код выхода 0 — обходов нет)
Команды меняют только временную папку: HOME подменён, пути в них — через ~ и относительные, /tmp не трогают.
Обратное (guard отказал, оболочка ничего не изменила) — не ошибка: guard берёт надмножество; с --verbose
такие случаи печатаются, чтобы видеть цену запаса.
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="shell_diff-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
SHELLS = [s for s in ("/bin/zsh", "/bin/bash") if os.path.exists(s)]
PROJECT = "projects/brokerAssistantApp"

# Цели: разные записи одного и того же файла ~/ai/pantheon/alerts.md (и папки ~/ai/pantheon)
TARGETS = [
    "~/ai/pantheon/alerts.md", "$HOME/ai/pantheon/alerts.md", '"$HOME"/ai/pantheon/alerts.md', "~/ai/pan''theon/alerts.md",
    "~/ai/pantheon/alert?.md", "~/ai/pantheon/{alerts,zz}.md", "../../ai/pantheon/alerts.md", "~/ai/PANTHEON/alerts.md",
    "~/ai/pantheon/./x/../alerts.md", '~/ai/"pantheon"/alerts.md', "~/ai/pantheon/a*s.md", "$PWD/../../ai/pantheon/alerts.md",
    "~/ai/pantheon/al\\erts.md", "${HOME}/ai/pantheon/alerts.md", "~+/../../ai/pantheon/alerts.md",
]
# Действия записи
ACTIONS = [
    "rm -f {t}", "echo x > {t}", "echo x >> {t}", "touch {t}", "cp /dev/null {t}", "mv {t} ~/tmp/moved",
    "sed -i '' 's/^/x/' {t}", "perl -pi -e 's/^/x/' {t}", "tee {t} </dev/null >/dev/null", "chmod 000 {t}",
    "dd if=/dev/null of={t} 2>/dev/null", "echo x >| {t}", "echo x 2>&1 >{t}", "echo x &> {t}",
    "ln -sf ~/tmp/z {t}", "find {t} -delete", "rsync /dev/null {t}",
]
# Обёртки и формы команд
WRAPS = [
    "{c}", "command {c}", "env {c}", "env -i HOME=$HOME PATH=$PATH {c}", "nice -n 1 {c}", "\\{c}",
    "bash -c {q}", "sh -c {q}", "zsh -c {q}", "eval {q}", "{{ {c}; }}", "( {c} )", "if true; then {c}; fi",
    "true && {c}", "false || {c}", "true\n{c}", "X=1 {c}", "for i in 1; do {c}; done", "echo $(true) && {c}",
    "true | {c}", "! {c}", "time {c}", "nohup {c} >/dev/null 2>&1", "f() {{ {c}; }}; f", "echo {q} | sh",
    "sh <<'EOF'\n{c}\nEOF", "cat <<EOF >/dev/null\n$({c})\nEOF", "x=$({c})", "echo `{c}`", "cd ~/tmp && cd - >/dev/null && {c}",
]
# Отдельные случаи: обходы из проверки безопасности и формы zsh
EXTRA = [
    "cd ~/ai/pantheon\nrm alerts.md", "echo $'\\'' > ~/ai/pantheon/alerts.md #'", "touch {.,~/ai/pantheon}/alerts.md",
    "command -p rm ~/ai/pantheon/alerts.md", "read D <<< ~/ai/pantheon; echo x > $D/alerts.md",
    "for d in ~/ai/pantheon; do echo x > $d/alerts.md; done", "echo x > ${P:-~/pantheon}/alerts.md",
    "set -- ~/ai/pantheon; echo x > $1/alerts.md", "pushd ~/ai/pantheon >/dev/null && rm alerts.md",
    "cd ~/ai/pantheon; cd ~/tmp; cd -; rm alerts.md", "f() { rm ~/ai/pantheon/alerts.md; }; f",
    "if true; then rm ~/ai/pantheon/alerts.md; fi", "echo x >! ~/ai/pantheon/alerts.md", "=rm ~/ai/pantheon/alerts.md",
    "echo x > >(cat > ~/ai/pantheon/alerts.md)", "cat <(rm ~/ai/pantheon/alerts.md)", "r\\\nm ~/ai/pantheon/alerts.md",
    "exec -a x rm ~/ai/pantheon/alerts.md", "echo ~/ai/pantheon/alerts.md | xargs rm",
    "find ~/ai/pantheon -name alerts.md -exec sh -c 'rm \"$0\"' {} \\;", "export P=$(echo ~); rm $P/ai/pantheon/alerts.md",
    "cd ~/ai/pantheon; cd ~/tmp; rm ~-/alerts.md", "noglob rm ~/ai/pantheon/alerts.md", "{ rm ~/ai/pantheon/alerts.md}",
    "{rm ~/ai/pantheon/alerts.md}", "if [[ -n x ]] rm ~/ai/pantheon/alerts.md", "for f (~/ai/pantheon/alerts.md) rm $f",
    "rm ~/ai/pantheon/(alerts|zz).md", "rm ~/ai/pantheon/alerts.md(.)", "repeat 1 rm ~/ai/pantheon/alerts.md",
    "X=~/ai/pantheon; (X=~/tmp); rm $X/alerts.md", "cd /nonexistent-dir 2>/dev/null || rm alerts.md",
    "true | cd ~/ai/pantheon; rm alerts.md", "ln -s ~/ai/pantheon/alerts.md l && echo x > l", "ln -s ~/ai/pantheon p; rm p/alerts.md",
    "cd ~/ai; rm -rf pantheon/alerts.md", "cd ~/ai/pantheon/directions && rm -rf ../alerts.md", "git -C ~/ai/pantheon add -A",
    "cd ~/ai/pantheon/directions && git add -A", "arr=(~/ai/pantheon/alerts.md); rm $arr", "X='a b'; rm $X ~/ai/pantheon/alerts.md",
    "IFS=:; X=a:~/ai/pantheon/alerts.md; rm $X", "D=~/ai/pantheon; f() { rm $D/alerts.md; }; D=~/tmp; f",
    "hash -p /bin/rm myrm 2>/dev/null; myrm ~/ai/pantheon/alerts.md", "mkdir -p ~/ai/pantheon/zz", "rm -rf ~/ai/pantheon/",
    "cd ~/ai/pantheon && rm -- -x alerts.md", "rm -rf ~/ai/pantheon-view/board.md", "echo x > ~/ai/pantheon-view/new.md",
    "cp -R ~/tmp/. ~/ai/pantheon/", "tar -cf ~/ai/pantheon/alerts.md ~/tmp", "cd ~/ai/pantheon && tar -xf ~/tmp/a.tar",
    "cd ~/ai/pantheon && unzip -o ~/tmp/a.zip >/dev/null", "awk 'BEGIN{print \"x\" > \"'$HOME'/ai/pantheon/alerts.md\"}'",
    "sed -n 'w '$HOME'/ai/pantheon/alerts.md' /dev/null", "gzip ~/ai/pantheon/alerts.md", "sort -o ~/ai/pantheon/alerts.md /dev/null",
    "zsh -fc 'rm ~/ai/pantheon/alerts.md'", "bash -ec 'rm ~/ai/pantheon/alerts.md'", "sh -s <<< 'rm ~/ai/pantheon/alerts.md'",
    "trap 'rm ~/ai/pantheon/alerts.md' EXIT", "eval \"$(echo rm ~/ai/pantheon/alerts.md)\"", "x=rm; $x ~/ai/pantheon/alerts.md",
    "${=:-rm} ~/ai/pantheon/alerts.md", "RM ~/ai/pantheon/alerts.md", "/BIN/RM ~/ai/pantheon/alerts.md",
    "rm ~/ai/pantheon/ALERTS.MD", "cd ~/ai/pantheon && rm *.md", "rm ~/ai/pantheon/.git/HEAD", "rm -rf ~/ai/pantheon/.g*",
    "cd ~/ai/pantheon; echo x | tee -a alerts.md", "cd ~/ai/pantheon && echo x > 'alerts.md'", "cd ~/ai && echo x > pantheon/alerts.md",
    "cd ~/projects && cd ../ai/pantheon && rm alerts.md", "mv ~/ai/pantheon ~/tmp/p2", "rm -rf ~/projects/..",
    # раунд 3: модификаторы и срезы zsh, квалификаторы с кодом, cdpath, опции git
    "echo x > $PWD:h:h/ai/pantheon/alerts.md", "echo x > \"$PWD:h:h\"/ai/pantheon/alerts.md",
    "X=$HOME/ai/pantheon/alerts.md; rm -f $X[1,500]", "cd ~/ai/pantheon && ls *(e:'rm -f alerts.md':) >/dev/null",
    "cdpath=(~/ai); cd pantheon && rm alerts.md", "git diff --no-index --output=$HOME/ai/pantheon/alerts.md /dev/null ~/tmp/z",
    "cd ~/tmp && git grep --no-index -O'rm -f ~/ai/pantheon/alerts.md' line",
    "X=--output=$HOME/ai/pantheon/alerts.md; git diff --no-index $X /dev/null ~/tmp/z",
]


def build(home):
    for d in ("ai/pantheon/directions/athena-broker", "ai/pantheon/directions/hermes-alex/inbox", "ai/pantheon/.git",
              "ai/pantheon-view", ".local/state/pantheon", ".claude/pantheon", PROJECT + "/src", "tmp"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    for f in ("ai/pantheon/board.md", "ai/pantheon/alerts.md", "ai/pantheon/.git/HEAD", "ai/pantheon-view/board.md",
              PROJECT + "/src/a.ts", "tmp/z"):
        with open(os.path.join(home, f), "w") as fh:
            fh.write("line\n")
    json.dump({"domains": {"athena-broker": ["~/" + PROJECT], "hermes-alex": ["~/projects/alexbroker"]}},
              open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    subprocess.run(["tar", "-cf", os.path.join(home, "tmp/a.tar"), "-C", os.path.join(home, "tmp"), "z"], check=True)
    subprocess.run(["zip", "-q", os.path.join(home, "tmp/a.zip"), "z"], cwd=os.path.join(home, "tmp"), check=True)


def snapshot(home):
    res = {}
    for top in ("ai/pantheon", "ai/pantheon-view"):
        root = os.path.join(home, top)
        if not os.path.lexists(root):
            res[top] = "нет"
            continue
        for dirpath, dirs, files in os.walk(root):
            for name in dirs + files:
                p = os.path.join(dirpath, name)
                st = os.lstat(p)
                h = ""
                if os.path.isfile(p) and not os.path.islink(p):
                    try:
                        h = hashlib.sha1(open(p, "rb").read()).hexdigest()
                    except OSError:
                        h = "?"
                res[os.path.relpath(p, home)] = (st.st_mode, st.st_ino, st.st_mtime_ns, h, os.path.islink(p))
    return res


def guard_says(home, cmd, role):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
             "cwd": os.path.join(home, PROJECT), "agent_type": role}
    env = {"HOME": home, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": os.path.join(home, PROJECT),
           "TMPDIR": os.path.join(home, "tmp")}
    r = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(event), capture_output=True, text=True,
                       env=env, timeout=20)
    return "deny" if r.returncode == 2 or '"deny"' in r.stdout else "allow"  # код 2 — сбой, отказ (metis-0094)


def shell_changes(home, shell, cmd):
    shutil.rmtree(home)
    os.makedirs(home)
    build(home)
    before = snapshot(home)
    env = {"HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": os.path.join(home, "tmp"), "LANG": "C"}
    args = [shell, "-f", "-c", cmd] if shell.endswith("zsh") else [shell, "--norc", "--noprofile", "-c", cmd]
    try:
        subprocess.run(args, cwd=os.path.join(home, PROJECT), env=env, capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        pass
    after = snapshot(home)
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def cases():
    """Два среза вместо полного произведения: все обёртки × все действия на одной цели и все действия × все цели."""
    seen = []
    pairs = [(w, a, TARGETS[0]) for w in WRAPS for a in ACTIONS] + [("{c}", a, t) for a in ACTIONS for t in TARGETS]
    for w, a, t in pairs:
        c = a.format(t=t)
        cmd = w.format(c=c, q=shlex.quote(c))
        if cmd not in seen:
            seen.append(cmd)
    return seen + EXTRA


# Что закрыто от роли: координатору — весь ~/ai/pantheon (кроме своего направления, его тут не трогают) и копия;
# штабу — alerts.md, .git и копия (остальное в ~/ai/pantheon он правит сам).
ROLES = {
    "domain-coordinator": ("ai/pantheon", "ai/pantheon-view"),
    "hq": ("ai/pantheon/alerts.md", "ai/pantheon/.git", "ai/pantheon-view"),
}


def check(cmd):
    """→ (команда, {роль: оболочки, где закрытое изменилось}, {роль: решение guard}). Своя временная папка."""
    base = os.path.realpath(tempfile.mkdtemp(prefix="guard-diff-"))
    home = os.path.join(base, "home")
    try:
        os.makedirs(home)
        changes = {sh: shell_changes(home, sh, cmd) for sh in SHELLS}
        shutil.rmtree(home, ignore_errors=True)
        os.makedirs(home)
        build(home)
        changed = {role: [sh for sh, ch in changes.items()
                          if any(k == p or k.startswith(p + "/") or k in ("ai", "ai/pantheon") for k in ch for p in closed)]
                   for role, closed in ROLES.items()}
        return cmd, changed, {role: guard_says(home, cmd, role) for role in ROLES}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def run_all(all_cases):
    """Процессы, а в песочнице окна (ProcessPoolExecutor → os.sysconf("SC_SEM_NSEMS_MAX") → PermissionError) —
    потоки: работа — подпроцессы оболочек и guard, так что результат тот же, меняется только способ раздачи."""
    workers = max(2, (os.cpu_count() or 4) - 1)
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(check, all_cases, chunksize=8))
    except (PermissionError, OSError):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(check, all_cases))


def main():
    verbose = "--verbose" in sys.argv
    if not SHELLS:
        print("нет /bin/zsh и /bin/bash — пропуск")
        return
    all_cases = cases()
    results = run_all(all_cases)
    bypass = [(r, c, ch[r]) for c, ch, v in results for r in ROLES if ch[r] and v[r] == "allow"]
    extra = [(r, c) for c, ch, v in results for r in ROLES if not ch[r] and v[r] == "deny"]
    if verbose:
        for r, c in extra:
            print("запас:", r, repr(c)[:140])
    for r, cmd, shells in bypass:
        print("ОБХОД", r, ",".join(os.path.basename(s) for s in shells), repr(cmd))
    print(f"\n{len(results)} команд × {len(ROLES)} роли, оболочки: {', '.join(SHELLS)}; обходов: {len(bypass)}; "
          f"отказов с запасом: {len(extra)}")
    sys.exit(1 if bypass else 0)


if __name__ == "__main__":
    main()
