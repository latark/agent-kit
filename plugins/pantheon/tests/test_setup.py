#!/usr/bin/env python3
"""pantheon-setup (bin/pantheon-setup + lib/setup.py + lib/platform_macos.py): проба установки целиком в изоляции.

Корень tempfile.mkdtemp(prefix="tmp-setup-") в $TMPDIR; HOME, PANTHEON_HOME, PANTHEON_STATE — в нём; PATH — папка
заглушек + /usr/bin:/bin (git настоящий). Все внешние программы — заглушки (uv, curl, claude, gh, brew,
terminal-notifier), каждая пишет argv в журнал. Настоящие ~/.claude/settings.json, ~/ai/pantheon и ~/.gitconfig
сверяются по хешу до и после.

Запуск: python3 -I plugins/pantheon/tests/test_setup.py  (код выхода 0 — все прошли; на 3.9 CLI честно пропускается)
"""
import atexit
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


def new_root(with_uv=False, with_claude=True, with_notifier=False):
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
    sh_file(os.path.join(stubs, "gh"),
            'echo "gh $*" >> "$STUB_LOG"\n'
            'if [ "$1 $2" = "auth status" ]; then [ "$GH_LOGGED" = "1" ]; exit $?; fi\nexit 0\n')
    for n in ("brew",) + (("terminal-notifier",) if with_notifier else ()):
        sh_file(os.path.join(stubs, n), f'echo "{n} $*" >> "$STUB_LOG"\nexit 0\n')
    env = {"PATH": stubs + ":/usr/bin:/bin", "HOME": home, "PANTHEON_HOME": os.path.join(home, "ai", "pantheon"),
           "PANTHEON_STATE": os.path.join(root, "state"), "PANTHEON_VIEW": os.path.join(root, "view"),
           "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": root, "STUB_LOG": log, "GH_LOGGED": "1",
           "LANG": "en_US.UTF-8"}
    return root, env, stubs


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

    # --- 8. настоящие файлы владельца не тронуты ------------------------------------------------------------------
    after = real_snapshot()
    check("настоящие ~/.claude/settings.json, ~/.gitconfig, ~/ai/pantheon не изменились", before == after,
          (before, after))


if __name__ == "__main__":
    atexit.register(lambda: [shutil.rmtree(r, True) for r in roots])
    main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)
