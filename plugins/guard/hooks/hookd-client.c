/* Клиент демона хуков guard (metis-0330, этап 2, ступень 2). Собирает hooks/hookd-build.sh в кэш вне дерева плагина
 * (~/.cache/pantheon/hookd/bin/client-<SRC>), зовёт hooks/hookd.sh — напрямую его не запускают.
 *
 *   client-<SRC> <сокет> <папка hooks> [аргументы guard…]      событие — на stdin, как у guard.py
 *
 * Принцип F1 (README guard): демон только ускоряет. Клиент читает stdin целиком и спрашивает демона; любой сбой
 * (каталог сокета чужой или открыт группе и прочим, нет сокета, нет «принят» за 300 мс, нет решения за 8,5 с, обрыв,
 * мусор, ответ «F <причина>») — строка «время<TAB>причина» в ~/.local/state/pantheon/logs/hookd-fallback.log (без
 * текста события) и медленный путь: /bin/sh <hooks>/python.sh <hooks>/guard.py <аргументы> с тем же stdin. Его код,
 * stdout и stderr — ответ клиента. Медленный путь не запустился (126, 127) или убит — двойной отказ: код 2 и причина,
 * запрет одного вызова. Коды 126 и 127 клиент не возвращает никогда: оболочка hookd.sh читает их как «клиент не
 * запустился» и сама идёт медленным путём, а stdin уже прочитан.
 * Канарейка: 1 вызов из PANTHEON_HOOKD_CANARY (по умолчанию 100; 0 — выключена) идёт обоими путями. Отдаётся решение
 * медленного пути; разошлись код, stdout или stderr — строка «время<TAB>canary-diff<TAB><хеш события FNV-1a 64>
 * <TAB>slow=<код>:<решение><TAB>daemon=<код>:<решение>» в тот же журнал.
 * Каждый read и write сокета — в пределах срока (сокет неблокирующий): демон, который завис и не читает запрос,
 * держит вызов не дольше 300 мс + 8,5 с (причина send), а не до таймаута хука.
 * Протокол — шапка hooks/daemon.py. Без зависимостей: cc -O2 -o client hookd-client.c. */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define ACK_MS 300
#define DECIDE_MS 8500
#define MAX_REQ (8u * 1024u * 1024u)
#define CANARY_DEFAULT 100

extern char **environ;

typedef struct { char *p; size_t n, cap; } buf_t;

static void put(buf_t *b, const char *s, size_t n) {
    if (b->n + n + 1 > b->cap) {
        size_t cap = (b->n + n + 1) * 2;
        char *p = realloc(b->p, cap);
        if (!p) { fputs("guard: клиент демона: нет памяти — действие остановлено.\n", stderr); _exit(2); }
        b->p = p; b->cap = cap;
    }
    if (n) memcpy(b->p + b->n, s, n);
    b->n += n; b->p[b->n] = 0;
}
static void puts_(buf_t *b, const char *s) { put(b, s, strlen(s)); }
static void put_json_str(buf_t *b, const char *s, size_t n) {
    put(b, "\"", 1);
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        char e[8];
        if (c == '"' || c == '\\') { e[0] = '\\'; e[1] = (char)c; put(b, e, 2); }
        else if (c < 0x20 || c == 0x7f) { snprintf(e, sizeof e, "\\u%04x", c); put(b, e, 6); }
        else put(b, (const char *)&c, 1);
    }
    put(b, "\"", 1);
}

static buf_t in;            /* stdin целиком */
static const char *hooks;   /* папка hooks плагина */
static int g_argc; static char **g_argv;

