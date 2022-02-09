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

import base64
import json
import os
import socket
import subprocess
import time

import dbus

from ironic_lib import disk_utils
from ironic_lib import utils
from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent import hardware
from oslo_log import log
import tenacity


LOG = log.getLogger()

ROOT_MOUNT_PATH = '/mnt/coreos'
NETWORK_MANAGER_DISPATCHER_PATH = '/etc/NetworkManager/dispatcher.d'

_ASSISTED_AGENT_UNIT = "agent.service"
_ASSISTED_POLLING_PERIOD = 15


class CoreOSInstallHardwareManager(hardware.HardwareManager):

    HARDWARE_MANAGER_NAME = 'CoreOSInstallHardwareManager'
    HARDWARE_MANAGER_VERSION = '1'

    def evaluate_hardware_support(self):
        return hardware.HardwareSupport.SERVICE_PROVIDER

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


    @property
    def dbus(self):
        return dbus.SystemBus()

    @property
    def systemd(self):
        systemd = self.dbus.get_object('org.freedesktop.systemd1', '/org/freedesktop/systemd1')
        return dbus.Interface(systemd, 'org.freedesktop.systemd1.Manager')

    @property
    def assisted_unit(self):
        try:
            unit = self.systemd.GetUnit(_ASSISTED_AGENT_UNIT)
            service = self.dbus.get_object('org.freedesktop.systemd1', object_path=unit)
            return dbus.Interface(service, dbus_interface='org.freedesktop.DBus.Properties')
        except dbus.exceptions.DBusException as e:
            if "org.freedesktop.systemd1.NoSuchUnit" in str(e):
                return None
            raise

    def _is_assisted_running(self):
        unit = self.assisted_unit

        if unit is None:
            return False

        return str(unit.Get('org.freedesktop.systemd1.Unit', 'ActiveState')) in ['activating', 'active']

    def start_assisted_install(self, node, ports):
        if self._is_assisted_running():
            LOG.error("Assisted Installer Agent should not be active at this stage")

        self.systemd.StartUnit(_ASSISTED_AGENT_UNIT, "fail")
        LOG.info('Triggered installation via the assisted agent')

        # Ironic already has a deploy timeout, we probably don't need another
        # one here.
        while self._is_assisted_running():
            LOG.debug('Still waiting for the assisted agent to finish')
            time.sleep(_ASSISTED_POLLING_PERIOD)

        LOG.info('Succesfully installed using the assisted agent')
    
    def _append_ignition_with_host_config(self, ignition):
        if isinstance(ignition, str):
            ignition_dict = json.loads(ignition)
        else:
            ignition_dict = ignition

        for filename in os.listdir(NETWORK_MANAGER_DISPATCHER_PATH):
            dispatcher_path = os.path.join(NETWORK_MANAGER_DISPATCHER_PATH, filename)

            with open(dispatcher_path, "r") as dispatcher_file:
                dispatcher_contents = dispatcher_file.read()
                LOG.debug('Dispatcher file %s: %s', dispatcher_path, dispatcher_contents)

                dispatcher_file_dict = {
                    "path": "{}".format(dispatcher_path),
                    "mode": 744,
                    "overwrite": False,
                    "contents": { "source": "data:,{}".format(base64.b64encode(dispatcher_contents.encode()))},
                }
                ignition_dict.setdefault('storage', {}).setdefault('files', []).append(dispatcher_file_dict)
	
                dispatcher_path = os.path.join("/sysroot", dispatcher_path)
                dispatcher_file_dict = {
                    "path": "{}".format(dispatcher_path),
                    "mode": 744,
                    "overwrite": False,
                    "contents": { "source": "data:,{}".format(base64.b64encode(dispatcher_contents.encode()))},
                }
                ignition_dict.setdefault('storage', {}).setdefault('files', []).append(dispatcher_file_dict)

        return ignition_dict

    def install_coreos(self, node, ports):
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

        if ignition:
            LOG.debug('Will use ignition %s', ignition)
            ignition = self._append_ignition_with_host_config(ignition)
            LOG.debug('Updated ignition %s', ignition)
            dest = os.path.join(ROOT_MOUNT_PATH, 'tmp', 'ironic.ign')
            with open(dest, 'wt') as fp:
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
        try:
            self._run_install(command)
        except subprocess.CalledProcessError as exc:
            raise errors.DeploymentError(
                f"coreos-install returned error code {exc.returncode}")

        # Just in case: re-read disk information
        disk_utils.trigger_device_rescan(root)

        boot = hardware.dispatch_to_managers('get_boot_info')
        if boot.current_boot_mode == 'uefi':
            LOG.info('Configuring UEFI boot from device %s', root)
            for count in range(3):
                try:
                    efi_utils.manage_uefi(root)
                    break
                except errors.CommandExecutionError as exc:
                    if count < 2:
                        time.sleep(3)
                        # https://bugzilla.redhat.com/show_bug.cgi?id=2057668
                        LOG.warning("UEFI boot configuration failed(retrying): %s", exc)
                    else:
                        raise exc
        LOG.info('Successfully installed via CoreOS installer on device %s',
                 root)

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(subprocess.CalledProcessError),
        stop=tenacity.stop_after_attempt(3),
        reraise=True)
    def _run_install(self, command):
        try:
            # NOTE(dtantsur): avoid utils.execute because it swallows output
            subprocess.run(command, check=True)
        except FileNotFoundError:
            raise errors.DeploymentError(
                "Cannot run coreos-installer, is it installed in "
                f"{ROOT_MOUNT_PATH}?")
        except subprocess.CalledProcessError as exc:
            LOG.warning("coreos-installer failed: %s", exc)
            raise
