#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* PID 1 owns the namespace lifetime, even when the container runtime cannot
 * service a stop request. Exec'd task processes cannot replace this deadline. */
static void reap(int signal_number) {
  (void)signal_number;
  int saved_errno = errno;
  while (waitpid(-1, NULL, WNOHANG) > 0) {}
  errno = saved_errno;
}

static void stop(int signal_number) {
  (void)signal_number;
  _exit(0);
}

int main(int argc, char **argv) {
  if (argc != 2 || getpid() != 1) {
    fputs("task supervisor requires PID 1 and an absolute expiry\n", stderr);
    return 1;
  }
  char *end;
  errno = 0;
  long expiry = strtol(argv[1], &end, 10);
  if (errno || *end || expiry <= 0 || prctl(PR_SET_DUMPABLE, 0) != 0) {
    fputs("invalid task lifetime\n", stderr);
    return 1;
  }
  struct sigaction child = {.sa_handler = reap, .sa_flags = SA_NOCLDSTOP};
  struct sigaction terminate = {.sa_handler = stop};
  if (sigemptyset(&child.sa_mask) || sigemptyset(&terminate.sa_mask) ||
      sigaction(SIGCHLD, &child, NULL) || sigaction(SIGTERM, &terminate, NULL) ||
      sigaction(SIGINT, &terminate, NULL)) {
    perror("task signal handlers");
    return 1;
  }
  struct timespec deadline = {.tv_sec = expiry};
  int result;
  do {
    result = clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &deadline, NULL);
  } while (result == EINTR);
  if (result) {
    errno = result;
    perror("task deadline");
    return 1;
  }
  _exit(124);
}
