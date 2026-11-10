#!/usr/bin/bash

# Source this file and call configure_python to derive the Python commands and
# RPM prefix for the image's RHEL major version.
configure_python()
{
    case "${RHEL_MAJOR:-}" in
        9)
            PYTHON_VERSION=3.12
            ;;
        10)
            PYTHON_VERSION=3.14
            ;;
        *)
            echo "ERROR: unsupported or unset RHEL_MAJOR: ${RHEL_MAJOR:-<unset>}" >&2
            return 1
            ;;
    esac

    PYTHON_BIN="python${PYTHON_VERSION}"
    PYTHON_PACKAGE_PREFIX="python${PYTHON_VERSION}"
    export PYTHON_VERSION PYTHON_BIN PYTHON_PACKAGE_PREFIX
}
