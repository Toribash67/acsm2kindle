# libgourou utils (acsmdownloader, adept_activate, adept_remove) live in
# /usr/local/bin of this image. Pin the `ubuntu` tag explicitly (not
# `latest`): upstream's `latest` currently resolves to the Alpine variant,
# which has no apt-get for the python3 install below.
FROM bcliang/docker-libgourou:ubuntu

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# Ubuntu 22.04's pip3 (22.0.2) predates PEP 668 / --break-system-packages
# (added in pip 23.0.1); this base has no externally-managed-environment
# restriction, so a plain install works.
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV DATA_DIR=/data
# Module-level `app` in app/main.py is built only when this is set (keeps
# pytest imports side-effect-free); the container opts in.
ENV ACSM2KINDLE_AUTOSTART=1
EXPOSE 8000
# The base image sets ENTRYPOINT ["/bin/bash","/home/libgourou/entrypoint.sh"],
# a hardcoded acsmdownloader->adept_remove pipeline that treats CMD[0] as an
# .acsm filename. Reset it so our CMD runs uvicorn directly instead of being
# swallowed as an argument to that script.
ENTRYPOINT []
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
