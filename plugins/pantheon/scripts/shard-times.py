#!/usr/bin/env python3
"""shard-times.py — файл времён частей CI из журнала прогона (metis-1117): вес файла для run-tests.py --shard.

  gh run view <id> --log | python3 -I plugins/pantheon/scripts/shard-times.py
  --job ИМЯ     строки только этого job (по началу первого поля журнала gh: «full-shard (2/3)»); по умолчанию
                full-shard — полный набор на macos-15, самый долгий; пустое — все строки, и вывод run-tests.py как есть
  --out ФАЙЛ    куда записать (по умолчанию scripts/shard-times.json рядом со скриптом — SHARD_TIMES раннера)
  --source ТЕКСТ откуда замер, в поле source (например «run 43407050859»); без него — «gh run view --log, job …»

Берёт строки зелёных файлов `ok   <метка> · <с> с` (FAIL и карантин — нет: таймаут даёт предел, а не время, упавший
файл кончается раньше) и пишет {"source", "times": {метка: с}, "estimated": [метки]} отсортированно, атомарно.
Метки, которых в журнале нет, остаются с прежним временем; метка, чьего файла тестов в репозитории больше нет, —
удаляется. estimated — метки, у которых время — оценка, а не замер (например после разреза файла); замер снимает
метку из списка. Код 1 и причина последней строкой, файл не тронут: во входе нет ни одной строки ok нужного job.
Только stdlib.
"""
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "shard-times.json")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # корень agent-kit: plugins/pantheon/scripts → ../../..
# строка раннера: «ok   pantheon/test_a.py · 12.3 с · проверок 45»; у gh перед ней «<job>\t<шаг>\t<время>Z »
OK_LINE = re.compile(r"(?:^|\s)ok {3}(?P<label>[\w.-]+/test_[\w.-]+\.py) · (?P<sec>\d+(?:\.\d+)?) с\b")


def parse(lines, job="full-shard"):
    """{метка: с} из строк журнала: только строки ok; job — начало первого поля строки gh (до табуляции), пустой —
    любые строки. Метка дважды (повтор) — берётся наибольшее время."""
    got = {}
    for ln in lines:
        if job:
            head, tab, _ = ln.partition("\t")
            if not tab or not head.lstrip("\ufeff").startswith(job):
                continue
        m = OK_LINE.search(ln)
        if m:
            got[m["label"]] = max(got.get(m["label"], 0.0), round(float(m["sec"]), 1))
    return got


def exists(label, repo=REPO):
    plugin, _, name = label.partition("/")
    return os.path.isfile(os.path.join(repo, "plugins", plugin, "tests", name))


def merge(old, new, repo=REPO):
    """(times, estimated) — прежние времена, поверх — новые; метки без файла тестов — прочь; estimated — без меток
    с новым замером."""
    times = {k: v for k, v in (old.get("times") or {}).items() if exists(k, repo)}
    times.update(new)
    est = sorted({lb for lb in old.get("estimated") or () if lb in times and lb not in new})
    return dict(sorted(times.items())), est


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def write(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".shard-times-", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def main(argv):
    opts = {"job": "full-shard", "out": OUT, "source": None}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ("--job", "--out", "--source"):
            if not args:
                print(f"shard-times: {a} без значения")
                return 2
            opts[a[2:]] = args.pop(0)
        else:
            print(__doc__)
            print(f"shard-times: неизвестный ключ {a}")
            return 2
    new = parse(sys.stdin.buffer.read().decode("utf-8", "replace").splitlines(), opts["job"])
    if not new:
        print(f"shard-times: во входе нет строк «ok   <метка> · <с> с» job {opts['job']!r} — файл не тронут")
        return 1
    old = load(opts["out"])
    times, est = merge(old, new)
    source = opts["source"] or f"gh run view --log, job {opts['job'] or 'любой'}"
    data = {"source": f"{source}; замер {len(new)} файлов, {time.strftime('%Y-%m-%d')}; estimated — оценка до "
                      "первого замера",
            "times": times, "estimated": est}
    write(opts["out"], data)
    print(f"shard-times: файлов {len(times)}, из журнала {len(new)}, оценок {len(est)} → {opts['out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
