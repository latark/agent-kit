#!/usr/bin/env python3
"""Замеры вне окна (metis-0537): тик пишет STATE/probes.json, окно читает свежий замер, старый/битый/нет — как «не прочитано».

Запуск: python3.14 -I plugins/pantheon/tests/test_probes.py  (код выхода 0 — все прошли)
Всё во временных папках: HOME, PANTHEON_HOME, PANTHEON_STATE подменены; sysctl, memory_pressure и claude — заглушки в PATH.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="probes-"))
atexit.register(shutil.rmtree, ROOT, True)
LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIBDIR, "run.py")
T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def script(path, body):
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n" + body)
    os.chmod(path, 0o755)


class Env:
    def __init__(self, tag, readable):
        """readable=True — «вне окна»: sysctl и memory_pressure отвечают; False — «окно роли»: sysctl даёт EPERM."""
        base = os.path.join(ROOT, tag)
        self.home, self.pan, self.state = (os.path.join(base, d) for d in ("home", "pantheon", "state"))
        self.bin = os.path.join(base, "bin")
        for d in (self.home, self.pan, self.state, self.bin):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(self.pan, "schedule.toml"), "w") as fh:
            fh.write('primary_host = "mac-a"\n')
        if readable:
            script(os.path.join(self.bin, "sysctl"),
                   'case "$*" in\n *vm.swapusage*) echo "vm.swapusage: total = 4096.00M  used = 2560.00M  free = 1.00M  (encrypted)";;\n'
                   ' *pressure_level*) echo 2;;\n *) exit 1;;\nesac\n')
            script(os.path.join(self.bin, "memory_pressure"), 'echo "System-wide memory free percentage: 40%"\n')
        else:
            script(os.path.join(self.bin, "sysctl"), 'echo "sysctl: Operation not permitted" >&2\nexit 1\n')
            script(os.path.join(self.bin, "memory_pressure"), 'exit 1\n')
        script(os.path.join(self.bin, "claude"), 'echo "Context Usage 12%"\necho "$@" > "$0.args"\n')
        self.probes = os.path.join(self.state, "probes.json")

    def env(self, t, **extra):
        e = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin", "HOME": self.home, "PANTHEON_HOME": self.pan,
             "PANTHEON_STATE": self.state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1",
             "TMPDIR": ROOT}
        e.update(extra)
        return e

    def run(self, args, t, **extra):
        return subprocess.run([PY311, "-I", RUN_PY] + args, env=self.env(t, **extra), capture_output=True, text=True,
                              timeout=60)

    def py(self, code, t, **extra):
        return subprocess.run([PY311, "-I", "-c", code, LIBDIR], env=self.env(t, **extra), capture_output=True,
                              text=True, timeout=60)

    def window(self, t):
        """capacity_probe и _memory_pressure так, как их зовёт окно роли."""
        code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import pantheon as P; "
                "m = P.capacity_probe(None); print(json.dumps({'m': m, 'p': P._memory_pressure()}))")
        r = self.py(code, t, PANTHEON_FAKE_PRESSURE="")
        return json.loads(r.stdout) if r.returncode == 0 else {"err": r.stderr[-300:]}

    def put(self, data):
        with open(self.probes, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def log(self):
        p = os.path.join(self.state, "dryrun.log")
        return open(p).read() if os.path.exists(p) else ""


def mem(t, **kw):
    return {"v": 1, "mem": dict({"time": t, "swap_gb": 2.5, "pressure": 2, "free_pct": 40}, **kw)}


# 1. тик вне окна пишет замер
e = Env("tick", True)
r = e.run(["tick"], T0, PANTHEON_DRYRUN="1")
d = json.load(open(e.probes)) if os.path.exists(e.probes) else {}
check("1. тик пишет probes.json со свопом, давлением и свободно %",
      r.returncode == 0 and d.get("mem", {}).get("swap_gb") == 2.5 and d["mem"].get("pressure") == 2
      and d["mem"].get("free_pct") == 40 and d["mem"].get("time") == T0, (r.stderr[-200:], d))

# 2. окно читает свежий замер
w = Env("fresh", False)
w.put(mem(T0 - 60))
res = w.window(T0)
m = res.get("m", {})
check("2. окно: свежий замер даёт своп, давление, свободно %",
      m.get("swap_gb") == 2.5 and m.get("pressure") == 2 and m.get("free_pct") == 40 and res.get("p") == 2, res)
check("2. окно: давление «предупреждение» из файла краснит замер, сигнал не «неизвестно»",
      m.get("red") and m.get("unknown") is False, m)

# 3. старый, битый, нет — прежнее поведение
bad = {
    "нет файла": None,
    "старый (601 с)": mem(T0 - 601),
    "из будущего": mem(T0 + 100),
    "битый JSON": "{не json",
    "список вместо словаря": "[1, 2]",
    "mem не словарь": {"mem": "x"},
    "время строкой": mem("вчера"),
    "время bool": mem(True),
    "значения строками": mem(T0 - 5, swap_gb="2.5", pressure="2", free_pct="40"),
    "давление 3 (остальное пусто)": mem(T0 - 5, swap_gb=None, pressure=3, free_pct=None),
}
for i, (label, content) in enumerate(bad.items()):
    w = Env(f"bad{i}", False)
    if content is not None:
        w.put(content)
    res = w.window(T0)
    m = res.get("m", {})
    ok = (m.get("swap_gb") is None and m.get("pressure") is None and m.get("free_pct") is None
          and m.get("unknown") is True and res.get("p") is None and "err" not in res)
    check(f"3. {label}: как раньше — «неизвестно», без падения", ok, res)

# 4. граница свежести: ровно 600 с — ещё свежий
w = Env("edge", False)
w.put(mem(T0 - 600))
check("4. 600 с — свежий, окно берёт", w.window(T0).get("m", {}).get("swap_gb") == 2.5)

# 5. прямое чтение главнее файла
e = Env("direct", True)
e.put(mem(T0 - 5, swap_gb=9.0, pressure=4, free_pct=1))
code = "import sys, json; sys.path.insert(0, sys.argv[1]); import pantheon as P; print(json.dumps(P.capacity_probe(None)))"
r = e.py(code, T0)
m = json.loads(r.stdout) if r.returncode == 0 else {}
check("5. sysctl читается — файл не нужен, цифры живые", m.get("swap_gb") == 2.5 and m.get("pressure") == 2
      and m.get("free_pct") == 40, (m, r.stderr[-200:]))

# 6. тик, который ничего не прочитал, не затирает прежний замер
e = Env("keep", False)
e.put(mem(T0 - 30))
before = open(e.probes).read()
e.run(["tick"], T0, PANTHEON_DRYRUN="1", PANTHEON_FAKE_PRESSURE="")
check("6. тик без сигналов не трогает файл", open(e.probes).read() == before)

# 7. /context: по умолчанию выключен
e = Env("ctx-off", True)
e.run(["tick"], T0, PANTHEON_DRYRUN="1")
check("7. выключатель не стоит — замер /context не запускается", "probes-context" not in e.log(), e.log())

# 8. включён: запуск, пауза N часов, повтор
e = Env("ctx-on", True)
with open(os.path.join(e.state, "probe-context"), "w") as fh:
    fh.write("2\n")
e.run(["tick"], T0, PANTHEON_DRYRUN="1")
n1 = e.log().count("probes-context")
e.run(["tick"], T0 + 7199, PANTHEON_DRYRUN="1")
n2 = e.log().count("probes-context")
e.run(["tick"], T0 + 7201, PANTHEON_DRYRUN="1")
n3 = e.log().count("probes-context")
check("8. включён на 2 ч: запуск сразу, нет на 7199-й секунде, есть на 7201-й", (n1, n2, n3) == (1, 1, 2), (n1, n2, n3))
with open(os.path.join(e.state, "probe-context"), "w") as fh:
    fh.write("не число\n")
e.run(["tick"], T0 + 7201 + 6 * 3600 - 1, PANTHEON_DRYRUN="1")
a = e.log().count("probes-context")
e.run(["tick"], T0 + 7201 + 6 * 3600 + 1, PANTHEON_DRYRUN="1")
check("8. в файле не число — шесть часов по умолчанию", (a, e.log().count("probes-context")) == (2, 3),
      (a, e.log().count("probes-context")))

# 9. сам замер /context: текст и код в файле; сбой — запись и код 1
e = Env("ctx-run", True)
r = e.run(["probes", "context"], T0)
c = json.load(open(e.probes)).get("context", {})
check("9. probes context: текст и код выхода в файле", r.returncode == 0 and c.get("rc") == 0
      and "Context Usage 12%" in c.get("text", "") and c.get("time") == T0, (r.returncode, c, r.stderr[-200:]))
check("9. вызван именно claude -p /context", open(os.path.join(e.bin, "claude.args")).read().split() == ["-p", "/context"])
script(os.path.join(e.bin, "claude"), 'echo "нет сети" >&2\nexit 3\n')
r = e.run(["probes", "context"], T0 + 5)
c = json.load(open(e.probes)).get("context", {})
check("9. claude упал: код 1, rc и причина в файле", r.returncode == 1 and c.get("rc") == 3 and "нет сети" in (c.get("error") or ""),
      (r.returncode, c))
os.remove(os.path.join(e.bin, "claude"))
r = e.run(["probes", "context"], T0 + 9, PATH=e.bin)
c = json.load(open(e.probes)).get("context", {})
check("9. claude не найден: код 1, ошибка в файле", r.returncode == 1 and c.get("error"), (r.returncode, c, r.stderr[-200:]))

# 10. pantheon probes show
e = Env("show", True)
e.run(["tick"], T0, PANTHEON_DRYRUN="1")
r = e.run(["probes"], T0 + 30)
check("10. probes show: возраст замера и состояние выключателя", r.returncode == 0 and "mem: 30 с назад (свежий)" in r.stdout
      and "выключен" in r.stdout, r.stdout + r.stderr[-200:])
r = e.run(["probes"], T0 + 700)
check("10. probes show: старый замер назван старым", "старый" in r.stdout, r.stdout)
r = e.run(["probes", "bogus"], T0)
check("10. неизвестная подкоманда: код 2", r.returncode == 2, r.returncode)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
