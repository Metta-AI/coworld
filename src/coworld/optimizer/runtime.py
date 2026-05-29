from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from coworld.cli_support import console
from coworld.config import DEFAULT_OPTIMIZER_REF, DEFAULT_OPTIMIZER_REPO

DEFAULT_DATABASE_URL = "postgres://coagent:coagent@localhost:5433/coagent"
BUN_INSTALL_SCRIPT = "https://bun.sh/install"
SERVER_READY_TIMEOUT_SECONDS = 240.0
POSTGRES_READY_TIMEOUT_SECONDS = 60.0
INSTALL_TIMEOUT_SECONDS = 900.0


class OptimizerSetupError(RuntimeError):
    """Raised when the optimizer workbench cannot be prepared or launched."""


@dataclass(frozen=True)
class OptimizerRepoSpec:
    clone_url: str
    ref: str
    slug: str

    @property
    def label(self) -> str:
        return f"{self.slug}@{self.ref}"


@dataclass(frozen=True)
class OptimizerContext:
    manifest_path: Path
    download_dir: Path
    images_path: Path | None
    coworld_id: str | None


@dataclass(frozen=True)
class OptimizerOpenResult:
    game_id: str
    detail_url: str


def parse_github_repo(url: str, *, default_ref: str = DEFAULT_OPTIMIZER_REF) -> tuple[str, str, str]:
    """Parse a GitHub URL into (clone_url, ref, slug).

    Supports:
    - https://github.com/Org/repo
    - https://github.com/Org/repo.git
    - https://github.com/Org/repo/tree/<ref>
    - https://github.com/Org/repo/tree/<ref>/sub/path  (subpath ignored)
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        raise OptimizerSetupError(f"Only GitHub repository URLs are supported for the optimizer, got: {url}")
    parts = [segment for segment in parsed.path.split("/") if segment]
    if len(parts) < 2:
        raise OptimizerSetupError(f"Could not parse owner/repo from optimizer URL: {url}")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    ref = default_ref
    if len(parts) >= 4 and parts[2] == "tree":
        ref = parts[3]
    clone_url = f"https://github.com/{owner}/{repo}.git"
    slug = f"{owner.lower()}-{repo.lower()}"
    return clone_url, ref, slug


def resolve_optimizer_repository(
    manifest_path: Path | None,
    *,
    override_repo: str | None = None,
    override_ref: str | None = None,
) -> OptimizerRepoSpec:
    repo_url = override_repo
    if repo_url is None and manifest_path is not None:
        repo_url = _manifest_optimizer_repository_url(manifest_path)
    if repo_url is None:
        repo_url = DEFAULT_OPTIMIZER_REPO
    clone_url, ref, slug = parse_github_repo(repo_url)
    if override_ref is not None:
        ref = override_ref
    return OptimizerRepoSpec(clone_url=clone_url, ref=ref, slug=slug)


def resolve_optimizer_context(manifest_path: Path | None) -> OptimizerContext | None:
    if manifest_path is None:
        return None
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise OptimizerSetupError(f"Manifest not found: {manifest_path}")
    download_dir = manifest_path.parent
    images_path = download_dir / "coworld_images.json"
    coworld_id = download_dir.name if download_dir.name.startswith("cow_") else None
    return OptimizerContext(
        manifest_path=manifest_path,
        download_dir=download_dir,
        images_path=images_path if images_path.is_file() else None,
        coworld_id=coworld_id,
    )


def optimizer_cache_root() -> Path:
    override = os.environ.get("COWORLD_OPTIMIZER_DIR")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "coworld" / "optimizers").resolve()


def check_prerequisites() -> list[str]:
    """Ensure host tools are available. Returns soft warnings; raises on hard failures."""
    if shutil.which("git") is None:
        raise OptimizerSetupError("git is required to install the optimizer. Install git and retry.")

    if not _docker_available():
        raise OptimizerSetupError("Docker is not available. Start Docker Desktop (or the Docker daemon) and retry.")

    if shutil.which("bun") is None:
        _install_bun()
    if shutil.which("bun") is None:
        raise OptimizerSetupError(
            "Bun is required to run the optimizer and could not be installed automatically. "
            f"Install it with: curl -fsSL {BUN_INSTALL_SCRIPT} | bash"
        )

    warnings: list[str] = []
    if not _softmax_authenticated():
        warnings.append(
            "Softmax auth not detected. The workbench loads, but running episodes needs `uv run softmax login`."
        )
    return warnings


def ensure_optimizer_project(repo_spec: OptimizerRepoSpec, install_root: Path, *, refresh: bool) -> Path:
    install_dir = install_root / repo_spec.slug / repo_spec.ref
    git_dir = install_dir / ".git"

    if git_dir.is_dir():
        if refresh:
            console.print(f"[dim]Updating optimizer checkout ({repo_spec.label})[/dim]")
            _run(["git", "fetch", "--depth", "1", "origin", repo_spec.ref], cwd=install_dir)
            _run(["git", "checkout", repo_spec.ref], cwd=install_dir)
            _run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=install_dir)
    else:
        install_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[dim]Cloning optimizer {repo_spec.label} into {install_dir}[/dim]")
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                repo_spec.ref,
                repo_spec.clone_url,
                str(install_dir),
            ]
        )

    _assert_optimizer_workbench(install_dir, repo_spec)

    console.print("[dim]Installing optimizer dependencies (bun install)[/dim]")
    _run(["bun", "install"], cwd=install_dir, timeout=INSTALL_TIMEOUT_SECONDS)

    if (install_dir / "pyproject.toml").is_file() and shutil.which("uv") is not None:
        console.print("[dim]Syncing optimizer Python deps (uv sync)[/dim]")
        # Best effort: the workbench still runs without the Python extras.
        _run(["uv", "sync"], cwd=install_dir, timeout=INSTALL_TIMEOUT_SECONDS, check=False)

    return install_dir


def ensure_postgres(install_dir: Path, database_url: str = DEFAULT_DATABASE_URL) -> None:
    console.print("[dim]Starting optimizer Postgres (docker compose up -d postgres)[/dim]")
    _run(["docker", "compose", "up", "-d", "postgres"], cwd=install_dir)

    user, _db = _postgres_user_and_db(database_url)
    deadline = time.monotonic() + POSTGRES_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        ready = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "pg_isready", "-U", user],
            cwd=install_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready.returncode == 0:
            return
        time.sleep(1.0)
    raise OptimizerSetupError("Optimizer Postgres did not become ready in time.")


def ensure_database_schema(install_dir: Path, env: dict[str, str]) -> None:
    """Push the optimizer schema and seed before the dev server starts.

    The optimizer app initializes its schema lazily in the root layout, but Next.js
    renders the layout and page concurrently, so a brand-new database loses the race on
    first load. Initializing here makes the very first render work.
    """
    database_url = env.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    if not _is_local_postgres_url(database_url):
        return
    if _agents_table_exists(install_dir, database_url):
        return

    console.print("[dim]Initializing optimizer database schema (drizzle push + seed)[/dim]")
    _run(["bunx", "drizzle-kit", "push", "--force"], cwd=install_dir, env=env, timeout=INSTALL_TIMEOUT_SECONDS)
    _run(["bunx", "tsx", "lib/db/seed.ts"], cwd=install_dir, env=env, timeout=INSTALL_TIMEOUT_SECONDS)


def build_optimizer_env(context: OptimizerContext | None, *, port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("DATABASE_URL", DEFAULT_DATABASE_URL)
    env["PORT"] = str(port)
    if context is not None:
        env["COWORLD_MANIFEST_PATH"] = str(context.manifest_path)
        env["COWORLD_DOWNLOAD_DIR"] = str(context.download_dir)
    return env


def start_optimizer_dev_server(install_dir: Path, env: dict[str, str], port: int) -> subprocess.Popen[bytes]:
    console.print(f"[dim]Launching optimizer dev server on port {port}[/dim]")
    return subprocess.Popen(
        ["bun", "run", "dev", "--port", str(port)],
        cwd=install_dir,
        env=env,
    )


def wait_for_optimizer_ready(
    base_url: str,
    proc: subprocess.Popen[bytes],
    *,
    timeout: float = SERVER_READY_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise OptimizerSetupError(
                f"Optimizer dev server exited early with code {proc.returncode} before becoming ready."
            )
        try:
            response = httpx.get(base_url, timeout=5.0)
            if response.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    raise OptimizerSetupError(f"Optimizer did not become ready at {base_url} within {timeout:.0f}s.")


def bootstrap_game(base_url: str, context: OptimizerContext) -> OptimizerOpenResult:
    payload = {
        "manifestPath": str(context.manifest_path),
        "downloadDir": str(context.download_dir),
        "imagesJsonPath": str(context.images_path) if context.images_path else None,
        "coworldId": context.coworld_id,
    }
    response = httpx.post(f"{base_url}/api/coworld/open-local", json=payload, timeout=60.0)
    if response.status_code >= 400:
        raise OptimizerSetupError(
            f"Failed to import Coworld into the optimizer ({response.status_code}): {response.text[:500]}"
        )
    data = response.json()
    game_id = str(data.get("gameId", ""))
    detail_path = (data.get("urls") or {}).get("detail") or (f"/games/{game_id}" if game_id else "/games")
    return OptimizerOpenResult(game_id=game_id, detail_url=f"{base_url}{detail_path}")


def run_optimizer_session(
    manifest_path: Path | None,
    *,
    port: int,
    open_browser: bool,
    refresh: bool,
    optimizer_repo: str | None,
    optimizer_ref: str | None,
    install_root: Path | None = None,
) -> None:
    repo_spec = resolve_optimizer_repository(manifest_path, override_repo=optimizer_repo, override_ref=optimizer_ref)
    context = resolve_optimizer_context(manifest_path)

    warnings = check_prerequisites()
    for warning in warnings:
        console.print(f"[yellow]{warning}[/yellow]")

    root = install_root if install_root is not None else optimizer_cache_root()
    install_dir = ensure_optimizer_project(repo_spec, root, refresh=refresh)

    env = build_optimizer_env(context, port=port)
    ensure_postgres(install_dir, env["DATABASE_URL"])
    ensure_database_schema(install_dir, env)
    proc = start_optimizer_dev_server(install_dir, env, port)

    base_url = f"http://127.0.0.1:{port}"
    try:
        wait_for_optimizer_ready(base_url, proc)

        target_url = base_url + "/"
        if context is not None:
            console.print("[dim]Importing Coworld into the optimizer[/dim]")
            result = bootstrap_game(base_url, context)
            target_url = result.detail_url

        console.print(f"[green]Optimizer running:[/green] {target_url}")
        console.print(f"[dim]Repo: {repo_spec.label}[/dim]")
        if context is not None:
            console.print(f"[dim]Manifest: {context.manifest_path}[/dim]")
        console.print("[dim]Press Ctrl+C to stop.[/dim]")

        if open_browser:
            webbrowser.open(target_url)

        proc.wait()
    except KeyboardInterrupt:
        console.print("\n[dim]Stopping optimizer dev server...[/dim]")
    finally:
        _terminate(proc)


def _manifest_optimizer_repository_url(manifest_path: Path) -> str | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptimizerSetupError(f"Could not read manifest {manifest_path}: {exc}") from exc
    entries = manifest.get("optimizer") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("repository_url"):
            return str(entry["repository_url"])
    return None


def _assert_optimizer_workbench(install_dir: Path, repo_spec: OptimizerRepoSpec) -> None:
    if not (install_dir / "package.json").is_file():
        raise OptimizerSetupError(
            f"Cloned repository {repo_spec.label} does not look like an optimizer workbench (missing package.json)."
        )


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _softmax_authenticated() -> bool:
    command = ["softmax", "status"] if shutil.which("softmax") else ["uv", "run", "softmax", "status"]
    if command[0] == "uv" and shutil.which("uv") is None:
        return False
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    output = (result.stdout + result.stderr).lower()
    return result.returncode == 0 and ("authenticated" in output or "logged in" in output or "@" in output)


def _install_bun() -> None:
    console.print("[dim]Bun not found. Installing Bun...[/dim]")
    try:
        script = httpx.get(BUN_INSTALL_SCRIPT, timeout=30.0, follow_redirects=True).text
        subprocess.run(["bash"], input=script, text=True, timeout=INSTALL_TIMEOUT_SECONDS, check=True)
    except (httpx.HTTPError, subprocess.SubprocessError, OSError) as exc:
        console.print(f"[yellow]Automatic Bun install failed: {exc}[/yellow]")
        return
    bun_bin = Path.home() / ".bun" / "bin"
    if bun_bin.is_dir():
        os.environ["PATH"] = f"{bun_bin}{os.pathsep}{os.environ.get('PATH', '')}"


def _postgres_user_and_db(database_url: str) -> tuple[str, str]:
    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgres"):
        return "coagent", "coagent"
    user = parsed.username or "coagent"
    db = parsed.path.lstrip("/") or "coagent"
    return user, db


def _is_local_postgres_url(database_url: str) -> bool:
    parsed = urlparse(database_url)
    return parsed.scheme.startswith("postgres") and parsed.hostname in ("localhost", "127.0.0.1", "::1")


def _agents_table_exists(install_dir: Path, database_url: str) -> bool:
    user, db = _postgres_user_and_db(database_url)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            db,
            "-tAc",
            "select to_regclass('public.agents')",
        ],
        cwd=install_dir,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() not in ("", "\\N")


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise OptimizerSetupError(
            f"Command failed ({' '.join(args)}):\n{result.stderr[-2000:] or result.stdout[-2000:]}"
        )
    return result


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
