#!/usr/bin/env python3
"""Проверка правок ~/.claude перед отправкой на другие Mac и после получения (SEC-15, решено 14.10).

Правки синхронизируются сами; человек нужен, только когда его решение что-то меняет: правка кода, который сам
запускается на каждом Mac (sync.sh, statusline.sh, bootstrap.sh, hooks/, tools/, хуки в настройках), или
подозрительная правка. Правила — по атаке Cisco на Claude Code (хук UserPromptSubmit в глобальных настройках,
переписанная память, алиас в ~/.zshrc):

  настройки (settings*.json) — битый JSON; новый или изменённый хук либо строка статуса с опасной командой или
      вне известных мест; режим bypassPermissions, disableAllHooks, пропуск предупреждения; снятый запрет deny;
      широкое allow; переменные окружения, которые меняют адрес API, прокси, загрузку кода или выключают guard;
      помощники, которые запускают команды (apiKeyHelper и др.); выключенный guard или pantheon; новый маркетплейс;
  исполняемое (sync.sh, statusline.sh, bootstrap.sh, hooks/, tools/, *.sh, *.py, *.js, *.mjs) — скачать и
      выполнить, адрес вне списка, /dev/tcp, base64 -d, nc/socat, osascript «do shell script», чтение Связки,
      дописывание в профиль оболочки, алиас claude, launchctl load, crontab;
  инструкции (*.md: CLAUDE.md, память, навыки, роли, правила) — фразы внедрения на русском и английском,
      скрытые символы Юникода, длинный base64, «скачай и выполни», роль с bypassPermissions, рост файла > 50 КБ;
  policy.toml — расширение привилегий (новые записи в [private], [coordinators], [sandbox_write], [agent_extra], always);
  везде — похожее на ключ (Anthropic, GitHub, AWS, Google, Slack, Hugging Face, приватный ключ).

Слитый выпуск (metis-0209, вариант А; решено владельцем 23.10): файл, побайтно равный файлу plugins/pantheon или
plugins/guard из коммита, который слил владелец (SHA из STATE/logs/merge.jsonl с событием merged или из
STATE/owner-log/merge-approve.log — Touch ID), и этот коммит лежит в origin/main клона agent-kit
(~/.claude/plugins/marketplaces/agent-kit), проходит без флагов и без карточки; имя файла должно совпасть с именем
файла выпуска. Не слит, чужая ветка, отличие в байт, другое имя, удаление, ключ в тексте — флаги как раньше.
Пути — только от HOME; переменных окружения проверка не читает.

Запуск:  config-check.py --repo ~/.claude --staged [--explain]     правки в индексе против HEAD
         config-check.py --repo ~/.claude --range A B [--explain]   правки между коммитами A и B
Вывод — JSON {"flags": [{"file", "kind", "reason"}], "files": {...}, "card": {...}}; код 0. С --explain для каждого
файла с флагом — что он делает, сколько строк, кто его изменил (сессия Claude по её записи в ~/.claude/projects:
папка, время, инструмент; «не сессия Claude» — главный признак атаки, как у Cisco: правку сделала программа), и
текст карточки для доски с советом. Сбой самой проверки — код 3 (вызывающий держит всё).
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

MD_GROWTH = 50_000
URL_HOSTS = ("github.com", "githubusercontent.com", "api.github.com", "anthropic.com", "claude.ai", "claude.com",
             "localhost", "127.0.0.1", "brew.sh", "githubassets.com", "npmjs.org", "pypi.org", "pythonhosted.org")
KNOWN_HOOK_PLACES = ("~/.claude/hooks/", "$HOME/.claude/hooks/", "~/.claude/sync.sh", "$HOME/.claude/sync.sh",
                     "~/.claude/statusline.sh", "$HOME/.claude/statusline.sh", "~/.claude/tools/", "$HOME/.claude/tools/",
                     "${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT", "~/.local/bin/pantheon", "$HOME/.local/bin/pantheon",
                     "~/.claude/plugins/marketplaces/agent-kit/", "$HOME/.claude/plugins/marketplaces/agent-kit/")
EXEC_SETTINGS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper", "fileSuggestion")
RISKY_ENV = re.compile(r"^(ANTHROPIC_BASE_URL|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|.*_PROXY|NODE_OPTIONS|"
                       r"NODE_EXTRA_CA_CERTS|DYLD_.*|LD_PRELOAD|PATH|PYTHONPATH|PYTHONSTARTUP|GUARD_OFF|"
                       r"CLAUDE_CODE_USE_.*|OTEL_EXPORTER_.*|BASH_ENV|ZDOTDIR)$", re.I)
BROAD_ALLOW = re.compile(r"^(Bash|Read|Edit|Write|WebFetch|MultiEdit|NotebookEdit)(\((\*|\*\*|\* \*|:\*)\))?$|"
                         r"^Bash\((curl|wget|sh|bash|zsh|eval|python3?|node|osascript|nc|security)\b", re.I)
DANGER_CMD = [
    (re.compile(r"\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?(ba|z)?sh\b"), "скачивает и сразу выполняет"),
    (re.compile(r"/dev/tcp/"), "соединение через /dev/tcp"),
    (re.compile(r"\bbase64\s+(-d|-D|--decode)\b"), "раскодирует base64 (прячет код)"),
    (re.compile(r"\bnc\s+-|\bncat\b|\bsocat\b"), "сетевой канал (nc/socat)"),
    (re.compile(r"osascript\b.*do shell script", re.I), "osascript выполняет команду"),
    (re.compile(r"\bsecurity\s+(find-generic-password|find-internet-password|dump-keychain|export)\b"), "читает Связку ключей"),
    (re.compile(r">>?\s*\S*\.(zshrc|bashrc|zprofile|bash_profile|profile)\b"), "дописывает профиль оболочки"),
    (re.compile(r"\balias\s+claude\b"), "подменяет команду claude"),
    (re.compile(r"\blaunchctl\s+(load|bootstrap)\b"), "ставит фоновую задачу launchd"),
    (re.compile(r"\bcrontab\b"), "ставит задачу cron"),
]
INJECTION = [
    re.compile(r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b.{0,20}\b(instructions?|rules?|prompts?)", re.I),
    re.compile(r"(игнорируй|забудь|не\s+учитывай).{0,30}(предыдущ|прежн|все|выше).{0,20}(инструкц|правил|указани)", re.I),
    re.compile(r"\b(do\s+not|don't|never)\s+(tell|inform|mention|notify|show)\b.{0,20}\b(the\s+)?(user|owner|human)", re.I),
    re.compile(r"without\s+(telling|informing|notifying)\s+the\s+(user|owner)", re.I),
    re.compile(r"не\s+(говори|сообщай|показывай|упоминай)\b.{0,20}(пользовател|владельц|человек)", re.I),
    re.compile(r"без\s+ведома\s+(пользовател|владельц)", re.I),
    re.compile(r"</?\s*(system|system-reminder|instructions)\s*>|BEGIN\s+SYSTEM|\bsystem\s+prompt\s*:", re.I),
    re.compile(r"\byou\s+are\s+now\b|\bnew\s+instructions\s*:|\bjailbreak\b", re.I),
]
HIDDEN = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
B64 = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
SECRETS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "ключ Anthropic"),
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"), "токен GitHub"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "ключ AWS"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "ключ Google"),
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"), "токен Slack"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "токен Hugging Face"),
    (re.compile(r"-----BEGIN (RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"), "приватный ключ"),
]
EXEC_EXT = (".sh", ".py", ".js", ".mjs", ".cjs", ".ts", ".zsh", ".bash")
# Файлы, которые меняют саму синхронизацию; безобидные — уходят сами; всё незнакомое — в карантин (по умолчанию —
# проверить нечем, значит спросить; находка проверки безопасности 14.10)
SYNC_RULES = {".gitignore": "меняет, какие файлы ~/.claude уходят на GitHub (можно открыть записи сессий, а в них ключи)",
              "sessync.conf": "меняет синхронизацию сессий — куда уходит ваша переписка"}
HARMLESS = {"keybindings.json"}
EXEC_FILES = ("sync.sh", "statusline.sh", "bootstrap.sh")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True).stdout


def show(repo, rev, path):
    """Содержимое файла в ревизии (rev '' — индекс); None — файла нет."""
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def show_bytes(repo, rev, path):
    r = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


RELEASE_DIRS = ("plugins/pantheon", "plugins/guard")
RELEASE_MAX = 300  # сколько последних слитых коммитов сверять
_RELEASE = None


def _home():
    return os.path.expanduser("~")


def owner_merged_shas():
    """SHA коммитов, которые слил владелец: merge.jsonl (merged) и merge-approve.log (Touch ID), новые первыми."""
    state = os.path.join(_home(), ".local", "state", "pantheon")
    found = []
    try:
        for line in open(os.path.join(state, "logs", "merge.jsonl"), encoding="utf-8").read().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("event") == "merged" and isinstance(d.get("sha"), str) \
                    and str(d.get("repo", "")).lower().endswith("/agent-kit"):
                found.append(d["sha"])
    except (OSError, UnicodeDecodeError):
        pass
    try:
        for line in open(os.path.join(state, "owner-log", "merge-approve.log"), encoding="utf-8").read().splitlines():
            m = re.match(r"^\S+(?: \S+)? merge-approve (\S+)#\d+ ([0-9a-f]{40})$", line.strip())
            if m and m.group(1).lower().endswith("/agent-kit"):
                found.append(m.group(2))
    except (OSError, UnicodeDecodeError):
        pass
    out = []
    for sha in reversed(found):
        if re.fullmatch(r"[0-9a-f]{40}", sha) and sha not in out:
            out.append(sha)
    return out[:RELEASE_MAX]


def release_blobs():
    """{(blob, имя файла)} файлов выпуска pantheon/guard из слитых владельцем коммитов, лежащих в main agent-kit."""
    global _RELEASE
    if _RELEASE is not None:
        return _RELEASE
    _RELEASE = set()
    clone = os.path.join(_home(), ".claude", "plugins", "marketplaces", "agent-kit")
    shas = owner_merged_shas()
    if not shas or not os.path.isdir(clone):
        return _RELEASE
    main = None
    for ref in ("origin/main", "main"):
        if subprocess.run(["git", "-C", clone, "rev-parse", "-q", "--verify", ref + "^{commit}"],
                          capture_output=True).returncode == 0:
            main = ref
            break
    if main is None:
        return _RELEASE
    for sha in shas:
        if subprocess.run(["git", "-C", clone, "merge-base", "--is-ancestor", sha, main], capture_output=True).returncode:
            continue  # не в main (чужая ветка) или коммита нет в клоне
        r = subprocess.run(["git", "-C", clone, "ls-tree", "-r", "-z", sha, "--", *RELEASE_DIRS], capture_output=True)
        if r.returncode:
            continue
        for ent in r.stdout.decode("utf-8", "replace").split("\0"):
            meta, _, name = ent.partition("\t")
            f = meta.split()
            if len(f) == 3 and f[1] == "blob":
                _RELEASE.add((f[2], os.path.basename(name)))
    return _RELEASE


def is_released(path, data):
    return data is not None and (blob_id(data), os.path.basename(path)) in release_blobs()


def changed(repo, staged, a=None, b=None):
    args = ["diff", "--cached", "--name-status", "-z", "--no-renames"] if staged else \
        ["diff", "--name-status", "-z", "--no-renames", a, b]
    parts = git(repo, *args).decode("utf-8", "replace").split("\0")
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2) if parts[i]]


def added_lines(old, new):
    o, n = (old or "").splitlines(), (new or "").splitlines()
    out = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            out.extend(n[j1:j2])
    return out


def url_hosts(line):
    return [h.lower() for h in re.findall(r"https?://([^/\s\"'`)>\]]+)", line)]


def foreign_host(h):
    h = h.split("@")[-1].split(":")[0]
    return not any(h == x or h.endswith("." + x) for x in URL_HOSTS)


def hook_commands(cfg):
    out = set()
    for groups in (cfg.get("hooks") or {}).values():
        for g in groups or []:
            for h in (g or {}).get("hooks") or []:
                if isinstance(h, dict):
                    out.add(str(h.get("command") or h.get("url") or h))
    sl = cfg.get("statusLine")
    if isinstance(sl, dict) and sl.get("command"):
        out.add(str(sl["command"]))
    return out


def risky_command(cmd):
    reasons = [why for rx, why in DANGER_CMD if rx.search(cmd)]
    reasons += [f"адрес вне списка ({h})" for h in url_hosts(cmd) if foreign_host(h)]
    if re.search(r"(/private)?/tmp/|/var/folders/", cmd):
        reasons.append("запускает файл из временной папки")
    if not any(p in cmd for p in KNOWN_HOOK_PLACES):
        reasons.append("файл вне известных мест (~/.claude/hooks, tools, плагины agent-kit, pantheon)")
    return reasons


def check_settings(path, old, new):
    flags = []
    if new is None:
        return [("settings", "файл настроек удалён — вместе с ним уходят запреты")]
    try:
        n = json.loads(new)
        o = json.loads(old) if old else {}
    except ValueError:
        return [("settings", "битый JSON — на других компьютерах Claude Code не прочитает настройки")]
    if not isinstance(n, dict):
        return [("settings", "настройки — не объект JSON")]
    for cmd in sorted(hook_commands(n) - hook_commands(o)):
        flags.append(("code", f"новый или изменённый хук или строка статуса: {cmd[:120]}"))
        for why in risky_command(cmd):
            flags.append(("danger", f"хук: {why}: {cmd[:120]}"))
    np, op = n.get("permissions") or {}, o.get("permissions") or {}
    if np.get("defaultMode") == "bypassPermissions" and op.get("defaultMode") != "bypassPermissions":
        flags.append(("settings", "режим bypassPermissions по умолчанию"))
    if n.get("disableAllHooks") and not o.get("disableAllHooks"):
        flags.append(("settings", "disableAllHooks — выключены все хуки, и guard тоже"))
    if n.get("skipDangerousModePermissionPrompt") and not o.get("skipDangerousModePermissionPrompt"):
        flags.append(("settings", "выключено предупреждение об опасном режиме"))
    gone = sorted(set(op.get("deny") or []) - set(np.get("deny") or []))
    if gone:
        flags.append(("settings", f"сняты запреты deny: {', '.join(gone[:5])}"))
    for rule in sorted(set(np.get("allow") or []) - set(op.get("allow") or [])):
        if BROAD_ALLOW.search(str(rule)):
            flags.append(("settings", f"широкое разрешение allow: {rule}"))
    ne, oe = n.get("env") or {}, o.get("env") or {}
    for k in sorted(ne):
        if RISKY_ENV.match(k) and ne.get(k) != oe.get(k):
            flags.append(("settings", f"переменная окружения {k} — меняет адрес API, прокси, загрузку кода или защиту"))
    for k in EXEC_SETTINGS:
        if n.get(k) and n.get(k) != o.get(k):
            flags.append(("settings", f"{k} запускает команду: {str(n.get(k))[:120]}"))
    npl, opl = n.get("enabledPlugins") or {}, o.get("enabledPlugins") or {}
    for p in ("guard@agent-kit", "pantheon@agent-kit"):
        if opl.get(p) and not npl.get(p):
            flags.append(("settings", f"выключен плагин {p}"))
    new_markets = sorted(set(n.get("extraKnownMarketplaces") or {}) - set(o.get("extraKnownMarketplaces") or {}))
    if new_markets:
        flags.append(("settings", f"новый маркетплейс плагинов: {', '.join(new_markets)}"))
    return flags


def check_exec(path, lines, deleted=False):
    flags = [("code", "удалён код, который запускается сам" if deleted else "меняется код, который сам запускается на каждом Mac")]
    for line in lines:
        for rx, why in DANGER_CMD:
            if rx.search(line):
                flags.append(("danger", f"{why}: {line.strip()[:120]}"))
        for h in url_hosts(line):
            if foreign_host(h):
                flags.append(("danger", f"адрес вне списка ({h}): {line.strip()[:120]}"))
    return flags


def check_instructions(path, old, new, lines):
    flags = []
    for line in lines:
        if any(rx.search(line) for rx in INJECTION):
            flags.append(("injection", f"похоже на внедрённую инструкцию: {line.strip()[:120]}"))
        if HIDDEN.search(line):
            flags.append(("injection", "скрытые символы Юникода (невидимый текст)"))
        if B64.search(line):
            flags.append(("injection", "длинный блок base64"))
        if DANGER_CMD[0][0].search(line):
            flags.append(("injection", f"«скачай и выполни»: {line.strip()[:120]}"))
        if re.match(r"^\s*permissionMode:\s*bypassPermissions\b", line):
            flags.append(("injection", "роль с permissionMode: bypassPermissions"))
        if path.startswith("agents/") and re.match(r"^\s*(?:-\s*)?(?:command|args|url):", line):
            flags.append(("code", f"команда в шапке роли (hooks или mcpServers) — запускается сама: {line.strip()[:120]}"))
    if new is not None and len(new.encode()) - len((old or "").encode()) > MD_GROWTH:
        flags.append(("injection", f"файл вырос больше чем на {MD_GROWTH // 1000} КБ за раз"))
    return flags


def check_policy(old, new):
    try:
        import tomllib
    except ImportError:
        return [("policy", "policy.toml изменён, а проверить нечем (нужен Python 3.11+)")]
    try:
        n, o = tomllib.loads(new or ""), tomllib.loads(old or "")
    except ValueError:
        return [("policy", "битый policy.toml")]

    def items(d, key):
        v = d.get(key)
        if isinstance(v, dict):
            return {(k, str(x)) for k, xs in v.items() for x in (xs if isinstance(xs, list) else [xs])}
        return {("", str(x)) for x in (v if isinstance(v, list) else [v] if v else [])}

    flags = []
    for key in ("private", "coordinators", "sandbox_write", "agent_extra", "always"):
        grown = sorted(items(n, key) - items(o, key))
        if grown:
            flags.append(("policy", f"расширены привилегии [{key}]: {', '.join(f'{a} {b}'.strip() for a, b in grown[:4])}"))
    return flags


def check_file(path, old, new):
    base = os.path.basename(path)
    lines = added_lines(old, new) if new is not None else []
    flags = []
    for line in lines:
        for rx, why in SECRETS:
            if rx.search(line):
                flags.append(("secret", f"похоже на ключ: {why}"))
    if base in ("settings.json", "settings.local.json"):
        flags += check_settings(path, old, new)
    elif path == "pantheon/policy.toml" or base == "policy.toml":
        flags += check_policy(old, new) if new is not None else [("policy", "policy.toml удалён")]
    elif base in EXEC_FILES or path.startswith(("hooks/", "tools/")) or base.endswith(EXEC_EXT):
        flags += check_exec(path, lines, deleted=new is None)
    elif base.endswith(".md") or path.startswith(("skills/", "agents/", "rules/", "commands/", "output-styles/",
                                                  "agent-memory/")):
        flags += check_instructions(path, old, new, lines)
    elif base in SYNC_RULES:
        flags.append(("settings", SYNC_RULES[base]))
    elif base not in HARMLESS:
        flags.append(("settings", "незнакомый тип файла — проверить его содержимое нечем"))
    seen, out = set(), []
    for kind, reason in flags:
        if (kind, reason) not in seen:
            seen.add((kind, reason))
            out.append({"file": path, "kind": kind, "reason": reason})
    return out


FILE_ROLE = [
    ("sync.sh", "синхронизирует ~/.claude между Mac; запускается в начале каждой сессии"),
    ("statusline.sh", "рисует строку статуса Claude Code; запускается при каждом обновлении экрана"),
    ("bootstrap.sh", "ставит нужное на новом Mac"),
    ("settings.json", "главные настройки Claude Code: разрешения, запреты, хуки, плагины"),
    ("settings.local.json", "настройки Claude Code этого Mac"),
    ("hooks/", "хук Claude Code: запускается сам на событиях каждой сессии"),
    ("tools/", "инструмент, который вызывают сессии и хуки"),
    ("pantheon/policy.toml", "привилегии guard: кто правит защиты, у кого доступ к личному"),
    ("agents/", "роль агента"),
    ("skills/", "навык — инструкция для агентов"),
    ("rules/", "правило для сессий"),
    (".gitignore", "список того, что из ~/.claude уходит на GitHub"),
    ("sessync.conf", "настройка синхронизации сессий"),
    ("commands/", "команда-заготовка"),
    ("CLAUDE.md", "ваши глобальные правила: грузятся в каждую сессию"),
    ("projects/", "автопамять Claude для папки: грузится в сессии там"),
]
KIND_WORD = {"code": "код", "danger": "опасное", "injection": "похоже на внедрение", "secret": "ключ",
             "settings": "настройки", "policy": "привилегии"}


def file_role(path):
    for key, role in FILE_ROLE:
        if path == key or path.startswith(key) or os.path.basename(path) == key:
            return role
    return "файл конфигурации Claude Code"


def numstat(repo, staged, a=None, b=None):
    args = ["diff", "--cached", "--numstat", "-z"] if staged else ["diff", "--numstat", "-z", a, b]
    out = {}
    for rec in git(repo, *args).decode("utf-8", "replace").split("\0"):
        parts = rec.split("\t")
        if len(parts) == 3:
            out[parts[2]] = (parts[0], parts[1])
    return out


def who_changed(abs_path, days=14):
    """Кто последним правил файл — по записям сессий в ~/.claude/projects.
    Смотрятся только записи, которые менялись не раньше самого файла: если после сессии файл правил кто-то
    ещё (программа, скрипт), сессия уже не последний автор — и ответ «не сессия Claude» верный.
    Правка инструментом (Edit, Write, MultiEdit, NotebookEdit) важнее упоминания файла в команде Bash.
    → {"sid", "title", "cwd", "ts", "tool", "sub", "strong"} или None."""
    import glob
    import time
    root = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    tilde = abs_path.replace(os.path.expanduser("~"), "~", 1)
    try:
        since = max(time.time() - days * 86400, os.path.getmtime(abs_path) - 60)
    except OSError:
        since = time.time() - days * 86400  # файл удалён — ищем за весь срок
    best = {True: None, False: None}
    for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(f) < since:
                continue
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        custom, ai, hits = "", "", []
        with fh:
            for line in fh:
                if '"custom-title"' in line or '"ai-title"' in line:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    custom = d.get("customTitle") or custom   # название, которое дали вы, главнее
                    ai = d.get("aiTitle") or ai
                    continue
                if abs_path not in line and tilde not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                content = (d.get("message") or {}).get("content")
                if d.get("type") != "assistant" or not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    inp, name = c.get("input") or {}, c.get("name")
                    strong = name in ("Edit", "Write", "MultiEdit", "NotebookEdit") and abs_path in (
                        inp.get("file_path"), inp.get("notebook_path"))
                    weak = name == "Bash" and (abs_path in str(inp.get("command")) or tilde in str(inp.get("command")))
                    if strong or weak:
                        hits.append({"sid": str(d.get("sessionId") or "")[:8], "cwd": d.get("cwd") or "",
                                     "ts": str(d.get("timestamp") or ""), "tool": name, "sub": bool(d.get("agentId")),
                                     "strong": strong})
        for h in hits:
            h["title"] = custom or ai
            cur = best[h["strong"]]
            if cur is None or h["ts"] > cur["ts"]:
                best[h["strong"]] = h
    return best[True] or best[False]


def local_time(ts):
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%d.%m %H:%M")
    except ValueError:
        return ts


def explain(repo, flags, stats):
    files = {}
    for fl in flags:
        files.setdefault(fl["file"], {"kinds": [], "reasons": []})
        files[fl["file"]]["kinds"].append(fl["kind"])
        files[fl["file"]]["reasons"].append(fl["reason"])
    home = os.path.expanduser("~")
    unknown, rows, sessions = [], [], {}
    for path, info in files.items():
        w = who_changed(os.path.join(repo, path))
        add, rem = stats.get(path, ("?", "?"))
        info.update(role=file_role(path), added=add, removed=rem)
        if w:
            name = f"«{w['title']}» ({w['sid']})" if w["title"] else w["sid"]
            how = w["tool"] if w["strong"] else "команда Bash"
            info["who"] = (f"сессия Claude {name}{', субагент' if w['sub'] else ''} в {w['cwd'].replace(home, '~')}, "
                           f"{local_time(w['ts'])}, {how}")
            sessions[path] = (name, f"{local_time(w['ts'])}, {how}")
        else:
            info["who"] = "не сессия Claude: за 14 дней ни одна сессия этот файл не правила — правку сделала программа или скрипт"
            info["who"] = ("не сессия Claude: после последней правки сессией этот файл менял кто-то другой "
                           "(программа или скрипт)") if os.path.exists(os.path.join(repo, path)) else info["who"]
            unknown.append(path)
        rows.append((path, info, "; ".join(dict.fromkeys(info["reasons"]))[:300]))
    # одна сессия на все файлы — «кто» один раз сверху, а не в каждой строке
    names = {n for n, _ in sessions.values()}
    common = next(iter(names)) if len(names) == 1 and len(sessions) == len(files) else None
    parts = []
    for path, info, why in rows:
        who = f"когда: {sessions[path][1]}" if common else f"кто: {info['who']}"
        parts.append(f"- **`{path}`** — {info['role']} · +{info['added']} −{info['removed']} строк\n"
                     f"    - {who}\n    - почему спрашиваю: {why}")
    bad = {k for f in files.values() for k in f["kinds"]} & {"danger", "injection", "secret"}
    if bad or unknown:
        advice = ("**Совет: НЕ отправлять**, пока не разберётесь. "
                  + ("Есть признаки опасного кода или внедрения. " if bad else "")
                  + ("Файл изменила не сессия Claude — так выглядела атака Cisco (правку внёс установочный скрипт пакета). " if unknown else "")
                  + "Сомневаетесь — «Откатить»: копия правки останется в ветке quarantine на GitHub.")
        recommend = "Откатить правку"
    else:
        advice = ("**Совет:** просили меня или Метиду менять эти файлы — «Отправить». Не просили — «Откатить».")
        recommend = "Отправить на другие Mac"
    n = len(files)
    question = (f"Правки `~/.claude` на этом Mac ({n}) не ушли на другие компьютеры — ждут вашего решения."
                + (f" Кто: сессия Claude {common} — все правки." if common else "")
                + "\n\n" + "\n".join(parts) + "\n\n" + advice
                + "\n\nПосмотреть разницу: `cd ~/.claude && git diff -- " + " ".join(files) + "`")
    kinds = sorted({KIND_WORD.get(k, k) for f in files.values() for k in f["kinds"]})
    title = f"Карантин правок ~/.claude: {', '.join(list(files)[:2])}{' и др.' if n > 2 else ''} ({', '.join(kinds)})"
    return files, {"title": title[:150], "question": question[:2500], "recommend": recommend,
                   "options": ["Отправить на другие Mac", "Откатить правку", "Пока держать"]}


def main(argv):
    repo = os.path.expanduser(argv[argv.index("--repo") + 1]) if "--repo" in argv else os.getcwd()
    if "--range" in argv:
        i = argv.index("--range")
        a, b = argv[i + 1], argv[i + 2]
        files, old_rev, new_rev = changed(repo, False, a, b), a, b
    else:
        files, old_rev, new_rev = changed(repo, True), "HEAD", ""
    flags = []
    for status, path in files:
        old = show(repo, old_rev, path) if status != "A" else None
        new = show(repo, new_rev, path) if status != "D" else None
        got = check_file(path, old, new)
        # слитый выпуск: побайтно равный файл — без флагов, кроме ключа (metis-0209)
        if got and status != "D" and is_released(path, show_bytes(repo, new_rev, path)):
            got = [f for f in got if f["kind"] == "secret"]
        flags += got
    out = {"flags": flags}
    if "--explain" in argv and flags:
        stats = numstat(repo, "--range" not in argv, *( [old_rev, new_rev] if "--range" in argv else []))
        out["files"], out["card"] = explain(os.path.realpath(repo), flags, stats)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # сбой проверки — вызывающий держит всё и пишет тревогу
        print(json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}, ensure_ascii=False))
        sys.exit(3)
