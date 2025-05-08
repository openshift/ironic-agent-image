# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import subprocess
import time
from urllib import parse as urlparse

import dbus

from ironic_python_agent import config
from ironic_python_agent import disk_utils
from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import netutils
from ironic_python_agent import utils
from oslo_log import log
import tenacity


LOG = log.getLogger(__name__)

ROOT_MOUNT_PATH = '/mnt/coreos'

_ASSISTED_AGENT_UNIT = "agent.service"
_ASSISTED_POLLING_PERIOD = 15
_ACTIVE_STATES = frozenset(['activating', 'active'])
_FAILED_STATES = frozenset(["failed"])


class CoreOSInstallHardwareManager(hardware.HardwareManager):

    HARDWARE_MANAGER_NAME = 'CoreOSInstallHardwareManager'
    HARDWARE_MANAGER_VERSION = '1'

    _firstboot_hostname = None
    _dbus = None

    # NOTE(dtantsur): this is a standard hardware manager call that is run on
    # IPA start-up to determine available plugins.
    def evaluate_hardware_support(self):
        try:
            self._fix_hostname()
        except Exception as exc:
            LOG.exception('Failed to update hostname')
            raise RuntimeError(f'Failed to update hostname: {exc}')
        return hardware.HardwareSupport.SERVICE_PROVIDER

    # NOTE(dtantsur): this is a standard hardware manager call that is run on
    # deployment to determine available deploy steps. The steps here refer to
    # methods on this class.
    def get_deploy_steps(self, node, ports):
        return [
            {
                'step': 'install_coreos',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': {},
            },
            {
                'step': 'start_assisted_install',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': {},
            },
        ]

    # NOTE(dtantsur): this is a standard hardware manager call that is run at
    # the end of an inspection, a cleaning, or a deployment to collect
    # additional system logs.
    def collect_system_logs(self, io_dict, file_list):
        try:
            journal = utils.get_command_output(
                ["journalctl", "--root", ROOT_MOUNT_PATH])
        except errors.CommandExecutionError:
            LOG.exception("Could not get journal for the host")
            raise errors.IncompatibleHardwareMethodError

        # Note: journal is an io.BytesIO object
        if journal.getbuffer().shape[0] < 50:
            LOG.error("Abnormally small journalctl output: %s",
                      journal.getvalue().decode("utf-8", errors="replace"))
            raise errors.IncompatibleHardwareMethodError

        io_dict["journal"] = journal
        # Avoid duplicating information: agent logs are in the journal
        file_list.remove(config.CONF.log_file)

    def _fix_hostname(self):
        try:
            current = subprocess.check_output(
                ['chroot', ROOT_MOUNT_PATH, 'hostnamectl', 'hostname'],
                encoding='utf-8',
                stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError) as exc:
            error = getattr(exc, 'stderr', None) or str(exc)
            LOG.warning("Failed to call hostnamectl, will use /etc/hostname "
                        "instead. Error: %s", error.strip())
            with open('/etc/hostname', 'rt') as hostfile:
                current = hostfile.read()

        current = current.strip()
        LOG.debug('The current hostname is %s', current)
        if current not in ('localhost', 'localhost.localdomain'):
            return

        new = os.getenv('IPA_DEFAULT_HOSTNAME')
        if not new:
            LOG.warning('This host has a local hostname %s, but the '
                        'BareMetalHost name is not provided to fix it',
                        current)
            return

        LOG.info('Fixing local hostname %s to BareMetalHost name %s',
                 current, new)
        subprocess.check_call(
            ['chroot', ROOT_MOUNT_PATH, 'hostnamectl', 'set-hostname',
             '--static', '--transient', new])
        # IPA is run in a container, /etc/hostname is not updated there
        with open('/etc/hostname', 'wt') as fp:
            fp.write(new)

    @property
    def dbus(self):
        if self._dbus is None:
            self._dbus = dbus.SystemBus()
        return self._dbus

    @property
    def systemd(self):
        systemd = self.dbus.get_object(
            'org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        return dbus.Interface(systemd, 'org.freedesktop.systemd1.Manager')

    @property
    def assisted_unit(self):
        unit = self.systemd.LoadUnit(_ASSISTED_AGENT_UNIT)
        service = self.dbus.get_object(
            'org.freedesktop.systemd1', object_path=unit)
        return dbus.Interface(
            service, dbus_interface='org.freedesktop.DBus.Properties')

    def _is_assisted_running(self):
        unit = self.assisted_unit
        state = unit.Get('org.freedesktop.systemd1.Unit', 'ActiveState')
        result = unit.Get('org.freedesktop.systemd1.Service', 'Result')
        LOG.debug('Assisted Agent is in state %s (result %s)', state, result)
        if state in _FAILED_STATES:
            raise errors.DeploymentError(
                f'Assisted Installer Agent has failed with result "{result}". '
                'Check the ramdisk logs for more details.')
        return state in _ACTIVE_STATES

    def start_assisted_install(self, node, ports):
        if self._is_assisted_running():
            LOG.error(
                "Assisted Installer Agent should not be active at this stage")

        self.systemd.StartUnit(_ASSISTED_AGENT_UNIT, "fail")
        LOG.info('Triggered installation via the assisted agent')

        # A short sleep to avoid catching systemd in-between actions.
        time.sleep(1)

        # Ironic already has a deploy timeout, we probably don't need another
        # one here.
        while self._is_assisted_running():
            LOG.debug('Still waiting for the assisted agent to finish')
            time.sleep(_ASSISTED_POLLING_PERIOD)

        LOG.info('Succesfully installed using the assisted agent')

    def _add_firstboot_hostname_fix(self, ignition):
        # Regardless of whether the hostname had been set via DHCP/DNS or in
        # _fix_hostname, we need to make sure it matches the name when the node
        # boots, so always set firstboot in ignition.
        hostname = netutils.get_hostname()
        if not hostname:
            return ignition

        if isinstance(ignition, str):
            ignition = json.loads(ignition)
        elif not ignition:
            ignition = {"ignition": {"version": "3.0.0"}}

        encoded = urlparse.quote(hostname)

        files = ignition.setdefault('storage', {}).setdefault('files', [])
        files.append({
            'path': '/etc/hostname',
            'mode': 0o644,
            'overwrite': True,
            'contents': {'source': f'data:,{encoded}'},
        })

        return ignition

    def _try_delete_raid(self, node, ports):
        if node['automated_clean'] is False:
            LOG.debug(
                "Cleaning is disabled, will not try to delete software RAID")
            return

        LOG.info("Deleting any software RAID devices")
        try:
            hardware.dispatch_to_managers('delete_configuration', node, ports)
        except Exception:
            LOG.warning("Unable to delete software RAID configuration, "
                        "deployment may fail", exc_info=True)
        else:
            disk_utils.udev_settle()

    def install_coreos(self, node, ports):
        self._try_delete_raid(node, ports)
        root = hardware.dispatch_to_managers('get_os_install_device',
                                             permit_refresh=True)
        configdrive = node['instance_info'].get('configdrive') or {}
        if isinstance(configdrive, str):
            raise errors.DeploymentError(
                "Cannot use a pre-rendered configdrive, please pass it "
                "as JSON data")

        meta_data = configdrive.get('meta_data') or {}
        ignition = configdrive.get('user_data')

        args = ['--preserve-on-error']  # We have cleaning to do this

        ignition = self._add_firstboot_hostname_fix(ignition)
        if ignition:
            LOG.debug('Will use ignition %s', ignition)
            dest = os.path.join(ROOT_MOUNT_PATH, 'tmp', 'ironic.ign')
            with open(dest, 'wt') as fp:
                if isinstance(ignition, str):
                    fp.write(ignition)
                else:
                    json.dump(ignition, fp)
            args += ['--ignition-file', '/tmp/ironic.ign']

        append_karg = meta_data.get('coreos_append_karg')
        if append_karg:
            args += ['--append-karg', ','.join(append_karg)]

        image_url = node['instance_info'].get('image_source')
        if image_url:
            args += ['--image-url', image_url, '--insecure']
        else:
            args += ['--offline']

        ip_args = os.getenv('IPA_COREOS_IP_OPTIONS')
        if ip_args:
            args += ['--append-karg', ip_args]

        copy_network = meta_data.get('coreos_copy_network',
                os.getenv('IPA_COREOS_COPY_NETWORK', '').lower() == 'true')
        if copy_network:
            args += ['--copy-network']

        command = ['chroot', ROOT_MOUNT_PATH,
                   'coreos-installer', 'install', *args, root]
        LOG.info('Executing CoreOS installer: %s', command)
        self._run_install(command)

        # Just in case: re-read disk information
        disk_utils.trigger_device_rescan(root)

        boot = hardware.dispatch_to_managers('get_boot_info')
        if boot.current_boot_mode == 'uefi':
            LOG.info('Configuring UEFI boot from device %s', root)
            for count in range(6):
                try:
                    efi_utils.manage_uefi(root)
                    break
                except errors.CommandExecutionError as exc:
                    if count < 5:
                        time.sleep(5)
                        # https://bugzilla.redhat.com/show_bug.cgi?id=2057668
                        LOG.warning("UEFI boot configuration failed(retrying): %s", exc)
                    else:
                        raise exc
        LOG.info('Successfully installed via CoreOS installer on device %s',
                 root)

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(errors.DeploymentError),
        stop=tenacity.stop_after_attempt(3),
        reraise=True)
    def _run_install(self, command):
        last_line = None
        try:
            # NOTE(dtantsur): we need to capture the output to be able to log
            # it properly. However, we also want to see it in the logs as it is
            # happening (to be able to debug hangs or performance problems).
            proc = subprocess.Popen(command,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    encoding="utf-8",
                                    errors='backslashreplace')
            for line in proc.stdout:
                line = line.strip()
                if line:
                    last_line = line
                LOG.debug("coreos-installer: %s", line)
        except FileNotFoundError:
            raise errors.DeploymentError(
                "Cannot run coreos-installer, is it installed in "
                f"{ROOT_MOUNT_PATH}?")

        code = proc.wait()
        if code:
            LOG.error("coreos-installer failed with code %d", code)
            error = f"coreos-installer failed with code {code}: {last_line}"
            raise errors.DeploymentError(error)
