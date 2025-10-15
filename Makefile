.PHONY: build-ocp

build-ocp:
	podman build -f Dockerfile.ocp

.PHONY: build-okd

build-okd:
	podman build -f Dockerfile.okd --build-arg EXTRA_PKGS_LIST="" -t ironic-agent-image.okd

.PHONY: check-reqs

check-reqs:
	./tools/check-requirements.sh