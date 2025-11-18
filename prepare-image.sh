#!/usr/bin/bash

set -euxo pipefail

echo "install_weak_deps=False" >> /etc/dnf/dnf.conf
# Tell RPM to skip installing documentation
echo "tsflags=nodocs" >> /etc/dnf/dnf.conf

dnf upgrade -y

grep -vE '^(#|$)' /tmp/${PKGS_LIST} | xargs -rtd'\n' dnf install -y
if [[ -s /tmp/${PKGS_LIST}-$(arch) ]]; then
    grep -vE '^(#|$)' /tmp/${PKGS_LIST}-$(arch) | xargs -rtd'\n' dnf install -y
fi
if [[ ! -z ${EXTRA_PKGS_LIST:-} ]]; then
    if [[ -s /tmp/${EXTRA_PKGS_LIST} ]]; then
        grep -vE '^(#|$)' /tmp/${EXTRA_PKGS_LIST} | xargs -rtd'\n' dnf install -y
    fi
fi

### cachito magic works for OCP only
if  [[ -f /tmp/packages-list.ocp ]]; then

    REQS="${REMOTE_SOURCES_DIR}/requirements.cachito"

    ls -la "${REMOTE_SOURCES_DIR}/" # DEBUG

    # load cachito variables only if they're available
    if [[ -d "${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps" ]]; then
        source "${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps/cachito.env"
        REQS="${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps/app/requirements.cachito"
    fi

    ### source install ###
    BUILD_DEPS="git python3.12-devel gcc gcc-c++ python3.12-wheel"

    # NOTE(elfosardo): wheel is needed because of pip "no-build-isolation" option
    # setting installation of setuptoools here as we may want to remove it
    # in the future once the container build is done
    dnf install -y python3.12-pip 'python3.12-setuptools >= 64.0.0' $BUILD_DEPS

    # NOTE(elfosardo): --no-index is used to install the packages emulating
    # an isolated environment in CI. Do not use the option for downstream
    # builds.
    # NOTE(janders): adding --no-compile option to avoid issues in FIPS
    # enabled environments. See https://issues.redhat.com/browse/RHEL-29028
    # for more information
    # NOTE(elfosardo): --no-build-isolation is needed to allow build engine
    # to use build tools already installed in the system, for our case
    # setuptools and pbr, instead of installing them in the isolated
    # pip environment. We may change this in the future and just use
    # full isolated environment and source build dependencies.
    PIP_OPTIONS="--no-compile --no-cache-dir --no-build-isolation"
    if [[ ! -d "${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps" ]]; then
        PIP_OPTIONS="$PIP_OPTIONS --no-index"
    fi

    # NOTE(elfosardo): download all the libraries and dependencies first, removing
    # --no-index but using --no-deps to avoid chain-downloading packages.
    # This forces to download only the packages specified in the requirements file,
    # but we leave the --no-index in the installation phase to again avoid
    # downloading unexpected packages and install only the downloaded ones.
    # This is done to allow testing any source code package in CI emulating
    # the cachito downstream build pipeline.
    # See https://issues.redhat.com/browse/METAL-1049 for more details.
    PIP_SOURCES_DIR="all_sources"
    mkdir $PIP_SOURCES_DIR
    python3.12 -m pip download --no-binary=:all: --no-build-isolation --no-deps -r "${REQS}" -d $PIP_SOURCES_DIR
    python3.12 -m pip install $PIP_OPTIONS --prefix /usr -r "${REQS}" -f $PIP_SOURCES_DIR

    # NOTE(janders) since we set --no-compile at install time, we need to
    # compile post-install (see RHEL-29028)
    python3.12 -m compileall --invalidation-mode=timestamp /usr

    PBR_VERSION=1.0 python3.12 -m pip install --no-build-isolation --no-index --verbose --prefix=/usr /tmp/hardware_manager

    dnf remove -y $BUILD_DEPS
    rm -fr $PIP_SOURCES_DIR

    if [[ -d "${REMOTE_SOURCES_DIR}/cachito-gomod-with-deps" ]]; then
        rm -rf $REMOTE_SOURCES_DIR
    fi

fi
###

### OKD Python 3.12 setup ###
if [[ -f /tmp/packages-list.okd ]]; then
    # Install OpenStack packages from requirements file
    if [[ -f /tmp/python-requirements.okd ]]; then
        echo "Installing OpenStack packages for Python 3.12 via pip"
        
        # Install build dependencies needed for compiling C extensions (e.g., dbus-python)
        # dbus-devel is already in packages-list.okd, python3.12-devel is in Dockerfile
        BUILD_DEPS="gcc gcc-c++ glib2-devel pkgconfig python3.12-wheel"
        dnf install -y python3.12-pip 'python3.12-setuptools >= 64.0.0' $BUILD_DEPS
        
        python3.12 -m pip install --no-cache-dir --prefix /usr -c https://releases.openstack.org/constraints/upper/master -r /tmp/python-requirements.okd
        
        # Compile Python files for better performance
        python3.12 -m compileall --invalidation-mode=timestamp -q /usr
        
        PBR_VERSION=1.0 python3.12 -m pip install --no-build-isolation --no-index --verbose --prefix=/usr /tmp/hardware_manager
        
        # Remove build dependencies to keep image small
        dnf remove -y $BUILD_DEPS
    fi
fi
###

if [[ ! -z ${PATCH_LIST:-} ]]; then
    if [[ -s "/tmp/${PATCH_LIST}" ]]; then
        /bin/patch-image.sh;
    fi
fi
rm -f /bin/patch-image.sh

# No subscriptions are required (or possible) in this container.
rpm -q subscription-manager && \
    dnf remove -y subscription-manager dnf-plugin-subscription-manager || true

# Pbr pulls in Git (30+ MiB), but actually only uses it in development context.
rpm -q git-core && rpm -e --nodeps git-core || true

dnf clean all
rm -rf /var/cache/{yum,dnf}/*

# This goes last since it violates package integrity.
rm -rf /var/log/anaconda /var/lib/dnf/history.* /usr/share/licenses/*
