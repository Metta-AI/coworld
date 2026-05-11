from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console

console = Console()


def emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
