#!/usr/bin/env python3
"""Скорость сборки карточек (metis-0926): проход доски на тысячах карточек читает каждый файл один раз (кэш текста по
(путь, dev, ino, mtime_ns, ctime_ns, size)), вывод тот же, что без кэша; изменённая карточка читается заново; порядок
пачки считается один раз на пачку; имена карточек, различающиеся регистром, получают суффикс «(id)».

Запуск: python3 -I plugins/pantheon/tests/test_board_speed.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-speed-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_794_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


DIRS = ["metis-pantheon", "zeus", "athena-brokerassistant", "mnemo-brain", "calliope-content"]
N, STORIES = 500, 20


def build(pan):
    """N задач в 5 направлениях и STORIES пачек; у каждой пачки дети, часть с depends_on и touches."""
    for d in DIRS:
        os.makedirs(os.path.join(pan, "directions", d, "tasks"))
    os.makedirs(os.path.join(pan, "inbox", "tasks"))
    for s in range(STORIES):
        h = {"type": "story", "id": f"metis-{s:04d}", "title": f"Пачка {s}", "status": "doing", "priority": 2,
             "direction": DIRS[s % 5], "owner": "zeus", "project": "Пантеон", "schema_version": 1, "created": "2026-11-01", "updated": "2026-11-02T10:00:00"}
        T.write_text(os.path.join(pan, "directions", DIRS[s % 5], "tasks", f"{h['id']}.md"), T.join(h, "# Пачка\n"))
    for i in range(STORIES, N):
        d = DIRS[i % 5]
        h = {"type": "task", "id": f"metis-{i:04d}", "title": f"Задача {i}" if i % 50 else "Одинаковое имя",
             "status": ("todo", "doing", "done", "waiting")[i % 4], "priority": i % 4, "direction": d, "owner": "zeus", "project": "Пантеон", "schema_version": 1,
             "created": "2026-11-01", "updated": "2026-11-02T10:00:00", "parent": f"metis-{i % STORIES:04d}",
             "touches": [f"plugins/p{i % 30}/lib/", f"docs/x{i % 7}.md"], "next": "шаг", "waiting_on": "human"}
        if i > STORIES + 5 and i % 3 == 0:
            h["depends_on"] = [f"metis-{i - 3:04d}"]
        if h["status"] == "done":
            h["closed"] = "2026-11-02"
        T.write_text(os.path.join(pan, "directions", d, "tasks", f"{h['id']}.md"), T.join(h, f"# {i}\n\nТекст {i}\n"))
    # имена, различающиеся только регистром: файл Mac один, второму нужен суффикс
    for k, title in enumerate(("Дубль имени", "ДУБЛЬ ИМЕНИ")):
        h = {"type": "task", "id": f"metis-{N + k:04d}", "title": title, "status": "todo", "priority": 2,
             "direction": "zeus", "owner": "zeus", "project": "Пантеон", "schema_version": 1, "created": "2026-11-01", "updated": "2026-11-02T10:00:00"}
        T.write_text(os.path.join(pan, "directions", "zeus", "tasks", f"{h['id']}.md"), T.join(h, "# Д\n"))


def run_sync(pan, view, label):
    return T.board_sync(pan, os.path.join(view, "Доска"), os.path.join(view, "st.json"), os.path.join(ROOT, "log-" + label),
                        T0, primary=False, projects={}, registry={})


def tree(d):
    out = {}
    for base, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(base, f)
            out[os.path.relpath(p, d)] = open(p, encoding="utf-8").read()
    return out


PAN = os.path.join(ROOT, "pan")
build(PAN)

# 1. с кэшем и без него — одни и те же карточки, состояние и строки
raw_calls = [0]
orig_raw = T._read_text_raw


def counting_raw(path):
    raw_calls[0] += 1
    return orig_raw(path)


T._read_text_raw = counting_raw
T._TEXT_CACHE.clear()
v1 = os.path.join(ROOT, "v1")
lines1 = run_sync(PAN, v1, "a")
reads_cached = raw_calls[0]

T._read_text_raw = counting_raw
orig_read_text = T.read_text
T.read_text = lambda p: counting_raw(p)  # путь «как раньше»: каждое чтение с диска
raw_calls[0] = 0
v2 = os.path.join(ROOT, "v2")
lines2 = run_sync(PAN, v2, "a")
reads_plain = raw_calls[0]
T.read_text = orig_read_text
T._read_text_raw = orig_raw

t1, t2 = tree(v1), tree(v2)
n_cards = sum(1 for k in t1 if k.startswith("Доска") and k.endswith(".md"))
check("вывод: те же карточки, Сводка и состояние с кэшем и без него", t1 == t2 and lines1 == lines2 and n_cards > N,
      (len(t1), len(t2), n_cards, set(t1) ^ set(t2)))
check("чтений с диска за проход с кэшем вдвое меньше, чем без него", reads_cached * 2 <= reads_plain,
      (reads_cached, reads_plain))
check("каждый файл задачи читается с диска не больше раза за проход (+ доска)", reads_cached <= 2 * n_cards + 50,
      (reads_cached, n_cards))
dubl = sorted(k for k in t1 if "ублирование" in k or "Дубль имени" in k or "ДУБЛЬ ИМЕНИ" in k)
check("имена, различающиеся регистром, — два разных файла доски",
      len(dubl) == 2 and dubl[0].casefold() != dubl[1].casefold(), dubl)

# 2. кэш сбрасывается при изменении файла
f = os.path.join(PAN, "directions", "zeus", "tasks", "metis-0003.md")
if not os.path.exists(f):
    f = next(os.path.join(PAN, "directions", d, "tasks", "metis-0003.md") for d in DIRS
             if os.path.exists(os.path.join(PAN, "directions", d, "tasks", "metis-0003.md")))
a = T.read_text(f)
check("чтение: второй раз из кэша — тот же текст", T.read_text(f) == a)
st = os.stat(f)
b = a.replace("Пачка 3", "Пачка 9", 1) if "Пачка 3" in a else None
check("тест подготовлен: замена той же длины найдена", b is not None and len(b) == len(a), a[:120])
# 2а. правка на месте (тот же inode, тот же размер), mtime возвращён — отличается только ctime
with open(f, "w", encoding="utf-8") as fh:
    fh.write(b)
os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
check("кэш сброшен: правка на месте, тот же размер и mtime (ловит ctime)", T.read_text(f) == b, T.read_text(f)[:100])
# 2б. замена через rename — другой inode, тот же размер и тот же mtime
tmpf = f + ".new"
with open(tmpf, "w", encoding="utf-8") as fh:
    fh.write(a)
os.utime(tmpf, ns=(st.st_atime_ns, os.stat(f).st_mtime_ns))
os.replace(tmpf, f)
check("кэш сброшен: замена файла через rename (другой inode)", T.read_text(f) == a, T.read_text(f)[:100])
# 2в. другой размер
c = a + "\nдобавка\n"
with open(f, "w", encoding="utf-8") as fh:
    fh.write(c)
check("кэш сброшен: другой размер", T.read_text(f) == c)
# 2г. запись через write_text сразу видна
T.write_text(f, a)
check("write_text: следующее чтение видит новый текст", T.read_text(f) == a)
# 2д. файл удалён / стал ссылкой — не из кэша
os.remove(f)
try:
    T.read_text(f)
    gone = False
except OSError:
    gone = True
check("удалённый файл не читается из кэша", gone)
other = os.path.join(PAN, "directions", "zeus", "tasks", "metis-0004.md")
if os.path.exists(other):
    T.read_text(other)
    os.remove(other)
    os.symlink(os.path.join(ROOT, "pan", "inbox"), other)
    try:
        T.read_text(other)
        sym = False
    except OSError:
        sym = True
    check("файл заменён ссылкой — из кэша не отдаётся", sym)
    check("ссылка не попадает в список задач", other not in set(T.task_files(PAN)))
    os.remove(other)

# 3. board_sync после правки карточки видит правку
build_dir = os.path.join(ROOT, "pan2")
build(build_dir)
v3 = os.path.join(ROOT, "v3")
run_sync(build_dir, v3, "b")
target = next(os.path.join(build_dir, "directions", d, "tasks", "metis-0100.md") for d in DIRS
              if os.path.exists(os.path.join(build_dir, "directions", d, "tasks", "metis-0100.md")))
h, body = T.read(target)
h["title"] = "Новое название сотой"
T.write(target, h, body)
run_sync(build_dir, v3, "b")
check("после правки задачи карточка доски с новым названием (кэш не держит старое)",
      any("Новое название сотой" in n for n in os.listdir(os.path.join(v3, "Доска"))))

# 4. порядок пачки: с общим словарём тот же, что без него
tasks = T.load_tasks(PAN, T.WORK_TYPES)
orders = {}
same = True
for tid, (_, hh, _) in tasks.items():
    c1 = T.card_ctx(tid, hh, tasks, {i: i for i in tasks}, {}, T0)
    c2 = T.card_ctx(tid, hh, tasks, {i: i for i in tasks}, {}, T0, orders=orders)
    same = same and c1 == c2
check("card_ctx: с общим словарём порядков результат тот же", same and len(orders) > 0, len(orders))
calls = [0]
orig_so = T.story_order
T.story_order = lambda sid, ts: (calls.__setitem__(0, calls[0] + 1), orig_so(sid, ts))[1]
orders = {}
for tid, (_, hh, _) in tasks.items():
    T.card_ctx(tid, hh, tasks, {i: i for i in tasks}, {}, T0, orders=orders)
T.story_order = orig_so
check("story_order считается один раз на пачку", 0 < calls[0] <= STORIES, calls[0])

# 5. области: кэш _area не меняет результат
check("_area: одинаково для разных видов записи",
      T._area("./plugins//x/") == "plugins//x" and T._area("a\\b/") == "a/b" and T._area(5) == "5"
      and T.paths_cross("plugins/pantheon/", "./plugins/pantheon/lib/x.py") and not T.paths_cross("plugins/pan", "plugins/pantheon"))

bad = len(results) - sum(results)
print(f"\n{len(results) - bad} из {len(results)}")
sys.exit(1 if bad else 0)
