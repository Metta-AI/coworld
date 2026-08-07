from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import Enum

import httpx
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field

from coworld.api_client import CoworldApiClient, LeaguePublic
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.upload import CoworldListEntry, CoworldUploadClient

DEFAULT_REPO_PREFIX = "coworld-"
DEFAULT_GITHUB_OWNER = "Metta-AI"


_KNOWN_COWORLD_NAMES = {
    "coworld-ctf": "paintbot",
    "coworld-crewrift": "crewrift_prime",
    "coworld-liars-cog": "liars-cog",
    "coworld-tribal-village": "tribal_village",
}


class WorkflowMode(str, Enum):
    automatic = "automatic"
    manual_gated = "manual-gated"
    manual = "manual"
    no_upload = "no-upload"
    none = "none"


class GitHubRepository(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    full_name: str
    default_branch: str
    archived: bool = False
    private: bool = False


class GitHubContent(BaseModel):
    name: str
    path: str
    type: str
    encoding: str | None = None
    content: str | None = None
    download_url: str | None = None


class GitHubWorkflowRun(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str | None = None
    event: str
    head_branch: str | None = None
    head_sha: str
    status: str
    conclusion: str | None = None
    created_at: datetime
    updated_at: datetime
    html_url: str = Field(alias="html_url")


class GitHubWorkflowRunsResponse(BaseModel):
    workflow_runs: list[GitHubWorkflowRun]


class WorkflowAudit(BaseModel):
    path: str
    name: str
    coworld_name: str | None
    has_workflow_dispatch: bool
    has_push_to_default_branch: bool
    uses_upload_coworld: bool
    waits_hosted_smoke: bool
    verifies_canonical: bool
    confirm_upload_default: str | None

    @property
    def mode(self) -> WorkflowMode:
        if not self.uses_upload_coworld:
            return WorkflowMode.no_upload
        if self.has_push_to_default_branch:
            return WorkflowMode.automatic
        if self.confirm_upload_default == "dry-run":
            return WorkflowMode.manual_gated
        if self.has_workflow_dispatch:
            return WorkflowMode.manual
        return WorkflowMode.no_upload


class CoworldRegistrySummary(BaseModel):
    coworld_name: str
    canonical_id: str | None
    canonical_version: str | None
    latest_id: str | None
    latest_version: str | None
    latest_is_canonical: bool | None


class RepoDeployAudit(BaseModel):
    repo: str
    default_branch: str
    archived: bool
    coworld_name: str | None
    active_leagues: list[str]
    workflow_mode: WorkflowMode
    workflow_files: list[str]
    canonical_version: str | None
    canonical_id: str | None
    latest_version: str | None
    latest_id: str | None
    latest_upload_run_conclusion: str | None
    latest_upload_run_url: str | None
    alerts: list[str]


class DeployAuditResult(BaseModel):
    owner: str
    generated_at: datetime
    rows: list[RepoDeployAudit]
    alerts: list[str]


class GitHubApi:
    def __init__(self, *, owner: str, token: str | None = None, base_url: str = "https://api.github.com") -> None:
        self.owner = owner
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(base_url=self._base_url, headers=self._headers, timeout=60.0)

    def close(self) -> None:
        self._client.close()

    def list_repositories(self, *, prefix: str) -> list[GitHubRepository]:
        repos: list[GitHubRepository] = []
        page = 1
        while True:
            response = self._client.get(
                f"/orgs/{self.owner}/repos",
                params={"type": "all", "per_page": 100, "page": page},
            )
            response.raise_for_status()
            payload = response.json()
            batch = [GitHubRepository.model_validate(item) for item in payload]
            repos.extend(repo for repo in batch if repo.name.startswith(prefix))
            if len(batch) < 100:
                return sorted(repos, key=lambda repo: repo.name)
            page += 1

    def get_repository(self, repo: str) -> GitHubRepository:
        response = self._client.get(f"/repos/{self.owner}/{repo}")
        response.raise_for_status()
        return GitHubRepository.model_validate(response.json())

    def list_workflow_files(self, *, repo: str, ref: str) -> list[GitHubContent]:
        response = self._client.get(
            f"/repos/{self.owner}/{repo}/contents/.github/workflows",
            params={"ref": ref},
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
        files = [GitHubContent.model_validate(item) for item in payload]
        return [item for item in files if item.type == "file" and item.name.endswith((".yml", ".yaml"))]

    def read_file_text(self, *, repo: str, path: str, ref: str) -> str:
        response = self._client.get(f"/repos/{self.owner}/{repo}/contents/{path}", params={"ref": ref})
        response.raise_for_status()
        content = GitHubContent.model_validate(response.json())
        assert content.encoding == "base64", f"GitHub content for {repo}/{path} was not base64 encoded"
        assert content.content is not None, f"GitHub content for {repo}/{path} was empty"
        return base64.b64decode(content.content).decode("utf-8")

    def latest_workflow_run(self, *, repo: str, workflow_file: str, branch: str) -> GitHubWorkflowRun | None:
        response = self._client.get(
            f"/repos/{self.owner}/{repo}/actions/workflows/{workflow_file}/runs",
            params={"branch": branch, "per_page": 1},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        runs = GitHubWorkflowRunsResponse.model_validate(response.json()).workflow_runs
        return runs[0] if runs else None


def github_token_from_env() -> str | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, check=False, text=True)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def load_coworld_registry(*, server: str = DEFAULT_SUBMIT_SERVER, limit: int = 500) -> list[CoworldListEntry]:
    rows: list[CoworldListEntry] = []
    offset = 0
    with CoworldUploadClient.from_login(server_url=server) as client:
        while True:
            batch = client.list_coworlds(limit=limit, offset=offset)
            rows.extend(batch)
            if len(batch) < limit:
                return rows
            offset += limit


def load_active_leagues_by_coworld(*, server: str = DEFAULT_SUBMIT_SERVER) -> dict[str, list[str]]:
    with CoworldApiClient.from_login(server_url=server) as client:
        leagues = client.list_leagues()
    active_by_coworld: dict[str, list[str]] = {}
    for league in leagues:
        if _league_is_active(league) and league.game.coworld_name is not None:
            active_by_coworld.setdefault(_coworld_name_key(league.game.coworld_name), []).append(league.name)
    return {name: sorted(leagues) for name, leagues in active_by_coworld.items()}


def classify_workflow(path: str, text: str, *, default_branch: str) -> WorkflowAudit:
    name = _workflow_display_name(text) or path.rsplit("/", 1)[-1]
    coworld_name = _workflow_coworld_name(text)
    confirm_upload_default = _confirm_upload_default(text)
    return WorkflowAudit(
        path=path,
        name=name,
        coworld_name=coworld_name,
        has_workflow_dispatch=_has_yaml_key(text, "workflow_dispatch"),
        has_push_to_default_branch=_pushes_to_default_branch(text, default_branch=default_branch),
        uses_upload_coworld="upload-coworld" in text,
        waits_hosted_smoke="--wait-hosted-smoke" in text,
        verifies_canonical=bool(
            re.search(r"(?i)verify .*canonical|canonical .*verify|is canonical|not canonical", text)
        ),
        confirm_upload_default=confirm_upload_default,
    )


def summarize_coworld_registry(
    coworld_name: str | None, rows: Sequence[CoworldListEntry]
) -> CoworldRegistrySummary | None:
    if coworld_name is None:
        return None
    matches = [row for row in rows if _coworld_name_key(row.name) == _coworld_name_key(coworld_name)]
    if not matches:
        return CoworldRegistrySummary(
            coworld_name=coworld_name,
            canonical_id=None,
            canonical_version=None,
            latest_id=None,
            latest_version=None,
            latest_is_canonical=None,
        )

    canonical_rows = [row for row in matches if row.canonical]
    canonical = canonical_rows[0] if canonical_rows else None
    latest = max(matches, key=lambda row: (Version(row.version), row.created_at, row.id))
    return CoworldRegistrySummary(
        coworld_name=coworld_name,
        canonical_id=canonical.id if canonical else None,
        canonical_version=canonical.version if canonical else None,
        latest_id=latest.id,
        latest_version=latest.version,
        latest_is_canonical=latest.canonical,
    )


def audit_coworld_deployments(
    *,
    owner: str = DEFAULT_GITHUB_OWNER,
    repo_prefix: str = DEFAULT_REPO_PREFIX,
    repositories: Sequence[str] | None = None,
    github_token: str | None = None,
    server: str = DEFAULT_SUBMIT_SERVER,
    include_coworld_registry: bool = True,
) -> DeployAuditResult:
    github = GitHubApi(owner=owner, token=github_token)
    try:
        repos = (
            [github.get_repository(repo) for repo in repositories]
            if repositories is not None
            else github.list_repositories(prefix=repo_prefix)
        )
        registry_rows = load_coworld_registry(server=server) if include_coworld_registry else []
        active_leagues_by_coworld = load_active_leagues_by_coworld(server=server) if include_coworld_registry else {}
        audit_rows = [
            _audit_repository(
                github=github,
                repo=repo,
                registry_rows=registry_rows,
                active_leagues_by_coworld=active_leagues_by_coworld,
            )
            for repo in repos
            if not repo.archived
        ]
    finally:
        github.close()

    alerts = [f"{row.repo}: {alert}" for row in audit_rows for alert in row.alerts]
    return DeployAuditResult(
        owner=owner,
        generated_at=datetime.now(UTC),
        rows=audit_rows,
        alerts=alerts,
    )


def format_deploy_audit_markdown(result: DeployAuditResult) -> str:
    lines = [
        "# Coworld deploy audit",
        "",
        f"Generated: {result.generated_at.isoformat()}",
        "",
        "| Repo | Coworld | Active leagues | Branch | Workflow | Canonical | Latest | Last upload run | Alerts |",
        "| ---- | ------- | -------------- | ------ | -------- | --------- | ------ | --------------- | ------ |",
    ]
    for row in result.rows:
        canonical = _version_cell(row.canonical_version, row.canonical_id)
        latest = _version_cell(row.latest_version, row.latest_id)
        run = row.latest_upload_run_conclusion or ""
        if row.latest_upload_run_url:
            run = f"[{run or 'run'}]({row.latest_upload_run_url})"
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(row.repo),
                    _md(row.coworld_name or ""),
                    _md(", ".join(row.active_leagues)),
                    _md(row.default_branch),
                    _md(row.workflow_mode.value),
                    _md(canonical),
                    _md(latest),
                    run,
                    _md("; ".join(row.alerts)),
                ]
            )
            + " |"
        )
    if result.alerts:
        lines.extend(["", "## Alerts", ""])
        lines.extend(f"- {alert}" for alert in result.alerts)
    else:
        lines.extend(["", "No alerts."])
    return "\n".join(lines) + "\n"


