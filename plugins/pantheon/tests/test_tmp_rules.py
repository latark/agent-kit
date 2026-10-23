#!/usr/bin/env python3
"""Правила общего $TMPDIR и защиты логов прогона в ролях (metis-0353).

Случай 20.10: разработчик хотел записать свой `$TMPDIR/runall.sh`, Write отказал («File has not been read yet» — файл
уже был), а он всё равно запустил `bash $TMPDIR/runall.sh`. Это был скрипт ночной сессии 19.10, и он начинался с
`: > …/logs/night-1019/fix-tests.log` — лог ночного прогона затёрт. guard такие запуски нарочно не разбирает
(README guard, модель угроз), поэтому защита — правило в общих частях ролей и `chmod a-w` у сданного лога.

Что проверяется (целые фразы, а не обрывки: перевёрнутый смысл той же фразы тест ловит):
- roles/_parts/tmp.part: своя папка — `mktemp -d -p "$TMPDIR" tmp-<задача>-XXXXXX`, не предсказуемое `tmp-<задача>`;
  $TMPDIR общий для всех сессий; файл в папке, которую создала не эта сессия, — чужой; чужой файл не запускать;
  отказ Write или Edit файла в $TMPDIR («File has not been read yet») — не запускать;
- roles/_parts/report.part: сданный лог прогона не перезаписывать и закрывать от записи (`chmod a-w`);
- tmp.part входит во все роли, которые запускают команды в общем $TMPDIR (обязательный набор, в нём hq), и каждый
  шаблон с `{{> tmp}}` найден обходом всех roles/*.tmpl; у них же, кроме hq, есть `{{> report}}`;
- сам приём работает: в закрытый `chmod a-w` лог `: > файл` не пишет, текст цел.

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


def has(text, phrase):
    return flat(phrase) in text


TMP_PHRASES = [
    "Временные файлы — только в своей папке внутри `$TMPDIR`.",
    "Её создаёт сама сессия, в начале работы: `mktemp -d -p \"$TMPDIR\" tmp-<задача>-XXXXXX` — случайный хвост имени,"
    " папка новая и пустая.",
    "Временный файл — `mktemp -p \"<своя папка>\"` или своё имя в ней.",
    "`$TMPDIR` — один на все сессии этого Mac:",
    "а папка `tmp-<задача>` без случайного хвоста бывает от прошлой сессии той же задачи.",
    "Свои скрипты и логи клади только в свою папку, не в корень `$TMPDIR`.",
    "Файл в папке, которую создала не эта сессия, — чужой.",
    "Чужой файл из `$TMPDIR` не запускай и не перезаписывай: он может писать в логи других сессий (metis-0353).",
    "Write или Edit файла в `$TMPDIR` отказал («File has not been read yet» — файл с этим именем уже есть) — не запускай"
    " его: возьми новое имя в своей папке.",
]
# Старые формулировки, которые спорили с правилом своей папки (ревью PR 111): mktemp в корень $TMPDIR, предсказуемая
# папка tmp-<задача> и «Write или Edit вернул ошибку» без оговорки про $TMPDIR — ни одной из них в части нет.
TMP_GONE = ['mktemp -p "$TMPDIR"', '"$TMPDIR/tmp-<задача>/', "вернул ошибку", "журнал"]

tmp = flat(read(PARTS, "tmp.part"))
for phrase in TMP_PHRASES:
    check("tmp.part: «" + phrase[:60] + "…»", has(tmp, phrase), tmp)
for old in TMP_GONE:
    check("tmp.part: нет старого «" + old + "»", old not in tmp)

REPORT_PHRASES = [
    "Лог прогона, на который уже ссылается отчёт, задача или `STATUS.md`, не перезаписывай: новый прогон — новый файл.",
    "Свой лог прогона вне `$TMPDIR` после сдачи закрой от записи: `chmod a-w <файл>`.",
    "Тогда чужой скрипт с `: > <файл>` упадёт с «Permission denied» и не затрёт его (metis-0353).",
]
report = flat(read(PARTS, "report.part"))
for phrase in REPORT_PHRASES:
    check("report.part: «" + phrase[:60] + "…»", has(report, phrase), report[-500:])
check("report.part: «журнал» заменён на «лог прогона»", "журнал" not in report.lower())

# Роли, которые запускают команды в общем $TMPDIR. Набор задан здесь, а не выводится из шаблонов: иначе роль, из
# которой убрали {{> tmp}}, просто выпала бы из проверки.
MUST_TMP = {"dev-opus", "dev-sonnet", "dev-haiku", "codex-dev", "talos", "hephaestus", "workshop",
            "domain-coordinator", "argus", "hq"}
NO_REPORT = {"hq"}  # Пританей пишет владельцу, а не отчёт DONE-01 наверх
templates = {f[:-len(".tmpl")]: read(ROLES, f) for f in sorted(os.listdir(ROLES)) if f.endswith(".tmpl")}
with_tmp = {r for r, text in templates.items() if "{{> tmp}}" in text}
check("шаблоны с {{> tmp}} найдены обходом roles/*.tmpl, hq среди них", "hq" in with_tmp, sorted(with_tmp))
for role in sorted(MUST_TMP | with_tmp):
    text = templates.get(role, "")
    check(f"{role}: входит часть tmp", "{{> tmp}}" in text)
    if role not in NO_REPORT:
        check(f"{role}: входит часть report", "{{> report}}" in text)

# Приём из report.part: закрытый от записи лог оболочка не обрезает и владельцу (не root).
d = tempfile.mkdtemp(prefix="tmp-0353-")
try:
    log = os.path.join(d, "fix-tests.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write("ночной прогон\n")
    os.chmod(log, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # chmod a-w
    r = subprocess.run(["/bin/sh", "-c", ': > "$1"', "sh", log], capture_output=True, text=True)
    check("chmod a-w: `: > лог` падает (код не 0)", r.returncode != 0 or os.geteuid() == 0, r.returncode)
    check("chmod a-w: текст лога цел", read(log) == "ночной прогон\n" or os.geteuid() == 0, read(log))
finally:
    for p in (d, os.path.join(d, "fix-tests.log")):
        if os.path.exists(p):
            os.chmod(p, stat.S_IRWXU)
    shutil.rmtree(d, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
