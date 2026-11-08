"""Раскладка открытых задач по пачкам без модели (metis-0595): `pantheon task batch-suggest`.

Берёт открытые задачи без parent (и без старого batch) и считает по каждой пару признаков с другими такими же и с составом
существующих пачек: общие файлы и функции (touches; где их нет — имена файлов и символов из текста), похожесть заголовка
и текста (TF-IDF с отсечением русских окончаний, внешних библиотек нет), ссылки друг на друга (metis-NNNN), общие PR и
источник. Результат — предложения: «в пачку X», «новая пачка из N задач», «дубль — объединить?». Ничего не пишет;
запись parent — только `apply()` для предложений «в существующую пачку» с высокой уверенностью.

Чистые функции от словаря задач `{id: (путь, шапка, тело)}`: время и ввод-вывод — у вызывающего.
"""
import math
import re
from collections import Counter

CLOSED = ("done", "dropped")

# пороги подобраны по настоящим задачам metis-pantheon (02.11, см. отчёт metis-0595); меняются здесь
PAIR_MIN = 0.30        # пара задач «подходит друг другу»
LINK_MIN = 0.32        # среднее по парам двух кластеров, ниже — не сливать
GROUP_MAX = 8          # больше задач в одной новой пачке не предлагаем
JOIN_MIN = 0.40        # задача подходит к существующей пачке
JOIN_HIGH = 0.48       # уверенность для --apply (вместе с признаком не из одного текста)
DUP_COS = 0.80         # почти дубль по тексту
DUP_TITLE = 0.45       # почти дубль по заголовку (вместе с DUP_TITLE_COS)
DUP_TITLE_COS = 0.40

_WORD = re.compile(r"[a-zа-яё][a-zа-яё0-9_]*", re.I)
_ID = re.compile(r"\b[a-z][a-z0-9]{1,11}-\d{3,}\b")
_PR = re.compile(r"(?:#|PR\s*|pull/)(\d{3,5})\b")
_FILE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|md|toml|json|sh|ts|tsx|js|jsx|swift|yml|yaml|html|css|"
                   r"applescript|sql|txt))\b")
_SYMBOL = re.compile(r"`([a-z_][a-z0-9_]{4,})(?:\(\))?`|\b([a-z][a-z0-9]*_[a-z0-9_]+)\(\)|\b([a-z][a-z0-9_]{4,})\(\)")
_JOURNAL = re.compile(r"^## Журнал\b.*", re.S | re.M)

STOP = set("""это как что для при или так его все она они был была были быть есть нет уже еще ещё тоже чтобы если когда
только нужно надо можно после перед между через также который которая которые этот эта эти того тому там тут где
чем без над под про из от по на за до во со не ни но да же ли бы the and for with from that this not are was but can
has have will into when then than also only each such must should задача задачи задачу готово сделать делать сделан
добавить добавлено пункт пункты проверка проверить проверен тест тесты теста тестов команда команды файл файлы файла
плановый проход проходе агент владелец владельца роль роли pantheon metis пантеон todo нужен нужна нужны""".split())

_ENDINGS = sorted("""ировать ирован ирова ование ования ованию ованием ении ения ение ений ением ется ются ится ятся
ость ости остью ами ями ого его ому ему ыми ими ной ная ное ные ных ным ому ую юю ой ей ом ем ах ях ов ев ам ям ы и а
я о е у ю ь ть ет ут ют ит ат ят ил ила ило или ал ала ало али ся сь""".split(), key=len, reverse=True)


def stem(w):
    w = w.lower().replace("ё", "е")
    if re.fullmatch(r"[a-z0-9_]+", w):
        return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
    if len(w) <= 3:
        return w
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[:-len(e)]
    return w


def _words(text):
    """[(stem, исходное слово)] без стоп-слов; snake_case даёт и целое имя, и части."""
    out = []
    for m in _WORD.finditer(text or ""):
        w = m.group(0)
        parts = [w] + ([p for p in w.split("_") if len(p) >= 4] if "_" in w else [])
        for p in parts:
            lw = p.lower()
            if len(lw) < 3 or lw in STOP or lw.isdigit():
                continue
            out.append((stem(lw), p))
    return out


def card_text(body):
    """Текст карточки без журнала (в нём «создана», «взята» и время — шум)."""
    return _JOURNAL.sub("", body or "")


