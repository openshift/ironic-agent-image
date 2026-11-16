#!/usr/bin/bash

# Source this file and call configure_python to derive the Python commands and
# RPM prefix from the base image's RHEL major version.
configure_python()
{
    local os_release_file="${1:-/etc/os-release}"
    local detected_rhel_major
    local VERSION_ID=

    if [[ ! -r "${os_release_file}" ]]; then
        echo "ERROR: cannot read OS release information from ${os_release_file}" >&2
        return 1
    fi

    . "${os_release_file}"
    if [[ -z "${VERSION_ID:-}" ]]; then
        echo "ERROR: VERSION_ID is missing from ${os_release_file}" >&2
        return 1
    fi
    detected_rhel_major="${VERSION_ID%%.*}"

    if [[ -n "${RHEL_MAJOR:-}" && "${RHEL_MAJOR}" != "${detected_rhel_major}" ]]; then
        echo "ERROR: RHEL_MAJOR=${RHEL_MAJOR} does not match base image major ${detected_rhel_major}" >&2
        return 1
    fi

    RHEL_MAJOR="${detected_rhel_major}"
    export RHEL_MAJOR

    case "${RHEL_MAJOR}" in
        9)
            PYTHON_VERSION=3.12
            ;;
        10)
            PYTHON_VERSION=3.14
            ;;
        *)
            echo "ERROR: unsupported RHEL major in ${os_release_file}: ${RHEL_MAJOR:-<unset>}" >&2
            return 1
            ;;
    esac

    PYTHON_BIN="python${PYTHON_VERSION}"
    PYTHON_PACKAGE_PREFIX="python${PYTHON_VERSION}"
    export PYTHON_VERSION PYTHON_BIN PYTHON_PACKAGE_PREFIX
}
