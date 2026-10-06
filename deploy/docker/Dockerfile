# Harbor-DL container: app + virtual display + noVNC so the embedded login browser can be shown in the web UI.
# Build from the rebuild/ directory:  docker build -f deploy/docker/Dockerfile -t harbor-dl .
FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        supervisor xvfb x11vnc novnc websockify fluxbox chromium fonts-noto-cjk ffmpeg \
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
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
