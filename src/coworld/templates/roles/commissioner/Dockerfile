FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir "coworld[examples]"
COPY commissioner.py /app/commissioner.py

CMD ["python", "/app/commissioner.py"]
