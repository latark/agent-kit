/* Исполняемый файл службы демона хуков pantheon.svc.hookd (metis-0811, решение владельца 04.11 по Д-A2, TCC).
 * Собирает hooks/hookd-build.sh --svc в ~/.cache/pantheon/hookd/bin/pantheon-hookd — путь постоянный, от версии
 * плагина и Python не зависит. Его зовёт launchd (ProgramArguments plist), руками его не запускают.
 *
 *   pantheon-hookd                    служба: сокеты launchd → демон
 *   pantheon-hookd --tcc-probe        проба доступа к папкам под TCC → ~/.cache/pantheon/hookd/probe/result.json
 *
 * Зачем он. Права «Файлы и папки» (Desktop, Documents, Downloads, iCloud Drive) macOS даёт ответственному процессу —
 * у службы launchd это первый процесс задания. Раньше им был /bin/sh python.sh, который делал exec в Python: разрешение
 * получал Python.app Homebrew. Его подпись — ad-hoc (cdhash), путь — с номером версии в Cellar: после `brew upgrade`
 * разрешение слетало бы, а то же разрешение получали бы все прочие задания launchd на этом Python. Этот файл не делает
 * exec: он остаётся родителем, а Python — его ребёнком, и macOS спрашивает и помнит разрешение для pantheon-hookd.
 * Пересобирается он только при правке этого исходника (метка pantheon-hookd.src): тогда macOS спросит снова.
 *
 * Чужой код с этим разрешением не запустить (confused deputy, находка проверки безопасности 05.11). Из аргументов и
 * окружения он ничего не берёт:
 * - свой путь — от ядра (proc_pidpath), он обязан кончаться на /.cache/pantheon/hookd/bin/pantheon-hookd; HOME — то,
 *   что до этого хвоста. Копия файла в другом месте — другой путь, и разрешения macOS у неё нет;
 * - папку hooks — из файла pantheon-hookd.hooks рядом. Его пишет hookd-install.sh из терминала владельца: свой, не
 *   ссылка, не открыт группе и прочим, путь абсолютный и канонический. Папка bin и папка hooks — свои и тоже не
 *   открыты на запись другим. Папку ~/.cache/pantheon/hookd роли не правят (protect-config, F7);
 * - окружение ребёнка — только HOME и PATH: PYTHON*, DYLD_*, BASH_FUNC_* и прочее от того, кто запустил, не доходят;
 * - итог пробы — всегда в ~/.cache/pantheon/hookd/probe/result.json.
 * Что-то не так — код 78 и причина, ничего не запускается.
 *
 * Служба: сокеты берёт сам (launch_activate_socket «Listeners»), снимает с них FD_CLOEXEC и запускает ребёнком
 * `/bin/sh <hooks>/python.sh <hooks>/daemon.py --fd <n> …`. Свои копии сокетов закрывает, ждёт ребёнка, SIGTERM,
 * SIGINT и SIGHUP передаёт ему. Код выхода — код ребёнка (сигнал — 128 + номер). Сбой — код не 0 и причина в stderr
 * (у службы — ~/.local/state/pantheon/logs/svc-hookd.log): клиенты в это время идут медленным путём (F1).
 * Проба: ребёнок `daemon.py --tcc-probe <итог>`, без сокетов. Без зависимостей: cc -O2 -o pantheon-hookd hookd-svc.c. */
#include <errno.h>
#include <fcntl.h>
#include <launch.h>
#include <libproc.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_FDS 8
#define TAIL "/.cache/pantheon/hookd/bin/pantheon-hookd"
#define CHILD_PATH "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

static volatile pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

