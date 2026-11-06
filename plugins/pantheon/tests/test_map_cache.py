#!/usr/bin/env python3
"""Карта тестов частями и кэш результата по хешу входов (metis-0692, metis-0698).

Запуск: python3 -I plugins/pantheon/tests/test_map_cache.py  (код выхода 0 — все прошли). Временный репозиторий с
плагинами alpha и pantheon: affected-map.py строит карту с sums, --check сверяет её с деревом, --update пересобирает
только файлы тестов, чьи связи могли устареть; run-tests.py --cache не гоняет файл, чей ключ входов совпал с зелёным
прогоном; --affected, которому нечего гонять, гонит дымовой файл вместо кода 3."""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = tempfile.mkdtemp(prefix="test_map_cache-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
RUNNER = os.path.join(PLUGIN, "scripts", "run-tests.py")
MAPPER = os.path.join(PLUGIN, "scripts", "affected-map.py")
fails = []
total = 0


def check(name, cond, extra=""):
    global total
    total += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {str(extra)[-900:]}"))
    if not cond:
        fails.append(name)


spec = importlib.util.spec_from_file_location("run_tests_mod", RUNNER)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

GENV = {k: v for k, v in os.environ.items() if not k.startswith("RUN_TESTS_")}
GENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
OK2 = "print('ok   один')\nprint('ok   два')\nprint('2 из 2 прошли')\n"
HDR = "import os, shutil, subprocess, sys, tempfile\nP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"


def put(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=GENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=True).stdout


# --- функции без процессов: расхождение карты с деревом, кого пересобрать, папка-копия ---
FILES = {"p/lib/x.py": {"a/test_x.py"}, "p/lib/y.py": {"a/test_y.py", "a/test_tree.py"},
         "p/lib/tree/t.txt": {"a/test_tree.py"}, "p/lib/tree/u.txt": {"a/test_tree.py"}, "README.md": set()}
check("folder_users: новый файл в папке, которую тест задел целиком, — этот тест",
      R.folder_users(FILES, "p/lib/tree/new.txt") == {"a/test_tree.py"}, R.folder_users(FILES, "p/lib/tree/new.txt"))
check("folder_users: папка, где файлы задеты разными тестами, — никто",
      R.folder_users(FILES, "p/lib/new.py") == set(), R.folder_users(FILES, "p/lib/new.py"))
check("folder_users: новая папка — ближайшая папка выше, где карта знает файлы",
      R.folder_users(FILES, "p/lib/tree/sub/n.txt") == {"a/test_tree.py"}, R.folder_users(FILES, "p/lib/tree/sub/n.txt"))
check("folder_users: файл в корне — никто", R.folder_users(FILES, "NEW.md") == set())
AMAP = {"tests": {"a/test_x.py", "a/test_y.py", "a/test_tree.py", "a/test_bad.py"}, "files": FILES,
        "broken": {"a/test_bad.py"}, "readers": set(), "always": {"a/test_bad.py"},
        "hashes": {}, "sums": {"p/lib/x.py": "1", "p/lib/y.py": "1", "p/lib/tree/t.txt": "1", "p/lib/tree/u.txt": "1",
                               "README.md": "1", "OLD.md": "1"}}
ITEMS = [("/нет", "a/test_x.py"), ("/нет", "a/test_y.py"), ("/нет", "a/test_tree.py"), ("/нет", "a/test_bad.py"),
         ("/нет", "a/test_new.py")]
NOW = ["p/lib/x.py", "p/lib/y.py", "p/lib/tree/t.txt", "p/lib/tree/u.txt", "README.md", "p/lib/tree/v.txt", "MAP.json"]
SUMS = {"p/lib/x.py": "1", "p/lib/y.py": "2", "p/lib/tree/t.txt": "1", "p/lib/tree/u.txt": "1", "README.md": "1",
        "p/lib/tree/v.txt": "1", "MAP.json": "9"}
D = R.map_drift(AMAP, ITEMS, "/нет", NOW, SUMS, ignore=("MAP.json",))
check("map_drift: новый тест, изменённый, добавленный и удалённый файлы; сама карта вне счёта",
      D == {"new_tests": ["a/test_new.py"], "stale": [], "changed": ["p/lib/y.py"], "added": ["p/lib/tree/v.txt"],
            "removed": ["OLD.md"]}, D)
check("map_drift: карта без sums — None (нечем сверить)", R.map_drift(dict(AMAP, sums=None), ITEMS, "/", NOW, SUMS) is None)
RR = R.drift_rerun(AMAP, ITEMS, D)
check("drift_rerun: новый, упавший при сборке, задевший изменённый y.py и копирующий папку нового v.txt — x не идёт",
      RR == ["a/test_bad.py", "a/test_new.py", "a/test_tree.py", "a/test_y.py"], RR)

# --- сквозная проба: репозиторий, карта, --check, --update ---
repo = tempfile.mkdtemp(prefix="repo-")
al = os.path.join(repo, "plugins", "alpha")
pa = os.path.join(repo, "plugins", "pantheon")
put(os.path.join(repo, "README.md"), "# r\n")
put(os.path.join(repo, ".gitignore"), "__pycache__/\n")
put(os.path.join(al, "lib", "x.py"), "X = 1\n")
put(os.path.join(al, "lib", "y.txt"), "y\n")
put(os.path.join(al, "lib", "tree", "a.txt"), "a\n")
put(os.path.join(al, "tests", "test_x.py"), HDR + "sys.path.insert(0, os.path.join(P, 'lib'))\nimport x\n"
    "assert not os.environ.get('FAILME'), 'FAILME'\n" + OK2)
put(os.path.join(al, "tests", "test_y.py"), HDR + "open(os.path.join(P, 'lib', 'y.txt')).read()\n" + OK2)
put(os.path.join(al, "tests", "test_tree.py"), HDR + "shutil.copytree(os.path.join(P, 'lib', 'tree'), "
    "os.path.join(tempfile.mkdtemp(), 't'))\n" + OK2)
put(os.path.join(al, "tests", "test_plain.py"), OK2)
put(os.path.join(pa, "tests", "test_glossary.py"), OK2)
git(repo, "init", "-q", "-b", "main")
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "база")
MAPF = os.path.join(tempfile.mkdtemp(prefix="map-"), "m.json")


