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

from ironic_python_agent import hardware
from oslo_log import log

LOG = log.getLogger()


ARGSINFO = {
    "ignition": {
        "description": (
            "Ignition JSON configuration to pass to the instance."
        ),
        "required": False,
    },
    "append_karg": {
        "description": (
            "List of kernel arguments to append."
        ),
        "required": False,
    },
    "delete_karg": {
        "description": (
            "List of kernel arguments to remove."
        ),
        "required": False,
    },
    "image_url": {
        "description": (
            "Use this URL instead of the built-in one."
        ),
        "required": False,
    },
    "copy_network": {
        "description": (
            "Whether to copy network information from the ramdisk."
        ),
        "required": False,
    },
}

ROOT_MOUNT_PATH = '/mnt/coreos'


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
                'argsinfo': ARGSINFO,
            }
        ]

    def install_coreos(self, node, ports, ignition=None, append_karg=None,
                       delete_karg=None, image_url=None, copy_network=False):
        root = hardware.dispatch_to_managers('get_os_install_device',
                                             permit_refresh=True)
        args = []

        if ignition is not None:
            dest = os.path.join(ROOT_MOUNT_PATH, 'tmp', 'ironic.ign')
            with open(dest, 'wt') as fp:
                json.dump(ignition, fp)
            args += ['--ignition-file', '/tmp/ironic.ign']

        if append_karg:
            args += ['--append-karg', ','.join(append_karg)]

        if delete_karg:
            args += ['--delete-karg', ','.join(delete_karg)]

        if image_url is not None:
            args += ['--image-url', image_url]
        else:
            args += ['--offline']

        if copy_network:
            args += ['--copy-network']

        command = ['chroot', ROOT_MOUNT_PATH,
                   'coreos-installer', 'install', *args, root]
        LOG.info('Executing CoreOS installer: %s', command)
        # NOTE(dtantsur): not using utils.execute because it swallows output
        subprocess.run(command, check=True)
        LOG.info('Successfully installed via CoreOS installer on device %s',
                 root)
