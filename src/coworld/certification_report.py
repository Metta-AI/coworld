from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Protocol, Sequence

from coworld.report import ReportManifest
from coworld.runner.runner import EpisodeArtifacts
from coworld.types import CoworldTranscript, StepResult, TranscriptStep


@dataclass(frozen=True)
class CertificationReportFile:
    path: Path

    @property
    def uri(self) -> str:
        return self.path.as_uri()


class CertificationReportReporter(Protocol):
    reporter_id: str
    manifest: ReportManifest
    report_path: Path


def write_certification_report(
    *,
    manifest_uri: str,
    transcript: CoworldTranscript,
    step_results: list[StepResult],
    artifacts: EpisodeArtifacts,
    reports: Sequence[CertificationReportReporter] | None = None,
    error: str | None = None,
) -> CertificationReportFile:
    path = artifacts.workspace / "certification_report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _render_certification_report(
            manifest_uri=manifest_uri,
            transcript=transcript,
            step_results=step_results,
            artifacts=artifacts,
            reports=reports or [],
            error=error,
        ),
        encoding="utf-8",
    )
    return CertificationReportFile(path=path)


def _render_certification_report(
    *,
    manifest_uri: str,
    transcript: CoworldTranscript,
    step_results: list[StepResult],
    artifacts: EpisodeArtifacts,
    reports: Sequence[CertificationReportReporter],
    error: str | None,
) -> str:
    result_by_id = {result.id: result for result in step_results if result.status in ("pass", "fail")}
    passed = sum(1 for result in result_by_id.values() if result.status == "pass")
    failed = [result for result in result_by_id.values() if result.status == "fail"]
    failed_result = failed[0] if failed else None
    status = "failed" if failed_result or error else "passed"
    total = len(transcript.steps)
    completed = len(result_by_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    title = f"Coworld certification {status}"

    rows = "\n".join(_step_block(step, result_by_id.get(step.id)) for step in transcript.steps)
    reporter_rows = (
        "\n".join(_reporter_row(report) for report in reports) or '<p class="muted">No reporter artifacts.</p>'
    )
    error_block = ""
    if failed_result is not None:
        error_block = f"""
          <section class="failure-panel">
            <div class="eyebrow">Failure</div>
            <h2>{escape(failed_result.id)}</h2>
            <p><strong>Reason:</strong> {escape(failed_result.failure_reason or "step_failed")}</p>
            {_labeled_detail("Details", failed_result.feedback or error)}
          </section>
        """
    elif error:
        error_block = f"""
          <section class="failure-panel">
            <div class="eyebrow">Failure</div>
            <h2>Certification stopped</h2>
            {_labeled_detail("Details", error)}
          </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --surface: #ffffff;
      --text: #18202f;
      --muted: #647084;
      --line: #d8dee9;
      --pass: #137a46;
      --pass-bg: #e8f6ee;
      --fail: #b42318;
      --fail-bg: #fdecec;
      --pending: #6b7280;
      --pending-bg: #eef1f5;
      --accent: #3056d3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.5;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    header {{
      display: grid;
      gap: 20px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 24px;
      margin-bottom: 24px;
    }}
    h1 {{
      margin: 0;
      font-size: 34px;
      line-height: 1.1;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    p {{ margin: 0 0 10px; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric, section, details {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .metric {{
      padding: 14px;
      min-width: 0;
    }}
    .metric .label, .eyebrow {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
    }}
    .metric .value {{
      font-size: 22px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }}
    .muted, code.path {{
      color: var(--muted);
    }}
    code.path {{
      display: inline-block;
      max-width: 100%;
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 13px;
    }}
    .status-pass {{ color: var(--pass); background: var(--pass-bg); }}
    .status-fail {{ color: var(--fail); background: var(--fail-bg); }}
    .status-not-run {{ color: var(--pending); background: var(--pending-bg); }}
    .failure-panel {{
      border-color: #f1aaa5;
      background: var(--fail-bg);
      padding: 18px;
      margin-bottom: 18px;
    }}
    .step-list {{
      display: grid;
      gap: 10px;
      margin-top: 18px;
    }}
    details {{
      overflow: hidden;
    }}
    summary {{
      cursor: pointer;
      display: grid;
      grid-template-columns: 120px minmax(180px, 1fr) auto;
      align-items: center;
      gap: 14px;
      padding: 14px 16px;
      list-style: none;
    }}
    summary::-webkit-details-marker {{ display: none; }}
    .step-id {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .step-check {{
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .step-body {{
      border-top: 1px solid var(--line);
      padding: 14px 16px 18px 150px;
    }}
    .field {{
      margin-top: 10px;
    }}
    .field-label {{
      color: var(--muted);
      font-weight: 700;
      font-size: 13px;
    }}
    .detail-lines {{
      display: grid;
      gap: 6px;
      overflow-wrap: anywhere;
    }}
    .artifacts, .reporters {{
      padding: 18px;
      margin-top: 18px;
    }}
    .artifact-grid {{
      display: grid;
      grid-template-columns: 160px minmax(0, 1fr);
      gap: 8px 14px;
    }}
    .reporter-row {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
      margin-top: 10px;
    }}
    @media (max-width: 760px) {{
      main {{ padding: 22px 14px 36px; }}
      h1 {{ font-size: 28px; }}
      .summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      summary {{ grid-template-columns: 1fr; gap: 8px; }}
      .step-body {{ padding-left: 16px; }}
      .artifact-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">Coworld certification</div>
        <h1>{escape(status.title())}</h1>
        <p class="muted">{escape(manifest_uri)}</p>
      </div>
      <div class="summary">
        <div class="metric"><div class="label">Transcript</div><div class="value">{escape(transcript.name)}</div></div>
        <div class="metric"><div class="label">Steps passed</div><div class="value">{passed}/{total}</div></div>
        <div class="metric"><div class="label">Completed</div><div class="value">{completed}/{total}</div></div>
        <div class="metric"><div class="label">Generated</div><div class="value">{escape(generated_at)}</div></div>
      </div>
    </header>
    {error_block}
    <section class="artifacts">
      <h2>Artifacts</h2>
      <div class="artifact-grid">
        <div class="field-label">Workspace</div><code class="path">{escape(str(artifacts.workspace))}</code>
        <div class="field-label">Results</div><code class="path">{escape(str(artifacts.results_path))}</code>
        <div class="field-label">Replay</div><code class="path">{escape(str(artifacts.replay_path))}</code>
        <div class="field-label">Logs</div><code class="path">{escape(str(artifacts.logs_dir))}</code>
      </div>
    </section>
    <section class="reporters">
      <h2>Reporter Artifacts</h2>
      {reporter_rows}
    </section>
    <div class="step-list">
      {rows}
    </div>
  </main>
</body>
</html>
"""


def _step_block(step: TranscriptStep, result: StepResult | None) -> str:
    status = result.status if result else "not-run"
    status_label = "not run" if status == "not-run" else status
    body = f"""
      <div class="field"><div class="field-label">Pass condition</div><div>{escape(step.pass_)}</div></div>
      <div class="field"><div class="field-label">How it is checked</div><div>{escape(step.how)}</div></div>
    """
    if result and result.failure_reason:
        body += f"""
      <div class="field"><div class="field-label">Failure reason</div><div>{escape(result.failure_reason)}</div></div>
        """
    if result and result.feedback:
        body += f"""
      <div class="field"><div class="field-label">Details</div>{_detail_lines(result.feedback)}</div>
        """
    return f"""
      <details {"open" if status == "fail" else ""}>
        <summary>
          <span class="step-id">{escape(step.id)}</span>
          <span class="step-check">{escape(step.checks)}</span>
          <span class="status-pill status-{escape(status)}">{escape(status_label)}</span>
        </summary>
        <div class="step-body">{body}</div>
      </details>
    """


def _reporter_row(report: CertificationReportReporter) -> str:
    render = report.manifest.render or "(no render entry)"
    return f"""
      <div class="reporter-row">
        <div><strong>{escape(report.reporter_id)}</strong></div>
        <div class="muted">render={escape(render)}</div>
        <code class="path">{escape(str(report.report_path))}</code>
      </div>
    """


def _labeled_detail(label: str, value: str | None) -> str:
    if not value:
        return ""
    return f"<div><strong>{escape(label)}:</strong>{_detail_lines(value)}</div>"


def _detail_lines(value: str) -> str:
    lines = [line for line in value.splitlines() if line.strip()]
    if not lines:
        lines = [value]
    rendered_lines = "".join(f'<div class="detail-line">{escape(line)}</div>' for line in lines)
    return f'<div class="detail-lines">{rendered_lines}</div>'
