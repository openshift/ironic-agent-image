# Ironic Agent Container

This is an container image for using [ironic-python-agent][ipa] (IPA) on top of
CoreOS. This is different from standard IPA images that are built with
[diskimage-builder][dib] from a conventional Linux distribution, such as
RHEL or Debian.

This repository also contains a CoreOS-specific [IPA hardware manager][ipamgrs]
called [ironic_coreos_install][hwmgr]. It is responsible for the customized
installation process.

[ipa]: https://docs.openstack.org/ironic-python-agent/latest/
[dib]: https://docs.openstack.org/diskimage-builder/latest/
[ipamgrs]: https://docs.openstack.org/ironic-python-agent/latest/contributor/hardware_managers.html
[hwmgr]: https://github.com/openshift/ironic-agent-image/blob/main/hardware_manager/ironic_coreos_install.py

## How it works

Unlike a conventional IPA image, the IPA source is not shipped with a CoreOS
image. Instead, another component called [image-customization-controller][icc]
is used to inject its configuration into the ramdisk's Ignition. IPA is started
as a systemd service that downloads its container image on start-up.

[Inspection][inspection] and [automated cleaning][cleaning] works as usual in
Ironic, but the deployment process is very different. Instead of downloading a
QCOW2 image and writing it to the disk, the [custom hardware manager][hwmgr]
runs the `coreos-installer` command shipped with the CoreOS image to install
the contents of the ramdisk onto the disk. This way, no separate CoreOS image
is required.

To achieve this, the BareMetal Operator [custom deploy][custom deploy] feature
is used. It allows replacing some of the normal Ironic [deploy steps][standard
steps] with the [install_coreos step][install-coreos] shipped here.

[icc]: https://github.com/openshift/image-customization-controller
[inspection]: https://docs.openstack.org/ironic/latest/admin/inspection/index.html
[cleaning]: https://docs.openstack.org/ironic/latest/admin/cleaning.html#automated-cleaning
[custom deploy]: https://github.com/metal3-io/metal3-docs/blob/main/design/baremetal-operator/deploy-steps.md
[standard steps]: https://docs.openstack.org/ironic/latest/admin/node-deployment.html#agent-steps
[install-coreos]: https://github.com/openshift/ironic-agent-image/blob/f4b86c20989a79e611a27975ac02d0f824b8e5c7/hardware_manager/ironic_coreos_install.py#L183

## Assisted agent integration

The [custom hardware manager][hwmgr] also ships another deploy step
`start_assisted_install` that allows integration with the [assisted
service][assisted service] in a so called *converged flow* (in a contrast with
the older *non-converged flow* that did not use IPA at all).

The assisted service invokes the converged flow by creating a CoreOS ramdisk
with an Ignition that starts IPA and also ships the [assisted agent][assisted
agent] without starting it.

The converged flow also starts with [inspection][inspection] unless disabled by
a user. To make a host available for the assisted installation, the assisted
service invokes the `start_assisted_install` step. This causes the host to move
to the `provisioning` state, while IPA uses the systemd D-BUS API to start the
assisted agent. IPA then waits for the assisted agent to exit and reports the
exit status back to Ironic and eventually to BareMetal Operator.

The converged flow also allows cleaning and preparation steps such as RAID
configuration or firmware settings to be run before provisioning.

[assisted service]: https://github.com/openshift/assisted-service
[assisted agent]: https://github.com/openshift/assisted-installer-agent
