FROM python:3.12-slim

# FFmpeg for audio probing and video processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libvidstab1.1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY assets/ ./assets/

# Build-time git metadata — injected by CI via --build-arg
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ARG GIT_TAG=unknown
ARG BUILD_TIME=unknown

# Single worker — APScheduler must not be duplicated across workers.
# Data dirs are bind-mounted from /srv/social-media-cms/data at runtime.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=prod \
    GIT_COMMIT=${GIT_COMMIT} \
    GIT_BRANCH=${GIT_BRANCH} \
    GIT_TAG=${GIT_TAG} \
    BUILD_TIME=${BUILD_TIME}

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
