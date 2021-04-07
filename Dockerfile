FROM docker.io/centos:centos8

ENV PKGS_LIST=packages-list.txt
ARG EXTRA_PKGS_LIST
ARG PATCH_LIST

COPY ${PKGS_LIST} ${EXTRA_PKGS_LIST:-$PKGS_LIST} ${PATCH_LIST:-$PKGS_LIST} /tmp/
COPY prepare-image.sh patch-image.sh runironicagent /bin/

RUN prepare-image.sh && \
  mkdir -p /etc/ironic-python-agent && \
  rm -f /bin/prepare-image.sh

ENTRYPOINT ["/bin/runironicagent"]
