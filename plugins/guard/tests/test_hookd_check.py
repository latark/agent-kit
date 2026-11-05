#!/usr/bin/env python3
"""Проверки службы демона хуков для владельца (metis-0811): scripts/hookd-check.py.

Запуск: python3 -I plugins/guard/tests/test_hookd_check.py   (код выхода 0 — все прошли)
- tcc: таблица по папкам (есть, папки нет, НЕТ, НЕ ПРОЧЕСТЬ); нет доступа — код 1, команды «Файлы и папки»,
  «Полный доступ к диску», перезапуск службы; ответственный процесс не pantheon-hookd — находка; пакет .app —
  строка tccutil с его идентификатором, иначе — почему tccutil не поможет; итог пробы не прочесть — код 1;
- windows (F7): allowWrite, накрывающий ~/.cache/pantheon/hookd (папка выше, сама, путь внутри, шаблон), —
  нарушение, если его не перекрыл denyWrite; соседняя папка (~/.cache/pantheon/heavy, hookd-x) — нет;
  allowUnixSockets в папку демона и allowAllUnixSockets — нарушение; файл настроек не прочесть — нарушение;
- windows на настоящей сборке окон (`pantheon domains build` плагина pantheon, временный HOME): окна по умолчанию
  папку демона не открывают; разрешение grants.toml с записью в ~/.cache — либо не применено сборкой, либо
  проверка его ловит (сборка и проверка не расходятся).
"""
import importlib.util
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
SCRIPT = os.path.join(PLUGIN, "scripts", "hookd-check.py")
LAUNCHER = os.path.join(PLUGIN, "hooks", "python.sh")
PANTHEON_RUN = os.path.join(os.path.dirname(PLUGIN), "pantheon", "lib", "run.py")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or info is None else "\n     " + str(info)[:1200]))


