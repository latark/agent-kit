#!/usr/bin/env python3
"""pantheon-setup (bin/pantheon-setup + lib/setup.py + lib/platform_macos.py): проба установки целиком в изоляции.

Корень tempfile.mkdtemp(prefix="tmp-setup-") в $TMPDIR; HOME, PANTHEON_HOME, PANTHEON_STATE — в нём; PATH — папка
заглушек + /usr/bin:/bin (git настоящий). Все внешние программы — заглушки (uv, curl, claude, gh, brew,
terminal-notifier, git-crypt, security), каждая пишет argv в журнал. «GitHub» резервной копии — голый репозиторий
в корне пробы, «Связка ключей» — файл; настоящие GitHub и Связка ключей не трогаются. Настоящие ~/.claude/settings.json, ~/ai/pantheon и ~/.gitconfig
сверяются по хешу до и после.

Запуск: python3 -I plugins/pantheon/tests/test_setup.py  (код выхода 0 — все прошли)
"""
import atexit
import base64
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN, LIB = os.path.join(ROOT, "bin"), os.path.join(ROOT, "lib")
SETUP_BIN = os.path.join(BIN, "pantheon-setup")
CLONE = subprocess.run(["git", "-C", ROOT, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
REAL_HOME = os.path.expanduser("~")
results = []
roots = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok else f"  [{detail}]"))


