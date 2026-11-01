#!/usr/bin/env python3
"""hooks.json guard и pantheon: onFailure=block (metis-0094 ч.2) и запуск через hooks/python.sh (metis-0571).

Документация: https://code.claude.com/docs/en/hooks — «Block the action when a hook fails» (Claude Code ≥ 2.1.295).
Каждый обработчик PreToolUse должен иметь "onFailure": "block" (сбой хука = отказ, как exit 2); на событиях, где
поле не действует (Stop, SubagentStop, TaskCompleted, TeammateIdle, async/asyncRewake), и на PostToolUse его нет.
Скрипты Python хуки запускают только запускателем hooks/python.sh (Python 3.11+), голого python3 в командах нет.
Запускатель: выбирает 3.11+ и при /usr/bin/python3 (3.9) первым в PATH; без 3.11+ — код 2 на PreToolUse и код 0
молча на остальных событиях; копии в guard и pantheon одинаковые.
metis-0330 F3 («залипший код 2»): пропавший файл скрипта — тоже код 2 только на PreToolUse, на Stop, UserPromptSubmit,
PostToolUse, SessionStart — код 0 (Python сам дал бы 2: Stop не заканчивал бы ход, сообщения владельца глотались бы во
всех окнах). Проверка — и запускателем, и настоящими командами hooks.json guard и pantheon на корне плагина без .py.
Каждый отказ запускателя — строка в guard-failures.log; висячая ссылка на интерпретатор пропускается.

Запуск: python3 -I plugins/guard/tests/test_hooks_json.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # plugins/
LAUNCHER = os.path.join(ROOT, "guard", "hooks", "python.sh")
NO_EFFECT = {"Stop", "SubagentStop", "TaskCompleted", "TeammateIdle"}
RUNNER = '/bin/sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/'
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


for plugin in ("guard", "pantheon"):
    path = os.path.join(ROOT, plugin, "hooks", "hooks.json")
    if plugin != "guard" and not os.path.exists(path):
        print(f"skip {plugin}: нет {path} (рядом нет плагина)")
        continue
    with open(path, encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    pre = [h for g in hooks.get("PreToolUse", []) for h in g["hooks"]]
    check(f"{plugin}: PreToolUse есть", len(pre) > 0)
    bad = [h["command"][:60] for h in pre if h.get("onFailure") != "block"]
    check(f"{plugin}: каждый обработчик PreToolUse — onFailure=block ({len(pre)})", not bad, bad)
    wrong = []
    for event, groups in hooks.items():
        for g in groups:
            for h in g["hooks"]:
                if "onFailure" not in h:
                    continue
                if event != "PreToolUse" or h.get("async") or h.get("asyncRewake"):
                    wrong.append(event)
    check(f"{plugin}: onFailure только на PreToolUse, не на Stop/async/PostToolUse", not wrong, wrong)
    cmds = [h["command"] for groups in hooks.values() for g in groups for h in g["hooks"]]
    py = [c for c in cmds if re.search(r"\.py\b", c)]
    check(f"{plugin}: каждый скрипт .py — через hooks/python.sh ({len(py)})",
          py and all(RUNNER in c for c in py), [c for c in py if RUNNER not in c])
    check(f"{plugin}: голого python3 в командах нет", not [c for c in cmds if re.search(r"\bpython3\b", c)],
          [c for c in cmds if re.search(r"\bpython3\b", c)])

other = os.path.join(ROOT, "pantheon", "hooks", "python.sh")
if os.path.exists(other):
    with open(LAUNCHER, "rb") as a, open(other, "rb") as b:
        check("python.sh: копии в guard и pantheon одинаковые", a.read() == b.read())
else:
    print(f"skip копия pantheon: нет {other}")
check("python.sh: исполняемый", os.access(LAUNCHER, os.X_OK))

# --- поведение запускателя ----------------------------------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="hooks-json-")
PROBE = "import sys; print('%d.%d' % sys.version_info[:2])"


def launch(args, path, stdin="", launcher=LAUNCHER, cwd=None):
    return subprocess.run(["/bin/sh", launcher] + args, input=stdin, env={"PATH": path, "HOME": tmp},
                          capture_output=True, text=True, timeout=60, cwd=cwd or tmp)


def check_mac(name, ok, info=None):
    """Известные папки DIRS/FW в python.sh. Раньше проверка шла только на macOS: на Linux /bin/sh — dash, а dash
    склеивал `$DIRS:$FW/…:$PATH` в одно слово, и папки DIRS, FW и PATH терялись (metis-0194). Теперь проверка идёт
    везде, и её прогоняют под dash (Linux CI)."""
    check(name, ok, info)


def fake(d, name, body):
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(p, 0o755)
    return p


def isolated(dirs, fw):
    """Копия запускателя, где известные места — временные папки (строки FW= и DIRS=)."""
    with open(LAUNCHER, encoding="utf-8") as fh:
        src = fh.read()
    new = re.sub(r"^FW=.*$", f"FW={fw}", src, count=1, flags=re.M)
    new = re.sub(r"^DIRS=.*$", f"DIRS={dirs}", new, count=1, flags=re.M)
    check("копия запускателя: строки FW= и DIRS= подменены", new.count(fw) == 1 and new.count(dirs) == 1)
    p = os.path.join(tmp, f"python-{len(os.listdir(tmp))}.sh")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(new)
    return p


try:
    # настоящий: /usr/bin/python3 (на macOS 3.9) первым в PATH — запускатель всё равно берёт 3.11+
    r = launch(["-c", PROBE], "/usr/bin:/bin:" + os.path.dirname(sys.executable))
    ver = tuple(int(x) for x in r.stdout.strip().split(".")) if re.fullmatch(r"\d+\.\d+", r.stdout.strip()) else ()
    check(f"PATH с /usr/bin первым → Python 3.11+ ({r.stdout.strip()})", r.returncode == 0 and ver >= (3, 11),
          r.stdout + r.stderr)

    known, fw, old = os.path.join(tmp, "known"), os.path.join(tmp, "fw"), os.path.join(tmp, "old")
    os.makedirs(known)
    os.makedirs(fw)
    open(os.path.join(tmp, "s.py"), "w").close()  # скрипт на месте (cwd=tmp): запускатель проверяет его до exec
    fake(old, "python3", "exit 1")  # python3 из PATH старше 3.11: проверка версии не проходит
    iso = isolated(known, fw)
    pre_ev = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}})
    spaced = '{\n  "hook_event_name" : "PreToolUse"\n}'
    r = launch([os.path.join(ROOT, "guard", "hooks", "guard.py")], old, pre_ev, iso)
    check("нет 3.11+ → PreToolUse: код 2 и причина в stderr",
          r.returncode == 2 and "нужен Python 3.11+" in r.stderr and "guard.py" in r.stderr and r.stdout == "",
          (r.returncode, r.stdout, r.stderr))
    r = launch(["x.py"], old, spaced, iso)
    check("нет 3.11+ → PreToolUse с пробелами в JSON: тоже код 2", r.returncode == 2, (r.returncode, r.stderr))
    for ev in ("Stop", "PostToolUse", "UserPromptSubmit", "SessionStart"):
        r = launch(["x.py"], old, json.dumps({"hook_event_name": ev}), iso)
        check(f"нет 3.11+ → {ev}: код 0 без вывода", r.returncode == 0 and r.stdout == "" and r.stderr == "",
              (r.returncode, r.stdout, r.stderr))
    r = launch(["x.py"], "", pre_ev, iso)
    check("нет 3.11+, PATH пуст → PreToolUse: код 2", r.returncode == 2, (r.returncode, r.stderr))

    # имя называет версию: python3.12 в известной папке берётся, -I и аргументы доходят
    fake(known, "python3.12", 'echo "K312 $*"')
    r = launch(["s.py", "a b", "--strict"], old, pre_ev, iso)
    check_mac("python3.12 в известной папке → exec с -I и аргументами", r.stdout.strip() == "K312 -I s.py a b --strict",
          (r.stdout, r.stderr))
    # новее — раньше: python3.14 в PATH важнее python3.12 в известной папке
    newer = os.path.join(tmp, "newer")
    fake(newer, "python3.14", 'echo "P314 $*"')
    r = launch(["s.py"], f"{old}:{newer}", pre_ev, iso)
    check("python3.14 из PATH важнее python3.12 из известной папки", r.stdout.strip() == "P314 -I s.py", r.stdout)
    # при одной версии известная папка раньше PATH
    fake(known, "python3.14", 'echo "K314 $*"')
    r = launch(["s.py"], f"{newer}:{old}", pre_ev, iso)
    check_mac("одна версия: известная папка раньше PATH", r.stdout.strip() == "K314 -I s.py", r.stdout)
    # python.org: FW/<v>/bin/python<v>
    os.remove(os.path.join(known, "python3.14"))
    os.remove(os.path.join(known, "python3.12"))
    fake(os.path.join(fw, "3.13", "bin"), "python3.13", 'echo "FW313 $*"')
    r = launch(["s.py"], old, pre_ev, iso)
    check_mac("python.org: Versions/3.13/bin/python3.13", r.stdout.strip() == "FW313 -I s.py", r.stdout)
    shutil.rmtree(os.path.join(fw, "3.13"))
    # относительная папка PATH не берётся (подложенный python в текущей папке)
    rel = os.path.join(tmp, "cwd")
    fake(os.path.join(rel, "bin"), "python3.14", 'echo "REL $*"')
    r = launch(["s.py"], f"bin:.:{old}", pre_ev, iso, cwd=rel)
    check("относительная папка PATH пропущена", "REL" not in r.stdout and r.returncode == 2, (r.stdout, r.returncode))
    # каталог с именем python3.14 — не интерпретатор
    os.makedirs(os.path.join(known, "python3.14"))
    r = launch(["s.py"], old, pre_ev, iso)
    check("папка python3.14 не берётся", r.returncode == 2, (r.returncode, r.stdout))
    # python3 из PATH 3.11+ (новее списка) — берётся после проверки версии
    v3 = os.path.join(tmp, "v3")
    fake(v3, "python3", 'case "$*" in *version_info*) exit 0 ;; esac; echo "PY3 $*"')
    r = launch(["s.py"], v3, pre_ev, iso)
    check("python3 из PATH 3.11+ → берётся", r.stdout.strip() == "PY3 -I s.py", (r.stdout, r.stderr))
    # metis-0194: средние места списка не склеиваются под dash. Второе место DIRS, и первое место PATH при пустых
    # DIRS и FW (dash склеивал последнее место DIRS, FW и первое место PATH в одно слово и терял их)
    second = os.path.join(tmp, "second")
    fake(second, "python3.13", 'echo "SEC313 $*"')
    iso2 = isolated(os.path.join(tmp, "nope1") + ":" + second, os.path.join(tmp, "nofw"))
    r = launch(["s.py"], old, pre_ev, iso2)
    check("второе место в DIRS: python3.13 берётся", r.stdout.strip() == "SEC313 -I s.py", (r.stdout, r.stderr))
    first = os.path.join(tmp, "first")
    fake(first, "python3.14", 'echo "FIRST314 $*"')
    iso3 = isolated(os.path.join(tmp, "nope2") + ":" + os.path.join(tmp, "nope3"), os.path.join(tmp, "nofw"))
    r = launch(["s.py"], f"{first}:{old}", pre_ev, iso3)
    check("первое место в PATH (при пустых DIRS и FW): python3.14 берётся",
          r.stdout.strip() == "FIRST314 -I s.py", (r.stdout, r.stderr))
    # --- metis-0330 F3: пропавший файл скрипта и висячий интерпретатор не «залипают» кодом 2 ----------------------
    fail_log = os.path.join(tmp, ".local", "state", "pantheon", "logs", "guard-failures.log")

    def log_lines():
        try:
            with open(fail_log, encoding="utf-8") as fh:
                return fh.read().splitlines()
        except OSError:
            return []

    real = os.path.dirname(sys.executable) + ":/usr/bin:/bin"
    gone = os.path.join(tmp, "renamed", "guard.py")
    r = launch([gone, "--strict"], real, pre_ev)
    check("нет файла скрипта → PreToolUse: код 2, причина с именем файла",
          r.returncode == 2 and "файла скрипта нет" in r.stderr and "guard.py" in r.stderr and r.stdout == ""
          and "can't open file" not in r.stderr, (r.returncode, r.stdout, r.stderr))
    check("нет файла скрипта → строка launcher в guard-failures.log",
          any(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\tlauncher\tPreToolUse\tno-script guard\.py", ln)
              for ln in log_lines()), log_lines())
    for ev in ("Stop", "UserPromptSubmit", "PostToolUse", "SessionStart", "SubagentStop"):
        r = launch([gone], real, json.dumps({"hook_event_name": ev, "session_id": "s"}))
        check(f"нет файла скрипта → {ev}: код 0 без вывода (не залипший код 2)",
              r.returncode == 0 and r.stdout == "" and r.stderr == "", (r.returncode, r.stdout, r.stderr))
    check("нет файла скрипта на Stop → строка launcher other в журнале",
          any(ln.endswith("\tlauncher\tother\tno-script guard.py") for ln in log_lines()), log_lines())
    os.makedirs(os.path.join(tmp, "dirpy", "ctx.py"))
    r = launch([os.path.join(tmp, "dirpy", "ctx.py")], real, json.dumps({"hook_event_name": "Stop"}))
    check("папка на месте скрипта → Stop: код 0", r.returncode == 0 and r.stderr == "", (r.returncode, r.stderr))
    # файл есть, но не читается (chmod 0): Python тоже вышел бы с кодом 2 — ветка `! [ -r ]` запускателя
    noread = os.path.join(tmp, "noread", "ctx.py")
    os.makedirs(os.path.dirname(noread))
    open(noread, "w").close()
    os.chmod(noread, 0)
    if os.geteuid() != 0:  # root читает и файл без прав — проверка там не о том
        r = launch([noread], real, json.dumps({"hook_event_name": "Stop"}))
        check("файл скрипта без прав чтения → Stop: код 0 без вывода",
              r.returncode == 0 and r.stdout == "" and r.stderr == "", (r.returncode, r.stdout, r.stderr))
        r = launch([noread, "maint-pre"], real, pre_ev)
        check("файл скрипта без прав чтения → PreToolUse: код 2 с причиной",
              r.returncode == 2 and "файла скрипта нет или он не читается" in r.stderr
              and "Permission denied" not in r.stderr,
              (r.returncode, r.stdout, r.stderr))
    os.chmod(noread, 0o600)
    n0 = len(log_lines())
    r = launch(["x.py"], old, json.dumps({"hook_event_name": "Stop"}), iso)
    check("нет 3.11+ → строка launcher no-python в журнале",
          len(log_lines()) == n0 + 1 and log_lines()[-1].endswith("\tlauncher\tother\tno-python x.py"), log_lines())
    r = launch(["-c", PROBE], real)
    check("-c без файла скрипта работает как раньше", r.returncode == 0 and re.fullmatch(r"\d+\.\d+", r.stdout.strip()),
          (r.returncode, r.stdout, r.stderr))
    script = os.path.join(tmp, "ok.py")
    with open(script, "w") as fh:
        fh.write("import sys; print('OK', sys.stdin.read()[:30])\n")
    r = launch([script], real, '{"hook_event_name": "Stop"}')
    check("файл скрипта на месте → stdin доходит до скрипта нетронутым",
          r.returncode == 0 and r.stdout.strip() == 'OK {"hook_event_name": "Stop"}', (r.returncode, r.stdout, r.stderr))

    # висячая ссылка python3.14 в известной папке (brew удалил Cellar) — пропускается, берётся следующий
    dang_known, dang_path = os.path.join(tmp, "dangk"), os.path.join(tmp, "dangp")
    os.makedirs(dang_known)
    os.symlink(os.path.join(tmp, "Cellar-removed", "python3.14"), os.path.join(dang_known, "python3.14"))
    fake(dang_path, "python3.13", 'echo "NEXT313 $*"')
    iso4 = isolated(dang_known, os.path.join(tmp, "nofw2"))
    r = launch(["s.py"], f"{dang_path}:{old}", pre_ev, iso4)
    check("висячая ссылка python3.14 пропущена → python3.13 из PATH", r.stdout.strip() == "NEXT313 -I s.py",
          (r.returncode, r.stdout, r.stderr))

    # настоящие команды hooks.json на корне плагина, где .py пропали (переименование, сломанный кэш версии):
    # PreToolUse — отказ с причиной (критичная защита не запустилась), остальные события — не код 2
    state = os.path.join(tmp, "pstate")
    os.makedirs(os.path.join(state, "push"))
    with open(os.path.join(state, "maintenance.json"), "w") as fh:
        fh.write("{}")
    for plugin in ("guard", "pantheon"):
        hj = os.path.join(ROOT, plugin, "hooks", "hooks.json")
        if not os.path.exists(hj):
            continue
        root = os.path.join(tmp, "broken-" + plugin)
        os.makedirs(os.path.join(root, "hooks"))
        shutil.copy2(os.path.join(ROOT, plugin, "hooks", "python.sh"), os.path.join(root, "hooks", "python.sh"))
        with open(hj, encoding="utf-8") as fh:
            hooks = json.load(fh)["hooks"]
        ran = 0
        for event, groups in hooks.items():
            for g in groups:
                for h in g["hooks"]:
                    if "python.sh" not in h["command"]:
                        continue
                    ran += 1
                    env = {"PATH": real, "HOME": tmp, "CLAUDE_PLUGIN_ROOT": root, "PANTHEON_STATE": state}
                    ev_json = json.dumps({"hook_event_name": event, "session_id": "s", "tool_name": "Bash",
                                          "tool_input": {"command": "ls"}})
                    r = subprocess.run(["/bin/sh", "-c", h["command"]], input=ev_json, env=env, capture_output=True,
                                       text=True, timeout=60, cwd=tmp)
                    tag = f"{plugin} {event} {h['command'].rsplit('/hooks/', 1)[-1][:40]}"
                    if event == "PreToolUse":
                        check(f"без .py: {tag} → код 2 с причиной", r.returncode == 2 and "файла скрипта нет" in r.stderr,
                              (r.returncode, r.stderr))
                    else:
                        check(f"без .py: {tag} → код 0, не залипший 2", r.returncode == 0 and r.stderr == "",
                              (r.returncode, r.stderr))
        check(f"без .py: команды {plugin} через python.sh проверены ({ran})", ran >= 3, ran)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"{sum(results)} из {len(results)}")
sys.exit(0 if all(results) else 1)
