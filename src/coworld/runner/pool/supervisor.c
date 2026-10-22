#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Runs as PID 1 in the game container's private PID namespace. The coordinator
 * alone mounts the root-owned control directory; game children run as 65532. */
#define CONTROL "/var/run/coworld-pool"
#define MAX_PACKET (1024 * 1024)
#define MAX_STRINGS 4096
static unsigned char packet[MAX_PACKET];
static size_t cursor, length;
static pid_t game_pid;
static int state, exit_code;
static char assignment[128];
static double deadline;
extern char **environ;

static void require(int ok, const char *operation) {
  if (!ok) {
    perror(operation);
    exit(1);
  }
}

static double now(void) {
  struct timespec ts;
  require(clock_gettime(CLOCK_MONOTONIC, &ts) == 0, "clock_gettime");
  return ts.tv_sec + ts.tv_nsec / 1e9;
}

static uint32_t number(void) {
  require(cursor + 4 <= length, "truncated request");
  uint32_t value;
  memcpy(&value, packet + cursor, 4);
  cursor += 4;
  return ntohl(value);
}

static char *string(void) {
  uint32_t size = number();
  require(size > 0 && cursor + size <= length, "invalid string length");
  char *value = (char *)packet + cursor;
  require(value[size - 1] == 0 && memchr(value, 0, size - 1) == NULL,
          "invalid string");
  cursor += size;
  return value;
}

static char **strings(void) {
  uint32_t count = number();
  require(count <= MAX_STRINGS, "too many strings");
  char **values = calloc(count + 1, sizeof(char *));
  require(values != NULL, "calloc");
  for (uint32_t i = 0; i < count; i++)
    values[i] = string();
  return values;
}

static void reap(void) {
  int status;
  pid_t pid;
  while ((pid = waitpid(-1, &status, WNOHANG)) > 0) {
    if (pid == game_pid) {
      state = 2;
      exit_code =
          WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
    }
  }
  require(pid == 0 || errno == ECHILD, "waitpid");
}

static void stop(void) {
  double until = now() + 5;
  for (;;) {
    int killed = kill(-1, SIGKILL);
    require(killed == 0 || errno == ESRCH, "kill namespace processes");
    int kill_error = errno;
    reap();
    if (killed < 0 && kill_error == ESRCH)
      break;
    require(now() < until, "game process cleanup deadline");
    struct timespec pause = {.tv_nsec = 1000000};
    nanosleep(&pause, NULL);
  }
  reap();
  state = 3;
}

/* Kernel IPC and user keyrings outlive processes. Qualified games use files in
 * the cleaned workspace and /dev/shm; reject these persistent kernel stores. */
static void restrict_game(void) {
#define DENY_CALL(call)                                                        \
  BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, call, 0, 1),                             \
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)
#if defined(__x86_64__)
#define NATIVE_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define NATIVE_ARCH AUDIT_ARCH_AARCH64
#else
#error Unsupported supervisor architecture
#endif
  struct sock_filter instructions[] = {
      BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
      BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, NATIVE_ARCH, 1, 0),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
      BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
      BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, 0x40000000, 0, 1),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
      DENY_CALL(__NR_shmget),
      DENY_CALL(__NR_shmat),
      DENY_CALL(__NR_shmctl),
      DENY_CALL(__NR_semget),
      DENY_CALL(__NR_semctl),
      DENY_CALL(__NR_semop),
      DENY_CALL(__NR_semtimedop),
      DENY_CALL(__NR_msgget),
      DENY_CALL(__NR_msgsnd),
      DENY_CALL(__NR_msgrcv),
      DENY_CALL(__NR_msgctl),
      DENY_CALL(__NR_mq_open),
      DENY_CALL(__NR_mq_unlink),
      DENY_CALL(__NR_mq_timedsend),
      DENY_CALL(__NR_mq_timedreceive),
      DENY_CALL(__NR_mq_notify),
      DENY_CALL(__NR_mq_getsetattr),
      DENY_CALL(__NR_add_key),
      DENY_CALL(__NR_request_key),
      DENY_CALL(__NR_keyctl),
      BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
  };
  struct sock_fprog program = {
      .len = sizeof(instructions) / sizeof(instructions[0]),
      .filter = instructions,
  };
  require(prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) == 0,
          "game IPC restrictions");
}

