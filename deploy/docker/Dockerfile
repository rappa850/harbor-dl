# Harbor-DL container: app + virtual display + noVNC so the embedded login browser can be shown in the web UI.
# Build from the repository root:  docker build -f deploy/docker/Dockerfile -t harbor-dl .
FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="Harbor-DL" \
      org.opencontainers.image.description="Self-hosted personal media workstation" \
      org.opencontainers.image.source="https://github.com/rappa850/harbor-dl" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update && apt-get install -y --no-install-recommends \
        supervisor xvfb x11vnc novnc websockify fluxbox chromium fonts-noto-cjk ffmpeg tzdata curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY --from=ui /ui/dist ./frontend/dist
COPY deploy/docker/supervisord.conf /etc/supervisor/conf.d/harbor-dl.conf
ENV HARBOR_BROWSER_MODE=docker \
    HARBOR_DISPLAY=:99 \
    HARBOR_CHROME=/usr/bin/chromium \
    HARBOR_DATA_DIR=/data \
    HARBOR_NOVNC_DIR=/usr/share/novnc \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/api/system/health || exit 1
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
