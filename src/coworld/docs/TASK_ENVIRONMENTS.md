# Episode-owned task environments

A game can declare isolated execution environments in `game.task_environments`. The hosted platform supplies
`COWORLD_TASK_ENDPOINT` and `COWORLD_TASK_TOKEN` to that game. Players and task containers receive neither value. This
capability is undergoing hosted qualification; code availability does not establish deployment availability.

```json
{
  "task_environments": {
    "agent": {
      "image": "registry.example/task@sha256:<64-hex-digest>",
      "cpu_millis": 1000,
      "memory_mib": 4096,
      "storage_mib": 10240,
      "max_instances": 131,
      "max_concurrent_instances": 1,
      "startup_timeout_seconds": 1200,
      "network": "public",
      "network_transitions": ["no-network", "public"]
    }
  }
}
```

The example is the `game` object's task declaration, not a complete manifest. Use registered image identities when
uploading; normal image resolution supplies digest-pinned references to the runtime. Resource requests equal limits.
Instance budgets count every creation, including failed or closed instances. They cannot be renewed during an episode.

Every request requires `Authorization: Bearer $COWORLD_TASK_TOKEN`. The endpoint is local to the game Pod.

| Operation     | Request                                                                                                                    |
| ------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Create        | `POST /tasks`, JSON `{"definition":"agent","key":"trial-agent"}`                                                           |
| Execute       | `POST /tasks/trial-agent/exec`, JSON `{"command":["/bin/bash","-lc","pwd"],"timeout_seconds":30,"max_output_bytes":65536}` |
| Upload file   | `PUT /tasks/trial-agent/file?path=/tmp/input`, raw bytes                                                                   |
| Download file | `GET /tasks/trial-agent/file?path=/tmp/output`                                                                             |
| Change phase  | `POST /tasks/trial-agent/network`, JSON `{"mode":"no-network"}`                                                            |
| Close         | `DELETE /tasks/trial-agent`                                                                                                |
| Close all     | `DELETE /tasks`                                                                                                            |

A successful command returns `kind: completed`, stdout, stderr, and its exit code. A nonzero exit code remains a command
result. Infrastructure failures have distinct kinds and close the environment. Command output is limited to 1 MiB; files
are streamed with a 200 MiB limit. Paths must be absolute. JSON bodies are limited to 64 KiB.

Creation is idempotent for a key and definition. A closed key stays closed. Fresh verification uses a new key; it never
reuses the agent's filesystem. Startup and command budgets are separate and both stop at the episode deadline.

The only network modes are public IPv4 and offline. Public access excludes private, reserved, loopback, and metadata
addresses outside the container's own loopback. IPv6 is blocked except loopback. Phase changes must follow the declared
sequence. The trusted guard enforces outbound restrictions independently of task commands.

Task execution runs in separate Pods, allowing offline task phases while the game continues communicating with players.
A loopback task-control sidecar owns creation, execution, evidence, and deletion. Task processes have no Docker socket,
Kubernetes token, or network-administration capability. A read-only PID 1 supervisor independently expires each task;
Kubernetes deadlines, parent ownership, and explicit cleanup provide additional bounds. Activity never extends expiry.

The worker archives task identity, status, and command results with episode debug artifacts. Games should close tasks as
soon as their phase ends. Game completion, cancellation, or worker termination also triggers cleanup. Tasks do not count
as scored players.

The initial profile supports single-container CPU Linux tasks. Compose, GPU, persistent runtimes, and local Docker
execution through this interface are not supported. Native benchmark releases must qualify their own task shapes,
network transitions, filesystem transfers, and grading semantics before activation.

`max_instances` is the lifetime creation budget (up to 1024), including failed and closed tasks.
`max_concurrent_instances` limits simultaneous pods (one or two, default two); terminating pods still count. For full
benchmark panels, declare the complete creation budget and close each sandbox before creating the next. A rejected
create with `concurrency_budget_exhausted` creates no instance; retry creation after the previous pod is removed. Closed
task keys remain closed, and uncertain commands must never be repeated as fresh scoring executions.
