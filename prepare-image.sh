#!/usr/bin/bash

set -euxo pipefail

. /bin/python-config.sh
configure_python

echo "install_weak_deps=False" >> /etc/dnf/dnf.conf
# Tell RPM to skip installing documentation
echo "tsflags=nodocs" >> /etc/dnf/dnf.conf

dnf upgrade -y

package_list="/tmp/${PKGS_LIST}"
rendered_package_list="${package_list}.rendered"
render_package_list "${package_list}" "${rendered_package_list}"
grep -vE '^(#|$)' "${rendered_package_list}" | xargs -rtd'\n' dnf install -y
arch_package_list="${package_list}-$(arch)"
if [[ -s "${arch_package_list}" ]]; then
    rendered_arch_package_list="${arch_package_list}.rendered"
    render_package_list "${arch_package_list}" "${rendered_arch_package_list}"
    grep -vE '^(#|$)' "${rendered_arch_package_list}" | xargs -rtd'\n' dnf install -y
fi
if [[ ! -z ${EXTRA_PKGS_LIST:-} ]]; then
    if [[ -s /tmp/${EXTRA_PKGS_LIST} ]]; then
        rendered_extra_pkgs_list="/tmp/${EXTRA_PKGS_LIST}.rendered"
        render_package_list "/tmp/${EXTRA_PKGS_LIST}" "${rendered_extra_pkgs_list}"
        grep -vE '^(#|$)' "${rendered_extra_pkgs_list}" | xargs -rtd'\n' dnf install -y
    fi
fi

### OCP: Install from pre-built wheels (built in wheel-builder stage)
if [[ -f /tmp/packages-list.ocp ]]; then

    dnf install -y "${PYTHON_PACKAGE_PREFIX}-pip"

    # NOTE(janders): adding --no-compile option to avoid issues in FIPS
    # enabled environments. See https://issues.redhat.com/browse/RHEL-29028
    # for more information
    "${PYTHON_BIN}" -m pip install \
        --no-compile \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        --prefix /usr \
        /wheels/*.whl

    # NOTE(janders) since we set --no-compile at install time, we need to
    # compile post-install (see RHEL-29028)
    "${PYTHON_BIN}" -m compileall --invalidation-mode=timestamp -q -x '/usr/share/doc' /usr

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

# Remove build-only and unnecessary packages; rpm -e is used instead of
# dnf remove to avoid autoremove of dependencies.
for pkg in "${PYTHON_PACKAGE_PREFIX}-pip" subscription-manager dnf-plugin-subscription-manager git-core; do
    rpm -e --nodeps "${pkg}" || true
done

dnf clean all
rm -rf /var/cache/{yum,dnf}/*

# This goes last since it violates package integrity.
rm -rf /var/log/anaconda /var/lib/dnf/history.* /usr/share/licenses/*