def _audit_repository(
    *,
    github: GitHubApi,
    repo: GitHubRepository,
    registry_rows: Sequence[CoworldListEntry],
    active_leagues_by_coworld: dict[str, list[str]],
) -> RepoDeployAudit:
    workflow_files = github.list_workflow_files(repo=repo.name, ref=repo.default_branch)
    workflows = [
        classify_workflow(
            file.path,
            github.read_file_text(repo=repo.name, path=file.path, ref=repo.default_branch),
            default_branch=repo.default_branch,
        )
        for file in workflow_files
    ]
    upload_workflows = [workflow for workflow in workflows if workflow.uses_upload_coworld]
    coworld_name = _repo_coworld_name(repo.name, upload_workflows)
    registry = summarize_coworld_registry(coworld_name, registry_rows)
    latest_run = _latest_upload_workflow_run(github=github, repo=repo, workflows=upload_workflows)
    alerts = _repo_alerts(upload_workflows=upload_workflows, registry=registry, latest_run=latest_run)
    return RepoDeployAudit(
        repo=repo.name,
        default_branch=repo.default_branch,
        archived=repo.archived,
        coworld_name=coworld_name,
        active_leagues=active_leagues_by_coworld.get(_coworld_name_key(coworld_name), []) if coworld_name else [],
        workflow_mode=_repo_workflow_mode(upload_workflows, workflows),
        workflow_files=[workflow.path for workflow in upload_workflows],
        canonical_version=registry.canonical_version if registry else None,
        canonical_id=registry.canonical_id if registry else None,
        latest_version=registry.latest_version if registry else None,
        latest_id=registry.latest_id if registry else None,
        latest_upload_run_conclusion=latest_run.conclusion if latest_run else None,
        latest_upload_run_url=latest_run.html_url if latest_run else None,
        alerts=alerts,
    )


