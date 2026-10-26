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
- `{{> tmp}}` есть в каждом roles/*.tmpl (обход всех шаблонов, новый шаблон тоже), кроме словаря исключений NO_TMP,
  где у каждой роли причина: momus и palamedes — Bash нет (и это сверено с disallowedTools), шесть ролей — решение в metis-0371;
  устаревшее исключение (шаблона нет или tmp уже есть) — тоже красное. У шаблонов с tmp, кроме hq, есть `{{> report}}`;
- ни в одном шаблоне и части нет предсказуемой папки: пути `$TMPDIR/tmp-…` и `tmp-…/` без `XXXXXX` (codex-dev:
  поручение — в своей папке из `mktemp -d -p "$TMPDIR" tmp-codex-<ветка>-XXXXXX`), а `mkdir -p` упомянут только в
  запрете «Не `mkdir -p` — на чужой папке он молча вернёт 0»;
- сам приём работает: в закрытый `chmod a-w` лог `: > файл` не пишет, текст цел.

Запуск: python3 -I plugins/pantheon/tests/test_tmp_rules.py  (код выхода 0 — все прошли; Python 3.9+)
"""
import os
import re
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
    "Не `mkdir -p` — на чужой папке он молча вернёт 0.",
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

# Шаблоны без {{> tmp}}: только с причиной. Любой другой шаблон, в том числе новый, обязан включать часть — иначе
# роль с Bash кладёт файлы в общий $TMPDIR без правила своей папки (ревью PR 111, мутант MA).
NO_BASH = "Bash нет"
NO_TMP = {
    "momus": NO_BASH,
    "palamedes": NO_BASH,  # исполнитель без кода (metis-0224): команд оболочки нет
    **{r: "решение в metis-0371" for r in ("apollo", "clio", "iris", "prometheus", "hestia", "chiron")},
}
NO_REPORT = {"hq"}  # Пританей пишет владельцу, а не отчёт DONE-01 наверх
templates = {f[:-len(".tmpl")]: read(ROLES, f) for f in sorted(os.listdir(ROLES)) if f.endswith(".tmpl")}
parts = {f: read(PARTS, f) for f in sorted(os.listdir(PARTS)) if f.endswith(".part")}
with_tmp = {r for r, text in templates.items() if "{{> tmp}}" in text}
check("обход roles/*.tmpl нашёл шаблоны с tmp, hq и codex-dev среди них", {"hq", "codex-dev"} <= with_tmp,
      sorted(with_tmp))


def disallowed(text):
    line = next((ln for ln in text.splitlines() if ln.startswith("disallowedTools:")), "")
    return {t.strip() for t in line.split(":", 1)[-1].split(",")}


for role, why in sorted(NO_TMP.items()):
    text = templates.get(role)
    check(f"{role}: исключение без tmp ({why}) — шаблон есть", text is not None)
    check(f"{role}: исключение не устарело — {{{{> tmp}}}} ещё нет", role not in with_tmp)
    if why == NO_BASH:
        check(f"{role}: Bash и правда запрещён (disallowedTools)", "Bash" in disallowed(text or ""))
for role in sorted(templates):
    if role in NO_TMP:
        continue
    text = templates[role]
    check(f"{role}: входит часть tmp (или причина в NO_TMP)", "{{> tmp}}" in text)
    if role not in NO_REPORT:
        check(f"{role}: входит часть report", "{{> report}}" in text)

# Предсказуемая папка в $TMPDIR — та же ловушка, что в случае 0353: её могла завести прошлая сессия. Своя папка
# называется только через mktemp -d, путь — из его вывода; в тексте ролей остаётся шаблон с XXXXXX.
FIXED_DIR = re.compile(r"\$TMPDIR/tmp-|tmp-[^\s`\"'/]*/")
MKDIR_BAN = "Не `mkdir -p` — на чужой папке он молча вернёт 0."
texts = {f"roles/{r}.tmpl": t for r, t in templates.items()}
texts.update({f"roles/_parts/{f}": t for f, t in parts.items()})
for name, text in sorted(texts.items()):
    bad = [m.group(0) for m in FIXED_DIR.finditer(text) if "XXXXXX" not in m.group(0)]
    check(f"{name}: нет предсказуемой папки в $TMPDIR", not bad, bad)
    allowed = flat(text).count(MKDIR_BAN)
    check(f"{name}: `mkdir -p` только в запрете", flat(text).count("mkdir -p") == allowed, allowed)

CODEX_PHRASES = [
    "1. Своя папка на поручение — отдельным вызовом `mktemp -d -p \"$TMPDIR\" tmp-codex-<ветка>-XXXXXX`, путь бери из"
    " его вывода.",
    "Папку `tmp-codex-<ветка>` без хвоста заводит обёртка для своих логов — поручение туда не клади.",
    "Поручение лида или координатора — дословно в файл `<своя папка>/brief.md`, без своих добавлений.",
    "`pantheon exec codex <папка worktree> \"<своя папка>/brief.md\"`.",
]
codex = flat(templates.get("codex-dev", ""))
for phrase in CODEX_PHRASES:
    check("codex-dev: «" + phrase[:60] + "…»", has(codex, phrase))

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
