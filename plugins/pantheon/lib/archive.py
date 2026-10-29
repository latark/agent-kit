"""Пантеон: копия для Obsidian (pantheon view), коммит ~/ai/pantheon (pantheon commit) и архив доски и тревог
(pantheon archive).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import contextlib
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

__all__ = [
    "VIEW_INBOX", "view", "PUSH_POST_BUFFER", "PUSH_FAIL_LIMIT", "PUSH_SERVER_ERR", "push_failed", "commit",
    "DONE_HEAD", "DATE_ISO", "DATE_RU", "line_date", "archive", "archive_status",
]


VIEW_INBOX = os.environ.get("PANTHEON_VIEW_INBOX") or os.path.join(P.PANTHEON, "inbox-view")


def view(quiet=False):
    if not os.path.isdir(P.PANTHEON):
        return 0
    with P.lock("view"):
        rc = subprocess.run(["/bin/zsh", os.path.join(P.LIB, "view-sync.sh"), P.PANTHEON, P.VIEW, VIEW_INBOX],
                            capture_output=quiet).returncode
    return rc


# push большого коммита по HTTPS упирается в буфер git (по умолчанию 1 МБ → «RPC failed; HTTP 400/413»): буфер 150 МБ
# задаётся ключом -c на каждый push, ~/.gitconfig не правится (metis-0133)
PUSH_POST_BUFFER = 157286400
PUSH_FAIL_LIMIT = 3
# отказ сервера, а не отсутствие сети: HTTP 4xx/5xx, RPC failed, обрыв при передаче пакета
PUSH_SERVER_ERR = re.compile(r"returned error: [45]\d\d|\bHTTP/?[\d.]*\s*[45]\d\d|RPC failed|"
                             r"remote end hung up|pack-objects died|send-pack: unexpected disconnect", re.I)


def push_failed(stderr):
    """Неудача push, не похожая на «нет сети», считается подряд: на 3-й — тревога (ошибка не исчезнет сама,
    как исчезает отсутствие сети); без сети счётчик не растёт и не сбрасывается."""
    if not PUSH_SERVER_ERR.search(stderr or ""):
        return
    f = P.path("push-fail.json")
    n = int(P.read_json(f).get("n") or 0) + 1
    P.write_json(f, {"n": n, "t": P.now()})
    if n >= PUSH_FAIL_LIMIT:
        P.alert_once("push-fail", PUSH_FAIL_LIMIT, f"~/ai/pantheon: push не проходит {n} раза подряд "
                   f"({(stderr.strip().splitlines() or [''])[-1][:200]}) — это не обрыв сети, нужен разбор",
                   "pantheon-commit", note="~/ai/pantheon: push не проходит несколько раз подряд")


def commit():
    """commit → pull без rebase → push, как Obsidian Git. Слияние шифрованных файлов — git-crypt-merge.sh
    (дописываемые файлы — объединением). Без сети — код TEMPFAIL и тишина; тревога, только если синхронизации
    нет дольше 6 часов. Конфликт — слияние отменяется, тревога одна на каждый новый коммит другого Mac."""
    if not os.path.isdir(os.path.join(P.PANTHEON, ".git")):
        return 0
    with P.lock("pantheon-git"):
        if P.git("status", "--porcelain").stdout.strip():
            P.git("add", "-A")
            P.git("commit", "-q", "-m", f"pantheon: {P.host()} {P.stamp()}")
        if not P.git("remote", check=False).stdout.strip():
            return 0

        def offline(stderr):
            ok = P.read_json(P.path("commit-ok.json")).get("t") or 0
            if P.now() - ok > 6 * 3600:
                P.alert_once("commit-offline", int(ok), "~/ai/pantheon не синхронизируется с GitHub больше 6 часов: "
                           f"{(stderr.strip().splitlines() or [''])[-1][:200]}", "pantheon-commit",
                           note="~/ai/pantheon давно не синхронизируется с GitHub")
            print(stderr.strip(), file=sys.stderr)
            return P.TEMPFAIL

        pull = P.git("pull", "--no-rebase", "--no-edit", "-q", check=False)
        if pull.returncode != 0:
            if os.path.exists(os.path.join(P.PANTHEON, ".git", "MERGE_HEAD")):
                files = P.git("diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
                theirs = P.git("rev-parse", "MERGE_HEAD", check=False).stdout.strip()
                P.git("merge", "--abort", check=False)
                P.alert_once("merge-conflict", theirs, f"~/ai/pantheon: конфликт слияния с другим компьютером "
                           f"({', '.join(files) or 'файлы не названы'}); локальный коммит цел, слияние отменено — "
                           "разобрать вручную", "pantheon-commit", note="~/ai/pantheon: конфликт слияния, нужен разбор")
                return P.ALERTED
            return offline(pull.stderr)
        P.clear_once("merge-conflict")
        ahead = P.git("rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
        if ahead and ahead != "0":
            push = P.git("-c", f"http.postBuffer={PUSH_POST_BUFFER}", "push", "-q", check=False)
            if push.returncode != 0:
                push_failed(push.stderr)
                return offline(push.stderr)
            P.clear_push_failures()
        P.write_json(P.path("commit-ok.json"), {"t": P.now()})
        P.clear_once("commit-offline")
    return 0


DONE_HEAD = re.compile(r"^##\s+Сделано\s*$")
DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE_RU = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?![\d.])")


def line_date(line, t):
    """Первая корректная дата строки: сначала ГГГГ-ММ-ДД, потом ДД.ММ[.ГГГГ] (версии вроде 2.1.12 — не даты)."""
    for m in DATE_ISO.finditer(line):
        with contextlib.suppress(ValueError):
            return datetime(int(m[1]), int(m[2]), int(m[3]))
    for m in DATE_RU.finditer(line):
        year = int(m[3]) if m[3] else datetime.fromtimestamp(t).year
        with contextlib.suppress(ValueError):
            d = datetime(year, int(m[2]), int(m[1]))
            return d if d <= datetime.fromtimestamp(t) + timedelta(days=1) else d.replace(year=year - 1)
    return None


def archive():
    """Раздел «Сделано» доски старше 7 дней и строки alerts.md старше 30 дней — в ~/ai/pantheon/archive/; STATUS.md
    длиннее предела 9 000 знаков — разделы с датой старше суток в archive/ направления (archive_status). Файл
    состояния и после этого длиннее предела — тревога: строки без даты архив не режет (metis-0397). Запуск — задача
    `pantheon archive` в schedule.toml раз в сутки или руками."""
    t = P.now()
    today = datetime.fromtimestamp(t)
    moved = {"board": 0, "alerts": 0}
    lk = P.lock("pantheon-git")  # коммит тика не захватит доску посреди переписывания
    lk.__enter__()
    os.makedirs(os.path.join(P.PANTHEON, "archive"), exist_ok=True)

    def append(name, lines):
        with open(os.path.join(P.PANTHEON, "archive", name), "a", encoding="utf-8") as fh:
            fh.writelines(lines)

    board = os.path.join(P.PANTHEON, "board.md")
    if os.path.exists(board):
        lines = open(board, encoding="utf-8").read().splitlines(keepends=True)
        out, old, in_done, item_old = [], {}, False, False
        for ln in lines:
            if ln.startswith("## "):
                in_done = bool(DONE_HEAD.match(ln.strip()))
                out.append(ln)
                continue
            if in_done and re.match(r"^\s*[-*] ", ln) and not ln.startswith((" ", "\t")):
                d = line_date(ln, t)
                item_old = bool(d and (today - d).days > 7)
            if in_done and item_old and ln.strip():
                key = (line_date(ln, t) or today).strftime("%Y-%m")
                old.setdefault(key, []).append(ln)
                moved["board"] += 1
            else:
                out.append(ln)
        for key, items in sorted(old.items()):
            append(f"board-{key}.md", items)
        if moved["board"]:
            P.write_atomic(board, "".join(out))
    alerts = os.path.join(P.PANTHEON, "alerts.md")
    if os.path.exists(alerts):
        with P.lock("alerts"):
            lines = open(alerts, encoding="utf-8").read().splitlines(keepends=True)
            out, old = [], {}
            for ln in lines:
                m = re.match(r"^(\d{4})-(\d{2})-(\d{2}) \d{2}:\d{2} · ", ln)
                if m and (today - datetime(int(m[1]), int(m[2]), int(m[3]))).days > 30:
                    old.setdefault(f"{m[1]}-{m[2]}", []).append(ln)
                    moved["alerts"] += 1
                else:
                    out.append(ln)
            for key, items in sorted(old.items()):
                append(f"alerts-{key}.md", items)
            if moved["alerts"]:
                P.write_atomic(alerts, "".join(out))
    sl = P.statelen_mod()
    moved["status"] = 0
    for f in sl.state_files(P.PANTHEON):
        if not os.path.isfile(f):
            continue
        if os.path.basename(f) == "STATUS.md":
            moved["status"] += archive_status(f, t, today, sl.STATE_FILE_LIMIT)
        n, rel = sl.length(f) or 0, os.path.relpath(f, P.PANTHEON)
        key = "trim-" + re.sub(r"[^\w-]", "_", rel)[:60]
        if n > sl.STATE_FILE_LIMIT:
            P.alert_once(key, "1", f"{rel}: {n} знаков при пределе {sl.STATE_FILE_LIMIT} — архив переносит только "
                       "строки и разделы с датой старше срока, строки без даты не режет: подрезать вручную",
                       "pantheon-archive")
        else:
            P.clear_once(key)
    lk.__exit__(None, None, None)
    print(f"в архив: доска — {moved['board']} строк, тревоги — {moved['alerts']} строк, "
          f"STATUS.md — {moved['status']} разделов")
    return 0


def archive_status(f, t, today, limit):
    """STATUS.md длиннее limit: разделы «## …» с датой в заголовке старше суток, кроме первого (текущего), — в
    directions/<d>/archive/STATUS-ГГГГ-ММ.md, старые первыми, пока файл не уложится в предел. Разделы без даты, первый
    раздел и строки до первого заголовка не трогает. Файл правили во время прохода — ничего не переносит (следующий
    проход). → сколько разделов перенесено."""
    text = open(f, encoding="utf-8").read()
    if len(text) <= limit:
        return 0
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    secs = []
    for k in range(1, len(starts)):
        i, end = starts[k], starts[k + 1] if k + 1 < len(starts) else len(lines)
        d = line_date(lines[i], t)
        if d and (today - d).days >= 1:
            secs.append((d, i, end))
    drop, size, moved = set(), len(text), {}
    for d, i, end in sorted(secs):
        if size <= limit:
            break
        chunk = "".join(lines[i:end])
        size -= len(chunk)
        drop.update(range(i, end))
        moved.setdefault(d.strftime("%Y-%m"), []).append(chunk)
    if not drop or open(f, encoding="utf-8").read() != text:
        return 0
    adir = os.path.join(os.path.dirname(f), "archive")
    os.makedirs(adir, exist_ok=True)
    for key, chunks in sorted(moved.items()):
        with open(os.path.join(adir, f"STATUS-{key}.md"), "a", encoding="utf-8") as fh:
            fh.writelines(chunks)
    P.write_atomic(f, "".join(ln for j, ln in enumerate(lines) if j not in drop))
    return sum(len(c) for c in moved.values())
