"""Холст «Кто есть кто.canvas» строится кодом из ролей, реестра направлений и статуса задач (metis-0825).

Раньше холст собрал одноразовый скрипт и дальше правили руками, а сверка (pantheon.who_is_who_check, metis-0120/0252)
проверяла только имена: Харон висел «🚧 строится», когда роль уже была. Теперь плановый проход (pantheon.who_canvas_tick)
пересобирает холст, когда изменились роли, реестр или статус задач из карточек, а не каждый тик.

Что строит код:
  - карточка роли — из CATALOG: есть роль → карточка без 🚧; роли нет, а в записи стоит `planned` (задача) → жёлтая
    карточка 🚧 и ссылка на задачу; роли нет и `planned` нет → карточки нет (удалённая роль уходит);
  - роль, которой нет в CATALOG и в IGNORED, получает карточку сама (имя + первая фраза description из её файла) в
    группу «Оракулы» — холст не отстаёт от новой роли, пока CATALOG не дописан;
  - координаторы — по одной карточке на направление из directions.toml (бог — приставка имени, подпись — `short`);
  - ссылка на задачу в тексте — условная `{?task:<id>=…}`: пока задача не закрыта (done, dropped) или её нет — текст
    с ссылкой остаётся, закрыта — выпадает; так же `{?role:<имя>=…}` — только пока роль есть.

Что берётся из текущего холста: x, y, ширина и высота узла по id (владелец двигает карточки руками), размер и место
групп, связи (остаются, если оба конца есть) и узлы с id, которых код не знает (добавил владелец). Новый узел встаёт в
первое свободное место своей группы; места нет — группа растёт вниз, а всё, что лежало под ней, сдвигается. Тексты,
цвет и подписи групп код пишет сам: правки текста руками пересборка затрёт.

Только стандартная библиотека; пути и чтение задач передаёт pantheon.py.
"""
import fnmatch
import hashlib
import json
import os
import re

CANVAS_NAME = "Кто есть кто.canvas"
GREEN, CALL, BUILD, YOU = "4", "5", "3", "6"  # цвета темы Obsidian: зелёный, голубой, жёлтый, фиолетовый
CW, CH, PAD, HEAD, GAP = 260, 120, 50, 70, 60  # карточка, поля группы, шапка группы, промежуток

# id группы → (подпись, цвет, x, y, ширина, высота) — по умолчанию, если в текущем холсте группы нет
GROUPS = {
    "top": ("👁 Пританей · Зевс и служебные роли", GREEN, 0, 220, 1320, 270),
    "coords": ("👁 Полисы · координаторы направлений, видны, когда запущены", GREEN, 0, 630, 1320, 420),
    "team": ("👻 Артель · команда внутри сессии координатора", None, 0, 1190, 1320, 420),
    "help": ("👻 Оракулы · зовут на время", None, 1620, 220, 680, 600),
    "sched": ("👻 Оры · по расписанию", None, 1620, 960, 680, 240),
}

LEGEND = ("### Как читать\n"
          "- **Зелёная группа** — вижу в `claude agents`, могу открыть и написать.\n"
          "- **Серая группа** — не вижу: работает внутри чужой сессии или по расписанию.\n"
          "- **Жёлтая карточка** 🚧 — роли ещё нет, её делают.\n"
          "- **Серая стрелка** — поручает работу. **Голубая** — зовёт на время или присылает итог.\n\n"
          "С координатором можно говорить напрямую: итог он запишет в свой STATUS и сообщит Зевсу.\n\n"
          "Подробно — [[Кто есть кто]].")


def _e(id, group, role, text, w=260, h=160, color=None, planned=None, name=None):
    """Запись каталога. role — имя роли или маска (`dev-*`), None — карточка без роли (всегда есть); planned — id задачи,
    пока роли нет (тогда 🚧); name — имя для 🚧-карточки (без него — первая жирная строка текста)."""
    return dict(id=id, group=group, role=role, text=text, w=w, h=h, color=color, planned=planned, name=name)


