#!/usr/bin/bash

# This script builds Python wheels from cachito sources for the OCP build.
# It runs in the wheel-builder stage of the Docker build.
# Adapted from ironic-image's build-wheels-ocp.sh with the addition of
# the hardware_manager local package.

set -euxo pipefail

REQS="${REMOTE_SOURCES_DIR}/requirements.cachito"

# load cachito variables only if they're available
if [[ -d "${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps" ]]; then
    source "${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps/cachito.env"
    REQS="${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps/app/requirements.cachito"
fi

# NOTE(elfosardo): --no-build-isolation is needed to allow build engine
# to use build tools already installed in the system, for our case
# setuptools and pbr, instead of installing them in the isolated
# pip environment.
WHEEL_OPTIONS="--no-cache-dir --no-build-isolation --no-index"

# NOTE(elfosardo): download all the libraries and dependencies first,
# using --no-deps to avoid chain-downloading packages.
# This forces to download only the packages specified in the requirements file.
# This is done to allow testing any source code package in CI emulating
# the cachito downstream build pipeline.
# See https://issues.redhat.com/browse/METAL-1049 for more details.
PIP_SOURCES_DIR="/tmp/all_sources"
mkdir -p "${PIP_SOURCES_DIR}"
python3.12 -m pip download --no-binary=:all: --no-build-isolation --no-deps -r "${REQS}" -d "${PIP_SOURCES_DIR}"

# Build wheels from downloaded sources
mkdir -p /wheels
# shellcheck disable=SC2086
python3.12 -m pip wheel \
    $WHEEL_OPTIONS \
    --wheel-dir=/wheels \
    --no-deps \
    --find-links="${PIP_SOURCES_DIR}" \
    -r "${REQS}"

# Build the hardware_manager local package
PBR_VERSION=1.0 python3.12 -m pip wheel \
    --no-build-isolation \
    --no-index \
    --no-deps \
    --wheel-dir=/wheels \
    /tmp/hardware_manager

rm -rf "${PIP_SOURCES_DIR}"

echo "Wheels built successfully in /wheels"
ls -la /wheels/
