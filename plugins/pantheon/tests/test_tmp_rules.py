#!/usr/bin/env python3
"""Правила общего $TMPDIR и защиты журналов в ролях (metis-0353).

Случай 20.10: разработчик хотел записать свой `$TMPDIR/runall.sh`, Write отказал («File has not been read yet» — файл
уже был), а он всё равно запустил `bash $TMPDIR/runall.sh`. Это был скрипт ночной сессии 19.10, и он начинался с
`: > …/logs/night-1019/fix-tests.log` — журнал ночного прогона затёрт. guard такие запуски нарочно не разбирает
(README guard, модель угроз), поэтому защита — правило в общих частях ролей и `chmod a-w` у сданного журнала.

Что проверяется:
- roles/_parts/tmp.part: $TMPDIR общий для всех сессий, чужой файл оттуда не запускать, после ошибки Write — не запускать;
- roles/_parts/report.part: сданный журнал не перезаписывать и закрывать от записи (`chmod a-w`);
- обе части входят в роли, которые запускают команды (dev-*, codex-dev, talos, hephaestus, workshop, domain-coordinator, argus);
- сам приём работает: в закрытый `chmod a-w` журнал `: > файл` не пишет, текст цел.

Запуск: python3 -I plugins/pantheon/tests/test_tmp_rules.py  (код выхода 0 — все прошли; Python 3.9+)
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLES = os.path.join(ROOT, "roles")
PARTS = os.path.join(ROLES, "_parts")
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else " — " + str(detail)))


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def flat(text):
    return " ".join(text.split())  # перенос строки внутри фразы не мешает поиску


tmp = flat(read(PARTS, "tmp.part"))
check("tmp.part: $TMPDIR один на все сессии", "один на все сессии" in tmp, tmp[-600:])
check("tmp.part: свои скрипты — только в своей папке tmp-<задача>, не в корень",
      "только в свою папку" in tmp and "не в корень `$TMPDIR`" in tmp)
check("tmp.part: чужой файл из $TMPDIR не запускать и не перезаписывать",
      "Чужой файл из `$TMPDIR` не запускай и не перезаписывай" in tmp)
check("tmp.part: Write или Edit вернул ошибку — не запускать", "вернул ошибку" in tmp and "запускать его нельзя" in tmp)

report = flat(read(PARTS, "report.part"))
check("report.part: сданный журнал не перезаписывать, новый прогон — новый файл",
      "не перезаписывай" in report and "новый прогон — новый файл" in report, report[-500:])
check("report.part: журнал после сдачи — chmod a-w", "chmod a-w" in report)

for role in ("dev-opus", "dev-sonnet", "dev-haiku", "codex-dev", "talos", "hephaestus", "workshop",
             "domain-coordinator", "argus"):
    text = read(ROLES, role + ".tmpl")
    check(f"{role}: входят части tmp и report", "{{> tmp}}" in text and "{{> report}}" in text)

# Приём из report.part: закрытый от записи журнал оболочка не обрезает и владельцу (не root).
d = tempfile.mkdtemp(prefix="tmp-0353-")
try:
    log = os.path.join(d, "fix-tests.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("ночной прогон\n")
    os.chmod(log, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # chmod a-w
    r = subprocess.run(["/bin/sh", "-c", ': > "$1"', "sh", log], capture_output=True, text=True)
    check("chmod a-w: `: > журнал` падает (код не 0)", r.returncode != 0 or os.geteuid() == 0, r.returncode)
    check("chmod a-w: текст журнала цел", read(log) == "ночной прогон\n" or os.geteuid() == 0, read(log))
finally:
    for p in (d, os.path.join(d, "fix-tests.log")):
        if os.path.exists(p):
            os.chmod(p, stat.S_IRWXU)
    shutil.rmtree(d, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