CATALOG = [
    _e("daed", "top", "workshop", "**Дедал** · мастерская\nОдна разовая задача; сколько задач — столько Дедалов. Поручает Зевс\n"
       "`daedalus-<задача>`"),
    _e("charon", "top", "charon", "**Харон** · служебная\nЧитает страницы в ваших Comet и Chrome со входами (`pantheon browser`); "
       "сайт не из списка — после вашего «да».{?task:metis-0765= Формы и кнопки — скоро ([[metis-0765]])}"
       "{?task:metis-0760=\n[[metis-0760]]}"),
    _e("hestia", "top", "hestia", "**Гестия** · служебная\nСтавит выпуски, перезапускает окна, чинит систему; спит, будит Зевс"
       "{?task:metis-0245=\n[[directions/metis-pantheon/tasks/metis-0245|metis-0245]]}"),
    _e("zeus", "top", "hq", "## Зевс · Пританей\nПринимает просьбы, раздаёт работу, ведёт доску. Вопросы к вам — через него\n"
       "`zeus` · [[Доска/Сводка|Сводка]] · [[decisions|Решения]]", w=340, h=150, color=GREEN),
    _e("heph", "team", "hephaestus*", "**Гефест** · лид кода\nПланирует, раздаёт, сливает ветки", w=240, h=110),
    _e("apollo", "team", "apollo*", "**Аполлон** · лид дизайна\nИнтерфейс, приёмка по скриншотам", w=240, h=110),
    _e("palamedes", "team", "palamedes", "**Паламед** · исполнитель без кода\nТексты, юр. разбор, выводы из данных; "
       "черновик с источниками", h=120),
    _e("argus", "team", "argus", "**Аргус** · ревьюер\nПроверяет работу, файлы не правит", h=120),
    _e("talos", "team", "talos", "**Талос** · проверка вживую\nПриложение в отдельном браузере", h=120),
    _e("devs", "team", "dev-*", "**Разработчики**\nOpus — сложное, Sonnet — обычное, Haiku — механика"
       "{?role:codex-dev=; Codex — если выбран}", w=240, h=150),
    _e("prom", "help", "prometheus", "**Прометей** · исследователь\nВеб → отчёт в knowledge; раз в месяц сам", h=120),
    _e("iris", "help", "iris", "**Ирида** · разведчик\nНовые версии и инструменты", h=120),
    _e("chiron", "help", "chiron", "**Хирон** · коуч\nДлинные разговоры; зовёт только Зевс", h=120),
    _e("momus", "help", "momus", "**Мом** · ревизор\nНезависимая проверка (навык audit)", h=120),
    _e("tg", "help", "tg-reader", "**Читатель Telegram**\nВыгрузки Telegram → выжимка; зовёт любая сессия", w=580, h=110),
    _e("tick", "sched", None, "**Дежурный** · раз в 1–5 мин\nДоска, копия, сессии; [[alerts|тревоги]]", h=120),
    _e("clio", "sched", "clio", "**Клио** · раз в неделю\nknowledge и [[system|реестр]]", h=120),
]
# роли, у которых своей карточки нет: учтены в тексте другой (codex-dev — в «Разработчиках») или это все координаторы
IGNORED = ("domain-coordinator", "codex-dev")
# бог из приставки имени направления → имя по-русски на карточке координатора
GODS_RU = {"athena": "Афина", "hermes": "Гермес", "themis": "Фемида", "calliope": "Каллиопа", "mnemo": "Мнемозина",
           "proteus": "Протей", "metis": "Метида", "janus": "Янус", "daedalus": "Дедал", "apollo": "Аполлон",
           "hephaestus": "Гефест", "argus": "Аргус", "chiron": "Хирон", "prometheus": "Прометей", "talos": "Талос",
           "clio": "Клио", "iris": "Ирида", "momus": "Мом", "charon": "Харон", "hestia": "Гестия",
           "palamedes": "Паламед", "zeus": "Зевс"}
