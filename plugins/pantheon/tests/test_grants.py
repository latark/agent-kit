#!/usr/bin/env python3
"""Ручные разрешения окнам — ~/.claude/pantheon/grants.toml ([sb-simplify] п. 6, «да» владельца 27.10).

Запуск: python3 -I plugins/pantheon/tests/test_grants.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: разрешение в силе попадает в окно (allow, write, domains), «*» — во все;
- истёкшее — не попадает, тревога одна на разрешение; без срока, с лишним ключом или с записью в ~/.ssh — не
  применяется, тревога grants-bad;
- файл запущенной сессии (settings/run/, PANTHEON_WINDOW) обновляется вместе с окном, её env остаётся;
- --if-changed пересобирает окна после правки grants.toml и к сроку разрешения (grants_next в domains.json);
- папка демона хуков ~/.cache/pantheon/hookd (metis-0845): grant write в неё и в папку выше (~/.cache) не даётся,
  sandbox_write policy.toml в неё — тоже, а denyWrite каждого окна её закрывает; итог сверяет проверка F7 guard
  (scripts/hookd-check.py windows).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="grants-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def py311():
    return sys.executable


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "ai/workshop", ".claude/pantheon", "data"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    out = os.path.join(state, "settings")
    win = lambda n: json.load(open(os.path.join(out, n + ".json")))  # noqa: E731
    grants = os.path.join(tmp, ".claude", "pantheon", "grants.toml")
    alerts = os.path.join(home, "alerts.md")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}

    def build(*args):
        r = subprocess.run([py311(), "-I", RUN_PY, "domains", "build", *args], env=env, capture_output=True, text=True,
                           timeout=120)
        if r.returncode:
            print(r.stderr)
        return r.returncode == 0

    def alert_text():
        return open(alerts).read() if os.path.isfile(alerts) else ""

    future, past = (date.today() + timedelta(days=7)).isoformat(), (date.today() - timedelta(days=1)).isoformat()
    data = os.path.realpath(os.path.join(tmp, "data"))
    with open(grants, "w") as fh:
        fh.write(f'''[[grant]]
window = "athena-shop"
until = "{future}"
why = "тесты на pnpm"
allow = ["Bash(pnpm test *)"]
write = ["~/data"]
domains = ["registry.example.org"]

[[grant]]
window = "*"
until = "{future}"
allow = ["Bash(make check)"]

[[grant]]
window = "athena-shop"
until = "{past}"
allow = ["Bash(old *)"]

[[grant]]
window = "athena-shop"
allow = ["Bash(nodate *)"]

[[grant]]
window = "athena-shop"
until = "{future}"
write = ["~/.ssh"]

[[grant]]
window = "athena-shop"
until = "{future}"
excluded = ["curl *"]

[[grant]]
window = "athena-shop"
until = "{future}"
write = ["~/.c*e"]

[[grant]]
window = "athena-shop"
until = "{future}"
write = ["~/state/x"]
''')
    check("сборка прошла", build())
    a = win("athena-shop")
    check("allow в силе — в окне", "Bash(pnpm test *)" in a["permissions"]["allow"])
    check("write в силе — настоящим путём в allowWrite", data in a["sandbox"]["filesystem"]["allowWrite"])
    dw = a["sandbox"]["filesystem"]["denyWrite"]
    check("выданная запись — .claude/hooks, .claude/agents и .git/hooks в ней закрыты (metis-1214)", all(
        data + sub in dw for sub in ("/.claude/hooks", "/**/.claude/hooks", "/.claude/agents", "/**/.claude/agents",
                                     "/.git/hooks", "/**/.git/hooks", "/.git/config", "/**/.git/config")))
    check("выданная запись — .claude/settings.json и settings.local.json в ней закрыты (metis-1221)", all(
        data + sub in dw for sub in ("/.claude/settings.json", "/**/.claude/settings.json",
                                     "/.claude/settings.local.json", "/**/.claude/settings.local.json")))
    check("domains в силе — в allowedDomains", "registry.example.org" in a["sandbox"]["network"]["allowedDomains"])
    check("«*» — в окне направления и в мастерской",
          "Bash(make check)" in a["permissions"]["allow"] and "Bash(make check)" in win("workshop")["permissions"]["allow"])
    check("истёкшее не применено", "Bash(old *)" not in a["permissions"]["allow"])
    check("без срока не применено", "Bash(nodate *)" not in a["permissions"]["allow"])
    check("запись в ~/.ssh не дана", not any(x.endswith("/.ssh") for x in a["sandbox"]["filesystem"]["allowWrite"]))
    check("excludedCommands не дан", "curl *" not in a["sandbox"]["excludedCommands"])
    check("write шаблоном не дан", not any("*" in x for x in a["sandbox"]["filesystem"]["allowWrite"]))
    # grants.toml в STATE запись не даёт; сама сборка даёт только очередь heavy (metis-0659, «да» владельца 02.11)
    check("write в состояние Пантеона не дан", not any(x.startswith(os.path.realpath(state))
                                                       and x != os.path.join(os.path.realpath(state), "locks", "heavy-queue")
                                                       for x in a["sandbox"]["filesystem"]["allowWrite"]))
    for n in ("hq", "hestia", "job-clio"):
        if os.path.isfile(os.path.join(out, n + ".json")):
            check(f"«*» не попадает в служебное окно {n}",
                  "Bash(make check)" not in win(n).get("permissions", {}).get("allow", []))
    txt = alert_text()
    check("тревога: истёкшее", f"истекло {past}" in txt)
    check("тревога: ошибки grants.toml", "grants.toml:" in txt and "until" in txt and "лишние: excluded" in txt
          and ".ssh" in txt)
    nxt = json.load(open(os.path.join(state, "domains.json"))).get("grants_next")
    check("domains.json помнит ближайший срок", isinstance(nxt, (int, float)) and nxt > 0)

    # запущенная сессия окна: её файл обновляется вместе с окном, env сессии остаётся
    run = os.path.join(out, "run")
    os.makedirs(run, exist_ok=True)
    sess = dict(win("athena-shop"))
    sess["env"] = dict(sess["env"], PANTHEON_SESSION="athena-shop", PANTHEON_ROLE="domain-coordinator",
                       PANTHEON_ORIGIN="hq", PANTHEON_WINDOW="athena-shop")
    sess["permissions"] = dict(sess["permissions"], allow=[x for x in sess["permissions"]["allow"]
                                                           if x != "Bash(pnpm test *)"])
    other = {"env": {"PANTHEON_WINDOW": "workshop"}, "x": 1}
    json.dump(sess, open(os.path.join(run, "athena-shop.json"), "w"))
    json.dump(other, open(os.path.join(run, "ws-task.json"), "w"))
    with open(grants, "a") as fh:
        fh.write(f'\n[[grant]]\nwindow = "athena-shop"\nuntil = "{future}"\nallow = ["Bash(new *)"]\n')
    t = os.path.getmtime(grants) + 5
    os.utime(grants, (t, t))
    check("--if-changed пересобрал после правки grants.toml", build("--if-changed"))
    r = json.load(open(os.path.join(run, "athena-shop.json")))
    check("файл сессии: новое разрешение дошло", "Bash(new *)" in r["permissions"]["allow"]
          and "Bash(pnpm test *)" in r["permissions"]["allow"])
    check("файл сессии: env сессии сохранён", r["env"].get("PANTHEON_ORIGIN") == "hq"
          and r["env"].get("PANTHEON_ROLE") == "domain-coordinator" and r["env"].get("PANTHEON_WINDOW") == "athena-shop")
    check("файл сессии мастерской обновлён по своему окну",
          "Bash(make check)" in json.load(open(os.path.join(run, "ws-task.json")))["permissions"]["allow"])

    # срок наступил: tick (--if-changed) пересобирает и снимает
    d = json.load(open(os.path.join(state, "domains.json")))
    d["grants_next"] = 1
    json.dump(d, open(os.path.join(state, "domains.json"), "w"))
    with open(grants, "w") as fh:
        fh.write(f'[[grant]]\nwindow = "athena-shop"\nuntil = "{past}"\nallow = ["Bash(new *)"]\n')
    old = os.path.getmtime(os.path.join(state, "domains.json")) - 3600
    os.utime(grants, (old, old))
    check("--if-changed пересобрал к сроку", build("--if-changed"))
    check("истёкшее снято и с окна, и с сессии", "Bash(new *)" not in win("athena-shop")["permissions"].get("allow", [])
          and "Bash(new *)" not in json.load(open(os.path.join(run, "athena-shop.json")))["permissions"].get("allow", []))


def hookd_closed():
    """Папка демона хуков (metis-0845): ни grant, ни sandbox_write не открывают её ни одному окну."""
    tmp = os.path.join(ROOT, "hk")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/br", "ai/knowledge", "ai/workshop", ".claude/pantheon", ".cache/pantheon/hookd/bin",
              ".cache/other"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[sandbox_write]\nathena-shop = ["~/.cache/pantheon/hookd", "~/.cache/pantheon/hookd/bin", '
                 '"~/.cache/pantheon"]\n')
    future = (date.today() + timedelta(days=7)).isoformat()
    with open(os.path.join(tmp, ".claude", "pantheon", "grants.toml"), "w") as fh:
        for w in ("~/.cache", "~/.cache/pantheon/hookd", "~/.cache/pantheon/hookd/bin", "~/.cache/other"):
            fh.write(f'[[grant]]\nwindow = "athena-shop"\nuntil = "{future}"\nwrite = ["{w}"]\n\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    r = subprocess.run([py311(), "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True, timeout=120)
    check("hookd: сборка прошла", r.returncode == 0)
    out = os.path.join(state, "settings")
    hk = os.path.realpath(os.path.join(tmp, ".cache", "pantheon", "hookd"))
    a = json.load(open(os.path.join(out, "athena-shop.json")))
    aw = a["sandbox"]["filesystem"]["allowWrite"]
    check("hookd: grant ~/.cache, ~/.cache/pantheon/hookd и папка внутри — не в allowWrite",
          not any(x == os.path.realpath(os.path.join(tmp, ".cache")) or x.startswith(hk) for x in aw))
    check("hookd: соседняя папка ~/.cache/other — дана (запрет только на папку демона и выше)",
          os.path.realpath(os.path.join(tmp, ".cache", "other")) in aw)
    al = open(os.path.join(home, "alerts.md")).read() if os.path.isfile(os.path.join(home, "alerts.md")) else ""
    check("hookd: тревога grants-bad называет ~/.cache и ~/.cache/pantheon/hookd",
          "не даётся: ~/.cache;" in al and "не даётся: ~/.cache/pantheon/hookd;" in al)
    check("hookd: sandbox_write в папку демона и внутрь — отброшен, папка выше (~/.cache/pantheon) — осталась",
          not any(x.startswith(hk) for x in aw) and os.path.realpath(os.path.join(tmp, ".cache", "pantheon")) in aw
          and "sandbox_write в папку демона хуков не даётся" in r.stderr)
    files = sorted(f for f in os.listdir(out) if f.endswith(".json"))
    closed = [f for f in files if hk in json.load(open(os.path.join(out, f)))["sandbox"]["filesystem"]["denyWrite"]
              and "~/.cache/pantheon/hookd" in json.load(open(os.path.join(out, f)))["sandbox"]["filesystem"]["denyWrite"]]
    check(f"hookd: denyWrite каждого окна закрывает папку демона ({len(closed)}/{len(files)})",
          len(files) >= 4 and closed == files)
    checker = os.path.join(os.path.dirname(PLUGIN), "guard", "scripts", "hookd-check.py")
    if os.path.isfile(checker):  # проверка F7 guard — по готовым настройкам окон
        r = subprocess.run([py311(), "-I", checker, "windows"], env=env, capture_output=True, text=True, timeout=60)
        check("hookd: проверка F7 guard (hookd-check.py windows) — ни одному окну папка демона не открыта",
              r.returncode == 0 and "ни одному не дана запись" in r.stdout)


if __name__ == "__main__":
    main()
    hookd_closed()
    print(f"\n{sum(results)}/{len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)
