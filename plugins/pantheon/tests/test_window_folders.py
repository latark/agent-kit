#!/usr/bin/env python3
"""Папки направления — рабочие папки его окна (metis-0911, решение Зевса 06.11).

Запуск: python3 -I plugins/pantheon/tests/test_window_folders.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: окно направления получает permissions.additionalDirectories — все
  свои папки из directions.toml настоящими путями (cd туда сохраняется, EnterWorktree в их .claude/worktrees/ Claude
  Code пускает без вопроса владельцу); папок чужого направления в нём нет;
- мастерская и окна без направления additionalDirectories не получают;
- allow_gate по всем папкам окна (ревью argus 2 PR #360): allow с gh pr merge во второй папке — окно не собрано, и
  при --if-changed; no_window_reason и direction check называют эту папку;
- строгий guard окна ловит EnterWorktree (matcher): чужой репозиторий закрывает правило worktree-own
  (plugins/guard/tests/test_worktree_own.py);
- [window_extra.<окно>] policy.toml (metis-0919): allow, deny и plugins вливаются в своё окно, поверх карты плагинов;
  allow с gh pr merge, не строка, не плагин «имя@каталог» и неизвестный ключ — не вливаются, тревога их называет.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(PLUGIN, "lib", "run.py")  # загрузчик, как bin/pantheon
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="winfold-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, info=None):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or info is None else "\n     " + str(info)[-1500:]))


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/legal-watch", "projects/expert-corpus", "projects/br", "ai/knowledge", "projects/workshop",
              ".claude/pantheon"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "themis-sources"\nfolders = ["~/projects/legal-watch", "~/projects/expert-corpus"]\n'
                 '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1", "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp")}  # общий /tmp/claude-<uid> меняется
    os.makedirs(env["PANTHEON_CLAUDE_TMP"])  # сам: иначе --if-changed пересобирал бы всегда
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("сборка прошла", r.returncode == 0, r.stderr)
    win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))  # noqa: E731
    real = lambda p: os.path.realpath(os.path.join(tmp, p))  # noqa: E731
    th, at, ws = win("themis-sources"), win("athena-shop"), win("workshop")
    got = (th.get("permissions") or {}).get("additionalDirectories")
    check("окно направления: все свои папки — рабочие (additionalDirectories), настоящими путями, по порядку реестра",
          got == [real("projects/legal-watch"), real("projects/expert-corpus")], got)
    check("окно направления: папок чужого направления в рабочих нет",
          real("projects/br") not in (got or []) and (at.get("permissions") or {}).get("additionalDirectories")
          == [real("projects/br")], (got, at.get("permissions")))
    check("мастерская additionalDirectories не получает",
          "additionalDirectories" not in (ws.get("permissions") or {}), ws.get("permissions"))
    matchers = [g["matcher"] for g in th["hooks"]["PreToolUse"]
                if any("guard.py" in h.get("command", "") for h in g.get("hooks") or [])]
    check("строгий guard окна ловит EnterWorktree (worktree-own)",
          len(matchers) == 1 and "EnterWorktree" in matchers[0].split("|"), matchers)

    # allow_gate по всем папкам окна (ревью argus 2 PR #360): вторая папка с allow, пускающим gh pr merge, — окно не
    # собирается, как и при таком allow в папке запуска (metis-0137)
    ifc = lambda: subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build", "--if-changed"], env=env,  # noqa: E731
                                 capture_output=True, text=True, timeout=120)
    built = lambda: json.load(open(os.path.join(state, "domains.json"))).get("built_ts")  # noqa: E731
    ifc()  # сборка ролей дописывает файлы после отметки: одна доводка, дальше тихо (как test_plugin_map)
    b0 = built()
    ifc()
    check("--if-changed без правок — пересборки нет (иначе проверка ниже ничего не доказывает)", built() == b0)
    second = os.path.join(tmp, "projects/expert-corpus/.claude")
    os.makedirs(second)
    with open(os.path.join(second, "settings.json"), "w") as fh:
        json.dump({"permissions": {"allow": ["Bash(gh pr *)", "Bash(mailkeeper scan *)"]},
                   "sandbox": {"excludedCommands": ["mailkeeper *"]}}, fh)
    os.utime(os.path.join(second, "settings.json"), (time.time() + 5,) * 2)  # новее built_ts: --if-changed заметит
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build", "--if-changed"], env=env, capture_output=True,
                       text=True, timeout=120)
    gone = not os.path.exists(os.path.join(state, "settings", "themis-sources.json"))
    check("вторая папка с allow gh pr merge — окно направления не собрано, причина названа",
          gone and "expert-corpus/.claude/settings.json" in r.stderr and "gh pr merge" in r.stderr, (gone, r.stderr))
    check("чужое направление при этом собрано", os.path.exists(os.path.join(state, "settings", "athena-shop.json")))
    sys.path.insert(0, os.path.join(PLUGIN, "lib"))
    os.environ.update(HOME=tmp, PANTHEON_HOME=home, PANTHEON_STATE=state, PANTHEON_NO_NOTIFY="1")
    import pantheon as P  # noqa: E402 — после HOME: модуль берёт пути при загрузке
    folders = ["~/projects/legal-watch", "~/projects/expert-corpus", "~/projects/legal-watch"]
    check("window_folders: папка запуска первой, остальные по реестру, без повторов",
          P.window_folders(folders) == [real("projects/legal-watch"), real("projects/expert-corpus")],
          P.window_folders(folders))
    reason = P.no_window_reason("themis-sources")
    check("no_window_reason называет allow второй папки", "expert-corpus" in reason and "gh pr merge" in reason, reason)
    line = [t for ok, t in P.direction_check("themis-sources") if "gh pr merge" in t]
    check("direction check: allow второй папки — пункт не готов, с путём",
          len(line) == 1 and "expert-corpus/.claude/settings.json" in line[0]
          and not dict((t, ok) for ok, t in P.direction_check("themis-sources"))[line[0]], line)
    os.remove(os.path.join(second, "settings.json"))
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("allow убран — окно снова собрано", os.path.exists(os.path.join(state, "settings", "themis-sources.json")),
          r.stderr)

    # разрешения, которые давал проект, — [window_extra.<окно>] policy.toml (metis-0919): окно настроек проекта не
    # читает (--setting-sources user), сборка вливает их сама; allow с gh pr merge и мусор — не вливаются, тревога
    with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[window_extra.athena-shop]\nallow = ["mcp__shadcn__*", "Bash(pnpm test *)", "Bash(gh *)", 7]\n'
                 'deny = ["Bash(git push --force*)"]\n'
                 'plugins = ["vercel@claude-plugins-official", "notion@anthropic-plugin-directory", "не плагин"]\n'
                 'model = "opus"\n'
                 '[window_extra.themis-sources]\nallow = "Bash(uv run pytest *)"\n')
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    at, th = win("athena-shop"), win("themis-sources")
    allow, deny = at["permissions"].get("allow") or [], at["permissions"].get("deny") or []
    check("window_extra: allow из policy.toml попал в окно направления",
          "mcp__shadcn__*" in allow and "Bash(pnpm test *)" in allow, at["permissions"])
    check("window_extra: allow с gh pr merge и не строка — не влиты", "Bash(gh *)" not in allow and 7 not in allow, allow)
    check("window_extra: deny влит, прежние deny окна на месте",
          "Bash(git push --force*)" in deny and any(x.startswith("Read(") for x in deny), deny)
    plugins = at.get("enabledPlugins") or {}
    check("window_extra: plugins — enabledPlugins: true, и поверх карты плагинов; не «имя@каталог» — не влит",
          plugins.get("vercel@claude-plugins-official") is True
          and plugins.get("notion@anthropic-plugin-directory") is True and "не плагин" not in plugins, plugins)
    check("window_extra: одно правило строкой — тоже allow; чужого окна не задевает",
          (th["permissions"].get("allow") or []) == ["Bash(uv run pytest *)"]
          and "mcp__shadcn__*" not in (th["permissions"].get("allow") or []), th["permissions"])
    check("window_extra: окно без записи — без изменений", "allow" not in (ws.get("permissions") or {})
          and "allow" not in (win("workshop").get("permissions") or {}), win("workshop").get("permissions"))
    alerts = open(os.path.join(home, "alerts.md"), encoding="utf-8").read() if os.path.exists(
        os.path.join(home, "alerts.md")) else ""
    check("window_extra: отброшенное названо в тревоге (gh *, 7, не плагин, неизвестный ключ model)",
          "[window_extra.athena-shop]" in alerts and "Bash(gh *)" in alerts and "не плагин" in alerts
          and "model" in alerts, alerts[-1500:])
    return all(results)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
