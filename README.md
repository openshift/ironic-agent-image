# Ironic Agent Container

This is an **experimental** container and associated tooling for using
[ironic-python-agent](https://docs.openstack.org/ironic-python-agent/latest/)
(IPA) on top of [CoreOS](https://docs.fedoraproject.org/en-US/fedora-coreos/).
This is different from standard IPA images that are built with
[diskimage-builder](https://docs.openstack.org/diskimage-builder/latest/) from
a conventional Linux distribution, such as CentOS.

This image is [published](https://quay.io/repository/dtantsur/ironic-agent)
on every commit, you can pull it with:
```
podman pull quay.io/dtantsur/ironic-agent
```

## Installation

So far it has **not** been tested with other [Metal3](http://metal3.io/)
components, to experiment with it you'll need a pure Ironic installation, such
as [Bifrost](https://docs.openstack.org/bifrost/latest/). Make sure to allocate
enough RAM to the testing nodes, I have used 6 GiB (e.g. add `--memory 6144` to
`./bifrost-cli testenv` invocation).

Make sure you have [patch
785372](https://review.opendev.org/c/openstack/ironic/+/785372) in your Ironic.

You will need to enroll nodes using the
[redfish-virtual-media](https://docs.openstack.org/ironic/latest/admin/drivers/redfish.html#virtual-media-boot)
boot interface. PXE and iPXE will be supported eventually, but currently are
not tested.

```
baremetal node update <node> \
    --driver redfish \
    --boot-interface redfish-virtual-media \
    --reset-interfaces
```

You will need `coreos-installer`, it can be installed with `cargo`:

```
sudo dnf install -y cargo
cargo install coreos-installer
```

Finally, you'll need a container registry. You can set one up locally:

```
sudo podman run --privileged -d --name registry -p 5000:5000 \
    -v /var/lib/registry:/var/lib/registry --restart=always registry:2
```

### Preparing deploy image

So far this project has been tested with Fedora CoreOS. Download the suitable
bare metal image, for example:

```
sudo curl -Lo /httpboot/fcos-ipa.iso \
    https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/33.20210314.3.0/x86_64/fedora-coreos-33.20210314.3.0-live.x86_64.iso
```

Next you need to inject the Ignition configuration into it. This repository
contains a Python script to generate such configuration from the IP addresses.
For Bifrost it may looks like:

```
./ignition/build.py \
    --host 192.168.122.1 \
    --registry 192.168.122.1:5000 \
    --insecure-registry > ~/ironic-agent.ign
```

Then use `coreos-installer` to inject it:

```
sudo ~/.cargo/bin/coreos-installer iso ignition embed \
    -i ~/ironic-agent.ign -f /httpboot/fcos-ipa.iso
```

Finally, update your node(s) to use the resulting image:

```
baremetal node set <node> \
    --driver-info redfish_deploy_iso=file:///httpboot/fcos-ipa.iso
```

### Preparing container

This is a straightforward step. Build the container from this repository
(or pull it using the instructions above) and push it to your registry:

```
podman build -t ironic-agent .
podman push ironic-agent localhost:5000/ironic-agent --tls-verify=false
```

Now you're ready to inspect, clean and deploy nodes.

### Using CoreOS installer (experimental)

If you want to use `coreos-installer` instead of the standard Ironic deploy
procedure, you need to switch to the `custom-agent` deploy interface from
Ironic [patch 786033](https://review.opendev.org/c/openstack/ironic/+/786033)
(and its parent patches):

```
baremetal node set <node> --deploy-interface custom-agent
```

Until we fix validation, provide a fake image source (won't be used):

```
baremetal node set <node> \
    --instance-info image_source=file:///httpboot/fcos-ipa.iso
```

Then prepare a custom deploy steps list in a YAML file, e.g.

```yaml
---
- interface: deploy
  step: install_coreos
  priority: 80
  args:
    ignition:
      ignition:
        version: 3.0.0
      passwd:
        users:
        - name: core
          sshAuthorizedKeys:
          - ssh-rsa AAAA ....
```

and use it when deploying:

```
baremetal node deploy <node> --deploy-steps /path/to/deploy/steps.yaml
```
