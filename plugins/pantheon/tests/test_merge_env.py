#!/usr/bin/env python3
"""Слияние по Touch ID, часть 4: окружение помощника и установка managed-настроек (общая часть — _merge_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403


def test_env_home():
    """HOME не домашняя папка учётной записи (launchctl setenv HOME) — проход не идёт. Без обвязки: как у тика."""
    b = Box()
    b.request()
    r = subprocess.run([PY311, "-I", RUN_PY, "merge", "run"], env=b.env(T0), capture_output=True, text=True, timeout=60)
    check("HOME из launchd не домашняя папка учётной записи → отказ (код 2), окна и слияния нет, заявка цела",
          r.returncode == 2 and not b.windows() and not b.merges() and b.req() is not None, r.stdout + r.stderr)


def test_env_clean():
    """Окружение прохода с нуля: всё, что не HOME и не постоянный PATH, снято; STATE и Пантеон — от HOME."""
    b = Box()
    code = ("import json, os, sys; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); m.TEST = {}\n"
            "why = m.clean_env(); print(json.dumps([why, dict(os.environ), p.STATE, p.PANTHEON, m.SAFE_PATH]))" % LIBDIR)
    env = b.env(T0, {"PANTHEON_STATE": os.path.join(b.tmp, "x"), "PANTHEON_HOME": os.path.join(b.tmp, "y"),
                     "DEVELOPER_DIR": b.tmp, "GH_CONFIG_DIR": b.tmp, "PANTHEON_TEST": "1"})
    r = subprocess.run([PY311, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    try:
        why, got, state, pan, safe = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        why, got, state, pan, safe = "?", {}, None, None, None
    check("clean_env: окружение = HOME и постоянный PATH, STATE и Пантеон — от HOME",
          why is None and got == {"HOME": os.path.realpath(b.home), "PATH": safe}
          and state == os.path.realpath(b.state) and pan == os.path.realpath(b.pantheon), r.stdout + r.stderr)


def test_env_home_link():
    """argus-b 0303, п. 2: HOME — ссылка на домашнюю папку учётной записи. Сверка проходит, но дальше — realpath:
    в окружение, gh, P.CURRENT и команду щелчка путь через ссылку не идёт (её можно перевесить после сверки)."""
    b = Box()
    real = os.path.realpath(b.home)
    ver = os.path.join(real, ".local", "share", "pantheon", "versions", "1")
    os.makedirs(os.path.join(ver, "bin"))
    os.symlink(ver, os.path.join(real, ".local", "share", "pantheon", "current"))
    link = os.path.join(b.tmp, "home-link")
    os.symlink(b.home, link)
    log = os.path.join(b.tmp, "notify.log")
    # без обвязки TEST: сверка с учётной записью идёт, pw_dir учётной записи — та же ссылка
    code = ("import json, os, sys, types; sys.path.insert(0, %r); import pwd\n"
            "pwd.getpwuid = lambda uid: types.SimpleNamespace(pw_dir=%r)\n"
            "import pantheon as p; m = p.merge_mod(); why = m.clean_env(); env = dict(os.environ)\n"
            "os.environ['PANTHEON_NOTIFY_LOG'] = %r; m.fallback_notify({}, 'окно')\n"
            "print(json.dumps([why, env, p.HOME, p.AI_HOME, p.CURRENT, p.STATE, m.pass_env()]))"
            % (LIBDIR, link, log))
    # PANTHEON_PYTHON прохода ставит bin/pantheon из pass_env тика: clean_env его оставляет, а щелчок берёт его, не
    # sys.executable (его подменяет PYTHONEXECUTABLE)
    env = dict(b.env(T0), HOME=link, PANTHEON_PYTHON=PY311, PYTHONEXECUTABLE=os.path.join(b.tmp, "evil-python"))
    r = subprocess.run([PY311, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    try:
        why, got, home, ai, cur, state, passed = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        why, got, home, ai, cur, state, passed = "?", {}, None, None, None, None, {}
    check("HOME-ссылка: сверка проходит, в окружение, P.HOME, AI_HOME, CURRENT, STATE и pass_env — realpath",
          why is None and got.get("HOME") == real and home == real and ai == os.path.join(real, "ai")
          and cur.startswith(real + os.sep) and state == os.path.realpath(b.state) and passed.get("HOME") == real,
          r.stdout + r.stderr)
    check("проход без обвязки: clean_env оставляет PANTHEON_PYTHON, pass_env — он, а не sys.executable",
          got.get("PANTHEON_PYTHON") == PY311 and passed.get("PANTHEON_PYTHON") == PY311, (got, passed))
    note = open(log).read() if os.path.exists(log) else ""
    cmd = note.rstrip().split("|execute:", 1)[-1].rsplit("|", 1)[0] if "|execute:" in note else ""
    words = shlex.split(cmd) if cmd else []
    check("HOME-ссылка: в команде щелчка HOME и bin/pantheon — realpath (current разрешён), не через ссылку",
          f"HOME={real}" in words and os.path.join(ver, "bin", "pantheon") in words and f"PANTHEON_PYTHON={PY311}" in words
          and not any(link in w for w in words), cmd or r.stderr)


def test_managed_finger_installs():
    b = managed_box()
    r, log = mkick(b)
    check("управляемые: отстали от проверенной версии — тик запускает проход", "merge-run" in log, r.stderr + log)
    r = mrun(b)
    wins = b.calls("osascript")
    st = mstate(b)
    check("управляемые: одно окно прав администратора с текстом «Обновить управляемые настройки guard до версии X»",
          len(wins) == 1 and wins[0]["argv"][-1] == f"Обновить управляемые настройки guard до версии {M_VER}"
          and "with administrator privileges" in " ".join(wins[0]["argv"]), (wins, b.outs[-1]))
    check("управляемые: касание → файл поставлен (временная папка вместо /Library), 644, версия записана",
          r.returncode == 0 and mdest(b) == M_NEW and oct(os.stat(b.mdest).st_mode & 0o777) == "0o644"
          and st.get("installed", {}).get("version") == M_VER
          and st["installed"].get("sha") == hashlib.sha256(M_NEW).hexdigest() and not mcards(b)
          and "pantheon-managed" not in b.alerts(), (b.outs[-1], st, b.alerts()))
    check("управляемые: временных файлов рядом не осталось",
          os.listdir(os.path.dirname(b.mdest)) == ["managed-settings.json"], os.listdir(os.path.dirname(b.mdest)))
    r, log = mkick(b)
    mrun(b)
    check("управляемые: после установки совпадают — тик прохода не запускает, окна больше нет",
          "merge-run" not in log and len(b.calls("osascript")) == 1, (log, b.calls("osascript")))


def test_managed_same_version_no_window():
    b = managed_box(installed=M_NEW)
    r, log = mkick(b)
    mrun(b)
    check("управляемые: версия совпадает — тик не запускает проход, окна и карточки нет",
          "merge-run" not in log and not b.calls("osascript") and not mcards(b) and mdest(b) == M_NEW,
          (log, b.calls("osascript"), b.outs[-1]))
    b = managed_box(installed=None)
    r, log = mkick(b)
    mrun(b)
    check("управляемые: файла в /Library нет — не отставание: окна нет (первый раз ставит владелец)",
          "merge-run" not in log and not b.calls("osascript") and mdest(b) is None, (log, b.outs[-1]))


def test_managed_refused_card_and_retry():
    b = managed_box()
    b.set("osascript-mode", "cancel")
    mrun(b)
    cards = mcards(b)
    st = mstate(b)
    text = cards[0][1] if cards else ""
    check("управляемые: отказ → файл не тронут, карточка «Руками» (Кому — владелец, без вопроса) с командой sudo install",
          mdest(b) == M_OLD and len(cards) == 1 and "owner: owner" in text and "question" not in text
          and "sudo install -m 644 -o root -g wheel" in text and b.msrc in text and st.get("result") == "refused"
          and st.get("asked") == T0, (b.outs[-1], cards, st))
    check("управляемые: отказ → тревога с причиной и командой",
          "pantheon-managed" in b.alerts() and "sudo install" in b.alerts() and "вы отменили окно" in b.alerts(),
          b.alerts())
    mrun(b, t=T0 + 3600)
    r, log = mkick(b, t=T0 + 3600)
    check("управляемые: раньше 6 ч — окна нет, тик прохода не запускает",
          len(b.calls("osascript")) == 1 and "merge-run" not in log, (b.calls("osascript"), log))
    mrun(b, t=T0 + 6 * 3600 + 1)
    check("управляемые: через 6 ч — окно снова, вторая карточка не заводится",
          len(b.calls("osascript")) == 2 and len(mcards(b)) == 1 and mstate(b).get("asked") == T0 + 6 * 3600 + 1,
          (b.calls("osascript"), mcards(b)))
    # владелец поставил командой из карточки: тик видит совпадение, закрывает карточку и пишет версию
    with open(b.mdest, "wb") as fh:
        fh.write(M_NEW)
    r, log = mkick(b, t=T0 + 7 * 3600)
    card = mcards(b)[0][1]
    check("управляемые: поставили командой — карточка закрыта, версия записана, прохода нет",
          "status: done" in card and mstate(b).get("installed", {}).get("version") == M_VER and "merge-run" not in log,
          (card, mstate(b), r.stderr))


def test_managed_timeout_card():
    b = managed_box()
    b.set("osascript-mode", "sleep")
    mrun(b)
    st = mstate(b)
    check("управляемые: касания нет (время вышло) → файл не тронут, карточка и тревога, повтор позже",
          mdest(b) == M_OLD and len(mcards(b)) == 1 and st.get("result") == "timeout"
          and "pantheon-managed" in b.alerts() and "ждало касания" in b.alerts(), (b.outs[-1], st, b.alerts()))
    b = managed_box()
    b.set("osascript-mode", "lie")
    mrun(b)
    st = mstate(b)
    check("управляемые: окно ответило «да», а файл не тот — версия не записана, карточка и тревога",
          mdest(b) == M_OLD and "installed" not in st and st.get("result") == "после касания файл не тот"
          and len(mcards(b)) == 1, (b.outs[-1], st))


def test_managed_swapped_source():
    b = managed_box()
    b.set("osascript-mode", "swap")
    mrun(b)
    check("управляемые: проверенный файл подменили после сверки — root не ставит (sha256), карточка и тревога",
          mdest(b) == M_OLD and len(mcards(b)) == 1 and "код 65" in str(mstate(b).get("result")),
          (b.outs[-1], mstate(b)))


def test_managed_new_version_replaces_card():
    b = managed_box()
    b.set("osascript-mode", "cancel")
    mrun(b)
    first = mcards(b)[0][0] if mcards(b) else ""
    with open(b.msrc, "wb") as fh:   # выпуск guard: новый проверенный файл, новая версия
        fh.write(b'{"hooks": {}, "v": "newer"}\n')
    with open(os.path.join(b.tree, ".claude-plugin", "plugin.json"), "w") as fh:
        json.dump({"name": "guard", "version": "0.5.100"}, fh)
    mverify(b, "0.5.100")
    mrun(b, t=T0 + 60)
    cards = dict(mcards(b))
    check("управляемые: новая версия — окно сразу, не через 6 ч; карточка прошлой версии закрыта, заведена новая",
          len(b.calls("osascript")) == 2 and len(cards) == 2 and "status: done" in cards.get(first, "")
          and any("0.5.100" in t and "status: done" not in t for t in cards.values()), (b.calls("osascript"), cards))


def test_managed_no_osascript_and_no_record():
    b = managed_box()
    b.mattrs["m"]["OSASCRIPT"] = os.path.join(b.bin, "нет-такого")
    mrun(b)
    check("управляемые: окно не показать (нет osascript) — файл не тронут, карточка и тревога с причиной",
          mdest(b) == M_OLD and len(mcards(b)) == 1 and "no-window (FileNotFoundError)" in b.alerts(),
          (b.outs[-1], b.alerts()))
    b = managed_box()
    os.remove(os.path.join(b.state, "plugins", "verified.json"))
    once = os.path.join(b.state, "once")
    r, log = mkick(b)
    mrun(b)
    check("управляемые: guard не проверен (нет записи verified.json) — ни окна, ни карточки, ни тревоги о дереве",
          "merge-run" not in log and not b.calls("osascript") and not mcards(b) and mdest(b) == M_OLD
          and not any(f.startswith("plugins-unverified") for f in (os.listdir(once) if os.path.isdir(once) else []))
          and "не проверено" not in b.alerts(),
          (log, b.alerts()))


def test_managed_once_per_version_after_crash():
    """metis-0710 п. 3: на одну версию окно не чаще раза в MANAGED_RETRY — и когда проход оборвали сразу после окна
    (ревью argus-274b, Д1: asked писался после ответа окна, и оборванный проход показывал окно каждую минуту)."""
    b = managed_box()
    b.set("osascript-mode", "cancel")
    mrun(b)
    mrun(b, t=T0 + 60)
    check("управляемые: два прохода подряд на одну версию — окно один раз",
          len(b.calls("osascript")) == 1 and len(mcards(b)) == 1, (b.calls("osascript"), mcards(b)))
    b = managed_box()
    b.set("osascript-mode", "die")
    r = mrun(b)
    st = mstate(b)
    check("управляемые: проход оборван после окна — попытка уже засчитана (asked до окна), файл не тронут",
          r.returncode != 0 and len(b.calls("osascript")) == 1 and st.get("asked") == T0
          and st.get("sha") == hashlib.sha256(M_NEW).hexdigest() and mdest(b) == M_OLD, (r.returncode, st))
    b.set("osascript-mode", "cancel")
    mrun(b, t=T0 + 60)
    r, log = mkick(b, t=T0 + 120)
    check("управляемые: после оборванного прохода — окна снова нет раньше 6 ч, тик прохода не запускает",
          len(b.calls("osascript")) == 1 and "merge-run" not in log, (b.calls("osascript"), log))
    mrun(b, t=T0 + 6 * 3600 + 1)
    check("управляемые: после оборванного прохода через 6 ч — окно снова, карточка «Руками»",
          len(b.calls("osascript")) == 2 and len(mcards(b)) == 1 and mstate(b).get("result") == "refused",
          (b.calls("osascript"), mcards(b), mstate(b)))


def test_managed_tree_changed_after_verify():
    """metis-0710 п. 4: дерево guard изменили после записи в verified.json (хеш не совпал) — его managed-settings.json
    не ставится: окна нет, файл в /Library не тронут, карточки нет. Ловит мутант installed_dir(checked=False)."""
    b = managed_box()
    with open(b.msrc, "wb") as fh:   # правка проверенного дерева мимо выпуска и accept
        fh.write(b'{"hooks": {}, "v": "tampered"}\n')
    later = os.stat(b.msrc).st_mtime + 5
    os.utime(b.msrc, (later, later))
    os.utime(b.tree, (later, later))
    r, log = mkick(b)
    mrun(b)
    check("управляемые: дерево изменено после verified.json — окна нет, файл не тронут, карточки нет",
          not b.calls("osascript") and mdest(b) == M_OLD and not mcards(b) and "merge-run" not in log
          and not mstate(b).get("asked"), (b.calls("osascript"), mdest(b), log, mstate(b)))


def test_managed_owner_away():
    b = managed_box()
    mrun(b, extra={"PANTHEON_FAKE_IDLE": "100000"})
    check("управляемые: вас нет у Mac — окна и карточки нет, попытка не засчитана",
          not b.calls("osascript") and not mcards(b) and not mstate(b).get("asked") and mdest(b) == M_OLD,
          (b.outs[-1], mstate(b)))


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544); исключение — провал случая
    run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)], FAILS,
              lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