def load():
    spec = importlib.util.spec_from_file_location("hookd_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(fn, *args, **kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(*args, **kw)
    return code, buf.getvalue()


def probe_json(root, name, dirs, responsible):
    p = os.path.join(root, name + ".json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"time": "t", "pid": 1, "home": root, "responsible": responsible, "dirs": dirs}, fh)
    return p


def test_tcc(C, root):
    svc = os.path.join(root, "bin", "pantheon-hookd")
    os.makedirs(os.path.dirname(svc))
    open(svc, "w").close()
    ok_dirs = {"Desktop": "ok", "Documents": "ok", "Downloads": "missing", "iCloud Drive": "ok"}
    code, out = run(C.tcc, probe_json(root, "ok", ok_dirs, svc), svc)
    check("tcc: доступ есть (Downloads нет — проверять нечего) — код 0, «итог: доступ ко всем папкам есть»",
          code == 0 and out.strip().splitlines()[-1] == "итог: доступ ко всем папкам есть"
          and "Downloads     папки нет" in out and "open " not in out, (code, out))
    bad = {"Desktop": "ok", "Documents": "denied", "Downloads": "error 5", "iCloud Drive": "ok"}
    code, out = run(C.tcc, probe_json(root, "bad", bad, svc), svc)
    last = out.strip().splitlines()[-1]
    check("tcc: Documents отказ, Downloads ошибка — код 1; «Файлы и папки», «Полный доступ к диску» с путём, "
          "kickstart службы, итог последней строкой",
          code == 1 and "Documents     НЕТ" in out and "Downloads     НЕ ПРОЧЕСТЬ (error 5)" in out
          and f'open "{C.PANE_FILES}"' in out and f'open "{C.PANE_ALL}"' in out and svc in out
          and f"launchctl kickstart -k gui/{os.getuid()}/pantheon.svc.hookd" in out
          and last == "итог: нет доступа: Documents, Downloads", (code, out))
    check("tcc: у pantheon-hookd нет идентификатора пакета — объяснено, почему tccutil не поможет",
          "tccutil тут не поможет" in out and "tccutil reset Sys" not in out, out)
    # служба старой установки: ответственный — Python.app (пакет с Info.plist)
    app = os.path.join(root, "Python.app", "Contents")
    os.makedirs(os.path.join(app, "MacOS"))
    with open(os.path.join(app, "Info.plist"), "wb") as fh:
        plistlib.dump({"CFBundleIdentifier": "org.python.python"}, fh)
    exe = os.path.join(app, "MacOS", "Python")
    open(exe, "w").close()
    code, out = run(C.tcc, probe_json(root, "app", {"Desktop": "denied", "iCloud Drive": "denied"}, exe), svc)
    check("tcc: ответственный — Python.app, а не pantheon-hookd — код 1, находка «переставить службу»",
          code == 1 and "ответственный процесс не pantheon-hookd" in out and "Переставить службу" in out, (code, out))
    check("tcc: пакет .app — строка tccutil с его идентификатором и службой Desktop (у iCloud Drive службы нет)",
          "tccutil reset SystemPolicyDesktopFolder org.python.python" in out and out.count("tccutil reset ") == 1, out)
    for name, body in (("broken", "{"), ("nodirs", json.dumps({"responsible": svc})),
                       ("listdirs", json.dumps({"responsible": svc, "dirs": []}))):
        p = os.path.join(root, name + ".json")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(body)
        code, out = run(C.tcc, p, svc)
        check(f"tcc: итог пробы {name} не прочесть — код 1 и причина", code == 1 and "не прочесть" in out, (code, out))
    code, out = run(C.tcc, os.path.join(root, "absent.json"), svc)
    check("tcc: итога пробы нет — код 1", code == 1 and "не прочесть" in out, (code, out))


def settings(state, name, fs=None, net=None, sub=""):
    d = os.path.join(state, "settings", sub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"sandbox": {"filesystem": fs or {}, "network": net or {}}}, fh)


def test_windows(C, root):
    home = os.path.realpath(os.path.join(root, "w"))
    target = os.path.join(home, ".cache", "pantheon", "hookd")
    os.makedirs(target)
    state = os.path.join(home, "state")
    code, out = run(C.windows, state=state, home=home)
    check("windows: файлов настроек нет — код 0, «проверять нечего»", code == 0 and "проверять нечего" in out,
          (code, out))
    settings(state, "ok", fs={"allowWrite": [os.path.join(home, ".cache", "pantheon", "heavy"),
                                             os.path.join(home, ".cache", "pantheon", "hookd-x"), "~/.cache/pantheon/h*",
                                             os.path.join(home, "projects")], "denyWrite": []},
             net={"allowUnixSockets": [os.path.join(home, "Library", "Caches", "pantheon-sandbox", "ok")]})
    code, out = run(C.windows, state=state, home=home)
    check("windows: шаблон ~/.cache/pantheon/h* накрывает (по части до шаблона), соседние папки рядом — нет",
          code == 1 and "ok.json: allowWrite ~/.cache/pantheon/h*" in out and "heavy" not in out
          and "hookd-x" not in out, (code, out))
    shutil.rmtree(os.path.join(state, "settings"))
    settings(state, "ok", fs={"allowWrite": [os.path.join(home, ".cache", "pantheon", "heavy"),
                                             os.path.join(home, ".cache", "pantheon", "hookd-x"),
                                             os.path.join(home, "projects")]},
             net={"allowUnixSockets": [os.path.join(home, "Library", "Caches", "pantheon-sandbox", "ok")]})
    code, out = run(C.windows, state=state, home=home)
    check("windows: соседние папки (heavy, hookd-x) — не нарушение, код 0", code == 0 and "ни одному" in out, (code, out))
    cases = (
        ("cache", {"allowWrite": [os.path.join(home, ".cache")]}, {}, "allowWrite " + os.path.join(home, ".cache")),
        ("tilde", {"allowWrite": ["~/.cache/pantheon"]}, {}, "allowWrite ~/.cache/pantheon"),
        ("same", {"allowWrite": [target + "/"]}, {}, "allowWrite " + target + "/"),
        ("inside", {"allowWrite": [os.path.join(target, "bin")]}, {}, "allowWrite " + os.path.join(target, "bin")),
        ("glob", {"allowWrite": [os.path.join(home, ".cache", "*")]}, {}, "allowWrite " + os.path.join(home, ".cache", "*")),
        ("sock", {}, {"allowUnixSockets": [os.path.join(target, "hookd.sock")]}, "allowUnixSockets "),
        ("allsock", {}, {"allowAllUnixSockets": True}, "allowAllUnixSockets: true"),
    )
    for name, fs, net, want in cases:
        shutil.rmtree(os.path.join(state, "settings"))
        settings(state, "x", fs=fs, net=net, sub="run" if name == "inside" else "")
        code, out = run(C.windows, state=state, home=home)
        check(f"windows: {name} — нарушение, код 1, «{want.strip()}» и итог последней строкой",
              code == 1 and want in out and out.strip().splitlines()[-1].startswith("итог: окнам открыта папка демона"),
              (code, out))
    for name, deny in (("deny-same", [target]), ("deny-above", ["~/.cache"])):
        shutil.rmtree(os.path.join(state, "settings"))
        settings(state, "x", fs={"allowWrite": [os.path.join(home, ".cache")], "denyWrite": deny})
        code, out = run(C.windows, state=state, home=home)
        check(f"windows: allowWrite ~/.cache перекрыт denyWrite ({name}) — не нарушение", code == 0, (code, out))
    shutil.rmtree(os.path.join(state, "settings"))
    settings(state, "x", fs={"allowWrite": [os.path.join(home, ".cache")], "denyWrite": [os.path.join(target, "bin")]})
    code, out = run(C.windows, state=state, home=home)
    check("windows: denyWrite только части папки (bin) — нарушение остаётся", code == 1, (code, out))
    shutil.rmtree(os.path.join(state, "settings"))
    os.makedirs(os.path.join(state, "settings"))
    with open(os.path.join(state, "settings", "bad.json"), "w") as fh:
        fh.write("{")
    code, out = run(C.windows, state=state, home=home)
    check("windows: файл настроек не прочесть — нарушение (код 1)", code == 1 and "bad.json: не прочесть" in out,
          (code, out))
    r = subprocess.run(["/bin/sh", LAUNCHER, SCRIPT, "bogus"], capture_output=True, text=True, timeout=60,
                       env={"PATH": "/usr/bin:/bin", "HOME": home})
    check("hookd-check.py с неизвестной командой — код 64", r.returncode == 64, (r.returncode, r.stderr))


def test_real_build(root):
    """Сборка окон плагином pantheon на временном HOME — проверка смотрит её результат."""
    if not os.path.isfile(PANTHEON_RUN):
        print("пропущено: нет плагина pantheon рядом — сборка окон")
        return
    tmp = os.path.realpath(os.path.join(root, "h"))
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    for d in ("pantheon", "projects/br", "ai/knowledge", "projects/workshop", ".claude/pantheon", ".cache/pantheon/hookd"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "PANTHEON_NO_NOTIFY": "1"}

    def build():
        r = subprocess.run([sys.executable, "-I", PANTHEON_RUN, "domains", "build"], env=env, capture_output=True,
                           text=True, timeout=180)
        return r.returncode, r.stderr[-400:]

    def verdict():
        r = subprocess.run(["/bin/sh", LAUNCHER, SCRIPT, "windows"], env=env, capture_output=True, text=True,
                           timeout=60)
        return r.returncode, r.stdout

    code, err = build()
    files = os.listdir(os.path.join(state, "settings")) if os.path.isdir(os.path.join(state, "settings")) else []
    vcode, vout = verdict()
    check("сборка окон по умолчанию: ни одно окно не пишет в ~/.cache/pantheon/hookd и не открывает его сокет",
          code == 0 and len(files) >= 2 and vcode == 0 and "ни одному не дана запись" in vout, (code, err, vout))
    until = (date.today() + timedelta(days=7)).isoformat()
    with open(os.path.join(tmp, ".claude", "pantheon", "grants.toml"), "w") as fh:
        fh.write(f'[[grant]]\nwindow = "athena-shop"\nuntil = "{until}"\nwrite = ["~/.cache"]\n')
    code, err = build()
    with open(os.path.join(state, "settings", "athena-shop.json"), encoding="utf-8") as fh:
        aw = json.load(fh)["sandbox"]["filesystem"].get("allowWrite") or []
    given = os.path.join(tmp, ".cache") in aw
    vcode, vout = verdict()
    check("grants.toml write ~/.cache: сборка и проверка не расходятся (дала запись — проверка ловит, код 1)",
          code == 0 and (vcode == 1 and "athena-shop.json: allowWrite" in vout if given else vcode == 0),
          (code, err, given, vout))
    if given:
        print("     находка: grants.toml с write = [\"~/.cache\"] открывает окну папку демона хуков — "
              "GRANT_NO_WRITE pantheon.py её не закрывает (в отчёт)")


def main():
    C = load()
    root = tempfile.mkdtemp(prefix="hkc")
    try:
        test_tcc(C, root)
        test_windows(C, root)
        test_real_build(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
