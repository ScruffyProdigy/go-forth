# Build context is the REPO ROOT, not api/ — so the root .dockerignore is the
# one authority on what reaches the daemon for both images. Building from api/
# would silently ship api/.venv and any sibling agent worktree into the
# context, since a .dockerignore only applies at the context root.
#   docker build -f api/Dockerfile .

# ---- Build stage: resolve dependencies into a virtualenv ----
FROM python:3.12-slim AS build
WORKDIR /app

# psycopg[binary] ships wheels, so no compiler is needed — but pip still wants
# the venv to exist before it can install into it.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies resolve from pyproject alone, so this layer is cached until the
# dependency list itself changes rather than on every source edit.
COPY api/pyproject.toml ./
COPY api/app/__init__.py ./app/
RUN pip install --no-cache-dir .

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

COPY --from=build /opt/venv /opt/venv

# The package, plus the raw SQL. Migrations are read at runtime rather than
# compiled, and the migrate initContainer runs `python -m app.migrate` out of
# this same image.
COPY api/app ./app
COPY api/migrations ./migrations

# Run as a non-root user. python:slim has no equivalent of node:alpine's
# built-in `node` user, so one is created here.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 3002

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('API_PORT','3002')+'/healthz')" || exit 1

CMD ["python", "-m", "app.server"]
