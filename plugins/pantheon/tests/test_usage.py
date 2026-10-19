#!/usr/bin/env python3
"""usage.py: расход по ролям и доля топ-10 % сессий на транскриптах-образцах во временном HOME.

Запуск: python3 -I plugins/pantheon/tests/test_usage.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "usage.py")
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name)


home = os.path.realpath(tempfile.mkdtemp(prefix="usage-test-"))
atexit.register(shutil.rmtree, home, True)
proj = os.path.join(home, ".claude", "projects", "-p")
NOW = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
SEQ = [0]


def req(out_tokens):
    """Запись assistant: sonnet-5-5, вывод 10 $ за 1M — out_tokens=100000 это ровно 1 $."""
    SEQ[0] += 1
    return {"type": "assistant", "timestamp": NOW, "requestId": f"r{SEQ[0]}",
            "message": {"id": f"m{SEQ[0]}", "model": "claude-sonnet-5-5",
                        "usage": {"input_tokens": 0, "output_tokens": out_tokens}}}


def write(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# S1: роль hq, 10 $ + субагент dev-sonnet по meta 6 $ = 16 $; S2: domain-coordinator 1 $ + субагент без meta 1 $;
# S3..S10: без роли по 1 $. Всего 10 сессий, 26 $, топ-10 % = одна сессия S1 = 16/26 = 62 %.
sid1 = "aaaaaaaa-0000-0000-0000-000000000001"
write(f"{proj}/{sid1}.jsonl", [{"type": "agent-setting", "agentSetting": "hq"},
                              {"type": "agent-name", "agentName": "zeus"}, req(1_000_000)])
write(f"{proj}/{sid1}/subagents/agent-x1.jsonl", [req(600_000)])
with open(f"{proj}/{sid1}/subagents/agent-x1.meta.json", "w") as fh:
    json.dump({"agentType": "dev-sonnet"}, fh)
sid2 = "bbbbbbbb-0000-0000-0000-000000000002"
write(f"{proj}/{sid2}.jsonl", [{"type": "agent-setting", "agentSetting": "domain-coordinator"}, req(100_000)])
write(f"{proj}/{sid2}/subagents/agent-y1.jsonl", [req(100_000)])
for i in range(3, 11):
    write(f"{proj}/cccccc{i:02d}-0000-0000-0000-000000000000.jsonl", [req(100_000)])

# metis-0208: недоступный транскрипт (в окне агента так было с чужими) пропускается, остальное считается
locked = f"{proj}/dddddddd-0000-0000-0000-000000000000.jsonl"
write(locked, [req(100_000)])
os.chmod(locked, 0)
can_lock = not os.access(locked, os.R_OK)  # под root chmod 0 не закрывает файл

env = {"PATH": os.environ["PATH"], "HOME": home}
p = subprocess.run([sys.executable, "-I", SCRIPT, "7"], env=env, capture_output=True, text=True)
out = p.stdout
check("прогон без ошибки", p.returncode == 0 and not p.stderr)


def row(label):
    return [x.split() for x in out.splitlines() if x.startswith(label)]


hq = row("hq ")
check("роль основной сессии из agent-setting: hq, 1 запрос, 10 $", hq and hq[0][1:3] == ["1", "10"])
ds = row("dev-sonnet")
check("роль субагента из meta: dev-sonnet, 6 $", ds and ds[0][1:3] == ["1", "6"])
dc = row("domain-coordinator")
check("domain-coordinator: 1 $", dc and dc[0][1:3] == ["1", "1"])
nt = row("субагент без типа")
check("субагент без meta — «субагент без типа»", nt and nt[0][3:6] == ["1", "1", "4%"])
nr = row("без роли")
check("без agent-setting — «без роли»: 8 сессий, 8 $", nr and nr[0][2:3] == ["8"] and nr[0][-1] == "8")
check("роли по убыванию $", out.index("\nhq ") < out.index("\ndev-sonnet"))
check("топ-10 %: 1 из 10 сессий, 16 $ = 62 % всех $", "1 из 10, на них $16 = 62%" in out)
check("самая дорогая сессия: id из 8 знаков и роль, без пути", "  aaaaaaaa  hq" in out and home not in out
      and sid1 not in out)
check("шапка объясняет, что такое сессия", "основной транскрипт вместе с его субагентами" in out)
check("недоступный .jsonl пропущен: сводка есть, в ней строка о пропуске",
      not can_lock or "Пропущено недоступных транскриптов: 1" in out)
os.chmod(locked, 0o600)
shutil.rmtree(home, True)
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
