"""Холст «Кто есть кто.canvas» строится кодом из ролей, реестра направлений и статуса задач (metis-0825).

Раньше холст собрал одноразовый скрипт и дальше правили руками, а сверка (pantheon.who_is_who_check, metis-0120/0252)
проверяла только имена: Харон висел «🚧 строится», когда роль уже была. Теперь задача расписания `pantheon who-canvas`
(scripts/who-canvas.sh, каждые 5 минут) пересобирает холст, когда изменились роли, реестр или статус задач из карточек, а не каждый тик.

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
цвет и подписи групп код пишет сам; узел, в котором не то, что код писал (хеш в отпечатке) и не то, что пишет сейчас,
правили руками — он остаётся как есть, а тревога приходит один раз на его текст (metis-0838).

Из тех же входов — таблица ролей в «Кто есть кто.md» и реестр ролей в system.md (metis-0828, sync_docs): код пишет
только между маркерами `<!-- pantheon:roles начало … -->` и `<!-- pantheon:roles конец -->`, текст вокруг — ручной.

Только стандартная библиотека; пути и чтение задач передаёт pantheon.py.
"""
import fnmatch
import hashlib
import json
import os
import re
import tempfile

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
    _e("charon", "top", "charon", "**Харон** · служебная\nЧитает страницы в ваших браузерах со входами (`pantheon browser`); "
       "сайт не из списка — после вашего «да».{?task:metis-0765= Ввод в поля и нажатия — скоро ([[metis-0765]])}"
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


def collect_roles(roles, statuses, catalog=None):
    """Единый список ролей для любого вывода (холст, таблица в «Кто есть кто.md», реестр в system.md — metis-0828):
    [{'name', 'kind', 'description', 'present', 'task'}], по порядку каталога, затем прочие роли по имени.
    kind: 'catalog' (запись каталога; name — id карточки), 'auto' (роль без записи), 'planned' (роли нет, есть planned).
    description — первая фраза description из файла роли ('' — файла нет); task — открытая задача записи или None."""
    catalog = CATALOG if catalog is None else catalog
    out, covered = [], set(IGNORED)
    for e in catalog:
        names = sorted(r for r in roles if e["role"] and fnmatch.fnmatchcase(r, e["role"]))
        covered.update(names)
        if e["role"] is not None and not names and not e["planned"]:
            continue
        refs = [m.group(2) for m in COND.finditer(e["text"]) if m.group(1) == "task"] + ([e["planned"]] if e["planned"] and not names else [])
        task = next((t for t in refs if _open(t, statuses)), None)
        out.append(dict(name=e["id"], kind="catalog" if names or e["role"] is None else "planned",
                        description=role_blurb(roles[names[0]]) if names and roles[names[0]] else "",
                        present=bool(names) or e["role"] is None, task=task, roles=names))
    for r in sorted(set(roles) - covered):
        out.append(dict(name=r, kind="auto", description=role_blurb(roles[r]), present=True, task=None, roles=[r]))
    return out


# --- таблица ролей в «Кто есть кто.md» и реестр ролей в system.md (metis-0828) -------------------------------------
# Те же входы, что у холста: роли (~/.claude/agents и шаблоны плагина), directions.toml, статус задач каталога. Код
# пишет только между маркерами своего блока; текст вокруг — ручной и остаётся. Маркеров нет — блок дописывается в
# конец файла под своим заголовком (перенести маркеры на место ручной таблицы можно руками, код их найдёт). Только
# один маркер из пары — файл не трогаем (ValueError: тревогу поднимает вызывающий).
MEMO_NAME = "Кто есть кто.md"
SYSTEM_NAME = "system.md"
BEGIN = "<!-- pantheon:{name} начало"
END = "<!-- pantheon:{name} конец -->"
BEGIN_FULL = BEGIN + " — собирает pantheon who-canvas из ролей и directions.toml; правка внутри затрётся -->"
MEMO_HEADING = "## Все роли — собирает код"
SYSTEM_HEADING = "## Реестр ролей — собирает код"
FIND = {"hq": "`zeus`", "workshop": "`daedalus-<задача>`"}  # роль окна ищут по имени сессии, а не роли
EXTRA = {"devs": ("codex-dev",)}  # роли из IGNORED, которые названы в тексте записи
GROUP_SHORT = {"top": "Пританей", "coords": "Полисы", "team": "Артель", "help": "Оракулы", "sched": "Оры"}


def _cell(s):
    """Ячейка таблицы markdown: одна строка, `|` экранирован (в том числе в [[ссылка|подпись]] — так читает Obsidian)."""
    return re.sub(r"\s*\n\s*", " · ", str(s or "").strip()).replace("|", "\\|")


def _who(line):
    """Первая строка карточки → «**Имя**, пояснение»: «## Зевс · Пританей» → «**Зевс**, Пританей»."""
    m = re.match(r"#+\s*(.+)", line)
    if m:
        name, _, rest = m.group(1).partition(" · ")
        line = f"**{name}**" + (f" · {rest}" if rest else "")
    return line.replace(" · ", ", ")


def _find(e, names, roles):
    if e["role"] is None:
        return "—"
    if e["role"] in FIND:
        return FIND[e["role"]]
    if e["role"].endswith("*") and not e["role"].startswith("dev-"):
        return f"`{e['role'].rstrip('*-')}-<проект>`"
    extra = [r for r in EXTRA.get(e["id"], ()) if r in roles]
    return ", ".join(f"`{r}`" for r in names + extra) or "—"


def role_rows(roles, directions, statuses, catalog=None):
    """Строки таблицы ролей по collect_roles и координаторам реестра: [(группа, кто, что делает, как найти, состояние)],
    по порядку групп GROUPS."""
    catalog = CATALOG if catalog is None else catalog
    by_id = {e["id"]: e for e in catalog}
    rows = []
    for x in collect_roles(roles, statuses, catalog):
        if x["kind"] == "auto":
            r = x["name"]
            rows.append(("help", f"**{r.replace('-', ' ').capitalize()}**", x["description"], f"`{r}`", "есть"))
            continue
        e = by_id[x["name"]]
        lines = render_text(e["text"], roles, statuses).split("\n")
        who = _who(lines[0])
        state = "есть" if x["present"] else "🚧 роли ещё нет"
        if x["task"] and not x["present"]:
            state += f" · [[{x['task']}]]"
        if not x["present"] and e["name"]:
            who = f"**{e['name']}**"
        rows.append((e["group"], who, "\n".join(lines[1:]), _find(e, x["roles"], roles), state))
    for d in directions:
        god = d["name"].split("-")[0]
        rows.append(("coords", f"**{GODS_RU.get(god, god.capitalize())}**", d.get("short") or "",
                     f"`{d['name']}` · [[directions/{d['name']}/STATUS|STATUS]]", "есть"))
    order = list(GROUPS)
    return sorted(rows, key=lambda r: order.index(r[0]))  # sorted устойчив: внутри группы — порядок каталога


def memo_table(roles, directions, statuses, catalog=None):
    """Таблица ролей для «Кто есть кто.md»."""
    out = ["| Кто | Что делает | Как найти | Группа | Состояние |", "| --- | --- | --- | --- | --- |"]
    for g, who, what, find, state in role_rows(roles, directions, statuses, catalog):
        out.append("| " + " | ".join(_cell(v) for v in (who, what, find, GROUP_SHORT.get(g, g), state)) + " |")
    return "\n".join(out)


def system_table(roles, statuses, catalog=None):
    """Реестр ролей для system.md: каждая роль по имени файла — кто она и откуда берётся."""
    catalog = CATALOG if catalog is None else catalog
    who = {}
    for e in catalog:
        name = _who(render_text(e["text"], roles, statuses).split("\n")[0])
        for r in sorted(roles):
            if e["role"] and r not in who and (fnmatch.fnmatchcase(r, e["role"]) or r in EXTRA.get(e["id"], ())):
                who[r] = name
    who.setdefault("domain-coordinator", "координатор направления — одна роль на все направления реестра")
    out = ["| Роль | Кто | Источник |", "| --- | --- | --- |"]
    for r in sorted(roles):
        src = roles[r] or ""
        src = (f"шаблон плагина `roles/{r}.tmpl`" if src.endswith(".tmpl")
               else f"`~/.claude/agents/{r}.md`" if src else "—")
        out.append("| " + " | ".join(_cell(v) for v in (f"`{r}`", who.get(r) or role_blurb(roles[r]) or "—", src)) + " |")
    return "\n".join(out)


def _marks(text, prefix):
    """Позиции начала строк, где строка начинается с prefix: маркер считается только в начале строки, а такой же текст
    в середине строки — обычный текст (metis-0992)."""
    out, pos = [], 0
    while True:
        i = text.find(prefix, pos)
        if i < 0:
            return out
        if i == 0 or text[i - 1] == "\n":
            out.append(i)
        pos = i + 1


def splice(text, name, body, heading):
    """Текст файла с автоблоком name: между маркерами — body, вне их — как было. Маркеры — только в начале строки: тот же
    текст в середине строки блоком не считается и не теряется. Маркеров нет — блок в конце файла под heading. Один маркер
    без пары, двойные или конец раньше начала — ValueError."""
    b, e = BEGIN.format(name=name), END.format(name=name)
    bs, es = _marks(text, b), _marks(text, e)
    block = f"{BEGIN_FULL.format(name=name)}\n{body.rstrip()}\n{e}"
    if not bs and not es:
        return text.rstrip("\n") + f"\n\n{heading}\n\n{block}\n"
    if len(bs) != 1 or len(es) != 1 or es[0] < bs[0]:
        raise ValueError(f"маркеры блока pantheon:{name} не парные — файл не тронут")
    return text[:bs[0]] + block + text[es[0] + len(e):]


def sync_doc(path, name, body, heading):
    """Записать автоблок в файл path. 'written' | 'same' | 'skip' (файла нет — не создаём: документ ведёт владелец).
    Чтение и запись — под замком path + '.lock' в той же папке (гонка двух проходов не теряет правку), временный файл
    уникальный (mkstemp), ссылка остаётся ссылкой: пишем в её цель."""
    import fcntl
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return "skip"
    with open(real + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(real, encoding="utf-8") as fh:
                cur = fh.read()
        except FileNotFoundError:
            return "skip"
        new = splice(cur, name, body, heading)
        if new == cur:
            return "same"
        fd, tmp = tempfile.mkstemp(prefix=".pantheon-doc.", suffix=".tmp", dir=os.path.dirname(real))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new)
            os.chmod(tmp, os.stat(real).st_mode & 0o777)
            os.replace(tmp, real)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return "written"


def sync_docs(base, roles, directions, statuses, catalog=None):
    """Автоблоки ролей в «Кто есть кто.md» и system.md папки base → {имя файла: итог sync_doc}. Сбой одного файла
    (маркеры не парные, не читается) — итог «ошибка: …» у него, второй файл обновляется."""
    out = {}
    for name, body, heading in ((MEMO_NAME, memo_table(roles, directions, statuses, catalog), MEMO_HEADING),
                                (SYSTEM_NAME, system_table(roles, statuses, catalog), SYSTEM_HEADING)):
        try:
            out[name] = sync_doc(os.path.join(base, name), "roles", body, heading)
        except (ValueError, OSError) as e:
            out[name] = f"ошибка: {e}"
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


def _hash(text, color):
    return hashlib.sha256(f"{text}\0{color or ''}".encode()).hexdigest()[:16]


def _known(hashes, nid):
    """Хеши, которые код записывал в узел nid: строка (обычная запись) или список (запись перед холстом, metis-0838 Д8:
    старый и новый, пока холст не записан)."""
    v = hashes.get(nid)
    return set(v) if isinstance(v, list) else {v} if isinstance(v, str) else set()


def _is_manual(hashes, nid, cur, want):
    """Узел правили руками: код его уже писал (есть запись), сейчас в нём не то, что код писал, и не то, что код
    пишет сейчас. Последнее — Д8: отпечаток отстал от холста (холст записан, а отпечаток нет) — узел кода не ручной."""
    return nid in hashes and cur != want and cur not in _known(hashes, nid)


def build(current, roles, directions, statuses, catalog=None, hashes=None, report=None):
    """Новый холст {'nodes', 'edges'} по текущему (словарь JSON Canvas или None) и входным данным.
    hashes — {id: хеш текста и цвета (у группы — подписи и цвета), записанных кодом в прошлый раз}: узел, у которого
    сейчас другое — и не то, что код пишет сейчас, — правили руками: его текст, цвет и подпись остаются. Нет записи
    (первая сборка) — пишет код. report (словарь) получает 'hashes' (что записано сейчас), 'manual' (id узлов,
    правленных руками), 'manual_hash' ({id: хеш их нынешнего текста} — значение тревоги, Д9) и 'auto' (id узлов,
    которые код пишет сам: их метку ручной правки можно снять)."""
    hashes = hashes or {}
    report = report if report is not None else {}
    report["hashes"], report["manual"], report["manual_hash"] = {}, [], {}
    cur_nodes = {n["id"]: n for n in (current or {}).get("nodes", []) if isinstance(n, dict) and "id" in n}
    known = {"you", "legend", *GROUPS, *[e["id"] for e in (catalog if catalog is not None else CATALOG)]}
    want = desired(roles, directions, statuses, catalog)
    want_ids = {w[0] for w in want}
    # карточки, которыми владеет код: из каталога, авто-карточки ролей и координаторы (ссылка на STATUS направления);
    # такая карточка, которой больше нет среди нужных, уходит, прочие узлы (добавил владелец) остаются
    # (по id, а не по тексту: заметка владельца со ссылкой на STATUS — не карточка кода)
    def owned(n):
        return (n["id"] in known or n["id"].startswith("role-") or n["id"] in hashes  # записан кодом в прошлый раз
                or n["id"] in GODS_RU)  # первая сборка по старому холсту: записей ещё нет
    # группы
    nodes = []
    for gid, (label, color, x, y, w, h) in GROUPS.items():
        old = cur_nodes.get(gid)
        if old and _geom(old) and old.get("type") == "group":
            cur_h = _hash(old.get("label"), old.get("color"))
            if _is_manual(hashes, gid, cur_h, _hash(label, color)):
                g = dict(old)  # подпись или цвет группы правили руками
                report["manual"].append(gid)
                report["manual_hash"][gid] = cur_h
                report["hashes"][gid] = hashes[gid]
                nodes.append(g)
                continue
            g = dict(old, label=label)
        else:
            g = {"id": gid, "type": "group", "x": x, "y": y, "width": w, "height": h, "label": label}
        if color:
            g["color"] = color
        else:
            g.pop("color", None)
        report["hashes"][gid] = _hash(label, color)
        nodes.append(g)
    for nid, n in cur_nodes.items():  # группы, которых код не знает (добавил владелец), остаются со связями
        if n.get("type") == "group" and nid not in GROUPS:
            nodes.append(dict(n))
    groups = {n["id"]: n for n in nodes}
    # узлы, которых код не знает (добавил владелец), и прежние карточки: порядок холста сохраняется
    rest = [n for nid, n in cur_nodes.items() if n.get("type") != "group" and (not owned(n) or nid in want_ids)]
    placed = []
    texts = {w[0]: w for w in want}
    for n in rest:
        if n["id"] in texts:
            _, _, text, w, h, color = texts[n["id"]]
            nid = n["id"]
            cur_h = _hash(n.get("text"), n.get("color"))
            if _is_manual(hashes, nid, cur_h, _hash(text, color)):
                placed.append(dict(n))  # текст или цвет правили руками — код карточку не обновляет
                report["manual"].append(nid)
                report["manual_hash"][nid] = cur_h
                report["hashes"][nid] = hashes[nid]
                continue
            report["hashes"][nid] = _hash(text, color)
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
        report["hashes"][nid] = _hash(text, color)
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
    report["auto"] = sorted(set(report["hashes"]) - set(report["manual"]))
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


def _file_hash(p):
    """Хеш содержимого холста: удалённая или правленная карточка меняет его, и следующий проход собирает холст заново,
    даже если входы те же (metis-0992). Файла нет или не читается — None."""
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _write_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, p)


