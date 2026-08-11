# Set the base image
FROM docker.io/library/python:3.13-slim AS builder

# Install system dependencies (compiler toolchain for the Cython extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /home/kairos

# Create a venv and install runtime dependencies
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY setup/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir Cython "numpy>=2.2.6" && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy remaining files
COPY bin/ bin/
COPY kairos/ kairos/
COPY scripts/ scripts/
COPY controllers/ controllers/
COPY scripts/ scripts-copy/
COPY setup.py .
COPY LICENSE .
COPY README.md .

COPY setup/pip_packages.txt /tmp/pip_packages.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/pip_packages.txt && \
    rm /tmp/pip_packages.txt

RUN python3 setup.py build_ext --inplace -j 8 && \
    rm -rf build/ && \
    find . -type f -name "*.cpp" -delete

# Cython is only needed to compile the extensions above; the resulting .so
# files don't need it at runtime.
RUN pip uninstall -y cython


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
COPY --from=builder /opt/venv/ /opt/venv/
COPY --from=builder /home/ /home/

# Put the venv on PATH so non-login shells (e.g. `podman exec … hbot`) find its python
# + console scripts, and expose the `hbot` CLI there (mirrors make install).
# This lets the image run as a single-bot container: `podman run … hbot start <config>`,
# `podman exec … hbot status`.
ENV PATH="/opt/venv/bin:$PATH"
RUN ln -sf /home/kairos/bin/hbot /opt/venv/bin/hbot

# Set the default command to run when starting the container.
# Exec form (not shell form) for a deterministic launch regardless of how the
# builder translates shell-form CMD/ENTRYPOINT.
CMD ["/bin/bash", "-c", "python3 ./bin/kairos_quickstart.py 2>> ./logs/errors.log"]
