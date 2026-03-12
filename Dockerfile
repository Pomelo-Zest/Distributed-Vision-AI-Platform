FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md /app/
COPY libs /app/libs
COPY services /app/services
COPY config /app/config
COPY dashboard /app/dashboard

RUN pip install --upgrade pip && pip install .

COPY . /app

