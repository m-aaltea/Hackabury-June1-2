# syntax=docker/dockerfile:1

# ---- build stage: install dependencies into an isolated virtualenv ----
FROM python:3.14-slim AS builder

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .

RUN python -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir -r requirements.txt

# ---- runtime stage: slim image with only the prebuilt venv + app code ----
FROM python:3.14-slim

# Lets the same ordinary ASGI web server run inside Lambda without changing the
# FastAPI application into Lambda-specific handlers.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 \
    /lambda-adapter /opt/extensions/lambda-adapter

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PROTOCOL=tcp

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . .

# GEMINI_API_KEY is supplied at runtime (never baked into the image):
#   docker run -p 8000:8000 -e GEMINI_API_KEY=... passpreview-backend
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
