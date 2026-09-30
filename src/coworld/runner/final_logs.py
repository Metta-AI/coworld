"""Capture episode shutdown logs before Kubernetes removes the container runtime state."""

import os
import signal
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from kubernetes import client
from kubernetes.client.rest import ApiException
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed
from urllib3.exceptions import HTTPError

from coworld.runner.io import FINAL_LOGS_CONTAINER_NAME, FINAL_LOGS_READY_PATH, FinalLogCapture, upload_data
from coworld.runner.kubernetes_runner import _load_incluster_config
from coworld.runner.llm_sidecar_wiring import LLM_SIDECAR_CONTAINER_NAME


def main() -> None:
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.set())
    api = _load_incluster_config(
        egress_enforcement_enabled=os.environ.get("COWORLD_EGRESS_ENFORCEMENT_ENABLED") == "true",
        retry_count=0,
    )
    core = client.CoreV1Api(api)
    Path(FINAL_LOGS_READY_PATH).touch()
    stopped.wait()
    namespace, name = os.environ["JOB_NAMESPACE"], os.environ["POD_NAME"]
    pod = Retrying(
        retry=retry_if_exception_type((ApiException, HTTPError)),
        stop=stop_after_attempt(3),
        wait=wait_fixed(0.5),
        reraise=True,
    )(core.read_namespaced_pod, name=name, namespace=namespace, _request_timeout=5)
    if pod.metadata.uid != os.environ["POD_UID"]:
        raise ValueError("Final log collection observed a replacement Pod")
    statuses = [*(pod.status.init_container_statuses or []), *(pod.status.container_statuses or [])]
    # Declared first among native sidecars, this collector receives SIGTERM last.
    # Keep the runtime alive until all other containers' final logs have reached storage.
    logs: dict[str, str] = {}
    errors: dict[str, str] = {}
    for status in statuses:
        if status.name == FINAL_LOGS_CONTAINER_NAME or not status.container_id:
            continue
        try:
            inference_logs = status.name == LLM_SIDECAR_CONTAINER_NAME
            byte_limit = (16 if inference_logs else 1) * 1024 * 1024
            transfer_seconds = 15 if inference_logs else 5
            deadline = time.monotonic() + transfer_seconds
            response = core.read_namespaced_pod_log(
                name=name,
                namespace=namespace,
                container=status.name,
                tail_lines=10000,
                _request_timeout=5,
                _preload_content=False,
            )
            try:
                # Server-side limit_bytes drops the end of the selected tail.
                # Stream instead, keeping the final bytes that include shutdown diagnostics.
                tail = bytearray()
                for chunk in response.stream(65536):
                    tail.extend(chunk)
                    if len(tail) > byte_limit:
                        errors[status.name] = f"diagnostic tail exceeded its {byte_limit // (1024 * 1024)} MiB budget"
                        del tail[:-byte_limit]
                    if time.monotonic() >= deadline:
                        errors[status.name] = f"log transfer exceeded its {transfer_seconds}-second budget"
                        break
                logs[status.name] = tail.decode("utf-8", errors="replace")
            finally:
                response.close()
                response.release_conn()
        except (ApiException, HTTPError) as exc:
            errors[status.name] = str(exc)
    # upload_data already retries transient HTTP/relay failures with bounded backoff.
    capture = FinalLogCapture(
        pod_uid=pod.metadata.uid,
        captured_at=datetime.now(UTC),
        logs=logs,
        errors=errors,
        status="partial" if errors else "complete",
        container_exit_codes={
            status.name: status.state.terminated.exit_code
            for status in statuses
            if status.name != FINAL_LOGS_CONTAINER_NAME and status.state.terminated is not None
        },
    )
    upload_data(os.environ["FINAL_LOGS_URI"], capture.model_dump_json(), content_type="application/json")


if __name__ == "__main__":
    main()
