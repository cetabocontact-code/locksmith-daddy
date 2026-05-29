# Locksmith Daddy — production image.
#
# We route all scraping through ScrapFly (HTTP API), so we don't need
# Chromium / Playwright in production. python:3.13-slim is much smaller
# (~50 MB) and faster to deploy than the Playwright base image.
#
# If you ever need to run Playwright locally for debugging, do it from your
# venv on your dev machine — production stays slim.

FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages needed for bcrypt + httpx[ssl] + lxml (bs4 parser)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching. Skip Playwright at runtime
# (still in pyproject.toml for dev — pip installs the SDK but we don't
# install the Chromium binary).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e . --no-deps && \
    pip install \
        "httpx>=0.27" "pydantic>=2.6" "tenacity>=8.2" \
        "fastapi>=0.110" "uvicorn[standard]>=0.29" \
        "bcrypt>=4.0" "python-multipart>=0.0.9" "itsdangerous>=2.2" \
        "email-validator>=2.1" "beautifulsoup4>=4.12" "lxml>=5.0" \
        "python-dotenv>=1.0" "typer>=0.12" "rich>=13.7"

# App data dir (SQLite + secret_key) — mounted as a Fly volume
RUN mkdir -p /data
ENV LBT1_DATA_DIR=/data \
    LBT1_DB_PATH=/data/lbt1.db

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "lbt1.api:app", "--host", "0.0.0.0", "--port", "8000"]