static long long now_ms(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (long long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

/* --- журнал откатов ----------------------------------------------------------------------------------------- */
static void log_line(const char *what) {
    const char *home = getenv("HOME");
    char path[4096], ts[32];
    if (!home || !*home) { fprintf(stderr, "hookd: %s — HOME пуст, строку в hookd-fallback.log не записать\n", what); return; }
    const char *parts[] = {"/.local", "/.local/state", "/.local/state/pantheon", "/.local/state/pantheon/logs"};
    for (size_t i = 0; i < sizeof parts / sizeof *parts; i++) {
        snprintf(path, sizeof path, "%s%s", home, parts[i]);
        mkdir(path, 0755);
    }
    snprintf(path, sizeof path, "%s/.local/state/pantheon/logs/hookd-fallback.log", home);
    time_t t = time(0); struct tm tm; localtime_r(&t, &tm);
    strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%S", &tm);
    char line[1024];
    int k = snprintf(line, sizeof line, "%s\t%s\n", ts, what);
    if (k < 0) return;
    if ((size_t)k >= sizeof line) k = sizeof line - 1;
    int fd = open(path, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0644);
    if (fd < 0 || write(fd, line, (size_t)k) != k)  /* одна запись O_APPEND — строки разных вызовов не смешиваются */
        fprintf(stderr, "hookd: %s — строку в hookd-fallback.log записать не удалось\n", what);
    if (fd >= 0) close(fd);
}

/* --- ввод-вывод со сроком ------------------------------------------------------------------------------------- */
/* Сокет демона после connect — O_NONBLOCK: после poll write берёт столько, сколько влезло в буфер, и не ждёт. Блокирующий
 * write писал бы весь остаток и ждал демон, который завис и не читает, мимо срока (argus, PR 307): буфер AF_UNIX на
 * macOS — около 8 КБ, и stdin больше него держал вызов до таймаута хука 10 с. EAGAIN — снова poll до срока. */
static int wait_fd(int fd, short ev, long long deadline) {
    for (;;) {
        long long left = deadline - now_ms();
        if (left <= 0) return 0;
        struct pollfd p = {fd, ev, 0};
        int r = poll(&p, 1, (int)left);
        if (r > 0) return 1;
        if (r < 0 && errno != EINTR) return 0;
        if (r == 0) return 0;
    }
}
static int read_line(int fd, char *out, size_t cap, long long deadline) {
    size_t n = 0;
    while (n + 1 < cap) {
        if (!wait_fd(fd, POLLIN, deadline)) return -1;
        ssize_t k = read(fd, out + n, 1);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) return -1;
        if (out[n] == '\n') { out[n] = 0; return 0; }
        n++;
    }
    return -1;
}
static int read_exact(int fd, char *out, size_t n, long long deadline) {
    size_t o = 0;
    while (o < n) {
        if (!wait_fd(fd, POLLIN, deadline)) return -1;
        ssize_t k = read(fd, out + o, n - o);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) return -1;
        o += (size_t)k;
    }
    return 0;
}
static int write_all_deadline(int fd, const char *p, size_t n, long long deadline) {
    size_t o = 0;
    while (o < n) {
        if (!wait_fd(fd, POLLOUT, deadline)) return -1;
        ssize_t k = write(fd, p + o, n - o);
        if (k < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (k <= 0) return -1;
        o += (size_t)k;
    }
    return 0;
}
static void write_all(int fd, const char *p, size_t n) {
    size_t o = 0;
    while (o < n) {
        ssize_t k = write(fd, p + o, n - o);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) return;
        o += (size_t)k;
    }
}

/* --- ответ ---------------------------------------------------------------------------------------------------- */
typedef struct { int code; buf_t out, err; } result_t;

static const char *decision(const result_t *r) {
    if (r->code == 2 || (r->out.p && strstr(r->out.p, "\"deny\""))) return "deny";
    if (r->out.p && strstr(r->out.p, "\"ask\"")) return "ask";
    return "allow";
}

/* --- медленный путь ------------------------------------------------------------------------------------------- */
/* Запуск python.sh guard.py с тем же stdin. capture — собрать stdout и stderr в r (канарейка), иначе они идут прямо
 * в наши. Код: код медленного пути; не запустился (126, 127) или убит — 2 и причина (двойной отказ). */
