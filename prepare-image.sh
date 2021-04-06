#!/usr/bin/bash

set -euxo pipefail

dnf install -y python3 python3-requests
curl https://raw.githubusercontent.com/openstack/tripleo-repos/master/tripleo_repos/main.py | python3 - -b master current-tripleo
dnf upgrade -y
grep -vE '^(#|$)' /tmp/${PKGS_LIST} | xargs -rtd'\n' dnf --setopt=install_weak_deps=False install -y
if [[ ! -z ${EXTRA_PKGS_LIST:-} ]]; then
    if [[ -s /tmp/${EXTRA_PKGS_LIST} ]]; then
        grep -vE '^(#|$)' /tmp/${EXTRA_PKGS_LIST} | xargs -rtd'\n' dnf --setopt=install_weak_deps=False install -y
    fi
fi

dnf clean all
rm -rf /var/cache/{yum,dnf}/*
if [[ ! -z ${PATCH_LIST:-} ]]; then
    if [[ -s "/tmp/${PATCH_LIST}" ]]; then
        /bin/patch-image.sh;
    fi
fi
rm -f /bin/patch-image.sh

