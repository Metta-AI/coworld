FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir pydantic
COPY diagnoser.py /app/diagnoser.py

CMD ["python", "/app/diagnoser.py"]
