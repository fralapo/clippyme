# ClippyMe — Multi-platform Dockerfile
#
# CPU / Apple Silicon (default):  docker compose up --build
# NVIDIA GPU:                     docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build

ARG GPU_RUNTIME=cpu

# ============================================================
# Stage 2a: NVIDIA CUDA runtime (x86_64 only)
# ============================================================
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04 AS runtime-nvidia

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev python3.11-distutils \
    ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    curl unzip ca-certificates && \
    curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/ && \
    rm -rf /root/.deno && \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
    rm -rf /var/lib/apt/lists/* && \
    # Install latest auto-editor Nim binary (v30.x track). The runtime
    # updater (auto_editor_updater.py) keeps it fresh after build.
    ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64)  AE_ASSET=auto-editor-linux-x86_64 ;; \
      aarch64) AE_ASSET=auto-editor-linux-aarch64 ;; \
      *) echo "Unsupported arch $ARCH for auto-editor binary"; exit 1 ;; \
    esac && \
    curl -fsSL -o /usr/local/bin/auto-editor \
      "https://github.com/WyattBlue/auto-editor/releases/latest/download/$AE_ASSET" && \
    chmod +x /usr/local/bin/auto-editor && \
    /usr/local/bin/auto-editor --version || echo "auto-editor install check failed (non-fatal)"

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# ============================================================
# Stage 2b: CPU runtime (multi-arch: amd64, arm64, Apple Silicon)
# ============================================================
FROM python:3.11-slim AS runtime-cpu

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    curl unzip ca-certificates && \
    curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/ && \
    rm -rf /root/.deno && \
    rm -rf /var/lib/apt/lists/* && \
    # Install latest auto-editor Nim binary (v30.x track). The runtime
    # updater (auto_editor_updater.py) keeps it fresh after build.
    ARCH=$(uname -m) && \
    case "$ARCH" in \
      x86_64)  AE_ASSET=auto-editor-linux-x86_64 ;; \
      aarch64) AE_ASSET=auto-editor-linux-aarch64 ;; \
      *) echo "Unsupported arch $ARCH for auto-editor binary"; exit 1 ;; \
    esac && \
    curl -fsSL -o /usr/local/bin/auto-editor \
      "https://github.com/WyattBlue/auto-editor/releases/latest/download/$AE_ASSET" && \
    chmod +x /usr/local/bin/auto-editor && \
    /usr/local/bin/auto-editor --version || echo "auto-editor install check failed (non-fatal)"

# ============================================================
# Stage 3: Final image
# ============================================================
FROM runtime-${GPU_RUNTIME} AS final

WORKDIR /app
ENV PYTHONUNBUFFERED=1
# /app/data/bin is the writable location where auto_editor_updater.py drops
# fresh auto-editor binaries at runtime. Prepend it so it shadows the
# system-wide install in /usr/local/bin when a newer version is available.
ENV PATH=/app/data/bin:$PATH

# Install Python deps. CUDA pip wheels (nvidia-cublas-cu12, cudnn) are only
# needed on the GPU path — skipping them on CPU saves ~500 MB per image.
#
# Speaker diarization on the Whisper path is OPT-IN via ENABLE_WHISPER_DIARIZE.
# pyannote.audio pulls ~500 MB of deps (pytorch-lightning, speechbrain,
# torchaudio extras) and requires accepting the pyannote/speaker-diarization-3.1
# license on HuggingFace, so we keep it out of the default image.
# Build with:   docker compose build --build-arg ENABLE_WHISPER_DIARIZE=1
ARG GPU_RUNTIME
ARG ENABLE_WHISPER_DIARIZE=0
COPY requirements.txt .
# BuildKit cache mount: pip's download cache lives in the mount (shared across
# rebuilds) and is NOT baked into the image layer, so we get fast rebuilds
# without the image bloat that dropping --no-cache-dir would otherwise cause.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    if [ "$GPU_RUNTIME" = "nvidia" ]; then \
        pip install nvidia-cublas-cu12 && \
        SITE=$(python -c "import site; print(site.getsitepackages()[0])") && \
        echo "$SITE/nvidia/cublas/lib" > /etc/ld.so.conf.d/nvidia-pip.conf && \
        echo "$SITE/nvidia/cudnn/lib" >> /etc/ld.so.conf.d/nvidia-pip.conf && \
        ldconfig 2>/dev/null || true; \
    fi && \
    if [ "$ENABLE_WHISPER_DIARIZE" = "1" ]; then \
        pip install 'pyannote.audio>=3.1'; \
    fi && \
    pip install --upgrade yt-dlp

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser && \
    mkdir -p /app/uploads /app/output /app/data /app/data/bin /tmp/Ultralytics && \
    chown -R appuser:appuser /app /tmp/Ultralytics

USER appuser

# Pre-download YOLO model
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY --chown=appuser:appuser . .

# Install the clippyme package itself (src-layout) so that
# `python -m clippyme.pipeline.main` and `uvicorn clippyme.api.app:app` resolve.
USER root
RUN pip install --no-cache-dir -e .
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl http://localhost:8000/ || exit 1

CMD ["uvicorn", "clippyme.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
