FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir websockets
COPY player.py /app/player.py

CMD ["python", "/app/player.py"]
