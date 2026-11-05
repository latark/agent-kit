/* Исполняемый файл службы демона хуков pantheon.svc.hookd (metis-0811, решение владельца 04.11 по Д-A2, TCC).
 * Собирает hooks/hookd-build.sh --svc в ~/.cache/pantheon/hookd/bin/pantheon-hookd — путь постоянный, от версии
 * плагина и Python не зависит. Его зовёт launchd (ProgramArguments plist), руками его не запускают.
 *
 *   pantheon-hookd <папка hooks>                         служба: сокеты launchd → демон
 *   pantheon-hookd <папка hooks> --tcc-probe <файл>      проба доступа к папкам под TCC → файл (hookd-install.sh)
 *
 * Зачем он. Права «Файлы и папки» (Desktop, Documents, Downloads, iCloud Drive) macOS даёт ответственному процессу —
 * у службы launchd это первый процесс задания. Раньше им был /bin/sh python.sh, который делал exec в Python: разрешение
 * получал Python.app Homebrew. Его подпись — ad-hoc (cdhash), путь — с номером версии в Cellar: после `brew upgrade`
 * разрешение слетало бы, а то же разрешение получали бы все прочие задания launchd на этом Python. Этот файл не делает
 * exec: он остаётся родителем, а Python — его ребёнком, и macOS спрашивает и помнит разрешение для pantheon-hookd.
 * Пересобирается он только при правке этого исходника (метка pantheon-hookd.src): тогда macOS спросит снова.
 *
 * Служба: сокеты берёт сам (launch_activate_socket «Listeners»), снимает с них FD_CLOEXEC и запускает ребёнком
 * `/bin/sh <hooks>/python.sh <hooks>/daemon.py --fd <n> …`. Свои копии сокетов закрывает, ждёт ребёнка, SIGTERM,
 * SIGINT и SIGHUP передаёт ему. Код выхода — код ребёнка (сигнал — 128 + номер). Сбой — код не 0 и причина в stderr
 * (у службы — ~/.local/state/pantheon/logs/svc-hookd.log): клиенты в это время идут медленным путём (F1).
 * Проба: ребёнок `daemon.py --tcc-probe <файл>`, без сокетов. Без зависимостей: cc -O2 -o pantheon-hookd hookd-svc.c. */
#include <errno.h>
#include <fcntl.h>
#include <launch.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_FDS 8

static volatile pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

static int fail(int code, const char *what, const char *detail) {
    fprintf(stderr, "pantheon-hookd: %s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    return code;
}

int main(int argc, char **argv) {
    int probe = argc == 4 && strcmp(argv[2], "--tcc-probe") == 0;
    if (!(argc == 2 || probe) || argv[1][0] != '/')
        return fail(64, "нужно <папка hooks, абсолютный путь> [--tcc-probe <файл>]", NULL);
    char py[PATH_MAX], dm[PATH_MAX];
    if ((size_t)snprintf(py, sizeof py, "%s/python.sh", argv[1]) >= sizeof py
        || (size_t)snprintf(dm, sizeof dm, "%s/daemon.py", argv[1]) >= sizeof dm)
        return fail(64, "путь папки hooks слишком длинный", NULL);

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
        args[n++] = argv[3];
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
        execv("/bin/sh", args);
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
