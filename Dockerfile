# Development image for the mounted sudofx checkout.
# Source, credentials, Git history, and authoritative SQLite records remain on
# the host; rebuilding this image must never copy or become an authority store.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/sudofx

# Git makes the mounted checkout usable for normal branch and push work, while
# credentials are bridged dynamically by VS Code. SQLite comes from Python's
# standard library; the repo currently has no runtime
# dependencies, so the development image avoids a second dependency contract.
# Debian's default image points at an HTTP mirror, which is unavailable in this
# Docker Desktop network. HTTPS keeps the dev image build on the reachable path.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sudofx \
    && useradd --uid 10001 --gid sudofx --create-home --shell /bin/bash sudofx \
    && chown -R sudofx:sudofx /home/sudofx \
    && git config --system --add safe.directory /workspace

WORKDIR /workspace
ENV PYTHONPATH=/workspace/src:/workspace
USER 10001:10001
EXPOSE 8765

# The idle command keeps an interactive development environment available.
# User commands execute against the bind-mounted host checkout, not image copies.
CMD ["sleep", "infinity"]
