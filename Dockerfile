# Set the base image. python:3.12-slim is an official multi-arch image (linux/amd64 +
# linux/arm64), so the buildx matrix in .github/workflows/docker_buildx_workflow.yml keeps
# working. 3.12 is the floor the dependency set requires (pandas-ta needs >=3.12).
FROM python:3.12-slim AS builder

# Install system dependencies. build-essential/gcc/g++ are needed both for the Cython
# extensions and for the few deps with no aarch64 wheel (safe-pysha3, crcmod).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gcc g++ libusb-1.0-0 && \
    rm -rf /var/lib/apt/lists/*

ENV POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir "poetry==2.4.1"

WORKDIR /home/hummingbot

# Install the locked dependency set first, as its own layer: it only reinvalidates when
# pyproject.toml/poetry.lock change, not on every source edit.
COPY pyproject.toml poetry.lock poetry.toml ./
RUN poetry install --no-root --only main

# Copy remaining files
COPY bin/ bin/
COPY hummingbot/ hummingbot/
COPY scripts/ scripts/
COPY controllers/ controllers/
COPY scripts/ scripts-copy/
COPY setup.py .
COPY LICENSE .
COPY README.md .

# Editable install: compiles the Cython extensions in place and puts the `hbot` console
# script in .venv/bin (replacing the symlink the conda image needed).
RUN poetry run pip install -e . --no-build-isolation --no-deps && \
    rm -rf build/ && \
    find . -type f -name "*.cpp" ! -path "./hummingbot/core/cpp/*" -delete


# Build final image using artifacts from builder
FROM python:3.12-slim AS release

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
    apt-get install -y --no-install-recommends libusb-1.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Create mount points
RUN mkdir -p /home/hummingbot/conf /home/hummingbot/conf/connectors /home/hummingbot/conf/strategies /home/hummingbot/conf/controllers /home/hummingbot/conf/scripts /home/hummingbot/logs /home/hummingbot/data /home/hummingbot/certs /home/hummingbot/scripts /home/hummingbot/controllers

WORKDIR /home/hummingbot

# Copy all build artifacts from builder, including the .venv. Both stages use the same base
# image and the same absolute path, which is what makes copying a venv safe (venvs are not
# relocatable — the interpreter path baked into .venv/bin/* must still resolve).
COPY --from=builder /home/hummingbot /home/hummingbot

# Put the venv on PATH so non-login shells (e.g. `docker exec … hbot`) find its python and
# console scripts without any activation step. This lets the image run as a single-bot
# container: `docker run … hbot start <config>`, `docker exec … hbot status`.
ENV VIRTUAL_ENV=/home/hummingbot/.venv
ENV PATH=/home/hummingbot/.venv/bin:$PATH

# Set the default command to run when starting the container
CMD ["/bin/sh", "-c", "./bin/hummingbot_quickstart.py 2>> ./logs/errors.log"]
