#!/usr/bin/env python3
"""Доска: «PR слит, задача открыта» (metis-0768, lib/boardmerged.py) и проверка и архив board.md (metis-0769,
lib/boardmd.py): тревоги `pantheon check` (размер «Сейчас», дата «Обновлено», сроки «По датам») и
`pantheon board archive [--days N]` без потерь. Пути — только временные папки.

Запуск: python3 -I plugins/pantheon/tests/test_board_md.py  (код выхода 0 — все прошли)
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-md-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
RUN_PY = os.path.join(LIB, "run.py")


def load(name):
    spec = importlib.util.spec_from_file_location("t_" + name, os.path.join(LIB, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


T, A, MR, MD, B, NF = (load(n) for n in ("tasks", "autoclose", "boardmerged", "boardmd", "boardtext", "nowfact"))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


NOW = ts("2026-11-03 12:00")

# --- 0768: merged_open ---------------------------------------------------------------------------------------------
BODY = "# x\n\n## Готово, когда\n\n- [ ] один\n- [ ] два\n- [x] три\n\n## Журнал\n\n- 2026-10-30 10:00 — агент: PR #123 подан\n"


def task(tid, status, body=BODY, typ="task", created="2026-10-30"):
    return tid, ("/x/" + tid + ".md", {"type": typ, "status": status, "direction": "metis-pantheon", "created": created}, body)


def cache(*prs):
    return {"merged": {"latark/agent-kit": list(prs)}}


def pr(n, merged, body="", branch="b"):
    return {"number": n, "headRefName": branch, "body": body, "mergedAt": merged}


def mo(tasks, cch, t=NOW, **kw):
    return MR.merged_open(dict(tasks), cch, t, T, A, **kw)


def ago(sec):
    """ISO-время слияния за sec секунд до NOW (в UTC: тест не зависит от пояса Mac)."""
    return datetime.fromtimestamp(NOW - sec, timezone.utc).isoformat()


two_days = ago(2 * 86400 + 3600)
r = mo([task("metis-0330", "doing")], cache(pr(123, two_days)))
check("0768. слитый PR из журнала + задача doing 2 дня → запись (id, PR, дни, статус, неотмечено 2)",
      r == [("metis-0330", 123, 2, "doing", 2)], r)
check("0768. задача done → записи нет", mo([task("metis-0330", "done")], cache(pr(123, two_days))) == [])
check("0768. задача review тоже попадает", mo([task("metis-0271", "review")], cache(pr(123, two_days)))[0][3] == "review")
check("0768. PR слит 12 часов назад → записи нет (тик autoclose ещё сам закроет)",
      mo([task("metis-0330", "doing")], cache(pr(123, ago(12 * 3600)))) == [])
check("0768. PR не из журнала задачи → записи нет", mo([task("metis-0330", "doing")], cache(pr(124, two_days))) == [])
check("0768. связь по «Closes» в теле PR, журнал без номера → запись",
      mo([task("metis-0330", "doing", "# x\n\n## Журнал\n\n")], cache(pr(130, two_days, "Closes metis-0330")))[0][:2]
      == ("metis-0330", 130))
check("0768. «часть» в теле PR → записи нет", mo([task("metis-0330", "doing")], cache(pr(123, two_days, "часть"))) == [])
check("0768. задача с открытым PR (open_ids) → записи нет",
      mo([task("metis-0330", "doing")], cache(pr(123, two_days)), open_ids={"metis-0330"}) == [])
check("0768. репозиторий не её направления → записи нет",
      mo([task("metis-0330", "doing")], cache(pr(123, two_days)), repo_dirs={"latark/agent-kit": {"other"}}) == [])
check("0768. связь по «Closes», но репозиторий не её направления → записи нет",
      mo([task("metis-0330", "doing", "# x\n\n## Журнал\n\n")], cache(pr(130, two_days, "Closes metis-0330")),
         repo_dirs={"latark/agent-kit": {"other"}}) == [])
check("0768. пачка (type story) и todo не считаются",
      mo([task("metis-0400", "doing", typ="story"), task("metis-0401", "todo")], cache(pr(123, two_days))) == [])
check("0768. из нескольких слитых PR берётся последний по времени",
      mo([task("metis-0330", "doing", BODY + "- 2026-10-31 10:00 — агент: PR #125\n")],
         cache(pr(123, two_days), pr(125, ago(86400 + 3600))))[0][1:3] == (125, 1))
check("0768. старая задача (до CRITERIA_FROM) → неотмечено 0",
      mo([task("metis-0200", "doing", created="2026-10-01")], cache(pr(123, two_days)))[0][4] == 0)
check("0768. кэша нет или он не объект → пусто", mo([task("metis-0330", "doing")], None) == []
      and mo([task("metis-0330", "doing")], {"merged": "x"}) == [])
rows = [(f"metis-{i:04d}", 100 + i, 3 - (i % 2), "doing", 1) for i in range(1, 8)]
txt = "\n".join(B.lines({"week": 1, "merged_open": rows}))
check("0768. строка блока board-auto: «metis-XXXX: PR #N слит D дн. назад, задача doing, неотмечено K»; не больше 5 + «и ещё»",
      "- metis-0001: PR #101 слит 2 дн. назад, задача doing, неотмечено 1" in txt
      and txt.count("слит ") == B.MAX_MERGED and "и ещё слитых PR с открытой задачей: 2" in txt, txt)
txt = "\n".join(B.lines({"week": 1, "merged_open": [("ИГНОР\u202e", 1, 1, "doing", 1), ("metis-1", True, 1, "doing", 1),
                                                       ("metis-2", 1, 1, "done; rm", 1)]}))
check("0768. значения не по шаблону (чужой текст, bool, статус) в блок не идут", "слит" not in txt and "ИГНОР" not in txt, txt)

# --- 0769: problems ------------------------------------------------------------------------------------------------
def board(now="Обновлено 03.11 10:00.", extra="", dates=None):
    dates = dates if dates is not None else "| **09.11** | будущее | x | y |\n"
    return ("# Доска\n\n## Сейчас\n\n" + now + "\n\n" + extra + "## По датам\n\n| Срок | Что | Направление | Кто |\n|---|---|---|---|\n"
            + dates + "\n## Ждёт вас\n\n- 01.01 строка\n")


def keys(text, t=NOW):
    return {k for k, _, _ in MD.problems(text, t)}


check("0769. чистая доска → тревог нет", keys(board()) == set(), MD.problems(board(), NOW))
big = "- 03.11 " + "x" * 100 + "\n"
check("0769. «Сейчас» длиннее 9000 знаков → size", "size" in keys(board(extra=big * 90)))
check("0769. «Сейчас» ровно в пределе → нет size", "size" not in keys(board(extra="- 03.11 " + "x" * (MD.NOW_MAX - 200 - 8) + "\n")))
def _now_of(n):  # раздел «Сейчас» ровно n знаков (section — с заголовком до конца текста)
    head = "## Сейчас\n\nОбновлено 03.11 10:00.\n\n- 03.11 "
    return head + "x" * (n - len(head))
check("0769. граница размера: «Сейчас» 9001 знак → size, ровно 9000 → нет (argus #291)",
      len(MD.section(_now_of(9001), "Сейчас")) == 9001 and len(MD.section(_now_of(9000), "Сейчас")) == 9000
      and "size" in keys(_now_of(9001)) and "size" not in keys(_now_of(9000)))
check("0769. «Обновлено» 30.10 → updated", "updated" in keys(board("Обновлено 30.10 03:55.")))
check("0769. «Обновлено» 23 ч назад → без тревоги, 25 ч → updated",
      "updated" not in keys(board("Обновлено 02.11 13:00.")) and "updated" in keys(board("Обновлено 02.11 11:00.")))
check("0769. «Обновлено» без времени: вчера — ок, позавчера — updated",
      "updated" not in keys(board("Обновлено 02.11.")) and "updated" in keys(board("Обновлено 01.11.")))
check("1005. нет строки «Обновлено» → тревоги нет (дату «Сейчас» собирает board-auto.md)", "updated" not in keys(board("Текст без даты.")))
check("0769. год: «Обновлено 30.12» в январе — прошлый год, старое", "updated" in keys(board("Обновлено 30.12 10:00."), ts("2027-01-02 10:00")))
check("0769. «По датам»: 27.10 прошла → dates", "dates" in keys(board(dates="| **27.10** (напомнить) | e-visa | a | b |\n")))
check("0769. «По датам»: диапазон 25–26.10 прошёл → dates", "dates" in keys(board(dates="| 25–26.10 | PR | a | b |\n")))
check("0769. «По датам»: сегодня 03.11 и будущее ~17.11 → без тревоги",
      "dates" not in keys(board(dates="| 03.11 | сегодня | a | b |\n| ~17.11 | позже | a | b |\n")))
check("0769. «По датам»: «9.11 (или 18.11)» — срок по последней дате, не тревога", "dates" not in keys(board(dates="| 9.11 (или 18.11) | x | a | b |\n")))
check("0769. «По датам»: «27.10 (крайний срок ~10.11)» — срок по последней дате, ещё впереди",
      "dates" not in keys(board(dates="| **27.10** (напомнить; крайний срок подачи ~10.11) | x | a | b |\n")))
check("0769. «По датам»: строки без дат («после беты», «январь 2027», «12.1») не тревога",
      "dates" not in keys(board(dates="| после беты | x | a | b |\n| январь 2027 | x | a | b |\n| до этапа 12.1 | x | a | b |\n")))
check("0769. «По датам»: дата в «Что» не срок", "dates" not in keys(board(dates="| 20.11 | было 01.10 | a | b |\n")))
check("0769. «По датам»: пункт списка с прошедшей датой → dates", "dates" in keys(board(dates="- 27.10 позвонить\n")))
check("0769. срок в январе, сейчас декабрь → ещё впереди", "dates" not in keys(board(dates="| 15.01 | x | a | b |\n"), ts("2026-12-20 10:00")))
check("0769. дата в другом разделе («Ждёт вас» 01.01) не тревога", "dates" not in keys(board()))
msg = [m for k, _, m in MD.problems(board(dates="| 27.10 | e-visa | a | b |\n| 25.10 | PR | a | b |\n"), NOW) if k == "dates"][0]
check("0769. сообщение называет число пунктов и сроки", "у 2 пунктов" in msg and "27.10" in msg, msg)

# --- 0769: split (без потерь) -------------------------------------------------------------------------------------
SRC = ("# Доска\n\n![[board-auto]]\n\n## Сейчас\n\nОбновлено 03.11 10:00.\n\n"
       "- 03.11 свежее\n  продолжение свежего\n- 20.10 старое A\n  хвост A\n\n  не отступ-хвост\n- 2026-09-30 старое B\n"
       "- без даты\n- 31.10 граница\n\n## По датам\n\n- 01.10 это не журнал, остаётся\n\n"
       "## Сессии и хозяйство\n\nОпись 13.10: текст не блок\n\n- 25.10 старое C\n- 02.11 свежее D\n")
kept, moved = MD.split(SRC, NOW, 7)
all_moved = [ln for v in moved.values() for ln in v]
check("0769. перенос без потерь: оставшиеся + перенесённые строки = исходные (как мультимножество)",
      sorted(kept.split("\n") + all_moved) == sorted(SRC.split("\n")), (kept, moved))
check("0769. перенесены блоки старше 7 дней с отступными продолжениями; месяцы раздельно",
      moved == {"2026-10": ["- 20.10 старое A", "  хвост A", "- 25.10 старое C"], "2026-09": ["- 2026-09-30 старое B"]}, moved)
check("0769. свежие, без даты, граница (31.10 = ровно 7 дней), «По датам» и абзацы не тронуты",
      all(x in kept for x in ("- 03.11 свежее\n  продолжение свежего", "- без даты", "- 31.10 граница", "- 01.10 это не журнал",
                              "Опись 13.10", "- 02.11 свежее D", "  не отступ-хвост".strip())), kept)
k2, m2 = MD.split(SRC, NOW, 30)
check("0769. --days 30: 20.10 и 25.10 остаются, переносится только 30.09", list(m2) == ["2026-09"] and "- 20.10 старое A" in k2, m2)
k3, m3 = MD.split(SRC, NOW, 7)
k4, m4 = MD.split(k3, NOW, 7)
check("0769. повторный перенос ничего не находит (идемпотентно)", m4 == {} and k4 == k3)
kb, mb = MD.split("## Сейчас\n\n- 27.10 ровно на границе\n- 26.10 на день старше\n", NOW, 7)
check("0769. граница: блок ровно days дней назад (27.10 при 03.11, 7 дней) остаётся, днём старше — переносится (argus #291)",
      "- 27.10 ровно на границе" in kb and mb == {"2026-10": ["- 26.10 на день старше"]}, (kb, mb))

# --- CLI: check, archive, board-auto -------------------------------------------------------------------------------
tmp = os.path.join(ROOT, "e2e")
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
for sub in ("directions/metis-pantheon/tasks", "inbox/tasks"):
    os.makedirs(os.path.join(home, sub))
os.makedirs(view)
write(os.path.join(home, "schedule.toml"), 'primary_host = "mac-a"\n\n[[job]]\nname = "board"\ncommand = "pantheon board"\nevery = "tick"\n')
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
       "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "PANTHEON_FAKE_IDLE": "0",
       "PANTHEON_METRICS": "0", "TMPDIR": tmp}


def cli(args, t=NOW):
    return subprocess.run([PY311, "-I", RUN_PY] + args, env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=300)


bm = os.path.join(home, "board.md")
write(bm, board("Обновлено 30.10 03:55.", extra=big * 90, dates="| 27.10 | e-visa | a | b |\n"))
r = cli(["check"])
check("check: board.md с тремя проблемами → три предупреждения, код не меняется",
      "«Сейчас»" in r.stdout and "старше 24 ч" in r.stdout and "«По датам»: срок прошёл" in r.stdout, r.stdout + r.stderr)
r = cli(["check", "--quiet"])
check("check --quiet: три тревоги", all(x in r.stdout for x in ("pantheon board archive", "старше 24 ч", "срок прошёл")),
      r.stdout + r.stderr)
r = cli(["check", "--quiet"])
check("check --quiet: повтор с теми же проблемами → тревоги не множатся",
      not any(x in r.stdout for x in ("pantheon board archive", "старше 24 ч", "срок прошёл")), r.stdout)
write(bm, board())
cli(["check", "--quiet"])
write(bm, board("Обновлено 30.10 03:55."))
r = cli(["check", "--quiet"])
check("check --quiet: после исправления и новой поломки тревога приходит заново (отметка снята)",
      "старше 24 ч" in r.stdout, r.stdout)
write(bm, board())
r = cli(["check", "--quiet"])
check("check --quiet: чистый board.md → тихо", "board.md" not in r.stdout, r.stdout)

# archive
src = SRC
write(bm, src)
r = cli(["board", "archive"])
kept_cli = read(bm)
a10 = os.path.join(home, "archive", "2026-10.md")
a09 = os.path.join(home, "archive", "2026-09.md")
check("board archive: старые блоки ушли в archive/ГГГГ-ММ.md, board.md без них",
      r.returncode == 0 and "- 20.10 старое A" not in kept_cli and "  хвост A" in read(a10) and "- 25.10 старое C" in read(a10)
      and "- 2026-09-30 старое B" in read(a09) and "перенесено строк 4" in r.stdout, r.stdout + r.stderr)
arch_lines = [ln for p in (a10, a09) for ln in read(p).split("\n") if ln and not ln.startswith("<!--")]
check("board archive: без потерь на диске (board.md + архив = исходные непустые строки)",
      sorted(ln for ln in kept_cli.split("\n") + arch_lines if ln) == sorted(ln for ln in SRC.split("\n") if ln))
before = read(bm)
a_before = read(a10)
r = cli(["board", "archive"])
check("board archive: повтор — нечего переносить, файлы не тронуты",
      r.returncode == 0 and "нет" in r.stdout and read(bm) == before and read(a10) == a_before, r.stdout + r.stderr)
r = cli(["board", "archive", "--days", "400"])
check("board archive --days 400 → всё остаётся", r.returncode == 0 and read(bm) == before, r.stdout)
for bad in (["--days"], ["--days", "x"], ["--days", "-3"], ["--wat"], ["--days", "3", "x"]):
    r = cli(["board", "archive"] + bad)
    check(f"board archive {' '.join(bad)} → код 2, строка использования", r.returncode == 2 and "[--days N]" in r.stderr
          and read(bm) == before, r.stdout + r.stderr)
write(bm, SRC)
r = cli(["board", "archive", "--days", "30"])
check("board archive --days 30 → в архив только 2026-09", r.returncode == 0 and not os.path.exists(os.path.join(home, "archive", "2026-11.md"))
      and "- 20.10 старое A" in read(bm) and "- 2026-09-30 старое B" not in read(bm), r.stdout + r.stderr)
os.remove(bm)
r = cli(["board", "archive"])
check("board archive без board.md → код 0, сообщение", r.returncode == 0 and "board.md нет" in r.stdout, r.stdout + r.stderr)

# 0780: board.md правят руками без замка — правка между чтением и записью не теряется. Обвязка в процессе pantheon:
# when=split — правка во время разбора (до записи архива), when=archive — сразу после открытия архива на дописывание
# (до замены board.md). Каждый how меняет только одну часть отметки: grow — размер (время возвращено), touch — время,
# swap — inode (замена через rename, тот же размер и время), delete — файл удалён (archive не создаёт его заново)
SWAP = ("- 03.11 свежее", "- 03.11 свежак")   # тот же размер в байтах
assert len(SWAP[0].encode()) == len(SWAP[1].encode())
RACE = ("import os, sys; sys.path.insert(0, %r); import pantheon as p\n"
        "when, how = sys.argv[1], sys.argv[2]\n"
        "bm = os.path.join(p.PANTHEON, 'board.md')\n"
        "done = []\n"
        "def edit():\n"
        "    if done:\n"
        "        return\n"
        "    done.append(1)\n"
        "    st = os.stat(bm)\n"
        "    if how == 'grow':\n"
        "        with open(bm, 'a', encoding='utf-8') as fh:\n"
        "            fh.write('- 04.11 правка Зевса\\n')\n"
        "        os.utime(bm, ns=(st.st_atime_ns, st.st_mtime_ns))\n"
        "    elif how == 'delete':\n"
        "        os.remove(bm)\n"
        "    elif how == 'touch':\n"
        "        os.utime(bm, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))\n"
        "    else:\n"
        "        tmp = bm + '.new'\n"
        "        with open(bm, encoding='utf-8') as fh:\n"
        "            text = fh.read()\n"
        "        with open(tmp, 'w', encoding='utf-8') as fh:\n"
        "            fh.write(text.replace(SWAP[0], SWAP[1]))\n"
        "        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))\n"
        "        os.replace(tmp, bm)\n"
        "SWAP = %r\n"
        "M = p.boardmd_mod()\n"
        "if when == 'split':\n"
        "    real = M.split\n"
        "    def split(*a):\n"
        "        edit(); return real(*a)\n"
        "    M.split = split\n"
        "else:\n"
        "    import builtins\n"
        "    def opener(f, mode='r', *a, **k):\n"
        "        fh = builtins.open(f, mode, *a, **k)\n"
        "        if mode == 'a' and os.sep + 'archive' + os.sep in str(f):\n"
        "            edit()\n"
        "        return fh\n"
        "    p.open = opener\n"
        "p.boardmd_mod = lambda: M\n"
        "sys.exit(p.board_archive([]))\n" % (LIB, SWAP))


def race(when, how):
    return subprocess.run([PY311, "-I", "-c", RACE, when, how], env=dict(env, PANTHEON_NOW=str(NOW)), capture_output=True,
                          text=True, timeout=300)


arch = os.path.join(home, "archive")
EDITED = {"grow": SRC + "- 04.11 правка Зевса\n", "touch": SRC, "swap": SRC.replace(*SWAP), "delete": None}


def text_of(p):
    return read(p) if os.path.exists(p) else None


for when in ("split", "archive"):
    for how in ("grow", "touch", "swap", "delete"):
        shutil.rmtree(arch, ignore_errors=True)
        write(bm, SRC)
        r = race(when, how)
        got = text_of(bm)
        check(f"0780. board archive: board.md изменён ({when}, {how}) → код 1, «board.md изменился, повтори», "
              "board.md с правкой цел, " + ("архив не создан" if when == "split" else "дописанное в архив удалено"),
              r.returncode == 1 and "board.md изменился, повтори" in r.stderr and got == EDITED[how]
              and (not os.path.exists(arch) if when == "split" else os.listdir(arch) == []),
              (r.returncode, r.stdout, r.stderr, (got or "")[-60:], os.listdir(arch) if os.path.isdir(arch) else None))
# архив уже был: дописанное откатывается до прежнего размера
write(a10, "старый архив 10\n")
write(a09, "старый архив 09\n")
write(bm, SRC)
r = race("archive", "grow")
check("0780. board archive: правка после дописывания в существующий архив → архив откатан до прежнего текста",
      r.returncode == 1 and text_of(a10) == "старый архив 10\n" and text_of(a09) == "старый архив 09\n"
      and read(bm) == EDITED["grow"], (r.returncode, r.stderr, text_of(a10), text_of(a09)))
write(bm, SRC)
r = cli(["board", "archive"])
check("0780. board archive: без правки — переносит как раньше (сверка не мешает)",
      r.returncode == 0 and "- 20.10 старое A" not in read(bm) and "- 20.10 старое A" in (text_of(a10) or ""),
      r.stdout + r.stderr)

# board-auto из кэша и карточек
write(bm, board())
new = cli(["task", "new", "--direction", "metis-pantheon", "--title", "Висит", "--text", "тело", "--mode", "single",
           "--done-when", "первое", "--done-when", "второе"], ts("2026-10-30 10:00"))
tid = new.stdout.split()[0]
cli(["task", "set", tid, "status=doing", "--note", "PR #123 подан"], ts("2026-10-30 11:00"))
cch = os.path.join(state, "autoclose-prs.json")
write(cch, json.dumps({"fetched": NOW, "open_prs": {}, "merged": {"latark/agent-kit": [pr(123, two_days)]}}))
r = cli(["board"])
got = read(os.path.join(home, "board-auto.md"))
check("0768. e2e pantheon board: в board-auto.md строка «ID: PR #123 слит 2 дн. назад, задача doing, неотмечено 2»",
      f"- {tid}: PR #123 слит 2 дн. назад, задача doing, неотмечено 2" in got, r.stdout + r.stderr + got)
cli(["task", "set", tid, "status=done", "--force", "тест"], ts("2026-11-03 11:00"))
r = cli(["board"], NOW + 60)
got = read(os.path.join(home, "board-auto.md"))
check("0768. e2e: задача done → строки на доске нет", tid not in got, r.stdout + r.stderr + got)

# metis-0792: OSError при дописывании архива или замене board.md откатывает дописанное. append2 — второй архив не открылся
# на дописывание (первый уже дописан), write — замена board.md упала
FAIL = ("import os, sys; sys.path.insert(0, %r); import pantheon as p, builtins\n"
        "what = sys.argv[1]\n"
        "if what == 'write':\n"
        "    def boom(*a): raise OSError(28, 'нет места')\n"
        "    p.write_atomic = boom\n"
        "else:\n"
        "    n = []\n"
        "    def opener(f, mode='r', *a, **k):\n"
        "        if mode == 'a' and os.sep + 'archive' + os.sep in str(f):\n"
        "            n.append(1)\n"
        "            if len(n) == 2: raise OSError(28, 'нет места')\n"
        "        return builtins.open(f, mode, *a, **k)\n"
        "    p.open = opener\n"
        "if len(sys.argv) > 2:  # откат сам падает (metis-0810): truncate и remove архива — OSError\n"
        "    def nope(*a): raise OSError(13, 'нет доступа')\n"
        "    p.os.truncate = nope\n"
        "    p.os.remove = nope\n"
        "sys.exit(p.board_archive([]))\n" % LIB)
for what in ("write", "append2"):
    for existed in (True, False):
        shutil.rmtree(arch, ignore_errors=True)
        if existed:
            write(a10, "старый архив 10\n")
            write(a09, "старый архив 09\n")
        write(bm, SRC)
        r = subprocess.run([PY311, "-I", "-c", FAIL, what], env=dict(env, PANTHEON_NOW=str(NOW)), capture_output=True,
                           text=True, timeout=300)
        left = sorted(os.listdir(arch)) if os.path.isdir(arch) else []
        check(f"0792. board archive: OSError ({what}), архивы {'были' if existed else 'не было'} → код 1, причина в stderr, "
              "board.md цел, архивы как были",
              r.returncode == 1 and "OSError" in r.stderr and read(bm) == SRC
              and (text_of(a10) == "старый архив 10\n" and text_of(a09) == "старый архив 09\n" if existed else left == []),
              (r.returncode, r.stderr[-300:], left))
        last = (r.stderr.strip().splitlines() or [""])[-1]
        check(f"0810. board archive: OSError ({what}, {'были' if existed else 'не было'}) — последняя строка «архив откатан, "
              "board.md не тронут», трассировки нет (мутант: снять except OSError)",
              "архив откатан, board.md не тронут" in last and "Traceback" not in r.stderr, r.stderr[-400:])
# откат сам не удался — сообщение не врёт «архив откатан», а называет архив и причину; код 1, трассировки нет
shutil.rmtree(arch, ignore_errors=True)
write(a10, "старый архив 10\n")
write(a09, "старый архив 09\n")
write(bm, SRC)
r = subprocess.run([PY311, "-I", "-c", FAIL, "write", "rollback"], env=dict(env, PANTHEON_NOW=str(NOW)), capture_output=True,
                   text=True, timeout=300)
last = (r.stderr.strip().splitlines() or [""])[-1]
check("0810. board archive: откат архива упал — код 1, «архив НЕ откатан (archive/…: PermissionError …)», не «архив откатан», "
      "board.md цел, трассировки нет",
      r.returncode == 1 and "архив НЕ откатан (archive/" in last and "PermissionError" in last and "архив откатан," not in last
      and read(bm) == SRC and "Traceback" not in r.stderr and text_of(a10) != "старый архив 10\n", (r.returncode, r.stderr[-500:]))

# --- 1005: «Сейчас» из факта ----------------------------------------------------------------------------------------
def fts(s):
    return ts("2026-11-" + s)


def jk(text, journal, t=NOW):
    return {k for k, _, _ in MD.problems(text, t, journal)}


# п. 3 для board.md: ручное «Обновлено» сверяется со свежим журналом, а не с часами
check("1005. board.md: «Обновлено» отстаёт от журнала на 7 ч → updated (тревога владельцу файла — Зевсу)",
      "updated" in jk(board("Обновлено 03.11 10:00."), fts("03 17:00")))
check("1005. board.md: отставание 5 ч 59 мин — тревоги нет; ровно 6 ч — нет; 6 ч 1 мин — есть",
      "updated" not in jk(board("Обновлено 03.11 10:00."), fts("03 15:59"))
      and "updated" not in jk(board("Обновлено 03.11 10:00."), fts("03 16:00"))
      and "updated" in jk(board("Обновлено 03.11 10:00."), fts("03 16:01")))
check("1005. board.md: журнал ПОЗЖЕ часов не ломает: «Обновлено» 30.10 при журнале 03.11 — updated, а свежее — нет",
      "updated" in jk(board("Обновлено 30.10 10:00."), fts("03 11:00")) and "updated" not in jk(board("Обновлено 03.11 11:00."), fts("03 11:30")))
msg = [m for k, _, m in MD.problems(board("Обновлено 03.11 10:00."), NOW, fts("03 17:00")) if k == "updated"][0]
check("1005. сообщение называет журнал и владельца файла", "журнала STATUS (03.11 17:00)" in msg and "Зевс" in msg, msg)
check("1005. журнала нет: прежнее правило «старше суток» осталось",
      "updated" in jk(board("Обновлено 02.11 11:00."), None) and "updated" not in jk(board("Обновлено 02.11 13:00."), None))

# nowfact: время журнала
T1 = fts("08 14:30")
J = "# S\n\n## Сейчас (06.11 10:0x)\n- шаг\n\n## Ход\nДо 08.11 12:56 — archive/x.md\n12:57 запись\n13:5x запись\n- 08.11 14:02 с датой\n"
check("1005. journal_time: последняя строка с датой 08.11 14:02", NF.journal_time(J, T1, T1) == fts("08 14:02"), NF.journal_time(J, T1, T1))
check("1005. journal_time: время без даты берёт дату выше («13:5x» → 13:59 08.11)",
      NF.journal_time("## Ход\n08.11 10:00 а\n13:5x б\n", T1, T1) == fts("08 13:59"))
check("1005. journal_time: время без даты и без дат выше — дата правки файла",
      NF.journal_time("## Ход\n09:15 а\n", fts("07 20:00"), T1) == fts("07 09:15"))
check("1005. journal_time: раздела-журнала нет → None; ‘Начато / сделано’ и ‘Журнал’ — тоже журнал",
      NF.journal_time("## Сейчас\n12:00 текст\n", T1, T1) is None
      and NF.journal_time("## Начато / сделано\n- 06.11 06:23 начато: x\n", T1, T1) == fts("06 06:23")
      and NF.journal_time("## Журнал\n- 2026-11-08 13:26 — агент\n12:00 y\n", T1, T1) == fts("08 12:00") - 0 * 1)
check("1005. journal_time: строки вне журнала (после следующего ##) не считаются",
      NF.journal_time("## Ход\n08.11 10:00 а\n\n## Другое\n08.11 23:00 б\n", T1, T1) == fts("08 10:00"))
check("1005. journal_time: дата из будущего больше чем на сутки — прошлого года; 25:99 не время",
      NF.journal_time("## Ход\n15.12 10:00 а\n", T1, T1) == datetime(2025, 12, 15, 10, 0).timestamp()
      and NF.journal_time("## Ход\n25:99 а\n", T1, T1) is None)
check("1005. display: десятки минут «ДД.ММ ЧЧ:Мx»", NF.display(fts("08 14:02")) == "08.11 14:0x")
new_t, ch = NF.retime_head(J, fts("08 14:02"))
check("1005. retime_head: шапка по журналу, остальной текст цел",
      ch and "## Сейчас (08.11 14:0x)" in new_t and new_t.replace("(08.11 14:0x)", "(06.11 10:0x)") == J, new_t)
check("1005. retime_head: уже верна / нет времени / заголовок с чужим суффиксом — не меняет",
      NF.retime_head(new_t, fts("08 14:02")) == (new_t, False) and NF.retime_head(J, None) == (J, False)
      and NF.retime_head("## Сейчас — итог\nх\n", fts("08 14:02")) == ("## Сейчас — итог\nх\n", False))
check("1005. retime_head: пометка после даты в скобках остаётся (Д3 argus #399)",
      NF.retime_head("## Сейчас (08.11 16:3x, точка сохранения ~17:30)\nх\n", fts("08 14:02"))[0]
      == "## Сейчас (08.11 14:0x, точка сохранения ~17:30)\nх\n")
check("1005. retime_head: скобки без даты — дата впереди, текст скобок цел; повтор не меняет",
      NF.retime_head("## Сейчас (черновик)\nх\n", fts("08 14:02"))[0] == "## Сейчас (08.11 14:0x, черновик)\nх\n"
      and not NF.retime_head("## Сейчас (08.11 14:0x, черновик)\nх\n", fts("08 14:02"))[1])
check("1005. retime_head: «## Сейчас» без даты получает дату", NF.retime_head("## Сейчас\nх\n", fts("08 14:02"))[0].startswith("## Сейчас (08.11 14:0x)"))
sm = "## Ждёт владельца (08.11 01:00)\n- х\n\n## Ранее (01.11 10:00) — в archive/x\n\n## Сейчас (01.11 10:00)\n\n## Ход\n08.11 14:00 а\n"
check("1005. stale_manual: раздел 13 ч позади журнала — да; «Ранее … archive», «Сейчас», «Ход» — нет",
      [n for n, _ in NF.stale_manual(sm, T1, T1)] == ["Ждёт владельца"], NF.stale_manual(sm, T1, T1))
check("1005. stale_manual: 6 ч ровно — нет, 6 ч 1 мин — да; без времени (только дата) — конец дня",
      not NF.stale_manual("## Х (08.11 08:00)\n## Ход\n08.11 14:00 а\n", T1, T1, 6)
      and NF.stale_manual("## Х (08.11 07:50)\n## Ход\n08.11 14:00 а\n", T1, T1, 6)
      and not NF.stale_manual("## Х (08.11)\n## Ход\n08.11 14:00 а\n", T1, T1, 6)
      and NF.stale_manual("## Х (07.11)\n## Ход\n08.11 14:00 а\n", T1, T1, 6))
check("1005. stale_manual: «Обновлено …» в разделе — считается; в «Сейчас» — нет",
      NF.stale_manual("## Х\nОбновлено 08.11 01:00\n## Ход\n08.11 14:00 а\n", T1, T1)
      and not NF.stale_manual("## Сейчас\nОбновлено 08.11 01:00\n## Ход\n08.11 14:00 а\n", T1, T1))

# board-auto.md: «Сейчас» из факта, board.md не тронут
pan = os.path.join(ROOT, "pan1005")
state = os.path.join(ROOT, "state1005")
os.makedirs(state, exist_ok=True)
OLD_BOARD = "# Доска\n\n![[board-auto]]\n\n## Сейчас\n\n- **06.11 14:1x.** старая ручная запись\n- вторая ручная строка\n"
write(os.path.join(pan, "board.md"), OLD_BOARD)
write(os.path.join(pan, "directions", "alpha", "STATUS.md"), "# S\n\n## Сейчас (06.11 10:0x)\n- шаг\n\n## Ход\n08.11 14:02 свежая запись\n")
write(os.path.join(pan, "directions", "beta", "STATUS.md"), "# S\n\n## Ход\n07.11 09:00 запись\n")
write(os.path.join(pan, "directions", "gamma", "STATUS.md"), "# S\n\n## Сейчас\n- нет журнала\n")
write(os.path.join(state, "merge-queue", "latark__agent-kit__394.json"), json.dumps({"repo": "latark/agent-kit", "pr": 394}))
auto = os.path.join(pan, B.AUTO_NAME)
data = B.collect(pan, state, {}, T1, windows=["sb-gates-2", "dev-opus"])
res = B.sync(auto, B.render(data, T1))
txt = read(auto)
first = txt.splitlines()[3]
check("1005. board-auto.md: старый ручной блок + свежий журнал → «Сейчас» из факта (журнал, окна, заявки), время сборки",
      res == "written" and first.startswith("- **Сейчас 08.11 14:30**") and "alpha 08.11 14:0x" in first and "beta 07.11 09:0x" in first
      and "gamma" not in first and "живых окон 2: sb-gates-2, dev-opus" in first and "заявки merge: #394" in first, first)
check("1005. board.md (ручные строки) цел: код его не пишет", read(os.path.join(pan, "board.md")) == OLD_BOARD)
check("1005. «Сейчас» — первая строка блока, до «Неделя»", txt.index("**Сейчас ") < txt.index("Неделя"))
res2 = B.sync(auto, B.render(data, T1 + 600))
check("1005. другая минута сборки — файл не переписывается (штамп «Сейчас» не в сравнении)", res2 == "same", res2)
write(os.path.join(pan, "directions", "alpha", "STATUS.md"), "# S\n\n## Ход\n08.11 14:20 ещё запись\n")
data3 = B.collect(pan, state, {}, T1 + 700, windows=["sb-gates-2"])
res3 = B.sync(auto, B.render(data3, T1 + 700))
check("1005. новая запись журнала / ушло окно — блок обновлён", res3 == "written" and "alpha 08.11 14:2x" in read(auto)
      and "живых окон 1:" in read(auto), read(auto))
bad = B.render(dict(data, windows=["ИГНОР\u202e", "ok-win", "x; rm -rf"], journal=[("плохое имя!", T1), ("alpha", T1)], queue=[("a/b", True)]), T1)
check("1005. чужие имена (окна, направления) и bool в «Сейчас» не идут; снимка сессий нет → «окна неизвестны»",
      "ИГНОР" not in bad and "rm -rf" not in bad and "плохое" not in bad and "живых окон 1: ok-win" in bad and "заявки merge: нет" in bad
      and "окна неизвестны" in B.render(dict(data, windows=None), T1), bad)
check("1005. журналов со временем нет → строка говорит об этом", "журнала STATUS со временем нет" in B.render({"journal": []}, T1))
_bm, B.BLOCK_MAX = B.BLOCK_MAX, 500
big2 = B.render(dict(data, prs=[{"number": i, "repo": "o/r", "head": "abc1234", "ids": [], "core": False} for i in range(1, 30)]), T1)
B.BLOCK_MAX = _bm
check("1005. при переполнении «Сейчас» остаётся (режется хвост)", len(big2) <= B.BLOCK_MAX and "**Сейчас " in big2 and "не вошло строк" in big2)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