static void run_slow(result_t *r, int capture) {
    char sh[4096], py[4096];
    snprintf(sh, sizeof sh, "%s/python.sh", hooks);
    snprintf(py, sizeof py, "%s/guard.py", hooks);
    int pin[2], pout[2] = {-1, -1}, perr[2] = {-1, -1};
    memset(r, 0, sizeof *r);
    r->code = 2;
    if (pipe(pin) != 0 || (capture && (pipe(pout) != 0 || pipe(perr) != 0))) goto fail;
    fflush(stdout); fflush(stderr);
    pid_t pid = fork();
    if (pid < 0) goto fail;
    if (pid == 0) {
        signal(SIGPIPE, SIG_DFL);
        dup2(pin[0], 0);
        if (capture) { dup2(pout[1], 1); dup2(perr[1], 2); }
        close(pin[0]); close(pin[1]);
        if (capture) { close(pout[0]); close(pout[1]); close(perr[0]); close(perr[1]); }
        char **av = calloc((size_t)g_argc + 4, sizeof *av);
        if (!av) _exit(127);
        int k = 0;
        av[k++] = "/bin/sh"; av[k++] = sh; av[k++] = py;
        for (int i = 3; i < g_argc; i++) av[k++] = g_argv[i];
        av[k] = 0;
        execv("/bin/sh", av);
        _exit(127);
    }
    close(pin[0]);
    if (capture) { close(pout[1]); close(perr[1]); }
    fcntl(pin[1], F_SETFL, fcntl(pin[1], F_GETFL) | O_NONBLOCK);
    size_t sent = 0;
    int fin = pin[1];
    if (in.n == 0) { close(fin); fin = -1; }
    int fo = capture ? pout[0] : -1, fe = capture ? perr[0] : -1;
    char tmp[65536];
    while (fin >= 0 || fo >= 0 || fe >= 0) {
        struct pollfd p[3]; int np = 0, ii = -1, io = -1, ie = -1;
        if (fin >= 0) { ii = np; p[np++] = (struct pollfd){fin, POLLOUT, 0}; }
        if (fo >= 0) { io = np; p[np++] = (struct pollfd){fo, POLLIN, 0}; }
        if (fe >= 0) { ie = np; p[np++] = (struct pollfd){fe, POLLIN, 0}; }
        if (poll(p, (nfds_t)np, -1) < 0) { if (errno == EINTR) continue; break; }
        if (ii >= 0 && p[ii].revents) {
            ssize_t k = write(fin, in.p + sent, in.n - sent);
            if (k > 0) sent += (size_t)k;
            if ((k < 0 && errno != EAGAIN && errno != EINTR) || sent >= in.n || (p[ii].revents & (POLLERR | POLLHUP))) {
                close(fin); fin = -1;  /* медленный путь не дочитал stdin (вышел раньше) — это его дело */
            }
        }
        if (io >= 0 && p[io].revents) {
            ssize_t k = read(fo, tmp, sizeof tmp);
            if (k > 0) put(&r->out, tmp, (size_t)k); else if (k == 0 || errno != EINTR) { close(fo); fo = -1; }
        }
        if (ie >= 0 && p[ie].revents) {
            ssize_t k = read(fe, tmp, sizeof tmp);
            if (k > 0) put(&r->err, tmp, (size_t)k); else if (k == 0 || errno != EINTR) { close(fe); fe = -1; }
        }
    }
    int st = 0;
    while (waitpid(pid, &st, 0) < 0 && errno == EINTR) {}
    if (WIFEXITED(st) && WEXITSTATUS(st) != 126 && WEXITSTATUS(st) != 127) { r->code = WEXITSTATUS(st); return; }
    if (WIFEXITED(st)) {
        char m[256];
        snprintf(m, sizeof m, "guard: демон и медленный путь недоступны (python.sh: код %d) — действие остановлено.\n",
                 WEXITSTATUS(st));
        if (capture) puts_(&r->err, m); else fputs(m, stderr);
        log_line("slow-exec");
    } else {
        char m[256];
        snprintf(m, sizeof m, "guard: медленный путь прерван сигналом %d — действие остановлено.\n",
                 WIFSIGNALED(st) ? WTERMSIG(st) : 0);
        if (capture) puts_(&r->err, m); else fputs(m, stderr);
        log_line("slow-signal");
    }
    r->code = 2;
    return;
fail:
    fputs("guard: демон и медленный путь недоступны (pipe/fork) — действие остановлено.\n", stderr);
    log_line("slow-fork");
    r->code = 2;
}

static int fallback(const char *why) {
    log_line(why);
    result_t r;
    run_slow(&r, 0);
    return r.code;
}