static int fail(int code, const char *what, const char *detail) {
    fprintf(stderr, "pantheon-hookd: %s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    return code;
}

/* Свой и не открыт на запись группе и прочим; dir — папка, иначе обычный файл. */
static int own_closed(const struct stat *st, int dir) {
    return st->st_uid == getuid() && !(st->st_mode & (S_IWGRP | S_IWOTH))
        && (dir ? S_ISDIR(st->st_mode) : S_ISREG(st->st_mode));
}

static int own_closed_path(const char *p, int dir) {
    struct stat st;
    return lstat(p, &st) == 0 && own_closed(&st, dir);
}

int main(int argc, char **argv) {
    int probe = argc == 2 && strcmp(argv[1], "--tcc-probe") == 0;
    if (!(argc == 1 || probe))
        return fail(64, "аргументов нет (служба) или один --tcc-probe; папку hooks берёт из pantheon-hookd.hooks", NULL);

    char self[PROC_PIDPATHINFO_MAXSIZE];
    if (proc_pidpath(getpid(), self, sizeof self) <= 0) return fail(78, "свой путь не узнать", strerror(errno));
    size_t ls = strlen(self), lt = strlen(TAIL);
    if (ls <= lt || strcmp(self + ls - lt, TAIL) != 0)
        return fail(78, "запущен не из ~" TAIL, self);
    char home[PATH_MAX], bindir[PATH_MAX], pin[PATH_MAX], hooks[PATH_MAX], real[PATH_MAX];
    snprintf(home, sizeof home, "%.*s", (int)(ls - lt), self);
    snprintf(bindir, sizeof bindir, "%.*s", (int)(ls - strlen("/pantheon-hookd")), self);
    if ((size_t)snprintf(pin, sizeof pin, "%s.hooks", self) >= sizeof pin) return fail(78, "путь слишком длинный", NULL);
    if (!own_closed_path(bindir, 1)) return fail(78, "папка bin чужая или открыта на запись другим", bindir);

    int fd = open(pin, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return fail(78, "нет pantheon-hookd.hooks (поставить службу: hookd-install.sh)", strerror(errno));
    struct stat st;
    ssize_t got = -1;
    int fine = fstat(fd, &st) == 0 && own_closed(&st, 0) && st.st_size > 1 && st.st_size < (off_t)sizeof hooks;
    if (fine) got = read(fd, hooks, sizeof hooks - 1);
    close(fd);
    if (!fine || got != st.st_size) return fail(78, "pantheon-hookd.hooks чужой, открыт другим или не прочесть", pin);
    hooks[got] = 0;
    if (hooks[got - 1] == '\n') hooks[--got] = 0;
    if (hooks[0] != '/' || strchr(hooks, '\n') || !realpath(hooks, real) || strcmp(real, hooks) != 0)
        return fail(78, "в pantheon-hookd.hooks не канонический абсолютный путь", hooks);
    char py[PATH_MAX + 16], dm[PATH_MAX + 16], out[PATH_MAX + 64], envhome[PATH_MAX + 8];
    snprintf(py, sizeof py, "%s/python.sh", hooks);
    snprintf(dm, sizeof dm, "%s/daemon.py", hooks);
    snprintf(out, sizeof out, "%s/.cache/pantheon/hookd/probe/result.json", home);
    snprintf(envhome, sizeof envhome, "HOME=%s", home);
    if (!own_closed_path(hooks, 1) || !own_closed_path(py, 0) || !own_closed_path(dm, 0))
        return fail(78, "папка hooks, python.sh или daemon.py чужие, ссылки или открыты на запись другим", hooks);

    char *args[8 + 2 * MAX_FDS];
    char fdtxt[MAX_FDS][16];
    int n = 0;
    args[n++] = "/bin/sh";
    args[n++] = py;
    args[n++] = dm;
    int *fds = NULL;
    size_t cnt = 0;
    if (probe) {
        args[n++] = "--tcc-probe";
        args[n++] = out;
    } else {
        int err = launch_activate_socket("Listeners", &fds, &cnt);
        if (err) return fail(1, "сокет от launchd не получен (вне службы launchd?)", strerror(err));
        if (cnt == 0 || cnt > MAX_FDS) return fail(1, "launchd дал не 1–8 сокетов (ключ Sockets → Listeners)", NULL);
        for (size_t i = 0; i < cnt; i++) {
            int fl = fcntl(fds[i], F_GETFD);
            if (fl < 0 || fcntl(fds[i], F_SETFD, fl & ~FD_CLOEXEC) < 0) return fail(1, "сокет launchd", strerror(errno));
            snprintf(fdtxt[i], sizeof fdtxt[i], "%d", fds[i]);
            args[n++] = "--fd";
            args[n++] = fdtxt[i];
        }
    }
    args[n] = NULL;
    char *envp[] = {envhome, CHILD_PATH, NULL};

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = forward;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    pid_t pid = fork();
    if (pid < 0) return fail(1, "fork", strerror(errno));
    if (pid == 0) {
        signal(SIGTERM, SIG_DFL);
        signal(SIGINT, SIG_DFL);
        signal(SIGHUP, SIG_DFL);
        execve("/bin/sh", args, envp);
        fprintf(stderr, "pantheon-hookd: /bin/sh не запустился: %s\n", strerror(errno));
        _exit(127);
    }
    child = pid;
    /* соединения принимает только демон-ребёнок: своих копий сокетов обёртке не нужно */
    for (size_t i = 0; i < cnt; i++) close(fds[i]);
    free(fds);
    int status;
    for (;;) {
        pid_t w = waitpid(pid, &status, 0);
        if (w == pid) break;
        if (w < 0 && errno != EINTR) return fail(1, "waitpid", strerror(errno));
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}