static void start(char *key) {
  uint32_t timeout = number();
  char *cwd = string();
  char **argv = strings();
  char **env = strings();
  require(cursor == length && argv[0] != NULL && timeout > 0,
          "invalid launch request");
  /* A repeated start observes the same process; it never executes it twice. */
  if (strcmp(key, assignment) == 0) {
    free(argv);
    free(env);
    return;
  }
  require(state == 0 || state == 3, "previous assignment not cleaned");
  require(strlen(key) < sizeof(assignment), "assignment too long");
  strcpy(assignment, key);
  int out =
      open(CONTROL "/stdout", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0600);
  int err =
      open(CONTROL "/stderr", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0600);
  require(out >= 0 && err >= 0, "open episode logs");
  game_pid = fork();
  require(game_pid >= 0, "fork");
  if (game_pid == 0) {
    require(dup2(out, STDOUT_FILENO) >= 0 && dup2(err, STDERR_FILENO) >= 0,
            "redirect game logs");
    close(out);
    close(err);
    require(setgroups(0, NULL) == 0 && setgid(65532) == 0 && setuid(65532) == 0,
            "drop game identity");
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "no_new_privs");
    restrict_game();
    require(chdir(cwd) == 0, "game working directory");
    environ = env;
    execvp(argv[0], argv);
    perror("exec game");
    _exit(127);
  }
  close(out);
  close(err);
  free(argv);
  free(env);
  state = 1;
  exit_code = 0;
  deadline = now() + timeout;
}

int main(void) {
  require(getpid() == 1 && geteuid() == 0, "supervisor requires root PID 1");
  umask(0077);
  require(chmod(CONTROL, 0700) == 0, "protect control directory");
  int server = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  require(server >= 0, "socket");
  struct sockaddr_un address = {.sun_family = AF_UNIX};
  strcpy(address.sun_path, CONTROL "/control.pending");
  require(bind(server, (struct sockaddr *)&address, sizeof(address)) == 0,
          "bind control socket");
  require(listen(server, 4) == 0, "listen");
  require(rename(CONTROL "/control.pending", CONTROL "/control.sock") == 0,
          "publish control socket");
  double idle_deadline = now() + 600;
  for (;;) {
    reap();
    /* The deadline also bounds descendants that outlive an exited leader; only
     * a leader still running is reported as timed out. */
    if ((state == 1 || state == 2) && now() >= deadline) {
      int leader_exit = state == 1 ? 124 : exit_code;
      stop();
      exit_code = leader_exit;
      idle_deadline = now() + 600;
    }
    if ((state == 0 || state == 3) && now() >= idle_deadline)
      return 0;
    struct pollfd watched = {.fd = server, .events = POLLIN};
    int ready = poll(&watched, 1, 100);
    require(ready >= 0 || errno == EINTR, "poll");
    if (ready <= 0)
      continue;
    int connection = accept4(server, NULL, NULL, SOCK_CLOEXEC);
    require(connection >= 0, "accept");
    struct ucred peer;
    socklen_t peer_size = sizeof(peer);
    require(getsockopt(connection, SOL_SOCKET, SO_PEERCRED, &peer,
                       &peer_size) == 0 &&
                peer.uid == 0,
            "unauthorized control peer");
    struct timeval timeout = {.tv_sec = 5};
    require(setsockopt(connection, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                       sizeof(timeout)) == 0,
            "control timeout");
    ssize_t received = recv(connection, packet, sizeof(packet), MSG_TRUNC);
    require(received > 0 && received <= MAX_PACKET, "invalid control packet");
    length = (size_t)received;
    cursor = 0;
    require(number() == 1, "unsupported protocol version");
    uint32_t operation = number();
    char *key = string();
    if (operation == 0) {
      require(cursor == length, "invalid inspect request");
      idle_deadline = now() + 600;
    } else if (operation == 1)
      start(key);
    else {
      require(cursor == length && strcmp(key, assignment) == 0,
              "assignment changed");
      if (operation == 3) {
        stop();
        idle_deadline = now() + 600;
      } else
        require(operation == 2, "unknown operation");
    }
    uint32_t response[3] = {htonl(state), htonl(game_pid), htonl(exit_code)};
    require(send(connection, response, sizeof(response), MSG_NOSIGNAL) ==
                sizeof(response),
            "control response");
    close(connection);
  }
}
