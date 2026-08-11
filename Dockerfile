# Set the base image
FROM docker.io/library/python:3.13-slim AS builder

# Install system dependencies (compiler toolchain for the Cython extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/kairos

# Poetry is the installer (not pip) — bootstrapped once into the base image, outside the
# project's own venv. `virtualenvs.in-project` makes `poetry install` create .venv/ right here,
# matching the same convention `make install` uses on a host. `keyring.enabled false` avoids
# Poetry probing for a (nonexistent, in a container) OS keyring/D-Bus session.
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.in-project true && \
    poetry config keyring.enabled false

# Copy remaining files
COPY pyproject.toml poetry.lock poetry.toml build.py ./
COPY bin/ bin/
COPY kairos/ kairos/
COPY scripts/ scripts/
COPY controllers/ controllers/
COPY scripts/ scripts-copy/
COPY LICENSE .
COPY README.md .

# `--only main` skips the dev dependency group (pytest, flake8, coverage, ...) — none of it is
# needed to run the bot. build.py's Cython/numpy requirement is satisfied by Poetry's own build
# isolation (an ephemeral env per [build-system] requires), so it isn't listed here.
RUN poetry install --only main --no-interaction && \
    rm -rf build/ && \
    find . -type f -name "*.cpp" -delete


# Build final image using artifacts from builder
FROM docker.io/library/python:3.13-slim AS release

# Dockerfile author / maintainer
LABEL maintainer="Fede Cardoso @dardonacci <federico@hummingbot.org>"

# Build arguments
ARG BRANCH=""
ARG COMMIT=""
ARG BUILD_DATE=""
LABEL branch=${BRANCH}
LABEL commit=${COMMIT}
LABEL date=${BUILD_DATE}

# Set ENV variables
ENV COMMIT_SHA=${COMMIT}
ENV COMMIT_BRANCH=${BRANCH}
ENV BUILD_DATE=${BUILD_DATE}

ENV INSTALLATION_TYPE=docker

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends sudo && \
    rm -rf /var/lib/apt/lists/*

# Create mount points
RUN mkdir -p /home/kairos/conf /home/kairos/conf/connectors /home/kairos/conf/strategies /home/kairos/conf/controllers /home/kairos/conf/scripts /home/kairos/logs /home/kairos/data /home/kairos/certs /home/kairos/scripts /home/kairos/controllers

WORKDIR /home/kairos

# Copy all build artifacts from builder image
COPY --from=builder /home/kairos/ /home/kairos/

# Put the venv on PATH so non-login shells (e.g. `podman exec … hbot`) find its python
# + console scripts, and expose the `hbot` CLI there (mirrors make install).
# This lets the image run as a single-bot container: `podman run … hbot start <config>`,
# `podman exec … hbot status`.
ENV PATH="/home/kairos/.venv/bin:$PATH"
RUN ln -sf /home/kairos/bin/hbot /home/kairos/.venv/bin/hbot

# Set the default command to run when starting the container.
# Exec form (not shell form) for a deterministic launch regardless of how the
# builder translates shell-form CMD/ENTRYPOINT.
CMD ["/bin/bash", "-c", "python3 ./bin/kairos_quickstart.py 2>> ./logs/errors.log"]