def _latest_upload_workflow_run(
    *,
    github: GitHubApi,
    repo: GitHubRepository,
    workflows: Sequence[WorkflowAudit],
) -> GitHubWorkflowRun | None:
    automatic_workflows = [workflow for workflow in workflows if workflow.has_push_to_default_branch]
    runs = [
        run
        for workflow in automatic_workflows
        if (
            run := github.latest_workflow_run(
                repo=repo.name,
                workflow_file=workflow.path.rsplit("/", 1)[-1],
                branch=repo.default_branch,
            )
        )
        is not None
    ]
    return max(runs, key=lambda run: run.created_at) if runs else None


def _repo_alerts(
    *,
    upload_workflows: Sequence[WorkflowAudit],
    registry: CoworldRegistrySummary | None,
    latest_run: GitHubWorkflowRun | None,
) -> list[str]:
    alerts: list[str] = []
    for workflow in upload_workflows:
        if not workflow.waits_hosted_smoke:
            alerts.append(f"{workflow.path} does not pass --wait-hosted-smoke")
        if not workflow.verifies_canonical:
            alerts.append(f"{workflow.path} does not verify canonical promotion")
        if workflow.mode == WorkflowMode.manual and workflow.confirm_upload_default != "dry-run":
            alerts.append(f"{workflow.path} manual upload is not dry-run gated")

    if registry and registry.latest_is_canonical is False:
        alerts.append(f"latest upload is non-canonical: {registry.coworld_name}:{registry.latest_version}")

    if latest_run:
        if latest_run.status != "completed" or latest_run.conclusion != "success":
            alerts.append(
                f"latest default-branch upload workflow did not succeed: "
                f"{latest_run.status}/{latest_run.conclusion or 'pending'}"
            )
    elif any(workflow.has_push_to_default_branch for workflow in upload_workflows):
        alerts.append("automatic upload workflow has no default-branch run")
    return alerts


