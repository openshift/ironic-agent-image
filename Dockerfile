ARG BASE_IMAGE=quay.io/centos/centos:stream8
FROM $BASE_IMAGE

ENV PKGS_LIST=packages-list.txt
ARG EXTRA_PKGS_LIST
ARG PATCH_LIST

COPY ${PKGS_LIST} ${EXTRA_PKGS_LIST:-$PKGS_LIST} ${PATCH_LIST:-$PKGS_LIST} /tmp/
COPY prepare-image.sh patch-image.sh /bin/

RUN dnf install -y python3 python3-requests && \
    curl -Lfv https://raw.githubusercontent.com/openstack/tripleo-repos/master/plugins/module_utils/tripleo_repos/main.py | python3 - -b master current-tripleo && \
    sed -i 's/>=.*$//g' /tmp/${PKGS_LIST} && \
    prepare-image.sh && \
    mkdir -p /etc/ironic-python-agent && \
    rm -f /bin/prepare-image.sh

COPY hardware_manager /tmp/hardware_manager

RUN PBR_VERSION=1.0 pip3 install --no-index --verbose --prefix=/usr /tmp/hardware_manager

COPY ironic-python-agent.conf /etc/ironic-python-agent/00-defaults.conf

ENTRYPOINT ["ironic-python-agent", "--config-dir", "/etc/ironic-python-agent"]
