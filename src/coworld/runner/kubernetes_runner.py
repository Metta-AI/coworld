from __future__ import annotations

import argparse
import asyncio
import hmac
import http.server
import json
import os
import socket
import socketserver
import ssl
import sys
import tempfile
import threading
import time
import zipfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import urlsplit

import httpx
import urllib3
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.utils import parse_quantity
from urllib3.exceptions import HTTPError
from urllib3.util import Retry

from coworld.runner.bedrock_enablement import BedrockEnablement, resolve_player_bedrock
from coworld.runner.bedrock_metadata import (
    CoworldEpisodeBedrockMetadata,
    serialize_bedrock_request_metadata,
)
from coworld.runner.bedrock_sidecar_wiring import (
    BEDROCK_SIDECAR_CONTAINER_NAME,
    COWORLD_EGRESS_ENFORCED_LABEL,
    RESERVED_SIDECAR_APP_ENV,
    bedrock_app_endpoint_env,
    bedrock_sidecar_token_volume,
    build_bedrock_sidecar,
    resolve_image_attribution_key,
)
from coworld.runner.io import (
    PlayerRuntimeStatus,
    PlayerRuntimeStatuses,
    RunnerEpisodeError,
    RunnerError,
    RunnerErrorType,
    read_data,
    upload_data,
    upload_file,
)
from coworld.runner.phase_timings import EpisodePhaseTimings
from coworld.runner.runner import (
    CERTIFICATION_EPISODE_SOURCE,
    DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS,
    DEFAULT_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    LOBBY_RUNTIME_STARTUP_TIMEOUT_SECONDS,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    _raise_if_game_declared_player_failure,
    _require_bad_player_rejected,
    _require_global_message,
    _require_http_ok,
    _validate_results_file,
    coworld_game_config,
    episode_player_tokens,
)
from coworld.runner.runner import (
    _player_query as _episode_player_query,
)
from coworld.types import CoworldEpisodeJobSpec, CoworldHumanPlayerSpec

WORKDIR = Path(os.environ.get("COWORLD_WORKDIR", "/coworld"))
STATE_PATH = WORKDIR / "state.json"
GAME_PORT = int(os.environ.get("COGAME_PORT", "8080"))
HEALTH_PORT = int(os.environ.get("COWORLD_WORKER_HEALTH_PORT", "9090"))
PLAYER_ARTIFACT_PORT = 9091

# Poll cadence for the two in-pod wait loops. Each tick issues a read_namespaced_pod against
# the API server; with many concurrent episodes the aggregate read rate contributes to API
# Priority & Fairness 429s (etcd throttle). Episodes run seconds-to-minutes, so a 1s cadence
# is latency-insensitive and cuts that steady read pressure.
_HEALTH_POLL_SECONDS = 1.0
_ARTIFACT_POLL_SECONDS = 1.0
_PLAYER_ARTIFACT_MAX_BYTES = 200 * 1024 * 1024
_PLAYER_ARTIFACT_HEADER_DEADLINE_SECONDS = 5.0
_PLAYER_ARTIFACT_BODY_DEADLINE_SECONDS = 60.0
_PLAYER_ARTIFACT_MAX_CONNECTIONS = 4
_PLAYER_ARTIFACT_MAX_CONNECTIONS_PER_SOURCE = 1
_PLAYER_ARTIFACT_MAX_ATTEMPTS = 3
_BEDROCK_SERVICE_ACCOUNT = "episode-runner"
_KUBERNETES_API_SERVICE_HOST = "kubernetes.default.svc"
_DIRECT_BEDROCK_APP_ENV = {
    "USE_BEDROCK",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
}
DEFAULT_PLAYER_CPU_REQUEST = "2"
DEFAULT_PLAYER_MEMORY_REQUEST = "2Gi"

# Keep the process-start gate inside the game's all-connected-or-timeout start window.
DEFAULT_PLAYER_CONNECT_TIMEOUT_SECONDS = 180.0
_PLAYER_WAITING_POLICY_FAILURE_REASONS = {
    "CrashLoopBackOff",
    "CreateContainerConfigError",
    "ErrImagePull",
    "ImagePullBackOff",
    "InvalidImageName",
}

# Standard math-library thread-pool knobs. PyTorch reads OMP_NUM_THREADS for its default
# intra-op thread count, so pinning these covers the common ML player stack.
_PLAYER_THREAD_POOL_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

# The path to the configuration file that dictates the game service runtime behavior.
_WAIT_FOR_GAME_SERVICE_SCRIPT = Path(WORKDIR / "config.json")

# Wait for game service script configuration
# Issue Title: Heartleaf league...
# Issue Body: ...
# End of constants block for runner