def features(tid, head, body):
    text = card_text(body)
    full = f"{head.get('title') or ''}\n{text}"
    touches = [str(x).strip().replace("\\", "/").lstrip("./") for x in head.get("touches") or []]
    files = {t.rsplit("/", 1)[-1] for t in touches if re.search(r"\.\w{1,5}$", t.rsplit("/", 1)[-1])}
    files |= {m.group(1).rsplit("/", 1)[-1] for m in _FILE.finditer(full)}
    syms = {next(g for g in m.groups() if g) for m in _SYMBOL.finditer(full)}
    refs = {i for i in _ID.findall(text) if i != tid}
    refs |= {str(head[k]) for k in ("source", "depends_on") if isinstance(head.get(k), str) and head.get(k) != tid}
    refs |= {i for i in head.get("depends_on") or [] if i != tid}
    prs = set(_PR.findall(full))
    title = Counter(s for s, _ in _words(head.get("title") or ""))
    tf, shown = Counter(), {}
    for s, w in _words(head.get("title") or ""):
        tf[s] += 3
        shown.setdefault(s, Counter())[w.lower()] += 1
    for s, w in _words(text):
        tf[s] += 1
        shown.setdefault(s, Counter())[w.lower()] += 1
    return {"id": tid, "title": head.get("title") or "", "files": files, "syms": syms, "refs": refs, "prs": prs,
            "source": head.get("source"), "tf": tf, "title_set": set(title), "shown": shown,
            "dirs": {t for t in touches if t.count("/") >= 2 and not re.search(r"\.\w{1,5}$", t)}}


def _vectors(feats):
    n = len(feats)
    df = Counter(s for f in feats.values() for s in f["tf"])
    idf = {s: math.log((n + 1) / (c + 1)) + 1 for s, c in df.items()}
    vec = {}
    for tid, f in feats.items():
        v = {s: (1 + math.log(c)) * idf[s] for s, c in f["tf"].items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        vec[tid] = {s: x / norm for s, x in v.items()}
    return vec, idf


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(s, 0) for s, x in a.items())


class Scorer:
    def __init__(self, feats):
        self.f = feats
        self.vec, self.idf = _vectors(feats)
        n = len(feats)
        cap = max(5, int(0.03 * n))
        self.common = set()  # общие для многих задач файлы и символы ничего не значат
        for key in ("files", "syms"):
            c = Counter(x for f in feats.values() for x in f[key])
            self.common |= {(key, x) for x, k in c.items() if k > cap}
        self.generic_files = {"README.md", "AGENTS.md", "CLAUDE.md", "plugin.json", "STATUS.md", "settings.json"}
        self.cache = {}

    def cos(self, a, b):
        return _cos(self.vec[a], self.vec[b])

    def pair(self, a, b):
        """→ (оценка 0..1, причины {files, syms, link, prs, text}). Симметрична."""
        key = (a, b) if a < b else (b, a)
        if key in self.cache:
            return self.cache[key]
        fa, fb = self.f[a], self.f[b]
        files = sorted(x for x in fa["files"] & fb["files"] if ("files", x) not in self.common
                       and x not in self.generic_files)
        syms = sorted(x for x in fa["syms"] & fb["syms"] if ("syms", x) not in self.common)
        link = b in fa["refs"] or a in fb["refs"]
        shared_refs = sorted(r for r in fa["refs"] & fb["refs"] if r not in (a, b))
        prs = sorted(fa["prs"] & fb["prs"])
        c = self.cos(a, b)
        s = 0.0
        if files:
            s += min(0.5, 0.30 + 0.10 * (len(files) - 1))
        if syms:
            s += min(0.25, 0.15 + 0.05 * (len(syms) - 1))
        s = min(s, 0.55)
        if link:
            s += 0.45
        if shared_refs:
            s += 0.15
        if prs:
            s += 0.30
        if c >= 0.15:
            s += 0.7 * c
        why = {"files": files, "syms": syms, "link": link, "refs": shared_refs, "prs": prs, "text": round(c, 2)}
        out = (min(1.0, s), why)
        self.cache[key] = out
        return out

    def hard(self, why):
        """Есть признак не из одного текста: файл, символ, ссылка, общий PR."""
        return bool(why["files"] or why["syms"] or why["link"] or why["prs"])


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _is_story_target(sid, tasks):
    h = tasks[sid][1]
    if h.get("type") != "story" or h.get("status") in CLOSED:
        return False
    if str(h.get("title") or "").startswith("Цель: "):
        return False
    return not any(x.get("type") == "story" and x.get("parent") == sid for _, x, _ in tasks.values())


