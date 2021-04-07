#!/usr/bin/env python3

import argparse
import glob
import json
import os
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--host', help='Ironic host', required=True)
parser.add_argument('--registry', help='Registry to use', required=True)
parser.add_argument('--insecure-registry',
                    help='Whether the registry is insecure',
                    action='store_true')
parser.add_argument('--tls', help='TLS support', default='off',
                    choices=['off', 'on', 'insecure'])
parser.add_argument('--param', help='Kernel params', default=[],
                    action='append')

args = parser.parse_args()

proto = 'http' if args.tls == 'off' else 'https'
params = args.param
if args.tls == 'insecure':
    params += ['ipa-insecure=1']

ironic = f'{proto}://{args.host}:6385'
inspector = f'{proto}://{args.host}:5050/v1/continue'
podman_flags = '--tls-verify=false' if args.insecure_registry else ''

with open(os.path.join(os.path.dirname(__file__), 'ignition.json'), 'rt') as f:
    template = f.read()

with open(os.path.join(os.path.dirname(__file__), 'service'), 'rt') as f:
    service = f.read()

try:
    ssh_key = next(glob.iglob(os.path.expanduser("~/.ssh/id_*.pub")))
except StopIteration:
    sys.exit('No SSH public keys found')

with open(ssh_key, 'rt') as f:
    ssh_key = f.read().strip()

service = service.replace('%REGISTRY%', args.registry)

print(template
      .replace('%SERVICE%', json.dumps(service))
      .replace('%SSH_KEY%', ssh_key))
