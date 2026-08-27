from __future__ import annotations

from datetime import UTC, datetime

import pytest

import coworld.deploy_audit as deploy_audit_module
from coworld.deploy_audit import (
    DeployAuditResult,
    RepoDeployAudit,
    WorkflowMode,
    _repo_alerts,
    _repo_coworld_name,
    classify_workflow,
    format_deploy_audit_markdown,
    load_coworld_registry,
    summarize_coworld_registry,
)
from coworld.upload import CoworldListEntry, CoworldListPage


def test_classify_manual_upload_workflow_is_dry_run_gated() -> None:
    workflow = classify_workflow(
        ".github/workflows/upload-coworld.yml",
        """
name: Upload Coworld (manual)
on:
  workflow_dispatch:
    inputs:
      confirm_upload:
        required: true
        default: "dry-run"
env:
  COWORLD_NAME: coworld-mtg
jobs:
  upload:
    steps:
      - name: Upload coworld
        if: ${{ github.event.inputs.confirm_upload == 'upload' }}
        run: |
          coworld upload-coworld tmp/coworld_manifest.json --wait-hosted-smoke
      - name: Verify canonical promotion
        run: echo "coworld-mtg is canonical"
""",
        default_branch="main",
    )

    assert workflow.coworld_name == "coworld-mtg"
    assert workflow.mode == WorkflowMode.manual_gated
    assert workflow.waits_hosted_smoke is True
    assert workflow.verifies_canonical is True


def test_classify_default_branch_upload_workflow_is_automatic() -> None:
    workflow = classify_workflow(
        ".github/workflows/upload-coworld.yml",
        """
name: Upload Coworld
on:
  push:
    branches: [master]
  workflow_dispatch:
jobs:
  upload:
    steps:
      - run: coworld upload-coworld dist/coworld_manifest.json --wait-hosted-smoke
      - run: echo "verified canonical promotion"
""",
        default_branch="master",
    )

    assert workflow.mode == WorkflowMode.automatic
    assert workflow.has_push_to_default_branch is True


def test_classify_canonical_failure_language_as_verification() -> None:
    workflow = classify_workflow(
        ".github/workflows/upload-coworld.yml",
        """
name: Upload Coworld
on:
  push:
    branches: [main]
jobs:
  upload:
    steps:
      - run: coworld upload-coworld dist/coworld_manifest.json --wait-hosted-smoke
      - run: |
          if not entry["canonical"]:
              raise SystemExit("uploaded but is not canonical")
""",
        default_branch="main",
    )

    assert workflow.verifies_canonical is True


def test_registry_summary_marks_latest_noncanonical() -> None:
    rows = [
        _coworld("cow_1", "ctf", "0.7.37", canonical=True, created_at="2026-07-20T18:44:10Z"),
        _coworld("cow_2", "ctf", "0.7.38", canonical=False, created_at="2026-07-20T18:49:11Z"),
    ]

    summary = summarize_coworld_registry("ctf", rows)

    assert summary is not None
    assert summary.canonical_version == "0.7.37"
    assert summary.latest_version == "0.7.38"
    assert summary.latest_is_canonical is False
    assert _repo_alerts(upload_workflows=[], registry=summary, latest_run=None) == [
        "latest upload is non-canonical: ctf:0.7.38"
    ]


def test_load_coworld_registry_accumulates_cursor_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        None: CoworldListPage(
            entries=[_coworld("cow_1", "ctf", "0.7.37", canonical=True, created_at="2026-07-20T18:44:10Z")],
            next_cursor="page-2",
        ),
        "page-2": CoworldListPage(
            entries=[_coworld("cow_2", "ctf", "0.7.38", canonical=False, created_at="2026-07-20T18:49:11Z")],
            next_cursor=None,
        ),
    }

    class _FakeClient:
        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def list_coworlds(self, *, limit: int, cursor: str | None = None) -> CoworldListPage:
            return pages[cursor]

    class _FakeClientFactory:
        @classmethod
        def from_login(cls, *, server_url: str) -> _FakeClient:
            return _FakeClient()

    monkeypatch.setattr(deploy_audit_module, "CoworldUploadClient", _FakeClientFactory)
    rows = load_coworld_registry(server="http://test")
    assert [row.id for row in rows] == ["cow_1", "cow_2"]


def test_ctf_repo_deploys_the_shared_paintbot_coworld() -> None:
    assert _repo_coworld_name("coworld-ctf", []) == "paintbot"


def test_markdown_output_includes_alert_summary() -> None:
    row = RepoDeployAudit(
        repo="coworld-ctf",
        default_branch="main",
        archived=False,
        coworld_name="paintbot",
        active_leagues=["CTF Daily", "Paintbot"],
        workflow_mode=WorkflowMode.automatic,
        workflow_files=[".github/workflows/upload-coworld-paintbot.yml"],
        canonical_version="0.7.38",
        canonical_id="cow_2",
        latest_version="0.7.38",
        latest_id="cow_2",
        latest_upload_run_conclusion="success",
        latest_upload_run_url="https://github.com/Metta-AI/coworld-ctf/actions/runs/1",
        alerts=[],
    )
    result = DeployAuditResult(
        owner="Metta-AI",
        generated_at=datetime(2026, 7, 20, tzinfo=UTC),
        rows=[row],
        alerts=[],
    )

    markdown = format_deploy_audit_markdown(result)

    assert "| coworld-ctf | paintbot | CTF Daily, Paintbot | main | automatic |" in markdown
    assert "No alerts." in markdown


def _coworld(
    coworld_id: str,
    name: str,
    version: str,
    *,
    canonical: bool,
    created_at: str,
) -> CoworldListEntry:
    return CoworldListEntry(
        id=coworld_id,
        name=name,
        version=version,
        manifest={"game": {"name": name}},
        manifest_hash=f"sha256:{coworld_id}",
        size_bytes=123,
        created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
        canonical=canonical,
    )