def mapper(*args):
    return subprocess.run([sys.executable, "-I", MAPPER, "-j", "3", "--out", MAPF, *args, al, pa], env=GENV,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240)


def users(path):
    with open(MAPF, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {raw["tests"][i] for i in raw["files"].get(path, [])}


r = mapper()
check("affected-map: полная сборка — код 0", r.returncode == 0, r.stdout)
with open(MAPF, encoding="utf-8") as fh:
    RAW = json.load(fh)
check("affected-map: sums — sha256 каждого файла репозитория",
      set(RAW.get("sums") or ()) == set(RAW["files"]) and RAW["sums"].get("README.md") == R.file_sha(
          os.path.join(repo, "README.md")), sorted(RAW.get("sums") or ()))
check("affected-map: связи — x.py → test_x, tree/a.txt → test_tree", users("plugins/alpha/lib/x.py") == {
    "alpha/test_x.py"} and users("plugins/alpha/lib/tree/a.txt") == {"alpha/test_tree.py"}, RAW["files"])
r = mapper("--check")
check("--check: свежая карта — код 0, «расхождений нет»", r.returncode == 0 and "расхождений нет" in r.stdout, r.stdout)
put(os.path.join(al, "lib", "y.txt"), "y2\n")
r = mapper("--check")
check("--check: изменён y.txt — код 1, пересобрать test_y", r.returncode == 1 and "1 файлов изменено" in r.stdout
      and "alpha/test_y.py" in r.stdout and "--update" in r.stdout, r.stdout)
r = mapper("--update")
check("--update: прогнан только test_y — 1 из 5, остальные связи из прежней карты",
      r.returncode == 0 and "пересобрать 1 из 5" in r.stdout and "ok   alpha/test_y.py" in r.stdout
      and "alpha/test_x.py ·" not in r.stdout and "(прогнано 1)" in r.stdout, r.stdout)
check("--update: связи непрогнанных на месте", users("plugins/alpha/lib/x.py") == {"alpha/test_x.py"}
      and users("plugins/alpha/lib/y.txt") == {"alpha/test_y.py"}, users("plugins/alpha/lib/x.py"))
r = mapper("--check")
check("--check после --update — код 0", r.returncode == 0, r.stdout)
put(os.path.join(al, "tests", "test_new.py"), HDR + "open(os.path.join(P, 'lib', 'x.py')).read()\n" + OK2)
put(os.path.join(al, "lib", "tree", "b.txt"), "b\n")
r = mapper("--update")
check("--update: новый тест и новый файл в копируемой папке — прогнаны test_new и test_tree, не больше",
      r.returncode == 0 and "пересобрать 2 из 6" in r.stdout and "alpha/test_new.py" in r.stdout
      and "ok   alpha/test_tree.py" in r.stdout, r.stdout)
check("--update: новые связи — x.py → test_x и test_new, tree/b.txt → test_tree",
      users("plugins/alpha/lib/x.py") == {"alpha/test_x.py", "alpha/test_new.py"}
      and users("plugins/alpha/lib/tree/b.txt") == {"alpha/test_tree.py"}, RAW)
st = os.stat(MAPF).st_mtime_ns
r = mapper("--update")
check("--update: свежая карта не переписывается", r.returncode == 0 and "не переписана" in r.stdout
      and os.stat(MAPF).st_mtime_ns == st, r.stdout)
os.remove(os.path.join(al, "tests", "test_new.py"))
r = mapper("--update")
check("--update: удалённый тест — уходит из карты, прогнан задевший удалённое (никто)",
      r.returncode == 0 and "alpha/test_new.py" not in json.load(open(MAPF))["tests"], r.stdout)
with open(MAPF, encoding="utf-8") as fh:
    nosums = json.load(fh)
nosums.pop("sums")
NOSUMS = os.path.join(tempfile.mkdtemp(prefix="map-"), "old.json")
with open(NOSUMS, "w", encoding="utf-8") as fh:
    json.dump(nosums, fh)
r = subprocess.run([sys.executable, "-I", MAPPER, "--check", "--out", NOSUMS, al, pa], env=GENV,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
check("--check: карта без sums — код 1, нужна полная сборка", r.returncode == 1 and "без sums" in r.stdout, r.stdout)
r = subprocess.run([sys.executable, "-I", MAPPER, "--update", "--out", NOSUMS, al, pa], env=GENV,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240)
check("--update: карта без sums — полная сборка, sums записаны", r.returncode == 0 and "полная сборка" in r.stdout
      and "sums" in json.load(open(NOSUMS)), r.stdout)
r = subprocess.run([sys.executable, "-I", MAPPER, "--update", "--check", al], env=GENV,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
check("--update с --check — отказ", r.returncode != 0 and "что-то одно" in r.stdout, r.stdout)
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "после update")

# --- run-tests.py --cache: ключ по входам карты ---
DRV = ("import importlib.util, sys\nspec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
       "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
       "m.MAP = sys.argv[2]\nsys.exit(m.main(sys.argv[3:]))\n")
CACHE = os.path.join(tempfile.mkdtemp(prefix="cache-"), "c")


def rt(*args, env=None):
    e = {**GENV, "RUN_TESTS_CACHE": CACHE, **(env or {})}
    return subprocess.run([sys.executable, "-I", "-c", DRV, RUNNER, MAPF, *args], env=e, cwd=repo,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)


def from_cache(out):
    return sorted(ln.split()[1] for ln in out.splitlines() if ln.startswith("кэш  "))


r = rt("--cache", al, env={"FAILME": "1"})
check("--cache: первый прогон — из кэша 0, test_x упал (FAILME), код 1", r.returncode == 1
      and "из кэша 0" in r.stdout and "FAIL alpha/test_x.py" in r.stdout and not from_cache(r.stdout), r.stdout)
r = rt("--cache", al)
check("--cache: второй прогон — зелёные из кэша (test_plain, test_tree, test_y), упавший test_x идёт снова",
      r.returncode == 0 and from_cache(r.stdout) == ["alpha/test_plain.py", "alpha/test_tree.py", "alpha/test_y.py"]
      and "ok   alpha/test_x.py" in r.stdout, r.stdout)
check("--cache: итог — «из кэша 3», формат «итого: файлов N, ok A, FAIL B» тот же",
      "итого: файлов 1, ok 1, FAIL 0, из кэша 3;" in r.stdout, r.stdout.splitlines()[-1:])
r = rt("--cache", al)
check("--cache: все из кэша — код 0, файлов 0", r.returncode == 0 and len(from_cache(r.stdout)) == 4
      and "итого: файлов 0, ok 0, FAIL 0, из кэша 4" in r.stdout, r.stdout)
r = rt(al)
check("без --cache — кэш не читается, идут все", r.returncode == 0 and not from_cache(r.stdout)
      and "файлов 4, ok 4" in r.stdout, r.stdout)
# вход изменён, карта не обновлена: связи test_x могли устареть — кэшу не верим, хоть ключ и посчитан бы по старому
put(os.path.join(al, "lib", "x.py"), "X = 2\n")
r = rt("--cache", al)
check("--cache: вход x.py изменён после сборки карты — test_x идёт, остальные из кэша",
      r.returncode == 0 and "ok   alpha/test_x.py" in r.stdout
      and from_cache(r.stdout) == ["alpha/test_plain.py", "alpha/test_tree.py", "alpha/test_y.py"], r.stdout)
# связи устарели: x.py начал читать z.txt, карта об этом не знает; правка z.txt не меняет ключ по старым связям, и без
# сверки входов с sums test_x пришёл бы из кэша, хотя его настоящий вход изменился
put(os.path.join(al, "lib", "z.txt"), "z1\n")
r = mapper("--update")
check("--update: z.txt в карте, x.py — по новому тексту", r.returncode == 0, r.stdout)
rt("--cache", al)
put(os.path.join(al, "lib", "x.py"), "import os\nX = 5\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), "
    "'z.txt')).read()\n")
rt("--cache", al)
put(os.path.join(al, "lib", "z.txt"), "z2\n")
r = rt("--cache", al)
check("--cache: x.py изменён после сборки (новый вход z.txt), затем правка z.txt — test_x идёт, не из кэша",
      "ok   alpha/test_x.py" in r.stdout and "alpha/test_x.py" not in from_cache(r.stdout), r.stdout)
# мутант «не учитывать файл входа»: карта обновлена (sums совпали), ключ test_x обязан смениться вместе с x.py
r = mapper("--update")
check("--update после правки x.py — код 0", r.returncode == 0, r.stdout)
put(os.path.join(al, "lib", "x.py"), "X = 3\n")
mapper("--update")
rt("--cache", al)
put(os.path.join(al, "lib", "x.py"), "X = 4\n")
mapper("--update")
r = rt("--cache", al)
check("--cache: x.py изменён и карта обновлена — ключ test_x другой, он идёт; остальные из кэша",
      r.returncode == 0 and "ok   alpha/test_x.py" in r.stdout and "alpha/test_x.py" not in from_cache(r.stdout)
      and len(from_cache(r.stdout)) == 3, r.stdout)
put(os.path.join(repo, "README.md"), "# r\nправка\n")
mapper("--update")
r = rt("--cache", al)
check("--cache: правка файла вне входов (README) — все из кэша", from_cache(r.stdout) == [
    "alpha/test_plain.py", "alpha/test_tree.py", "alpha/test_x.py", "alpha/test_y.py"], r.stdout)
put(os.path.join(al, "lib", "tree", "c.txt"), "c\n")
r = rt("--cache", al)
check("--cache: новый файл в папке, которую test_tree копирует, — test_tree идёт", "ok   alpha/test_tree.py" in r.stdout
      and "alpha/test_tree.py" not in from_cache(r.stdout), r.stdout)
os.remove(os.path.join(al, "lib", "tree", "c.txt"))
# ключ: тот же вход — тот же ключ; правка входа — другой; правка не-входа — тот же
AM, _ = R.load_map(MAPF)
FN = R.repo_files(repo)
S0 = {p: R.file_sha(os.path.join(repo, p)) for p in FN}
K0, W0 = R.cache_keys([(al, "alpha/test_y.py")], AM, repo, FN, S0)
K1, _ = R.cache_keys([(al, "alpha/test_y.py")], AM, repo, FN, dict(S0, **{"README.md": "другой"}))
check("cache_keys: правка не-входа — ключ тот же", K0 and K0 == K1, (K0, K1, W0))
AM2 = dict(AM, sums=dict(AM["sums"], **{"plugins/alpha/lib/y.txt": "другой"}))
K2, _ = R.cache_keys([(al, "alpha/test_y.py")], AM2, repo, FN, dict(S0, **{"plugins/alpha/lib/y.txt": "другой"}))
check("cache_keys: правка входа (y.txt) при совпавших sums — ключ другой", K2 and K2 != K0, (K0, K2))
_, W3 = R.cache_keys([(al, "alpha/test_y.py")], dict(AM, always={"alpha/test_y.py"}), repo, FN, S0)
check("cache_keys: читающий дерево или упавший при сборке — без кэша", "дерево" in W3.get("alpha/test_y.py", ""), W3)
_, W4 = R.cache_keys([(al, "alpha/test_y.py")], dict(AM, sums=None), repo, FN, S0)
check("cache_keys: карта без sums — без кэша", W4.get("alpha/test_y.py") == "карта без sums", W4)
r = rt("--cache", al, env={"RUN_TESTS_CACHE": os.path.join(repo, "README.md", "нельзя")})
check("--cache: папка кэша недоступна — строка с причиной, все идут, код 0", r.returncode == 0
      and "недоступна" in r.stdout and "файлов 4, ok 4" in r.stdout, r.stdout)
old = os.path.join(CACHE, "старое.json")
put(old, "{}")
os.utime(old, (1, 1))
r = rt("--cache", al)
check("--cache: запись старше CACHE_DAYS удалена", not os.path.exists(old) and "удалено старых записей 1" in r.stdout,
      r.stdout)

# --- --affected: нечего гонять — дымовой файл вместо кода 3 (metis-0692) ---
git(repo, "checkout", "-q", "--", ".")
git(repo, "checkout", "-q", "-b", "work")
r = rt("--affected", "--base", "main", al, pa)
check("--affected: изменений нет, дымовой файл среди файлов — он идёт, код 0, запись даёт",
      r.returncode == 0 and "дымовой файл pantheon/test_glossary.py" in r.stdout
      and "ok   pantheon/test_glossary.py" in r.stdout and "файлов 1, ok 1" in r.stdout, r.stdout)
put(os.path.join(repo, "README.md"), "# r\nещё\n")
r = rt("--affected", "--base", "main", al, pa)
check("--affected: только README (никем не задет) — дымовой файл, код 0", r.returncode == 0
      and "ни один не проверяется" in r.stdout and "ok   pantheon/test_glossary.py" in r.stdout, r.stdout)
r = rt("--affected", "--base", "main", al)
check("--affected: дымового файла среди файлов нет — код 3, «нечего гонять», как раньше",
      r.returncode == 3 and "нечего гонять" in r.stdout and "итого" not in r.stdout, r.stdout)
check("SMOKE — существующий файл тестов pantheon", os.path.isfile(os.path.join(PLUGIN, "tests", R.SMOKE.split("/")[1]))
      and R.SMOKE.startswith("pantheon/"), R.SMOKE)
check("WINDOW_FS: этот файл (git init во временной папке) в списке", "pantheon/test_map_cache.py" in R.WINDOW_FS)

print(f"\n{total - len(fails)} из {total} прошли")
sys.exit(1 if fails else 0)