def _cluster(ids, sc):
    """Средняя связь: сливает кластеры, пока средняя оценка пар между ними ≥ LINK_MIN и размер ≤ GROUP_MAX."""
    clusters = {i: [i] for i in ids}
    sums = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            s = sc.pair(a, b)[0]
            if s >= PAIR_MIN * 0.5:
                sums[(a, b)] = s
    while sums:
        best, bv = None, LINK_MIN
        for (x, y), tot in sums.items():
            if len(clusters[x]) + len(clusters[y]) > GROUP_MAX:
                continue
            v = tot / (len(clusters[x]) * len(clusters[y]))
            if v > bv or (v == bv and best is not None and (x, y) < best):
                best, bv = (x, y), v
        if best is None:
            break
        x, y = best
        clusters[x] += clusters.pop(y)
        new = {}
        for (p, q), tot in sums.items():
            if (p, q) == best:
                continue
            p = x if p == y else p
            q = x if q == y else q
            k = (p, q) if p < q else (q, p)
            new[k] = new.get(k, 0) + tot
        sums = new
    return [sorted(v) for v in clusters.values() if len(v) >= 2]


def _name(members, sc):
    """Черновое название по самым весомым словам группы (в начале заголовка вес больше)."""
    w = Counter()
    for m in members:
        for s, x in sc.vec[m].items():
            w[s] += x
    n = len(members)
    df = Counter(s for m in members for s in sc.f[m]["tf"])
    top = [s for s, _ in w.most_common(40) if df[s] >= min(2, n)][:3]
    words = []
    for s in top:
        shown = Counter()
        for m in members:
            shown.update(sc.f[m]["shown"].get(s, {}))
        words.append(shown.most_common(1)[0][0])
    return "Пачка: " + (" ".join(words) or "общая тема")


def _summary(members, sc):
    files, syms, link, prs = Counter(), Counter(), False, set()
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            _, why = sc.pair(a, b)
            files.update(why["files"])
            syms.update(why["syms"])
            link = link or why["link"]
            prs |= set(why["prs"])
    out = []
    if files:
        out.append("общие файлы: " + ", ".join(f for f, _ in files.most_common(4)))
    if syms:
        out.append("общие имена: " + ", ".join(f for f, _ in syms.most_common(3)))
    if link:
        out.append("ссылаются друг на друга")
    if prs:
        out.append("общий PR: " + ", ".join("#" + p for p in sorted(prs)))
    return out or ["похожие заголовок и текст"]


def suggest(tasks, direction):
    """Предложения по направлению direction → словарь (см. модуль). tasks — load_tasks(..., WORK_TYPES)."""
    scope = {i: v for i, v in tasks.items() if v[1].get("direction") == direction}
    opened = {i: v for i, v in scope.items() if v[1].get("type") == "task" and v[1].get("status") not in CLOSED}
    loose = sorted(i for i, (_, h, _) in opened.items() if not h.get("parent") and not h.get("batch"))
    stories = sorted(s for s in scope if _is_story_target(s, scope))
    members = {s: sorted(i for i, (_, h, _) in scope.items() if h.get("parent") == s and h.get("type") == "task")
               for s in stories}
    need = set(loose) | set(stories) | {m for ms in members.values() for m in ms}
    feats = {i: features(i, scope[i][1], scope[i][2]) for i in need}
    sc = Scorer(feats)

    joins, rest = [], []
    for t in loose:
        best = None
        for s in stories:
            scores = sorted(((sc.pair(t, m)[0], m) for m in members[s] if m in feats), reverse=True)
            card = sc.pair(t, s)
            cand = [x[0] for x in scores[:2]]
            if not cand:
                v, why_id = card[0] * 0.8, s
            else:
                v = (cand[0] + (cand[1] if len(cand) > 1 else cand[0] * 0.6)) / 2
                v = max(v, card[0] * 0.8)
                why_id = scores[0][1] if scores[0][0] >= card[0] else s
            if best is None or v > best[0]:
                best = (v, s, why_id)
        if best and best[0] >= JOIN_MIN:
            v, s, via = best
            why = sc.pair(t, via)[1]
            joins.append({"task": t, "title": feats[t]["title"], "story": s, "story_title": scope[s][1].get("title"),
                          "score": round(v, 2), "via": via, "reasons": _reasons(why),
                          "confidence": "high" if v >= JOIN_HIGH and sc.hard(why) else "normal"})
        else:
            rest.append(t)

    groups = []
    for g in _cluster(rest, sc):
        pairs = [sc.pair(a, b)[0] for i, a in enumerate(g) for b in g[i + 1:]]
        groups.append({"name": _name(g, sc), "tasks": [{"id": i, "title": feats[i]["title"]} for i in g],
                       "score": round(sum(pairs) / len(pairs), 2), "reasons": _summary(g, sc)})
    groups.sort(key=lambda x: (-len(x["tasks"]), -x["score"], x["tasks"][0]["id"]))
    grouped = {t["id"] for g in groups for t in g["tasks"]}

    dups, ids = [], sorted(set(loose) | {m for ms in members.values() for m in ms
                                         if scope[m][1].get("status") not in CLOSED})
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            c = sc.cos(a, b)
            tj = jaccard(feats[a]["title_set"], feats[b]["title_set"])
            if c >= DUP_COS or (tj >= DUP_TITLE and c >= DUP_TITLE_COS):
                dups.append({"a": a, "b": b, "a_title": feats[a]["title"], "b_title": feats[b]["title"],
                             "similarity": round(c, 2), "title_overlap": round(tj, 2)})
    dups.sort(key=lambda x: (-x["similarity"], x["a"], x["b"]))
    singles = sorted(set(rest) - grouped)
    return {"direction": direction, "open_loose": len(loose), "stories": len(stories), "joins": joins, "groups": groups,
            "duplicates": dups, "singles": [{"id": i, "title": feats[i]["title"]} for i in singles]}