# связи для холста, собираемого с нуля; в готовом холсте связи остаются как есть (владелец мог убрать лишние)
EDGES = [
    ("you", "zeus", "bottom", "top", "просьбы и ответы", None),
    ("zeus", "daed", "bottom", "bottom", "поручает", None),
    ("zeus", "coords", "bottom", "top", "поручает", None),
    ("zeus", "help", "right", "left", "зовёт", CALL),
    ("coords", "team", "bottom", "top", "зовут на эпик", CALL),
    ("heph", "devs", "right", "left", None, None),
    ("apollo", "devs", "bottom", "top", None, None),
    ("heph", "argus", "bottom", "top", None, None),
    ("heph", "talos", "bottom", "top", None, None),
    ("sched", "zeus", "left", "right", "тревоги и сводка", CALL),
]
COND = re.compile(r"\{\?(task|role):([^=}]+)=([^{}]*)\}")
TASK_ID = re.compile(r"[a-z][a-z0-9]{1,11}-\d{3,}")
CLOSED = ("done", "dropped")


def role_present(spec, roles):
    return any(fnmatch.fnmatchcase(r, spec) for r in roles)


def task_refs(catalog=None):
    """Id задач, на которые ссылаются тексты и planned каталога: по ним проход смотрит статус."""
    ids = set()
    for e in catalog if catalog is not None else CATALOG:
        ids.update(m.group(2) for m in COND.finditer(e["text"]) if m.group(1) == "task")
        if e["planned"]:
            ids.add(e["planned"])
    return sorted(ids)


def _open(tid, statuses):
    """Задача открыта: статус известен и не done/dropped. Нет в доске — как закрытая (ссылка в никуда не нужна)."""
    st = statuses.get(tid)
    return st is not None and st not in CLOSED


def render_text(text, roles, statuses):
    def sub(m):
        kind, key, body = m.groups()
        ok = _open(key, statuses) if kind == "task" else role_present(key, roles)
        return body if ok else ""
    return COND.sub(sub, text)


def role_blurb(path):
    """Первая фраза description из шапки файла роли (до 140 знаков) или ''."""
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(4000)
    except (OSError, UnicodeDecodeError):
        return ""
    m = re.search(r"^description:\s*(.+)$", head, re.M)
    if not m:
        return ""
    s = m.group(1).strip().strip("\"'")
    first = re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0]
    return first if len(first) <= 140 else first[:137].rstrip() + "…"


def desired(roles, directions, statuses, catalog=None):
    """Нужные карточки: список (id, group, text, w, h, color). roles — {имя: путь к файлу роли или ''},
    directions — [{'name', 'short'}], statuses — {id задачи: статус}."""
    catalog = CATALOG if catalog is None else catalog
    out = [("you", None, "## 🙂 Вы", 200, 90, YOU), ("legend", None, LEGEND, 480, 360, None)]
    covered = set(IGNORED)
    for e in catalog:
        have = e["role"] is None or role_present(e["role"], roles)
        if e["role"]:
            covered.update(r for r in roles if fnmatch.fnmatchcase(r, e["role"]))
        if have:
            out.append((e["id"], e["group"], render_text(e["text"], roles, statuses), e["w"], e["h"], e["color"]))
        elif e["planned"]:
            name = e["name"] or (re.search(r"\*\*(.+?)\*\*", e["text"]) or re.search(r"(\S.*)", e["text"])).group(1)
            link = f"\n[[{e['planned']}]]" if _open(e["planned"], statuses) else ""
            out.append((e["id"], e["group"], f"🚧 **{name}**{link}", e["w"], e["h"], BUILD))
    for r in sorted(set(roles) - covered):
        blurb = role_blurb(roles[r])
        out.append(("role-" + r, "help", f"**{r.replace('-', ' ').capitalize()}**\n`{r}`" + (f"\n{blurb}" if blurb else ""),
                    CW, 130, None))
    for d in directions:
        god = d["name"].split("-")[0]
        out.append((god, "coords", f"**{GODS_RU.get(god, god.capitalize())}**\n{d.get('short') or ''}\n"
                    f"[[directions/{d['name']}/STATUS|{d['name']}]]", 240, 110, None))
    return out


