FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY libs /app/libs
COPY services /app/services
COPY config /app/config
COPY dashboard /app/dashboard

RUN pip install --upgrade pip && pip install .