def _reasons(why):
    out = []
    if why["files"]:
        out.append("файлы: " + ", ".join(why["files"][:3]))
    if why["syms"]:
        out.append("имена: " + ", ".join(why["syms"][:3]))
    if why["link"]:
        out.append("ссылка")
    if why["prs"]:
        out.append("PR " + ", ".join("#" + p for p in why["prs"]))
    if why["text"] >= 0.15:
        out.append(f"текст {why['text']}")
    return out


def best_join(res, tid):
    """Лучшая существующая пачка для задачи tid по результату suggest() → предложение «в пачку» или None
    (`pantheon task new` без --parent: подсказка, metis-0940)."""
    return next((j for j in res["joins"] if j["task"] == tid), None)


def keys(res):
    """Ключи предложений: по ним проход видит, что нового."""
    return sorted([f"join:{j['task']}>{j['story']}" for j in res["joins"]]
                  + ["group:" + "+".join(t["id"] for t in g["tasks"]) for g in res["groups"]]
                  + [f"dup:{d['a']}+{d['b']}" for d in res["duplicates"]])


def render(res):
    d = res["direction"]
    lines = [f"{d}: открытых задач без пачки — {res['open_loose']}, открытых пачек — {res['stories']}; "
             f"в существующую пачку — {len(res['joins'])}, новых пачек — {len(res['groups'])}, "
             f"дублей — {len(res['duplicates'])}, без пары — {len(res['singles'])}"]
    if res["duplicates"]:
        lines += ["", "Объединить? (почти дубли)"]
        lines += [f"  {x['a']} и {x['b']} (текст {x['similarity']}): «{x['a_title']}» / «{x['b_title']}»"
                  for x in res["duplicates"]]
    if res["joins"]:
        lines += ["", "Положить в существующую пачку"]
        for j in res["joins"]:
            mark = " [уверенно]" if j["confidence"] == "high" else ""
            lines.append(f"  {j['task']} → {j['story']} «{j['story_title']}»{mark} ({j['score']}; "
                         f"{', '.join(j['reasons'])}) — {j['title']}")
    if res["groups"]:
        lines += ["", "Новые пачки (черновые названия)"]
        for g in res["groups"]:
            lines.append(f"  {g['name']} — {len(g['tasks'])} задач, {g['score']} ({'; '.join(g['reasons'])})")
            lines += [f"    {t['id']} {t['title']}" for t in g["tasks"]]
    return "\n".join(lines)


def apply(res, tasks, attach):
    """Прикрепляет только предложения confidence=high через attach(task_id, story_id) (tasks.task_attach).
    Задача без решённого mode attach не пускает — пропуск со строкой. Сбой записи (OSError и прочее) тоже пропуск со
    строкой, а не падение прохода: одна задача не отменяет остальные (metis-0960); parent мог успеть записаться
    до сбоя — строка просит сверить журнал. → (сделано, пропущено) списками строк."""
    done, skipped = [], []
    for j in res["joins"]:
        if j["confidence"] != "high":
            continue
        try:
            attach(j["task"], j["story"])
            done.append(f"{j['task']} → {j['story']}")
        except ValueError as e:
            skipped.append(f"{j['task']} → {j['story']}: {e}")
        except Exception as e:  # noqa: BLE001 — сбой диска посреди пары записей
            skipped.append(f"{j['task']} → {j['story']}: сбой записи ({type(e).__name__}: {e}) — сверьте parent и журнал")
    return done, skipped