def _repo_workflow_mode(upload_workflows: Sequence[WorkflowAudit], workflows: Sequence[WorkflowAudit]) -> WorkflowMode:
    modes = [workflow.mode for workflow in upload_workflows]
    if WorkflowMode.automatic in modes:
        return WorkflowMode.automatic
    if WorkflowMode.manual_gated in modes:
        return WorkflowMode.manual_gated
    if WorkflowMode.manual in modes:
        return WorkflowMode.manual
    return WorkflowMode.no_upload if workflows else WorkflowMode.none


def _repo_coworld_name(repo_name: str, workflows: Sequence[WorkflowAudit]) -> str | None:
    workflow_names = [workflow.coworld_name for workflow in workflows if workflow.coworld_name]
    if workflow_names:
        assert len(set(workflow_names)) == 1, f"Multiple COWORLD_NAME values found for {repo_name}: {workflow_names}"
        return workflow_names[0]
    return _KNOWN_COWORLD_NAMES.get(repo_name)


def _league_is_active(league: LeaguePublic) -> bool:
    return not league.hidden and league.disabled_at is None


def _workflow_display_name(text: str) -> str | None:
    match = re.search(r"(?m)^name:\s*[\"']?([^\"'\n]+)[\"']?\s*$", text)
    return match.group(1).strip() if match else None


def _workflow_coworld_name(text: str) -> str | None:
    match = re.search(r"(?m)^\s*COWORLD_NAME:\s*[\"']?([^\"'\s#]+)", text)
    return match.group(1).strip() if match else None


def _confirm_upload_default(text: str) -> str | None:
    confirm = re.search(
        r"(?ms)^\s*confirm_upload:\s*\n(?P<body>(?:\s{8,}.+\n)+)",
        text,
    )
    if not confirm:
        return None
    default = re.search(r"(?m)^\s*default:\s*[\"']?([^\"'\n]+)[\"']?\s*$", confirm.group("body"))
    return default.group(1).strip() if default else None


def _has_yaml_key(text: str, key: str) -> bool:
    return bool(re.search(rf"(?m)^\s*{re.escape(key)}:\s*(?:#.*)?$", text))


def _pushes_to_default_branch(text: str, *, default_branch: str) -> bool:
    push = re.search(r"(?ms)^\s*push:\s*\n(?P<body>(?:\s{4,}.+\n)+)", text)
    if not push:
        return bool(re.search(r"(?m)^\s*push:\s*(?:\{\}\s*)?(?:#.*)?$", text))
    body = push.group("body")
    if "branches:" not in body:
        return True
    return default_branch in re.findall(r"[\w./-]+", body)


def _coworld_name_key(name: str) -> str:
    return name.replace("-", "_")


def _version_cell(version: str | None, coworld_id: str | None) -> str:
    if version is None:
        return ""
    if coworld_id is None:
        return version
    return f"{version} ({coworld_id})"


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
