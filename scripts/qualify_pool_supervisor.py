"""Manually qualify pooled-game isolation using prebuilt images and real Docker processes."""

import argparse
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


def qualify_supervisor(coordinator_image: str, game_image: str, tmp_path: Path) -> None:
    name = f"xp-pool-system-{uuid4().hex[:12]}"
    volumes = {kind: f"{name}-{kind}" for kind in ("control", "work", "tmp", "shm")}
    mounts = [
        argument
        for kind, path in (
            ("control", "/var/run/coworld-pool"),
            ("work", "/coworld"),
            ("tmp", "/tmp"),
            ("shm", "/dev/shm"),
        )
        for argument in ("-v", f"{volumes[kind]}:{path}")
    ]
    copy_container = f"{name}-copy"
    subprocess.run(["docker", "create", "--name", copy_container, coordinator_image], check=True, capture_output=True)
    try:
        subprocess.run(
            ["docker", "cp", f"{copy_container}:/opt/coworld-supervisor", str(tmp_path / "supervisor")], check=True
        )
    finally:
        subprocess.run(["docker", "rm", copy_container], check=True, capture_output=True)
    program = r'''
import os, shutil, time
from pathlib import Path
from coworld.runner.pool.control import control
root = Path('/var/run/coworld-pool')
until = time.monotonic() + 15
while not (root / 'control.sock').exists():
    assert time.monotonic() < until
    time.sleep(.05)
for directory in ('/coworld', '/tmp', '/dev/shm'):
    os.chown(directory, 65532, 65532)
# A trusted coordinator keeps an idle supervisor alive while preparing an assignment.
# An image with a four-second idle deadline exercises expiry without a ten-minute wait.
for _ in range(6):
    assert control('', 0).state == 0
    time.sleep(1)
script = """
import os, ctypes, errno, time
from pathlib import Path
assert os.getuid() == 65532
assert not os.access('/var/run/coworld-pool', os.R_OK)
assert not os.access('/proc/1/environ', os.R_OK)
libc = ctypes.CDLL(None, use_errno=True)
assert libc.semget(12345678, 1, 0o1000 | 0o600) == -1 and ctypes.get_errno() == errno.EPERM
queue = libc.mq_open(b'/pool-qualification', os.O_CREAT | os.O_RDWR, 0o600, None)
assert queue == -1 and ctypes.get_errno() == errno.EPERM
for directory in ('/coworld', '/tmp', '/dev/shm'):
    Path(directory + '/prior').write_text('private episode input')
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        Path('/coworld/escaped-pid').write_text(str(os.getpid()))
        time.sleep(3600)
    os._exit(0)
while not Path('/coworld/escaped-pid').exists(): time.sleep(.01)
print('first episode', flush=True)
"""
first = control('first', 1, command=('python', '-c', script),
                env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, timeout_seconds=15)
# Replaying a lost start response must not launch another game.
assert control('first', 1, command=('/bin/false',), env={}, timeout_seconds=15).pid == first.pid
until = time.monotonic() + 20
while control('first', 2).state == 1:
    assert time.monotonic() < until
    time.sleep(.05)
assert control('first', 2).exit_code == 0, (root / 'stderr').read_text()
escaped = Path('/coworld/escaped-pid').read_text()
assert control('first', 3).state == 3
for directory in ('/coworld', '/tmp', '/dev/shm'):
    for path in Path(directory).iterdir():
        if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
        else: path.unlink()
script = f"""
from pathlib import Path
assert not Path('/proc/{escaped}').exists()
for directory in ('/coworld', '/tmp', '/dev/shm'):
    assert not (Path(directory) / 'prior').exists()
print('second episode', flush=True)
"""
control('second', 1, command=('python', '-c', script),
        env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, timeout_seconds=15)
until = time.monotonic() + 20
while control('second', 2).state == 1:
    assert time.monotonic() < until
    time.sleep(.05)
assert control('second', 2).exit_code == 0, (root / 'stderr').read_text()
assert control('second', 3).state == 3
assert (root / 'stdout').read_text().strip() == 'second episode'
# The deadline also reaps descendants of an exited leader, keeping its recorded exit code.
control('detached', 1, command=('/bin/sh', '-c', 'sleep 3600 & echo $! > /coworld/detached-pid'),
        env={'PATH': '/usr/bin:/bin'}, timeout_seconds=1)
until = time.monotonic() + 15
while control('detached', 2).state != 3:
    assert time.monotonic() < until
    time.sleep(.05)
assert control('detached', 2).exit_code == 0
detached = Path('/coworld/detached-pid').read_text().strip()
script = f"""
from pathlib import Path
assert not Path('/proc/{detached}').exists()
"""
control('detached-check', 1, command=('python', '-c', script),
        env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, timeout_seconds=15)
until = time.monotonic() + 20
while control('detached-check', 2).state == 1:
    assert time.monotonic() < until
    time.sleep(.05)
assert control('detached-check', 2).exit_code == 0, (root / 'stderr').read_text()
assert control('detached-check', 3).state == 3
# Passing the deadline after exit stops the namespace without replacing the recorded exit code.
for code in (0, 7):
    assignment = f'finished-{code}'
    control(assignment, 1, command=('/bin/sh', '-c', f'exit {code}'), env={}, timeout_seconds=1)
    until = time.monotonic() + 15
    while control(assignment, 2).state == 1:
        assert time.monotonic() < until
        time.sleep(.05)
    assert control(assignment, 2).exit_code == code
    # Cross the deadline while the finished game waits for collection.
    time.sleep(1.2)
    finished = control(assignment, 2)
    assert (finished.state, finished.exit_code) == (3, code), finished
    assert control(assignment, 3).exit_code == code
# The supervisor must stop an overdue game even if the coordinator disappears.
control('deadline', 1, command=('/bin/sh', '-c', 'sleep 3600'), env={'PATH': '/usr/bin:/bin'}, timeout_seconds=1)
until = time.monotonic() + 15
while control('deadline', 2).state != 3:
    assert time.monotonic() < until
    time.sleep(.05)
assert control('deadline', 2).exit_code == 124
'''
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "SETUID",
                "--cap-add",
                "SETGID",
                "--cap-add",
                "KILL",
                *mounts,
                "-v",
                f"{tmp_path / 'supervisor'}:/supervisor:ro",
                "--entrypoint",
                "/supervisor",
                game_image,
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                *mounts,
                "--entrypoint",
                "python",
                coordinator_image,
                "-c",
                program,
            ],
            check=True,
            timeout=60,
        )
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)
        subprocess.run(["docker", "volume", "rm", *volumes.values()], check=True, capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coordinator-image", required=True, help="Prebuilt coordinator image containing the supervisor"
    )
    parser.add_argument(
        "--game-image", required=True, help="Prebuilt game image with an unprivileged Python executable"
    )
    args = parser.parse_args()
    with TemporaryDirectory(prefix="xp-pool-qualification-") as directory:
        qualify_supervisor(args.coordinator_image, args.game_image, Path(directory))
    print("Pool supervisor qualification passed")
