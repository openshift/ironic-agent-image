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

from ironic_lib import disk_utils
from ironic_lib import utils
from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent import hardware
from oslo_log import log
import tenacity


LOG = log.getLogger()

ROOT_MOUNT_PATH = '/mnt/coreos'
ASSISTED_STATE_MOUNT_PATH = '/mnt/assisted'

_ASSISTED_PID_PATH = os.path.join(ASSISTED_STATE_MOUNT_PATH, 'pid')
_ASSISTED_TRIGGER_PATH = os.path.join(ASSISTED_STATE_MOUNT_PATH, 'trigger')
_ASSISTED_RESULT_PATH = os.path.join(ASSISTED_STATE_MOUNT_PATH, 'result')
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
                'step': 'install_assisted',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': {},
            },
        ]

    def _check_assisted_status(self):
        if not os.path.exists(_ASSISTED_RESULT_PATH):
            return False

        with open(_ASSISTED_RESULT_PATH, 'rt') as fp:
            result = fp.read().strip()
            if result:
                raise errors.DeploymentError(
                    f"Failed to install using assisted agent: {result}")
            else:
                return True

    def install_assisted(self, node, ports):
        if not os.path.exists(_ASSISTED_PID_PATH):
            raise errors.DeploymentError(
                "Assisted agent is not running or is not configured "
                "for communication with the ironic agent")

        utils.unlink_without_raise(_ASSISTED_TRIGGER_PATH)
        utils.unlink_without_raise(_ASSISTED_RESULT_PATH)

        open(_ASSISTED_TRIGGER_PATH, "w").close()
        LOG.info('Triggered installation via the assisted agent')

        # Ironic already has a deploy timeout, we probably don't need another
        # one here.
        while not self._check_assisted_status():
            LOG.debug('Still waiting for the assisted agent to finish')
            time.sleep(_ASSISTED_POLLING_PERIOD)

        LOG.info('Succesfully installed using the assisted agent')

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

        copy_network = meta_data.get('coreos_copy_network', True)
        if copy_network:
            try:
                os.unlink(os.path.join(ROOT_MOUNT_PATH, 'etc',
                                       'NetworkManager/system-connections',
                                       'default_connection.nmconnection'))
            except FileNotFoundError:
                pass
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
            efi_utils.manage_uefi(root)

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
