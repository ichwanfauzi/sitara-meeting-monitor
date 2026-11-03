FROM python:3.12-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic.ini ./
COPY migrations/ ./migrations/

RUN python -m pip install --no-cache-dir . \
    && addgroup -g 10001 sitara \
    && adduser -D -H -u 10001 -G sitara -s /bin/false sitara \
    && mkdir -p /var/lib/sitara/evidence \
    && chown 10001:10001 /var/lib/sitara/evidence \
    && chmod 0700 /var/lib/sitara/evidence

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