def sha(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def real_snapshot():
    """Хеши настоящих файлов владельца (снимок до подмены HOME)."""
    pan = os.path.join(REAL_HOME, "ai", "pantheon")
    try:
        top = sorted(os.listdir(pan))
    except OSError:
        top = None
    return (sha(os.path.join(REAL_HOME, ".claude", "settings.json")), sha(os.path.join(REAL_HOME, ".gitconfig")), top)


def tree_hash(path):
    h = hashlib.sha256()
    for d, dirs, files in os.walk(path):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(d, f)
            h.update(os.path.relpath(p, path).encode())
            h.update(sha(p).encode() if sha(p) else b"-")
    return h.hexdigest()


def sh_file(path, body):
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n" + body)
    os.chmod(path, 0o755)


def uv_body(py):
    return ('echo "uv $*" >> "$STUB_LOG"\n'
            'if [ "$1 $2" = "python find" ]; then echo "' + py + '"; fi\nexit 0\n')


GC_KEY = "FAKEKEY0476zzSECRET"  # «ключ» заглушки git-crypt: ни он, ни его base64 не должны попасть в вывод
GC_KEY_B64 = base64.b64encode(GC_KEY.encode()).decode()
CRYPT_HEADER = b"\x00GITCRYPT\x00"


def new_root(with_uv=False, with_claude=True, with_notifier=False, with_crypt=True):
    """→ (корень, env, папка заглушек). Пантеона в корне ещё нет."""
    root = os.path.realpath(tempfile.mkdtemp(prefix="tmp-setup-"))
    roots.append(root)
    home = os.path.join(root, "home")
    stubs = os.path.join(root, "stubs")
    os.makedirs(home)
    os.makedirs(stubs)
    log = os.path.join(root, "stub.log")
    open(log, "w").close()
    uv_stub = uv_body(PY311)
    if with_uv:
        sh_file(os.path.join(stubs, "uv"), uv_stub)
    # curl отдаёт «установщик uv», который кладёт заглушку uv в HOME/.local/bin
    sh_file(os.path.join(stubs, "curl"),
            'echo "curl $*" >> "$STUB_LOG"\n'
            "cat <<'INSTALLER'\n"
            'echo "uv-installer UV_NO_MODIFY_PATH=$UV_NO_MODIFY_PATH" >> "$STUB_LOG"\n'
            'mkdir -p "$HOME/.local/bin"\n'
            "cat > \"$HOME/.local/bin/uv\" <<'UV'\n#!/bin/sh\n" + uv_stub + "UV\n"
            'chmod +x "$HOME/.local/bin/uv"\nINSTALLER\n')
    if with_claude:
        sh_file(os.path.join(stubs, "claude"),
                'echo "claude $*" >> "$STUB_LOG"\n'
                'case "$1 $2 $3" in\n'
                '  "plugin marketplace list") [ -e "$HOME/.claude/plugins/marketplaces/agent-kit" ] && echo "agent-kit";;\n'
                '  "plugin marketplace add")\n'
                '    mkdir -p "$HOME/.claude/plugins/marketplaces"\n'
                '    ln -s "' + CLONE + '" "$HOME/.claude/plugins/marketplaces/agent-kit";;\n'
                'esac\nexit 0\n')
    # gh repo create заводит «GitHub» — голый репозиторий в корне пробы — и печатает его адрес, как настоящий gh
    sh_file(os.path.join(stubs, "gh"),
            'echo "gh $*" >> "$STUB_LOG"\n'
            'if [ "$1 $2" = "auth status" ]; then [ "$GH_LOGGED" = "1" ]; exit $?; fi\n'
            'if [ "$1 $2" = "repo create" ]; then\n'
            '  [ "$FAIL_CMD" = "gh repo" ] && { echo "gh repo create: заглушка упала" >&2; exit 1; }\n'
            '  git init -q --bare "$GH_REMOTE" || exit 1\n  echo "$GH_URL"\nfi\nexit 0\n')
    # git-crypt: init ставит фильтр в .git/config, clean «шифрует» (заголовок GITCRYPT + base64 текста, открытого
    # текста в объекте нет; GC_NOENC=1 — фильтр отдаёт текст как есть)
    if with_crypt:
        sh_file(os.path.join(stubs, "git-crypt"),
                'case "$1" in\n'
                "  clean) if [ \"$GC_NOENC\" = \"1\" ]; then cat; else printf '\\000GITCRYPT\\000'; base64; fi; exit 0;;\n"
                '  smudge) tail -c +11 | base64 -D; exit 0;;\n  diff) tail -c +11 "$2" | base64 -D; exit 0;;\nesac\n'
                'echo "git-crypt $*" >> "$STUB_LOG"\n'
                '[ "$FAIL_CMD" = "git-crypt $1" ] && { echo "git-crypt $1: заглушка упала" >&2; exit 1; }\n'
                'case "$1" in\n'
                '  init) git config filter.git-crypt.clean "git-crypt clean" && '
                'git config filter.git-crypt.smudge "git-crypt smudge" && git config filter.git-crypt.required true '
                '&& mkdir -p .git/git-crypt/keys;;\n'
                '  export-key) printf "%s" "$GC_KEY" > "$2";;\nesac\nexit 0\n')
    # Связка ключей — файл KC_FILE; настоящий /usr/bin/security в пробе не вызывается никогда
    sh_file(os.path.join(stubs, "security"),
            # в журнал — только argv; команда из stdin (`security -i`) в журнал идёт одним глаголом, без аргументов,
            # а целиком — в «Связку» (KC_FILE): так тест видит, что ключ дошёл, и что в argv его не было
            'echo "security $*" >> "$STUB_LOG"\n'
            'cmd="$*"\n'
            'if [ "$1" = "-i" ]; then read -r cmd; echo "security ${cmd%% *}" >> "$STUB_LOG"; fi\n'
            'verb="${cmd%% *}"\n'
            '[ "$FAIL_CMD" = "security $verb" ] && { echo "security: заглушка упала" >&2; exit 1; }\n'
            'case "$verb" in\n'
            '  find-generic-password) [ -s "$KC_FILE" ]; exit $?;;\n'
            '  add-generic-password) [ -s "$KC_FILE" ] && { echo "already exists" >&2; exit 45; }; '
            '[ "$SEC_SILENT" = "1" ] && exit 0; echo "$cmd" >> "$KC_FILE";;\nesac\nexit 0\n')
    for n in ("brew",) + (("terminal-notifier",) if with_notifier else ()):
        sh_file(os.path.join(stubs, n), f'echo "{n} $*" >> "$STUB_LOG"\nexit 0\n')
    env = {"PATH": stubs + ":/usr/bin:/bin", "HOME": home, "PANTHEON_HOME": os.path.join(home, "ai", "pantheon"),
           "PANTHEON_STATE": os.path.join(root, "state"), "PANTHEON_VIEW": os.path.join(root, "view"),
           "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": root, "STUB_LOG": log, "GH_LOGGED": "1",
           "LANG": "en_US.UTF-8", "GC_KEY": GC_KEY, "KC_FILE": os.path.join(root, "keychain"),
           "GH_REMOTE": os.path.join(root, "remote.git"), "GH_URL": "file://" + os.path.join(root, "remote.git")}
    return root, env, stubs


def prep_pan(env, history=False):
    """Готовый Пантеон без копии (для `--add backup`): файлы, git init; history — ещё коммит открытым текстом."""
    pan = env["PANTHEON_HOME"]
    os.makedirs(os.path.join(pan, "directions", "x"))
    for rel, text in (("board.md", "доска\n"), ("directions/x/STATUS.md", "SECRET-PLAINTEXT-0476\n"),
                      (".gitignore", "*.tmp\n")):
        with open(os.path.join(pan, rel), "w", encoding="utf-8") as fh:
            fh.write(text)
    subprocess.run(["git", "-C", pan, "init", "-q"], check=True, env=env)
    if history:
        g = ["git", "-C", pan, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["add", "-A"], check=True, env=env)
        subprocess.run(g + ["commit", "-q", "-m", "старое"], check=True, env=env)
    return pan


def git_out(env, repo, *args):
    return subprocess.run(["git", "-C", repo, *args], env=env, capture_output=True, text=True).stdout.strip()


def remote_objects(env):
    """Все объекты «GitHub» байтами (для поиска открытого текста)."""
    r = subprocess.run(["git", "-C", env["GH_REMOTE"], "cat-file", "--batch-all-objects", "--batch"], env=env,
                       capture_output=True)
    return r.stdout


def leaked_key_files(root, env):
    """Файлы пробы, где лежит ключ, кроме журнала заглушек и «Связки» (туда его кладёт сама заглушка)."""
    bad = []
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            if p in (env["STUB_LOG"], env["KC_FILE"]):
                continue
            try:
                data = open(p, "rb").read()
            except OSError:
                continue
            if GC_KEY.encode() in data or GC_KEY_B64.encode() in data:
                bad.append(p)
    return bad


def setup(env, stdin="", *args):
    return subprocess.run(["/bin/bash", SETUP_BIN, *args], env=env, input=stdin, capture_output=True, text=True,
                          timeout=300)


def log_of(env):
    return open(env["STUB_LOG"], encoding="utf-8").read().splitlines()


def main():
    before = real_snapshot()

    # --- 1. полный проход: uv нет (ставит заглушка curl), без Codex, gh вошёл, на setup-git «нет» ---------------
    root, env, _ = new_root()
    r = setup(env, "нет\n", "--no-codex")
    out = r.stdout + r.stderr
    pan = env["PANTHEON_HOME"]
    lg = log_of(env)
    open(os.path.join(root, "out.txt"), "w").write(out)
    check("полный проход: код 0", r.returncode == 0, out[-1500:])
    check("нет uv — его ставит установщик (curl, затем uv python install/find)",
          any(x.startswith("curl ") and "astral.sh/uv/install.sh" in x for x in lg)
          and "uv python install 3.14" in lg and "uv python find 3.14" in lg, lg)
    check("пустой Пантеон: .git и файлы шаблона",
          os.path.isdir(os.path.join(pan, ".git")) and all(os.path.exists(os.path.join(pan, f)) for f in
                                                           ("board.md", "decisions.md", "directions.toml", "schema.md")),
          os.listdir(pan) if os.path.isdir(pan) else "нет папки")
    agents = os.path.join(env["HOME"], ".claude", "agents")
    names = sorted(os.listdir(agents)) if os.path.isdir(agents) else []
    # hephaestus-<направление> собирается по реестру направлений; в пустом Пантеоне направлений нет
    check("роли собраны в HOME/.claude/agents (argus, dev-*, hq, workshop)",
          all(n in names for n in ("argus.md", "dev-sonnet.md", "hq.md", "workshop.md", "domain-coordinator.md")), names)
    cfg = os.path.join(env["PANTHEON_STATE"], "config.toml")
    cfg_text = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
    check("python записан в config.toml, исполнители = [claude]",
          f'python = "{PY311}"' in cfg_text and 'set = ["claude"]' in cfg_text, cfg_text)
    inst = [x for x in lg if x.startswith("claude plugin install")]
    check("три claude plugin install", inst == ["claude plugin install guard@agent-kit",
                                                "claude plugin install pantheon@agent-kit",
                                                "claude plugin install project-tools@agent-kit"], inst)
    check("claude plugin marketplace add вызван", any(x.startswith("claude plugin marketplace add ") for x in lg), lg)
    check("gh auth setup-git НЕ вызван при ответе «нет»", not any("gh auth setup-git" in x for x in lg), lg)
    check("--no-codex: Codex не вызывался, строка «Codex: пропуск»",
          "[пропуск] Codex" in out and not any("codex" in x for x in lg), out[-600:])
    check("terminal-notifier: brew install и инструкция уведомлений",
          "brew install terminal-notifier" in lg and "Системные настройки" in out, lg)
    check("проверка личных следов без файла маркеров — пропуск", "[пропуск] проверка личных следов: нет файла маркеров" in out, out[-800:])
    check("у каждого шага строка итога (нет «не вышло»)", "[не вышло]" not in out, out)
    check("резервная копия: конец ввода — «нет», строка «копии нет», GitHub и git-crypt не тронуты",
          "[пропуск] резервная копия: копии нет: при потере Mac данные пропадут; включить позже: "
          "`pantheon-setup --add backup`" in out and not any(x.startswith(("gh repo", "git-crypt", "security"))
                                                             for x in lg), (out[-800:], lg))

    # --- 2. повторный запуск на готовом Пантеоне: отказ, файлы не тронуты --------------------------------------
    h1 = tree_hash(pan)
    n_log = len(lg)
    r2 = setup(env, "", "--no-codex")
    check("повторный запуск: отказ, код ≠ 0, текст понятный",
          r2.returncode != 0 and "уже есть" in r2.stderr, (r2.returncode, r2.stderr))
    check("повторный запуск: файлы Пантеона не изменились", tree_hash(pan) == h1)
    new = [x for x in log_of(env)[n_log:] if x.split()[0] in ("claude", "gh", "brew", "terminal-notifier")]
    check("повторный запуск: ни claude, ни gh, ни brew не вызывались", not new, new)

    # --- 3. uv уже есть, ответ «да» на вопрос gh → gh auth setup-git вызван; curl не нужен ---------------------
    root, env, _ = new_root(with_uv=True, with_notifier=True)
    r = setup(env, "да\n", "--no-codex")
    lg = log_of(env)
    check("terminal-notifier уже стоит — brew не вызывался", not any(x.startswith("brew") for x in lg)
          and "[ок] terminal-notifier: уже стоит" in r.stdout, lg)
    check("ответ «да»: gh auth setup-git вызван", r.returncode == 0 and "gh auth setup-git" in lg,
          (r.returncode, r.stdout[-800:] + r.stderr[-400:]))
    check("uv уже есть — curl не вызывался", not any(x.startswith("curl") for x in lg), lg)
    check("gh вошёл — gh auth login не звали", "gh auth login" not in lg, lg)

    # --- 4. gh не вошёл: «да, да» → login и setup-git; «нет» на вход → ни того ни другого -------------------------
    root, env, _ = new_root(with_uv=True)
    env["GH_LOGGED"] = "0"
    r = setup(env, "да\nда\n", "--no-codex")
    lg = log_of(env)
    check("gh не вошёл, «да» и «да»: login и setup-git", "gh auth login" in lg and "gh auth setup-git" in lg, lg)
    root, env, _ = new_root(with_uv=True)
    env["GH_LOGGED"] = "0"
    r = setup(env, "нет\n", "--no-codex")
    lg = log_of(env)
    check("gh не вошёл, «нет»: ни login, ни setup-git, установка идёт",
          r.returncode == 0 and "gh auth login" not in lg and "gh auth setup-git" not in lg, (r.returncode, lg))
    root, env, _ = new_root(with_uv=True)
    r = setup(env, "", "--no-codex")  # конец ввода — «нет»
    check("конец ввода — «нет»: setup-git не вызван", r.returncode == 0 and "gh auth setup-git" not in log_of(env),
          log_of(env))

    # --- 5. нет claude: отказ до изменений ---------------------------------------------------------------------
    root, env, _ = new_root(with_uv=True, with_claude=False)
    r = setup(env, "", "--no-codex")
    check("нет claude: отказ «сначала поставьте Claude Code»", r.returncode != 0 and "Claude Code" in r.stderr,
          (r.returncode, r.stderr))
    check("нет claude: ничего не создано (Пантеон, config.toml, роли)",
          not os.path.exists(env["PANTHEON_HOME"]) and not os.path.exists(env["PANTHEON_STATE"])
          and not os.path.exists(os.path.join(env["HOME"], ".claude")), os.listdir(env["HOME"]))

    # --- 5б. отказы раньше установки uv: нет uv + нет claude / непустой Пантеон → curl не звали, HOME пуст -------
    root, env, _ = new_root(with_uv=False, with_claude=False)
    r = setup(env, "", "--no-codex")
    check("нет claude и нет uv: отказ, curl и uv не вызваны, HOME пуст",
          r.returncode != 0 and "Claude Code" in r.stderr and log_of(env) == [] and os.listdir(env["HOME"]) == [],
          (r.returncode, r.stderr, log_of(env), os.listdir(env["HOME"])))
    root, env, _ = new_root(with_uv=False)
    os.makedirs(env["PANTHEON_HOME"])
    open(os.path.join(env["PANTHEON_HOME"], "x.md"), "w").write("моё")
    r = setup(env, "", "--no-codex")
    check("непустой Пантеон и нет uv: отказ, curl не вызван, нового в HOME нет",
          r.returncode != 0 and "уже есть" in r.stderr and log_of(env) == [] and not os.path.exists(
              os.path.join(env["HOME"], ".local")), (r.returncode, r.stderr, log_of(env)))
    root, env, _ = new_root(with_uv=False)
    r = setup(env, "нет\n", "--no-codex")
    check("установщик uv зовётся с UV_NO_MODIFY_PATH=1", "uv-installer UV_NO_MODIFY_PATH=1" in log_of(env), log_of(env))

    # --- 6. Codex: модуля исполнителей нет — строка и установка идёт; при его наличии вопрос по умолчанию «нет» ---
    if not os.path.exists(os.path.join(LIB, "executors.py")):
        root, env, _ = new_root(with_uv=True)
        r = setup(env, "нет\n", "--codex")
        check("--codex без модуля исполнителей: «Codex: пропуск, модуль исполнителей не найден», код 0",
              r.returncode == 0 and "[пропуск] Codex: модуль исполнителей не найден" in r.stdout, r.stdout[-500:])
        r = setup(env, "", "--add", "codex")
        check("--add codex на готовой установке: только этот шаг (Пантеон не отвергает)",
              "Codex" in r.stdout and "уже есть" not in r.stderr and "[ок] Python" not in r.stdout,
              (r.stdout, r.stderr))
    else:
        # модуль есть, codex на PATH нет: Codex — только дополнение, установка проходит (решение 175)
        root, env, _ = new_root(with_uv=True)
        r = setup(env, "нет\n", "--codex")
        cfg_p = os.path.join(env["PANTHEON_STATE"], "config.toml")
        cfg = open(cfg_p, encoding="utf-8").read() if os.path.exists(cfg_p) else ""
        check("--codex, codex нет на PATH: «[пропуск] Codex», установка проходит с кодом 0",
              r.returncode == 0 and "[пропуск] Codex: не добавлен" in r.stdout and "Не вышло" not in r.stdout,
              r.stdout[-700:] + r.stderr[-300:])
        check("--codex, codex нет на PATH: в наборе только claude, Codex выключен с причиной",
              '"codex"' not in cfg.split("[codex]")[0] and 'reason = "нет на PATH"' in cfg, cfg)
        r = setup(env, "", "--add", "codex")
        check("--add codex на готовой установке без codex: только этот шаг, Пантеон не отвергает, код 1",
              r.returncode == 1 and "Codex" in r.stdout and "уже есть" not in r.stderr
              and "[ок] Python" not in r.stdout, (r.returncode, r.stdout[-500:], r.stderr[-300:]))
    root, env, _ = new_root(with_uv=True)
    r = setup(env, "нет\nнет\n")  # без флагов: вопрос про Codex, «нет»
    check("без флагов: вопрос про Codex, ответ «нет» — пропуск", "Подключить Codex" in r.stdout
          and "[пропуск] Codex" in r.stdout and not any("codex" in x for x in log_of(env)), r.stdout[-600:])

    # --- 7. проверка личных следов ---------------------------------------------------------------------------------------
    root, env, _ = new_root(with_uv=True)
    mk = os.path.join(root, "markers.txt")
    with open(mk, "w", encoding="utf-8") as fh:
        fh.write("# синтетические маркеры\nzzqq-такого-слова-нет\n/Users/\n")
    r = setup(env, "нет\n", "--no-codex", "--markers", mk)
    check("проверка следов: синтетические маркеры → «следов нет», код 0",
          r.returncode == 0 and "[ок] проверка личных следов: следов нет" in r.stdout, r.stdout[-700:] + r.stderr[-300:])
    root, env, _ = new_root(with_uv=True)
    mk = os.path.join(root, "markers.txt")
    with open(mk, "w", encoding="utf-8") as fh:
        fh.write("pantheon_pconfig\n")  # слово есть в setup.py → проверка обязана покраснеть
    env["PANTHEON_TRACE_MARKERS"] = mk
    r = setup(env, "нет\n", "--no-codex")
    check("проверка личных следов через PANTHEON_TRACE_MARKERS: маркер найден в файле установщика → «не вышло», код 1",
          r.returncode == 1 and "[не вышло] проверка личных следов" in r.stdout and "setup.py" in r.stdout,
          (r.returncode, r.stdout[-600:]))

    # --- 9. резервная копия (metis-0476): «да» в полном проходе ----------------------------------------------------
    root, env, _ = new_root(with_uv=True)
    r = setup(env, "нет\nда\n", "--no-codex")  # setup-git — нет, копия — да
    out = r.stdout + r.stderr
    lg = log_of(env)
    pan = env["PANTHEON_HOME"]
    check("копия «да»: код 0, строка «[ок] резервная копия», вопрос задан",
          r.returncode == 0 and "[ок] резервная копия" in out
          and "Завести резервную копию в приватном репозитории GitHub" in out, out[-1500:])
    qline = next((ln for ln in out.splitlines() if "Завести резервную копию" in ln), "")
    check("копия: вопрос до «да» — история заменится одним снимком, прежняя останется в refs/pantheon/pre-backup",
          "заменится одним снимком" in qline and "прежние коммиты останутся" in qline
          and "refs/pantheon/pre-backup" in qline and qline.rstrip().endswith("[да/нет, по умолчанию нет]"),
          qline[:600])
    want = ["git-crypt init", "git-crypt export-key", "security add-generic-password", "gh repo create"]
    pos = [next((i for i, x in enumerate(lg) if x.startswith(w)), -1) for w in want]
    check("копия: порядок — git-crypt init, export-key, ключ в Связку, и только потом gh repo create",
          -1 not in pos and pos == sorted(pos), (pos, lg))
    check("копия: gh repo create pantheon-hq --private, один раз",
          [x for x in lg if x.startswith("gh repo")] == ["gh repo create pantheon-hq --private"], lg)
    sec = [x for x in lg if x.startswith("security add-generic-password")]
    kc = open(env["KC_FILE"], encoding="utf-8").read()
    check("копия: ключ в Связке — одна запись через stdin: служба pantheon-git-crypt, значение base64 ключа",
          len(sec) == 1 and "security -i" in lg and "-s \"pantheon-git-crypt\"" in kc and GC_KEY_B64 in kc, (sec, kc))
    check("копия: ключа (ни сырого, ни base64) нет в аргументах ни одного вызова security и вообще в журнале заглушек",
          not any(GC_KEY_B64 in x or GC_KEY in x or "-w" in x.split() for x in lg if x.startswith("security")), lg)
    check("копия: ключа (ни сырого, ни base64) нет в выводе установщика",
          GC_KEY not in out and GC_KEY_B64 not in out, out[-800:])
    check("копия: файла с ключом в пробе не осталось (временный удалён)", leaked_key_files(root, env) == [],
          leaked_key_files(root, env))
    attrs = open(os.path.join(pan, ".gitattributes"), encoding="utf-8").read() \
        if os.path.exists(os.path.join(pan, ".gitattributes")) else ""
    check("копия: .gitattributes по образцу, без merge-драйверов",
          attrs == "* filter=git-crypt diff=git-crypt\n.gitattributes !filter !diff\n.gitignore !filter !diff\n", attrs)
    branch = git_out(env, pan, "symbolic-ref", "--short", "HEAD")
    commits = git_out(env, env["GH_REMOTE"], "rev-list", "--all").split()
    check("копия: на «GitHub» один коммит без родителей, ветка с upstream origin",
          len(commits) == 1 and git_out(env, env["GH_REMOTE"], "log", "-1", "--format=%P", commits[0]) == ""
          and git_out(env, pan, "rev-parse", "--abbrev-ref", "@{u}") == f"origin/{branch}",
          (commits, branch, git_out(env, pan, "rev-parse", "--abbrev-ref", "@{u}")))
    names = git_out(env, env["GH_REMOTE"], "ls-tree", "-r", "--name-only", commits[0] if commits else "HEAD").split()
    enc = all(subprocess.run(["git", "-C", env["GH_REMOTE"], "cat-file", "blob", f"{commits[0]}:{n}"], env=env,
                             capture_output=True).stdout.startswith(CRYPT_HEADER)
              for n in names if n != ".gitattributes") if commits else False
    check("копия: в «GitHub» все файлы, кроме .gitattributes, зашифрованы (board.md там есть)",
          enc and "board.md" in names, names)
    check("копия: рабочая папка чистая после шага", git_out(env, pan, "status", "--porcelain") == "",
          git_out(env, pan, "status", "--porcelain"))
    n_gh = len([x for x in log_of(env) if x.startswith("gh repo create")])
    r = setup(env, "да\n", "--add", "backup")
    check("повторно --add backup при заданном origin: пропуск, второго репозитория нет, код 0",
          r.returncode == 0 and "origin уже задан" in r.stdout and "второй репозиторий не завожу" in r.stdout
          and len([x for x in log_of(env) if x.startswith("gh repo create")]) == n_gh == 1, (r.returncode, r.stdout))

    # --- 10. --add backup на готовой установке: «нет», старая история, сбои -------------------------------------
    root, env, _ = new_root(with_uv=True)
    pan = prep_pan(env)
    r = setup(env, "нет\n", "--add", "backup")
    check("--add backup, «нет»: строка «копии нет», код 1, ничего не заведено",
          r.returncode == 1 and "[пропуск] резервная копия: копии нет" in r.stdout
          and "[ок] Python" not in r.stdout
          and not any(x.startswith(("gh repo", "git-crypt", "security add")) for x in log_of(env))
          and not os.path.exists(os.path.join(pan, ".gitattributes")), (r.returncode, r.stdout, log_of(env)))

    root, env, _ = new_root(with_uv=True)
    pan = prep_pan(env, history=True)
    old = git_out(env, pan, "rev-parse", "HEAD")
    r = setup(env, "да\n", "--add", "backup")
    objs = remote_objects(env)
    check("--add backup на истории открытым текстом: код 0, в «GitHub» нет открытого текста старых коммитов",
          r.returncode == 0 and objs and b"SECRET-PLAINTEXT-0476" not in objs
          and len(git_out(env, env["GH_REMOTE"], "rev-list", "--all").split()) == 1, (r.returncode, r.stdout[-600:]))
    check("--add backup: старая история цела локально в refs/pantheon/pre-backup",
          git_out(env, pan, "rev-parse", "refs/pantheon/pre-backup") == old, old)

    # повтор после сбоя на GitHub: коммит между попытками не теряется (Б1)
    root, env, _ = new_root(with_uv=True)
    pan = prep_pan(env, history=True)
    old = git_out(env, pan, "rev-parse", "HEAD")
    env["FAIL_CMD"] = "gh repo"
    r1 = setup(env, "да\n", "--add", "backup")
    git_out(env, pan, "rev-parse", "HEAD")
    gc = ["git", "-C", pan, "-c", "user.name=t", "-c", "user.email=t@t"]
    with open(os.path.join(pan, "board.md"), "a", encoding="utf-8") as fh:
        fh.write("после первого снимка\n")
    subprocess.run(gc + ["commit", "-q", "-a", "-m", "между попытками"], check=True, env=env)
    c1 = git_out(env, pan, "rev-parse", "HEAD")
    env.pop("FAIL_CMD")
    r2 = setup(env, "да\n", "--add", "backup")
    holders = git_out(env, pan, "for-each-ref", "--contains", c1, "--format=%(refname)", "refs/pantheon/")
    check("повтор после сбоя gh: коммит между попытками достижим из refs/pantheon/*, старая история тоже",
          r1.returncode == 1 and r2.returncode == 0 and holders != ""
          and git_out(env, pan, "for-each-ref", "--contains", old, "--format=%(refname)", "refs/pantheon/") != ""
          and git_out(env, pan, "rev-parse", "refs/pantheon/pre-backup") == old,
          (r1.returncode, r2.returncode, holders, r2.stdout[-500:]))
    # повтор без коммитов между попытками: лишних ссылок нет
    root, env, _ = new_root(with_uv=True)
    pan = prep_pan(env, history=True)
    env["FAIL_CMD"] = "gh repo"
    setup(env, "да\n", "--add", "backup")
    env.pop("FAIL_CMD")
    r2 = setup(env, "да\n", "--add", "backup")
    refs = git_out(env, pan, "for-each-ref", "--format=%(refname)", "refs/pantheon/").split()
    check("повтор без новых коммитов: код 0, ссылка одна — pre-backup", r2.returncode == 0
          and refs == ["refs/pantheon/pre-backup"], (r2.returncode, refs, r2.stdout[-400:]))

    # `security -i` вышел с кодом 0, но записи нет — шаг не врёт «ок»
    root, env, _ = new_root(with_uv=True)
    prep_pan(env)
    env["SEC_SILENT"] = "1"
    r = setup(env, "да\n", "--add", "backup")
    check("security -i без записи в Связке: «не вышло», gh repo create не звали, код 1",
          r.returncode == 1 and "[не вышло] резервная копия" in r.stdout
          and not any(x.startswith("gh repo") for x in log_of(env)), (r.returncode, r.stdout[-500:]))

    for fail, why, github in (("git-crypt init", "git-crypt init: git-crypt init: заглушка упала", False),
                              ("git-crypt export-key", "git-crypt export-key: заглушка упала", False),
                              ("security add-generic-password", "security: заглушка упала", False),
                              ("gh repo", "gh repo create: заглушка упала", True),
                              ("push", "push не прошёл", True)):
        root, env, _ = new_root(with_uv=True)
        prep_pan(env)
        env["FAIL_CMD"] = fail
        if fail == "push":
            env["GH_URL"] = "file://" + os.path.join(root, "нет-такого", "x.git")
        r = setup(env, "да\n", "--add", "backup")
        out = r.stdout + r.stderr
        lg = log_of(env)
        check(f"сбой «{fail}»: «[не вышло] резервная копия» с причиной, код 1, без трассы, ключа в выводе нет",
              r.returncode == 1 and "[не вышло] резервная копия" in out and why in out and "Traceback" not in out
              and GC_KEY not in out and GC_KEY_B64 not in out, (r.returncode, out[-700:]))
        check(f"сбой «{fail}»: GitHub {'тронут только после локальной подготовки' if github else 'не тронут'}",
              any(x.startswith("gh repo create") for x in lg) == github, lg)

    root, env, _ = new_root(with_uv=True)
    prep_pan(env)
    env["GC_NOENC"] = "1"  # фильтр не шифрует — push запрещён
    r = setup(env, "да\n", "--add", "backup")
    check("фильтр не зашифровал файлы: «не вышло», gh repo create не звали",
          r.returncode == 1 and "не зашифровал" in r.stdout and not any(x.startswith("gh repo") for x in log_of(env)),
          (r.stdout[-600:], log_of(env)))

    root, env, _ = new_root(with_uv=True)
    prep_pan(env)
    open(env["KC_FILE"], "w").write("чужой ключ\n")
    r = setup(env, "да\n", "--add", "backup")
    check("в Связке уже есть pantheon-git-crypt: «не вышло», git-crypt init не звали, запись не тронута",
          r.returncode == 1 and "уже есть ключ" in r.stdout and "git-crypt init" not in log_of(env)
          and open(env["KC_FILE"]).read() == "чужой ключ\n", (r.stdout[-500:], log_of(env)))

    root, env, _ = new_root(with_uv=True, with_crypt=False)
    prep_pan(env)
    r = setup(env, "да\n", "--add", "backup")
    check("нет git-crypt: пропуск с `brew install git-crypt` и «копии нет», вопрос не задан",
          r.returncode == 1 and "`brew install git-crypt`" in r.stdout and "копии нет" in r.stdout
          and "Завести резервную копию" not in r.stdout, r.stdout[-500:])

    root, env, _ = new_root(with_uv=True)
    prep_pan(env)
    env["GH_LOGGED"] = "0"
    r = setup(env, "да\n", "--add", "backup")
    check("gh не вошёл: пропуск «копии нет», вопрос не задан, gh repo create не звали",
          r.returncode == 1 and "копии нет" in r.stdout and "Завести резервную копию" not in r.stdout
          and not any(x.startswith("gh repo") for x in log_of(env)), r.stdout[-500:])
    r = setup(env, "", "--add", "backup", "--backup-name", "-x")
    check("--backup-name с «-»: отказ разбора, код 2", r.returncode == 2 and "--backup-name" in r.stderr,
          (r.returncode, r.stderr))

    # --- 8. настоящие файлы владельца не тронуты ------------------------------------------------------------------
    after = real_snapshot()
    check("настоящие ~/.claude/settings.json, ~/.gitconfig, ~/ai/pantheon не изменились", before == after,
          (before, after))


if __name__ == "__main__":
    atexit.register(lambda: [shutil.rmtree(r, True) for r in roots])
    main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)
