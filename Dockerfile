FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/modelgate/.venv/bin:$PATH"

WORKDIR /srv/modelgate

RUN pip install --no-cache-dir uv==0.10.0
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY worker ./worker
RUN uv sync --locked --no-dev --no-cache

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