/* --- демон ---------------------------------------------------------------------------------------------------- */
static void plugin_version(char *out, size_t cap) {
    char path[4096];
    out[0] = 0;
    snprintf(path, sizeof path, "%s/../.claude-plugin/plugin.json", hooks);
    FILE *f = fopen(path, "r");
    if (!f) return;
    char data[16384];
    size_t n = fread(data, 1, sizeof data - 1, f);
    fclose(f);
    data[n] = 0;
    char *p = strstr(data, "\"version\"");
    if (!p) return;
    p += 9;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p++ != ':') return;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p++ != '"') return;
    size_t k = 0;
    while (*p && *p != '"' && *p != '\\' && k + 1 < cap) out[k++] = *p++;
    if (*p != '"') { out[0] = 0; return; }
    out[k] = 0;
}

/* Причина отказа демона из строки «F <причина>»: только [a-z-], иначе proto. */
static const char *reason_of(const char *line, char *buf, size_t cap) {
    if (strncmp(line, "F ", 2) != 0) return "proto";
    const char *s = line + 2;
    size_t n = strlen(s);
    if (n == 0 || n >= cap) return "proto";
    for (size_t i = 0; i < n; i++) if (!((s[i] >= 'a' && s[i] <= 'z') || s[i] == '-')) return "proto";
    memcpy(buf, s, n + 1);
    return buf;
}

/* Решение демона в r; 0 — есть, иначе причина отката (статическая строка или why_buf). */
static const char *ask_daemon(const char *sock, result_t *r, char *why_buf, size_t why_cap) {
    memset(r, 0, sizeof *r);
    char dir[1024];
    if (strlen(sock) >= sizeof dir) return "path-long";
    snprintf(dir, sizeof dir, "%s", sock);
    char *sl = strrchr(dir, '/');
    if (!sl || sl == dir) return "dir-perm";
    *sl = 0;
    struct stat st;
    if (lstat(dir, &st) != 0) return "no-socket";
    if (!S_ISDIR(st.st_mode) || st.st_uid != getuid() || (st.st_mode & 077)) return "dir-perm";
    struct sockaddr_un a;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    if (strlen(sock) >= sizeof a.sun_path) return "path-long";
    memcpy(a.sun_path, sock, strlen(sock) + 1);

    /* шапка до соединения: слишком большой запрос — сразу медленный путь */
    char ver[256];
    plugin_version(ver, sizeof ver);
    buf_t h = {0};
    char cwd[4096];
    puts_(&h, "{\"argv\":[");
    for (int i = 3; i < g_argc; i++) { if (i > 3) puts_(&h, ","); put_json_str(&h, g_argv[i], strlen(g_argv[i])); }
    puts_(&h, "],\"cwd\":");
    if (!getcwd(cwd, sizeof cwd)) { free(h.p); return "cwd"; }
    put_json_str(&h, cwd, strlen(cwd));
    puts_(&h, ",\"hooks\":"); put_json_str(&h, hooks, strlen(hooks));
    puts_(&h, ",\"version\":"); put_json_str(&h, ver, strlen(ver));
    mode_t um = umask(0);
    umask(um);
    char ums[32];
    snprintf(ums, sizeof ums, ",\"umask\":%u", (unsigned)um);
    puts_(&h, ums);
    puts_(&h, ",\"env\":{");
    int first = 1;
    for (char **e = environ; *e; e++) {
        char *eq = strchr(*e, '=');
        if (!eq) continue;
        if (!first) puts_(&h, ",");
        first = 0;
        put_json_str(&h, *e, (size_t)(eq - *e)); puts_(&h, ":"); put_json_str(&h, eq + 1, strlen(eq + 1));
    }
    puts_(&h, "}}");
    if (h.n + in.n > MAX_REQ) { free(h.p); return "big"; }

    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    if (s < 0) { free(h.p); return "socket"; }
    fcntl(s, F_SETFD, FD_CLOEXEC);
#ifdef SO_NOSIGPIPE
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#endif
    if (connect(s, (struct sockaddr *)&a, sizeof a) != 0) {
        int e = errno;
        close(s); free(h.p);
        return e == ENOENT ? "no-socket" : e == ECONNREFUSED ? "refused" : "connect";
    }
    fcntl(s, F_SETFL, fcntl(s, F_GETFL) | O_NONBLOCK);  /* срок держат poll и запись кусками, а не блокирующий write */
    char line[256];
    if (read_line(s, line, sizeof line, now_ms() + ACK_MS) != 0) { close(s); free(h.p); return "no-ack"; }
    if (strcmp(line, "A") != 0) { close(s); free(h.p); return reason_of(line, why_buf, why_cap); }
    long long deadline = now_ms() + DECIDE_MS;
    char head[64];
    int hn = snprintf(head, sizeof head, "G2 %zu %zu\n", h.n, in.n);
    if (write_all_deadline(s, head, (size_t)hn, deadline) || write_all_deadline(s, h.p, h.n, deadline)
        || write_all_deadline(s, in.p ? in.p : "", in.n, deadline)) {
        /* демон отказал посреди запроса (F big и т. п.) — его причина, если успел */
        free(h.p);
        if (read_line(s, line, sizeof line, now_ms() + 50) == 0) { close(s); return reason_of(line, why_buf, why_cap); }
        close(s);
        return "send";
    }
    free(h.p);
    if (read_line(s, line, sizeof line, deadline) != 0) { close(s); return "no-reply"; }
    int code; size_t no, ne; char tail;
    if (line[0] == 'F') { close(s); return reason_of(line, why_buf, why_cap); }
    if (sscanf(line, "X %d %zu %zu%c", &code, &no, &ne, &tail) != 3 || code < 0 || code > 255
        || no > MAX_REQ || ne > MAX_REQ) { close(s); return "proto"; }
    char *o = malloc(no + 1), *er = malloc(ne + 1);
    if (!o || !er || read_exact(s, o, no, deadline) || read_exact(s, er, ne, deadline)) {
        free(o); free(er); close(s); return "short-reply";
    }
    close(s);
    put(&r->out, o, no); put(&r->err, er, ne);
    free(o); free(er);
    r->code = code;
    return 0;
}

