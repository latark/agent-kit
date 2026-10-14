#!/usr/bin/env python3
"""Сверка guard с настоящей оболочкой: каждая команда выполняется в zsh и bash на временном HOME, и если
оболочка изменила ~/pantheon (или ~/pantheon-view), а guard команду пропустил, — это обход разбора.

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
from concurrent.futures import ProcessPoolExecutor

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
SHELLS = [s for s in ("/bin/zsh", "/bin/bash") if os.path.exists(s)]
PROJECT = "projects/brokerAssistantApp"

# Цели: разные записи одного и того же файла ~/pantheon/alerts.md (и папки ~/pantheon)
TARGETS = [
    "~/pantheon/alerts.md", "$HOME/pantheon/alerts.md", '"$HOME"/pantheon/alerts.md', "~/pan''theon/alerts.md",
    "~/pantheon/alert?.md", "~/pantheon/{alerts,zz}.md", "../../pantheon/alerts.md", "~/PANTHEON/alerts.md",
    "~/pantheon/./x/../alerts.md", '~/"pantheon"/alerts.md', "~/pantheon/a*s.md", "$PWD/../../pantheon/alerts.md",
    "~/pantheon/al\\erts.md", "${HOME}/pantheon/alerts.md", "~+/../../pantheon/alerts.md",
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
    "cd ~/pantheon\nrm alerts.md", "echo $'\\'' > ~/pantheon/alerts.md #'", "touch {.,~/pantheon}/alerts.md",
    "command -p rm ~/pantheon/alerts.md", "read D <<< ~/pantheon; echo x > $D/alerts.md",
    "for d in ~/pantheon; do echo x > $d/alerts.md; done", "echo x > ${P:-~/pantheon}/alerts.md",
    "set -- ~/pantheon; echo x > $1/alerts.md", "pushd ~/pantheon >/dev/null && rm alerts.md",
    "cd ~/pantheon; cd ~/tmp; cd -; rm alerts.md", "f() { rm ~/pantheon/alerts.md; }; f",
    "if true; then rm ~/pantheon/alerts.md; fi", "echo x >! ~/pantheon/alerts.md", "=rm ~/pantheon/alerts.md",
    "echo x > >(cat > ~/pantheon/alerts.md)", "cat <(rm ~/pantheon/alerts.md)", "r\\\nm ~/pantheon/alerts.md",
    "exec -a x rm ~/pantheon/alerts.md", "echo ~/pantheon/alerts.md | xargs rm",
    "find ~/pantheon -name alerts.md -exec sh -c 'rm \"$0\"' {} \\;", "export P=$(echo ~); rm $P/pantheon/alerts.md",
    "cd ~/pantheon; cd ~/tmp; rm ~-/alerts.md", "noglob rm ~/pantheon/alerts.md", "{ rm ~/pantheon/alerts.md}",
    "{rm ~/pantheon/alerts.md}", "if [[ -n x ]] rm ~/pantheon/alerts.md", "for f (~/pantheon/alerts.md) rm $f",
    "rm ~/pantheon/(alerts|zz).md", "rm ~/pantheon/alerts.md(.)", "repeat 1 rm ~/pantheon/alerts.md",
    "X=~/pantheon; (X=~/tmp); rm $X/alerts.md", "cd /nonexistent-dir 2>/dev/null || rm alerts.md",
    "true | cd ~/pantheon; rm alerts.md", "ln -s ~/pantheon/alerts.md l && echo x > l", "ln -s ~/pantheon p; rm p/alerts.md",
    "cd ~; rm -rf pantheon/alerts.md", "cd ~/pantheon/directions && rm -rf ../alerts.md", "git -C ~/pantheon add -A",
    "cd ~/pantheon/directions && git add -A", "arr=(~/pantheon/alerts.md); rm $arr", "X='a b'; rm $X ~/pantheon/alerts.md",
    "IFS=:; X=a:~/pantheon/alerts.md; rm $X", "D=~/pantheon; f() { rm $D/alerts.md; }; D=~/tmp; f",
    "hash -p /bin/rm myrm 2>/dev/null; myrm ~/pantheon/alerts.md", "mkdir -p ~/pantheon/zz", "rm -rf ~/pantheon/",
    "cd ~/pantheon && rm -- -x alerts.md", "rm -rf ~/pantheon-view/board.md", "echo x > ~/pantheon-view/new.md",
    "cp -R ~/tmp/. ~/pantheon/", "tar -cf ~/pantheon/alerts.md ~/tmp", "cd ~/pantheon && tar -xf ~/tmp/a.tar",
    "cd ~/pantheon && unzip -o ~/tmp/a.zip >/dev/null", "awk 'BEGIN{print \"x\" > \"'$HOME'/pantheon/alerts.md\"}'",
    "sed -n 'w '$HOME'/pantheon/alerts.md' /dev/null", "gzip ~/pantheon/alerts.md", "sort -o ~/pantheon/alerts.md /dev/null",
    "zsh -fc 'rm ~/pantheon/alerts.md'", "bash -ec 'rm ~/pantheon/alerts.md'", "sh -s <<< 'rm ~/pantheon/alerts.md'",
    "trap 'rm ~/pantheon/alerts.md' EXIT", "eval \"$(echo rm ~/pantheon/alerts.md)\"", "x=rm; $x ~/pantheon/alerts.md",
    "${=:-rm} ~/pantheon/alerts.md", "RM ~/pantheon/alerts.md", "/BIN/RM ~/pantheon/alerts.md",
    "rm ~/pantheon/ALERTS.MD", "cd ~/pantheon && rm *.md", "rm ~/pantheon/.git/HEAD", "rm -rf ~/pantheon/.g*",
    "cd ~/pantheon; echo x | tee -a alerts.md", "cd ~/pantheon && echo x > 'alerts.md'", "cd ~ && echo x > pantheon/alerts.md",
    "cd ~/projects && cd ../pantheon && rm alerts.md", "mv ~/pantheon ~/tmp/p2", "rm -rf ~/projects/..",
    # раунд 3: модификаторы и срезы zsh, квалификаторы с кодом, cdpath, опции git
    "echo x > $PWD:h:h/pantheon/alerts.md", "echo x > \"$PWD:h:h\"/pantheon/alerts.md",
    "X=$HOME/pantheon/alerts.md; rm -f $X[1,500]", "cd ~/pantheon && ls *(e:'rm -f alerts.md':) >/dev/null",
    "cdpath=(~); cd pantheon && rm alerts.md", "git diff --no-index --output=$HOME/pantheon/alerts.md /dev/null ~/tmp/z",
    "cd ~/tmp && git grep --no-index -O'rm -f ~/pantheon/alerts.md' line",
    "X=--output=$HOME/pantheon/alerts.md; git diff --no-index $X /dev/null ~/tmp/z",
]


def build(home):
    for d in ("pantheon/directions/athena-broker", "pantheon/directions/hermes-alex/inbox", "pantheon/.git",
              "pantheon-view", ".local/state/pantheon", ".claude/pantheon", PROJECT + "/src", "tmp"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    for f in ("pantheon/board.md", "pantheon/alerts.md", "pantheon/.git/HEAD", "pantheon-view/board.md",
              PROJECT + "/src/a.ts", "tmp/z"):
        with open(os.path.join(home, f), "w") as fh:
            fh.write("line\n")
    json.dump({"domains": {"athena-broker": ["~/" + PROJECT], "hermes-alex": ["~/projects/alexbroker"]}},
              open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    subprocess.run(["tar", "-cf", os.path.join(home, "tmp/a.tar"), "-C", os.path.join(home, "tmp"), "z"], check=True)
    subprocess.run(["zip", "-q", os.path.join(home, "tmp/a.zip"), "z"], cwd=os.path.join(home, "tmp"), check=True)


def snapshot(home):
    res = {}
    for top in ("pantheon", "pantheon-view"):
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
    out = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(event), capture_output=True, text=True,
                         env=env, timeout=20).stdout
    return "deny" if '"deny"' in out else "allow"


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


# Что закрыто от роли: координатору — весь ~/pantheon (кроме своего направления, его тут не трогают) и копия;
# штабу — alerts.md, .git и копия (остальное в ~/pantheon он правит сам).
ROLES = {
    "domain-coordinator": ("pantheon", "pantheon-view"),
    "hq": ("pantheon/alerts.md", "pantheon/.git", "pantheon-view"),
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
                          if any(k == p or k.startswith(p + "/") or k == "pantheon" for k in ch for p in closed)]
                   for role, closed in ROLES.items()}
        return cmd, changed, {role: guard_says(home, cmd, role) for role in ROLES}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    verbose = "--verbose" in sys.argv
    if not SHELLS:
        print("нет /bin/zsh и /bin/bash — пропуск")
        return
    all_cases = cases()
    with ProcessPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 1)) as pool:
        results = list(pool.map(check, all_cases, chunksize=8))
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
