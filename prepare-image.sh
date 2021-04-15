#!/usr/bin/bash

set -euxo pipefail

echo "install_weak_deps=False" >> /etc/dnf/dnf.conf
# Tell RPM to skip installing documentation
echo "tsflags=nodocs" >> /etc/dnf/dnf.conf

dnf install -y python3 python3-requests
curl https://raw.githubusercontent.com/openstack/tripleo-repos/master/tripleo_repos/main.py | python3 - -b master current-tripleo
dnf upgrade -y
grep -vE '^(#|$)' /tmp/${PKGS_LIST} | xargs -rtd'\n' dnf install -y
if [[ ! -z ${EXTRA_PKGS_LIST:-} ]]; then
    if [[ -s /tmp/${EXTRA_PKGS_LIST} ]]; then
        grep -vE '^(#|$)' /tmp/${EXTRA_PKGS_LIST} | xargs -rtd'\n' dnf install -y
    fi
fi

# Pbr pulls in Git (30+ MiB), but actually only uses it in development context.
rpm -q git-core && rpm -e --nodeps git-core || true

dnf clean all
rm -rf /var/cache/{yum,dnf}/*

# This goes last since it violates package integrity.
rm -rf /var/log/anaconda /var/lib/dnf/history.* /usr/share/licenses/*

if [[ ! -z ${PATCH_LIST:-} ]]; then
    if [[ -s "/tmp/${PATCH_LIST}" ]]; then
        /bin/patch-image.sh;
    fi
fi
rm -f /bin/patch-image.sh

