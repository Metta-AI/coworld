FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir "coworld[examples]"
COPY game_server.py /app/game_server.py

CMD ["python", "/app/game_server.py"]
