FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# держать в соответствии с dependencies в pyproject.toml
RUN pip install --no-cache-dir "httpx>=0.27,<1"

COPY bot ./bot

CMD ["python", "-m", "bot"]
