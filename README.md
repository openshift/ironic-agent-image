# Ironic Agent Container

This is an **experimental** container and associated tooling for using
[ironic-python-agent](https://docs.openstack.org/ironic-python-agent/latest/)
(IPA) on top of [CoreOS](https://docs.fedoraproject.org/en-US/fedora-coreos/).
This is different from standard IPA images that are built with
[diskimage-builder](https://docs.openstack.org/diskimage-builder/latest/) from
a conventional Linux distribution, such as CentOS.

## Installation

So far it has **not** been tested with other [Metal3](http://metal3.io/)
components, to experiment with it you'll need a pure Ironic installation, such
as [Bifrost](https://docs.openstack.org/bifrost/latest/). Make sure to allocate
enough RAM to the testing nodes, I have used 6 GiB (e.g. add `--memory 6144` to
`./bifrost-cli testenv` invocation).

Make sure you have [patch
790472](https://review.opendev.org/c/openstack/ironic/+/790472) in your Ironic.

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

### Preparing deploy image - Redfish virtual media

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

Configure the nodes to use the
[redfish-virtual-media](https://docs.openstack.org/ironic/latest/admin/drivers/redfish.html#virtual-media-boot)
boot interface:

```
baremetal node update <node> \
    --driver redfish \
    --boot-interface redfish-virtual-media \
    --reset-interfaces
```

Finally, update your node(s) to use the resulting image:

```
baremetal node set <node> \
    --driver-info redfish_deploy_iso=file:///httpboot/fcos-ipa.iso
```

### Preparing deploy image - PXE

For PXE/iPXE boot you will need to download 3 artifacts: the kernel, the
initramfs and the root file system, for example:

```
sudo curl -Lo /httpboot/fcos.kernel \
    https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/34.20210427.3.0/x86_64/fedora-coreos-34.20210427.3.0-live-kernel-x86_64
sudo curl -Lo /httpboot/fcos.initramfs \
    https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/34.20210427.3.0/x86_64/fedora-coreos-34.20210427.3.0-live-initramfs.x86_64.img
sudo curl -Lo /httpboot/fcos.rootfs.img \
    https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/34.20210427.3.0/x86_64/fedora-coreos-34.20210427.3.0-live-rootfs.x86_64.img
```

Next, copy the Ignition configuration, generated on the previous step, to the
HTTP root directory, for example:

```
sudo cp ~/ironic-agent.ign /httpboot/ironic-agent.ign
```

Then you'll need to update the kernel parameters to point at the generated
file. Open `/etc/ironic/ironic.conf` and edit the following option:

```ini
[pxe]
pxe_append_params = nofb nomodeset systemd.journald.forward_to_console=yes console=ttyS0 ipa-insecure=1 ignition.config.url=http://192.168.122.1:8080/ironic-agent.ign coreos.live.rootfs_url=http://192.168.122.1:8080/fcos.rootfs.img ignition.firstboot ignition.platform.id=metal
```

You'll need to add the following parameters to the existing value (use your IP
where needed):

- `ignition.config.url=http://192.168.122.1:8080/ironic-agent.ign`
- `coreos.live.rootfs_url=http://192.168.122.1:8080/fcos.rootfs.img`
- `ignition.firstboot`
- `ignition.platform.id=metal`

Restart the ironic conductor if it's already started.

Finally, configure the nodes:

```
baremetal node set <node> \
    --driver-info deploy_kernel=file:///httpboot/fcos.kernel \
    --driver-info deploy_ramdisk=file:///httpboot/fcos.initramfs \
    --boot-interface ipxe
```

### Preparing container

This is a straightforward step. Build the container from this repository
(or pull it using the instructions above) and push it to your registry:

```
podman build -t ironic-agent -f Dockerfile.ocp
podman push ironic-agent localhost:5000/ironic-agent --tls-verify=false
```

Now you're ready to inspect, clean and deploy nodes.

### Using CoreOS installer

If you want to use `coreos-installer` instead of the standard Ironic deploy
procedure, you need to switch to the `custom-agent` deploy interface added
(very) recently to Ironic:

```
baremetal node set <node> --deploy-interface custom-agent
```

Then you can deploy with:

```
baremetal node deploy <node> \
    --deploy-steps '[{"interface": "deploy", "step": "install_coreos", "priority": 80, "args": {}}]' \
    --config-drive '{"user_data": {.. your ignition ..}}'
```