static uint64_t fnv1a(const char *p, size_t n) {
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) { h ^= (unsigned char)p[i]; h *= 1099511628211ULL; }
    return h;
}

static int canary_hit(void) {
    const char *v = getenv("PANTHEON_HOOKD_CANARY");
    long n = CANARY_DEFAULT;
    if (v && *v) {
        char *end;
        long x = strtol(v, &end, 10);
        if (*end == 0 && x >= 0) n = x;
    }
    if (n <= 0) return 0;
    if (n == 1) return 1;
    struct timespec t; clock_gettime(CLOCK_REALTIME, &t);
    uint64_t z = ((uint64_t)t.tv_nsec << 20) ^ (uint64_t)t.tv_sec ^ ((uint64_t)getpid() << 40);
    z += 0x9e3779b97f4a7c15ULL;  /* splitmix64 */
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    z ^= z >> 31;
    return z % (uint64_t)n == 0;
}

static int same(const result_t *a, const result_t *b) {
    return a->code == b->code && a->out.n == b->out.n && a->err.n == b->err.n
        && (a->out.n == 0 || memcmp(a->out.p, b->out.p, a->out.n) == 0)
        && (a->err.n == 0 || memcmp(a->err.p, b->err.p, a->err.n) == 0);
}

int main(int argc, char **argv) {
    g_argc = argc; g_argv = argv;
    signal(SIGPIPE, SIG_IGN);
    char tmp[65536];
    for (;;) {
        ssize_t k = read(0, tmp, sizeof tmp);
        if (k < 0 && errno == EINTR) continue;
        if (k <= 0) break;
        put(&in, tmp, (size_t)k);
    }
    if (argc < 3) {
        fputs("hookd-client: нужно <сокет> <папка hooks> [аргументы guard…] — действие остановлено.\n", stderr);
        log_line("usage");
        return 2;
    }
    hooks = argv[2];
    char why_buf[64];
    result_t d;
    const char *why = ask_daemon(argv[1], &d, why_buf, sizeof why_buf);
    if (why) return fallback(why);
    if (canary_hit()) {
        result_t s;
        run_slow(&s, 1);
        if (!same(&s, &d)) {
            char m[256];
            snprintf(m, sizeof m, "canary-diff\t%016llx\tslow=%d:%s\tdaemon=%d:%s",
                     (unsigned long long)fnv1a(in.p ? in.p : "", in.n), s.code, decision(&s), d.code, decision(&d));
            log_line(m);
        }
        d = s;  /* вызывающему — решение медленного пути */
    }
    write_all(1, d.out.p ? d.out.p : "", d.out.n);
    write_all(2, d.err.p ? d.err.p : "", d.err.n);
    return d.code == 126 || d.code == 127 ? 2 : d.code;
}
