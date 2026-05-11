FROM python:3.12-slim

RUN pip install --no-cache-dir \
    mettagrid==0.26.17

WORKDIR /app
COPY packages/mettagrid/python/src/mettagrid/policy/policy.py /tmp/mettagrid_policy.py
RUN python - <<'PY'
from pathlib import Path
import shutil

import mettagrid

policy_path = Path(mettagrid.__file__).parent / "policy" / "policy.py"
shutil.copyfile("/tmp/mettagrid_policy.py", policy_path)
PY
COPY packages/cogames/src/cogames /app/cogames
COPY packages/coworld/src/coworld/examples/cogs_vs_clips/player/policy_player.py /app/coworld_policy_player.py
ENV PYTHONPATH=/app

CMD ["python", "/app/coworld_policy_player.py"]