def _merged(prev, new):
    """Хеши на время записи холста (Д8): у каждого узла — и прежний, и новый. Сбой между отпечатком и холстом
    оставит холст со старым текстом — старый хеш в записи есть, узел не станет «ручным»."""
    out = {}
    for nid, v in new.items():
        both = _known(prev, nid) | _known(new, nid)
        out[nid] = sorted(both) if len(both) > 1 else v
    return out


def sync(canvas_path, sig_path, roles, directions, statuses, catalog=None, force=False, manual_out=None,
         report_out=None):
    """Пересобирает холст, если изменился отпечаток входов (или force). Возвращает 'written' | 'same' | 'unchanged'.
    Под замком (файл sig_path + '.lock'): два запуска сразу не пишут холст и отпечаток вперемешку (metis-0838 Д8).
    roles — {имя: путь файла роли}; в отпечаток идёт и время правки файла (описание новой роли без каталога).
    В файл отпечатка пишутся и хеши текста и цвета каждого узла кода: узел, правленный руками, не обновляется, его id
    попадает в manual_out (список). Удалённая карточка собирается заново. report_out (словарь) получает отчёт build
    ('manual', 'manual_hash', 'auto'); при 'unchanged' он пуст. Порядок записи: отпечаток со старым и новым хешем
    узлов (прежний sig) → холст → отпечаток с новым sig и хешами — убитый на любом шаге процесс не делает узлы кода
    «ручными» и не теряет пересборку."""
    import fcntl
    os.makedirs(os.path.dirname(sig_path), exist_ok=True)
    with open(sig_path + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        return _sync(canvas_path, sig_path, roles, directions, statuses, catalog, force, manual_out, report_out)


def _sync(canvas_path, sig_path, roles, directions, statuses, catalog, force, manual_out, report_out):
    stamped = {}
    for r, p in roles.items():
        try:
            stamped[r] = os.stat(p).st_mtime_ns if p else 0
        except OSError:
            stamped[r] = 0
    sig = signature(stamped, directions, statuses, catalog)
    try:
        with open(sig_path, encoding="utf-8") as fh:
            saved = json.load(fh)
        old, prev = saved.get("sig"), saved.get("hashes")
        if not isinstance(prev, dict):
            prev = {}
    except (OSError, ValueError, AttributeError):
        saved, old, prev = {}, None, {}
    if old == sig and not force and os.path.exists(canvas_path) and saved.get("cv") == _file_hash(canvas_path):
        return "unchanged"
    try:
        with open(canvas_path, encoding="utf-8") as fh:
            current = json.load(fh)
        if not isinstance(current, dict) or not isinstance(current.get("nodes"), list):
            raise ValueError("не холст")
    except FileNotFoundError:
        current = None
    # холст есть, но не читается — не затираем: ошибку видит вызывающий (тревога тика)
    report = {}
    text = render(build(current, roles, directions, statuses, catalog, prev, report))
    if manual_out is not None:
        manual_out.extend(report["manual"])
    if report_out is not None:
        report_out.update(report)
    result = "same"
    try:
        same = open(canvas_path, encoding="utf-8").read() == text
    except OSError:
        same = False
    if not same:
        _write_json(sig_path, {"sig": old, "hashes": _merged(prev, report["hashes"]), "cv": None})  # отпечаток до холста
        os.makedirs(os.path.dirname(canvas_path), exist_ok=True)
        tmp = canvas_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, canvas_path)
        result = "written"
    _write_json(sig_path, {"sig": sig, "hashes": report["hashes"], "cv": _file_hash(canvas_path)})
    return result