def _overlap(a, b, margin=0):
    return not (a[0] + a[2] + margin <= b[0] or b[0] + b[2] + margin <= a[0]
                or a[1] + a[3] + margin <= b[1] or b[1] + b[3] + margin <= a[1])


def _place(g, w, h, taken):
    """Первое свободное место (x, y) в группе g — словарь узла; None — места нет."""
    gx, gy, gw, gh = g["x"], g["y"], g["width"], g["height"]
    y = gy + HEAD
    while y + h <= gy + gh - 30:
        x = gx + PAD
        while x + w <= gx + gw - PAD:
            if not any(_overlap((x, y, w, h), t, 30) for t in taken):
                return x, y
            x += 20
        y += 20
    return None


def _grow(g, dy, nodes):
    """Группа g выросла вниз на dy: всё, что лежало целиком под ней и пересекалось с ней по горизонтали, сдвигается."""
    old_bottom = g["y"] + g["height"]
    for n in nodes:
        if n is g or n["y"] < old_bottom or n["x"] >= g["x"] + g["width"] or n["x"] + n["width"] <= g["x"]:
            continue
        n["y"] += dy
    g["height"] += dy


def build(current, roles, directions, statuses, catalog=None):
    """Новый холст {'nodes', 'edges'} по текущему (словарь JSON Canvas или None) и входным данным."""
    cur_nodes = {n["id"]: n for n in (current or {}).get("nodes", []) if isinstance(n, dict) and "id" in n}
    known = {"you", "legend", *GROUPS, *[e["id"] for e in (catalog if catalog is not None else CATALOG)]}
    want = desired(roles, directions, statuses, catalog)
    want_ids = {w[0] for w in want}
    # карточки, которыми владеет код: из каталога, авто-карточки ролей и координаторы (ссылка на STATUS направления);
    # такая карточка, которой больше нет среди нужных, уходит, прочие узлы (добавил владелец) остаются
    def owned(n):
        return n["id"] in known or n["id"].startswith("role-") or "/STATUS|" in str(n.get("text", ""))
    # группы
    nodes = []
    for gid, (label, color, x, y, w, h) in GROUPS.items():
        old = cur_nodes.get(gid)
        if old and _geom(old) and old.get("type") == "group":
            g = dict(old, label=label)
        else:
            g = {"id": gid, "type": "group", "x": x, "y": y, "width": w, "height": h, "label": label}
        if color:
            g["color"] = color
        else:
            g.pop("color", None)
        nodes.append(g)
    groups = {n["id"]: n for n in nodes}
    # узлы, которых код не знает (добавил владелец), и прежние карточки: порядок холста сохраняется
    rest = [n for nid, n in cur_nodes.items() if n.get("type") != "group" and (not owned(n) or nid in want_ids)]
    placed = []
    texts = {w[0]: w for w in want}
    for n in rest:
        if n["id"] in texts:
            _, _, text, w, h, color = texts[n["id"]]
            m = dict(n, type="text", text=text)  # место, размер и порядок полей — как на холсте
            if not _geom(n):
                m.update(x=0, y=0, width=w, height=h)
            if color:
                m["color"] = color
            else:
                m.pop("color", None)
            placed.append(m)
        else:
            placed.append(dict(n))
    have = {n["id"] for n in placed}
    # координаты «you» и «legend» у холста с нуля — над зелёной группой и слева от неё
    fixed = {"you": (1000, 0), "legend": (-640, 0)}
    taken = [(n["x"], n["y"], n["width"], n["height"]) for n in placed if n.get("type") != "group"]
    for nid, gid, text, w, h, color in want:
        if nid in have:
            continue
        m = {"id": nid, "type": "text", "text": text, "x": 0, "y": 0, "width": w, "height": h}
        if color:
            m["color"] = color
        if gid is None:
            m["x"], m["y"] = fixed[nid]
        else:
            g = groups[gid]
            pos = _place(g, w, h, taken)
            if pos is None:
                inside = [t for t in taken if g["x"] <= t[0] < g["x"] + g["width"] and g["y"] <= t[1] < g["y"] + g["height"]]
                low = max([t[1] + t[3] for t in inside], default=g["y"] + HEAD - GAP)
                pos = (g["x"] + PAD, low + GAP)
                need = pos[1] + h + 50 - (g["y"] + g["height"])
                if need > 0:  # группа растёт вниз, всё под ней (в том числе группы) сдвигается
                    _grow(g, need, nodes + placed)
                    taken = [(n["x"], n["y"], n["width"], n["height"]) for n in placed if n.get("type") != "group"]
            m["x"], m["y"] = pos
        placed.append(m)
        taken.append((m["x"], m["y"], m["width"], m["height"]))
    nodes = sorted(nodes + placed, key=lambda n: n["type"] != "group")
    ids = {n["id"] for n in nodes}
    if current is None:
        edges = [{"id": f"e-{a}-{b}", "fromNode": a, "fromSide": fs, "toNode": b, "toSide": ts,
                  **({"color": c} if c else {}), **({"label": lb} if lb else {})}
                 for a, b, fs, ts, lb, c in EDGES if a in ids and b in ids]
    else:
        edges = [dict(e) for e in current.get("edges", []) if isinstance(e, dict)
                 and e.get("fromNode") in ids and e.get("toNode") in ids]
    return {"nodes": nodes, "edges": edges}


