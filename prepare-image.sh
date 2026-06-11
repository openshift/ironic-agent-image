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

### OCP: Install from pre-built wheels (built in wheel-builder stage)
if [[ -f /tmp/packages-list.ocp ]]; then

    dnf install -y python3.12-pip

    # NOTE(janders): adding --no-compile option to avoid issues in FIPS
    # enabled environments. See https://issues.redhat.com/browse/RHEL-29028
    # for more information
    python3.12 -m pip install \
        --no-compile \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        --prefix /usr \
        /wheels/*.whl

    # NOTE(janders) since we set --no-compile at install time, we need to
    # compile post-install (see RHEL-29028)
    python3.12 -m compileall --invalidation-mode=timestamp -q -x '/usr/share/doc' /usr

fi
###

### OKD Python 3.12 setup ###
if [[ -f /tmp/packages-list.okd ]]; then
    setup.okd
fi
###

if [[ ! -z ${PATCH_LIST:-} ]]; then
    if [[ -s "/tmp/${PATCH_LIST}" ]]; then
        /bin/patch-image.sh;
    fi
fi
rm -f /bin/patch-image.sh

# pip is only needed at build time, remove it to reduce image size
if [[ -f /tmp/packages-list.ocp ]]; then
    dnf remove -y python3.12-pip
fi

# No subscriptions are required (or possible) in this container.
rpm -q subscription-manager && \
    dnf remove -y subscription-manager dnf-plugin-subscription-manager || true

# Pbr pulls in Git (30+ MiB), but actually only uses it in development context.
rpm -q git-core && rpm -e --nodeps git-core || true

dnf clean all
rm -rf /var/cache/{yum,dnf}/*

# This goes last since it violates package integrity.
rm -rf /var/log/anaconda /var/lib/dnf/history.* /usr/share/licenses/*