def _geom(n):
    return all(isinstance(n.get(k), int) and not isinstance(n.get(k), bool) for k in ("x", "y", "width", "height"))


def render(canvas):
    """Текст файла — как его пересохраняет сам Obsidian (табы, поле на строку, без перевода строки в конце): иначе
    Obsidian перепишет файл при открытии. Порядок полей узла остаётся как был, у новых — NODE_KEYS."""
    return json.dumps(canvas, ensure_ascii=False, indent="\t")


def signature(roles, directions, statuses, catalog=None):
    """Отпечаток входов: роли (имя и время правки файла), направления и статусы задач из каталога."""
    blob = json.dumps({"roles": sorted(roles.items()), "dirs": directions,
                       "tasks": sorted((t, statuses.get(t)) for t in task_refs(catalog)),
                       "catalog": hashlib.sha256(repr((CATALOG if catalog is None else catalog, GROUPS, EDGES, LEGEND,
                                                       GODS_RU, IGNORED)).encode()).hexdigest()},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def sync(canvas_path, sig_path, roles, directions, statuses, catalog=None, force=False):
    """Пересобирает холст, если изменился отпечаток входов (или force). Возвращает 'written' | 'same' | 'unchanged'.
    roles — {имя: путь файла роли}; в отпечаток идёт и время правки файла (описание новой роли без каталога)."""
    stamped = {}
    for r, p in roles.items():
        try:
            stamped[r] = os.stat(p).st_mtime_ns if p else 0
        except OSError:
            stamped[r] = 0
    sig = signature(stamped, directions, statuses, catalog)
    try:
        with open(sig_path, encoding="utf-8") as fh:
            old = json.load(fh).get("sig")
    except (OSError, ValueError, AttributeError):
        old = None
    if old == sig and not force and os.path.exists(canvas_path):
        return "unchanged"
    try:
        with open(canvas_path, encoding="utf-8") as fh:
            current = json.load(fh)
        if not isinstance(current, dict) or not isinstance(current.get("nodes"), list):
            raise ValueError("не холст")
    except FileNotFoundError:
        current = None
    # холст есть, но не читается — не затираем: ошибку видит вызывающий (тревога тика)
    text = render(build(current, roles, directions, statuses, catalog))
    result = "same"
    try:
        same = open(canvas_path, encoding="utf-8").read() == text
    except OSError:
        same = False
    if not same:
        os.makedirs(os.path.dirname(canvas_path), exist_ok=True)
        tmp = canvas_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, canvas_path)
        result = "written"
    os.makedirs(os.path.dirname(sig_path), exist_ok=True)
    with open(sig_path, "w", encoding="utf-8") as fh:
        json.dump({"sig": sig}, fh)
    return result
