#!/usr/bin/env python3
"""Bootstrap the dedicated Narx kind cluster and shared Argo CD integration.

Explicit contexts, preserved runtime credentials, no AWS provisioning.
"""
import argparse
import base64
import json
import ipaddress
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.parse import urlparse


def command(*args, input=None):
    return subprocess.check_output(args, input=input, text=True).strip()


NODE_CONTEXTS = {
    'mega-local-control-plane': ('mega-local', 'kind-mega-local'),
    'mega-local-worker': ('mega-local', 'kind-mega-local'),
    'mega-local-worker2': ('mega-local', 'kind-mega-local'),
    'narx-commerce-control-plane': ('narx-commerce', 'kind-narx-commerce'),
}


def node_reconnect_command(node, network='kind'):
    args = ['docker', 'network', 'connect', '--ip', node['ipv4']]
    if node['ipv6']:
        args += ['--ip6', node['ipv6']]
    for alias in node['aliases']:
        args += ['--alias', alias]
    return args + [network, node['containerId']]


def plan_node_addresses(context, management_context, path):
    """Read-only Docker/Kubernetes inspection; save explicit, reviewable commands."""
    if (context, management_context) != ('kind-narx-commerce', 'kind-mega-local'):
        raise ValueError('Address planning requires the two explicit local contexts')
    containers = json.loads(command('docker', 'inspect', *NODE_CONTEXTS))
    network = json.loads(command('docker', 'network', 'inspect', 'kind'))[0]
    if network.get('Driver') != 'bridge' or network.get('Name') != 'kind':
        raise ValueError('Expected the existing local kind bridge')
    actual = {c['Name'].lstrip('/'): c for c in containers}
    if set(actual) != set(NODE_CONTEXTS) or len(actual) != len(containers):
        raise ValueError('The expected node containers are missing or duplicated')
    attached = {n['Name'] for n in network.get('Containers', {}).values()}
    if attached != set(NODE_CONTEXTS):
        raise ValueError('Unexpected bridge members; review network ownership first')
    subnets = [ipaddress.ip_network(n['Subnet']) for n in network['IPAM']['Config']]
    kubernetes = {}
    for ctx in ('kind-mega-local', 'kind-narx-commerce'):
        items = json.loads(command('kubectl', '--context', ctx, '--request-timeout=15s',
                                   'get', 'nodes', '-o', 'json'))['items']
        kubernetes[ctx] = {n['metadata']['name']: n for n in items}
    plan = {'schemaVersion': 1, 'network': 'kind', 'networkId': network['Id'],
            'impact': 'Applying commands briefly disconnects each node; use reviewed maintenance, one node at a time.',
            'nodes': []}
    for name, (cluster, ctx) in NODE_CONTEXTS.items():
        container = actual[name]
        if not container['State']['Running'] or container['Config']['Labels'].get('io.x-k8s.kind.cluster') != cluster:
            raise ValueError('Node ownership or running-state mismatch: ' + name)
        endpoint = container['NetworkSettings']['Networks'].get('kind', {})
        if endpoint.get('NetworkID') != network['Id']:
            raise ValueError('Node is attached to a different network: ' + name)
        ipv4, ipv6 = endpoint.get('IPAddress'), endpoint.get('GlobalIPv6Address', '')
        for value in [ipv4] + ([ipv6] if ipv6 else []):
            address = ipaddress.ip_address(value)
            if not any(address.version == subnet.version and address in subnet for subnet in subnets):
                raise ValueError('Node address is outside the bridge subnet: ' + name)
        node = kubernetes[ctx].get(name)
        if not node or ipv4 not in [a['address'] for a in node['status']['addresses'] if a['type'] == 'InternalIP']:
            raise ValueError('Docker/Kubernetes address mismatch; recover before planning: ' + name)
        if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']):
            raise ValueError('Node is not Ready: ' + name)
        entry = {'name': name, 'context': ctx, 'containerId': container['Id'],
                 'nodeUid': node['metadata']['uid'], 'ipv4': ipv4, 'ipv6': ipv6,
                 'aliases': sorted(set((endpoint.get('Aliases') or []) + [name]))}
        entry['disconnect'] = ['docker', 'network', 'disconnect', 'kind', container['Id']]
        entry['connect'] = node_reconnect_command(entry)
        plan['nodes'].append(entry)
    path = path.resolve()
    if path.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Keep host-specific address plans outside the repository')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as file:
        json.dump(plan, file, indent=2)
        file.write('\n')
    print('Saved address plan for four existing nodes:', path)
    print('No network attachments changed. Review before a maintenance window.')
    return plan


def configure_repository_webhook(base):
    config = json.loads((Path(__file__).resolve().parent / 'argocd.json').read_text())['webhook']
    if config != {'repository': 'Narx-Space-Prod/platform-gitops',
                  'url': 'https://argocd.narx.space/api/webhook', 'events': ['push']}:
        raise ValueError('Unexpected repository webhook destination')
    endpoint = 'repos/' + config['repository'] + '/hooks'
    pages = json.loads(command('gh', 'api', '--paginate', '--slurp', endpoint + '?per_page=100'))
    hooks = [h for page in pages for h in page if h.get('config', {}).get('url') == config['url']]
    if len(hooks) > 1:
        raise ValueError('Duplicate Argo webhooks require operator review')
    current = json.loads(command(*base, '-n', 'argocd', 'get', 'secret', 'argocd-secret', '-o', 'json'))
    encoded = current.get('data', {}).get('webhook.github.secret')
    if hooks and not encoded:
        raise ValueError('Existing webhook has no local secret; review rotation before changing it')
    key = base64.b64decode(encoded, validate=True).decode() if encoded else secrets.token_hex(32)
    if len(key) < 32:
        raise ValueError('Webhook shared secret must be at least 32 characters')
    # Patch only this key, preserving admin credentials and Argo signing keys.
    command(*base, '-n', 'argocd', 'patch', 'secret', 'argocd-secret', '--type=merge',
            '--patch-file=/dev/stdin', input=json.dumps({'stringData': {'webhook.github.secret': key}}))
    payload = {'name': 'web', 'active': True, 'events': config['events'],
               'config': {'url': config['url'], 'content_type': 'json', 'insecure_ssl': '0', 'secret': key}}
    path = endpoint + ('/' + str(hooks[0]['id']) if hooks else '')
    response = json.loads(command('gh', 'api', '--method', 'PATCH' if hooks else 'POST', path,
                                  '--input', '-', input=json.dumps(payload)))
    print('Configured signed GitOps push webhook:', response['id'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'register-cluster', 'refresh-registry', 'configure-observer', 'configure-delivery-notifications', 'configure-repository-webhook', 'plan-node-addresses'])
    parser.add_argument('--context', required=True)
    parser.add_argument('--management-context')
    parser.add_argument('--environment', choices=['dev', 'qa', 'production'])
    parser.add_argument('--registry-user')
    parser.add_argument('--registry-token-file', type=Path)
    parser.add_argument('--app-id')
    parser.add_argument('--installation-id')
    parser.add_argument('--private-key-file', type=Path)
    parser.add_argument('--notifications-file', type=Path)
    parser.add_argument('--slack-webhook-file', type=Path)
    parser.add_argument('--node-plan-file', type=Path)
    args = parser.parse_args()
    if not args.context.startswith('kind-'):
        parser.error('This helper is only for an explicitly named local kind cluster')
    if args.operation in {'prepare', 'register-cluster', 'refresh-registry', 'configure-repository-webhook'} and args.context != 'kind-narx-commerce':
        parser.error('Narx workloads must use the dedicated kind-narx-commerce context')
    if args.operation == 'plan-node-addresses':
        if not args.node_plan_file:
            parser.error('Address planning requires --node-plan-file outside the repository')
        plan_node_addresses(args.context, args.management_context, args.node_plan_file)
        return
    base = ['kubectl', '--context', args.context]
    if args.operation == 'configure-repository-webhook':
        configure_repository_webhook(base)
        return
    def apply(value):
        command(*base, 'apply', '--server-side', '--field-manager=narx-local-bootstrap', '-f', '-', input=json.dumps(value))
    def notification_secret(values):
        patch = {'stringData': values}
        exists = command(*base, '-n', 'argocd', 'get', 'secret', 'argocd-notifications-secret', '--ignore-not-found', '-o', 'name')
        if exists:
            command(*base, '-n', 'argocd', 'patch', 'secret', 'argocd-notifications-secret', '--type=merge', '--patch-file=/dev/stdin', input=json.dumps(patch))
        else:
            apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'argocd-notifications-secret','namespace':'argocd'}, **patch})
    if args.operation == 'register-cluster':
        if not args.management_context or not args.management_context.startswith('kind-') or (args.management_context == args.context and args.context != 'kind-narx-commerce'):
            parser.error('Registration needs an explicit local --management-context hosting Argo CD')
        namespaces = ['commerce-dev', 'commerce-qa', 'commerce-production']
        for namespace in namespaces:
            command(*base, 'get', 'namespace', namespace, '-o', 'name')
        apply({'apiVersion':'v1','kind':'Namespace','metadata':{'name':'narx-system'}})
        apply({'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'argocd-manager','namespace':'narx-system'}})
        for namespace in namespaces:
            # Namespace administrator, like argocd cluster add --namespace.
            # No ClusterRole/ClusterRoleBinding: platform CRDs remain an operator task.
            apply({'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role',
                   'metadata':{'name':'narx-argocd-manager','namespace':namespace},
                   'rules':[{'apiGroups':['*'],'resources':['*'],
                             'verbs':['get','list','watch','create','update','patch','delete']}]})
            apply({'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding',
                   'metadata':{'name':'narx-argocd-manager','namespace':namespace},
                   'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':'narx-argocd-manager'},
                   'subjects':[{'kind':'ServiceAccount','name':'argocd-manager','namespace':'narx-system'}]})
        apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'argocd-manager-token','namespace':'narx-system',
               'annotations':{'kubernetes.io/service-account.name':'argocd-manager'}},
               'type':'kubernetes.io/service-account-token'})
        for _ in range(20):
            token_secret = json.loads(command(*base, '-n', 'narx-system', 'get', 'secret', 'argocd-manager-token', '-o', 'json'))
            if token_secret.get('data', {}).get('token'):
                break
            time.sleep(1)
        else:
            raise SystemExit('Kubernetes did not populate the Argo service-account token; registration was not written')
        kubeconfig = json.loads(command(*base, 'config', 'view', '--raw', '--minify', '-o', 'json'))
        ca = kubeconfig['clusters'][0]['cluster']['certificate-authority-data']
        registration = {'apiVersion':'v1','kind':'Secret','metadata':{
            'name':'narx-local-cluster','namespace':'argocd',
            'labels':{'argocd.argoproj.io/secret-type':'cluster'}},'type':'Opaque',
            'stringData':{'name':'narx-local','server':'https://narx-commerce-control-plane:6443',
                          'project':'narx-commerce-local','namespaces':','.join(namespaces),
                          'clusterResources':'false','config':json.dumps({
                              'bearerToken':base64.b64decode(token_secret['data']['token'], validate=True).decode(),
                              'tlsClientConfig':{'insecure':False,'caData':ca}})}}
        command('kubectl', '--context', args.management_context, 'apply', '--server-side',
                '--field-manager=narx-local-bootstrap', '-f', '-', input=json.dumps(registration))
        print('Registered narx-local in shared Argo CD, scoped to the three commerce namespaces. Token not displayed.')
        return
    if args.operation == 'configure-delivery-notifications':
        if not args.notifications_file or not args.slack_webhook_file:
            parser.error('Delivery notifications need --notifications-file and an independent --slack-webhook-file')
        source = json.loads(args.notifications_file.read_text())['data']
        data = {k:v for k,v in source.items() if k == 'service.webhook.slack' or k.startswith(('trigger.narx-slack-', 'template.narx-slack-'))}
        if not data or not data.get('service.webhook.slack', '').startswith('url: $narx-slack-webhook\n'):
            parser.error('The reviewed Slack service must reference the dedicated Narx secret key')
        current = json.loads(command(*base, '-n', 'argocd', 'get', 'configmap', 'argocd-notifications-cm', '-o', 'json'))
        existing = current.get('data', {}).get('service.webhook.slack')
        if existing and existing != data['service.webhook.slack']:
            parser.error('An existing Slack webhook service needs operator review; it will not be overwritten')
        webhook = args.slack_webhook_file.read_text().strip()
        url = urlparse(webhook)
        if url.scheme != 'https' or url.hostname not in {'hooks.slack.com', 'hooks.slack-gov.com'} or url.username or url.password or not url.path:
            parser.error('The monitoring credential must be an HTTPS Slack webhook')
        notification_secret({'narx-slack-webhook': webhook})
        command(*base, '-n', 'argocd', 'patch', 'configmap', 'argocd-notifications-cm', '--type=merge', '--patch-file=/dev/stdin', input=json.dumps({'data': data}))
        print('Configured Narx delivery summaries using its own Slack credential, preserving other settings.')
        return
    if args.operation == 'configure-observer':
        if not (args.app_id and args.app_id.isdecimal() and args.installation_id and args.installation_id.isdecimal()
                and args.private_key_file and args.notifications_file):
            parser.error('Observer configuration needs numeric --app-id/--installation-id, --private-key-file and --notifications-file')
        data = json.loads(args.notifications_file.read_text())['data']
        if not data or any((not k.startswith(('trigger.narx-', 'template.narx-')) and k != 'service.webhook.slack') or not isinstance(v, str) for k, v in data.items()):
            parser.error('Notification patch may contain only Narx templates and triggers')
        data = {k:v for k,v in data.items() if k != 'service.webhook.slack' and not k.startswith(('trigger.narx-slack-', 'template.narx-slack-'))}
        service = f'appID: {args.app_id}\ninstallationID: {args.installation_id}\nprivateKey: $narx-github-privateKey\n'
        current = json.loads(command(*base, '-n', 'argocd', 'get', 'configmap', 'argocd-notifications-cm', '-o', 'json'))
        existing = current.get('data', {}).get('service.github')
        if existing and existing != service:
            parser.error('An existing GitHub notification integration needs operator review; it will not be overwritten')
        key = args.private_key_file.read_text()
        if not key.startswith(('-----BEGIN RSA PRIVATE KEY-----', '-----BEGIN PRIVATE KEY-----')):
            parser.error('Provide an unencrypted GitHub App PEM key file stored outside the repository')
        notification_secret({'narx-github-privateKey': key})
        data['service.github'] = service
        command(*base, '-n', 'argocd', 'patch', 'configmap', 'argocd-notifications-cm', '--type=merge', '--patch-file=/dev/stdin', input=json.dumps({'data': data}))
        print('Configured Narx deployment evidence, preserving other notification settings.')
        return
    if not args.environment:
        parser.error('--environment is required for namespace and registry operations')
    namespace = 'commerce-' + args.environment
    if args.operation == 'prepare':
        apply({'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace,'labels':{
            'pod-security.kubernetes.io/enforce':'restricted','pod-security.kubernetes.io/enforce-version':'v1.34',
            'delivery.narx.space/project':'commerce','delivery.narx.space/environment':args.environment}}})
        exists = bool(command(*base,'-n',namespace,'get','secret','commerce-runtime','--ignore-not-found','-o','json'))
        if not exists:
            values = {'DATABASE_USER':'commerce','DATABASE_PASSWORD':secrets.token_hex(32),
                'DATABASE_URL':'jdbc:postgresql://commerce-postgres:5432/commerce',
                'SESSION_SECRET':secrets.token_hex(32),'REDIS_URL':'redis://commerce-redis:6379/0',
                'DELIVERY_QUEUE_URL':'http://elasticmq:9324/000000000000/order-paid'}
            apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'commerce-runtime','namespace':namespace},
                   'type':'Opaque','stringData':values})
        apply({'apiVersion':'v1','kind':'ResourceQuota','metadata':{'name':'commerce-capacity','namespace':namespace},
               'spec':{'hard':{'requests.memory':'1536Mi','limits.memory':'3Gi','pods':'30','requests.storage':'4Gi'}}})
        print('Prepared',namespace,'without changing existing database/session credentials.')
    else:
        if not args.registry_user or not args.registry_token_file:
            parser.error('Private GHCR pulls need --registry-user and --registry-token-file')
        if ':' in args.registry_user or any(c.isspace() for c in args.registry_user):
            parser.error('Registry username may not contain a colon or whitespace')
        if args.registry_token_file.stat().st_mode & 0o077:
            parser.error('Registry token file must be private to its owner (chmod 600)')
        if args.registry_token_file.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            parser.error('Registry token file must be outside the repository')
        password = args.registry_token_file.read_text().strip()
        if not password or any(c.isspace() for c in password):
            parser.error('Registry token must be nonempty and contain no whitespace')
        docker = {'auths':{'ghcr.io':{'auth':base64.b64encode((args.registry_user+':'+password).encode()).decode()}}}
        apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'ghcr-pull','namespace':namespace},
               'type':'kubernetes.io/dockerconfigjson','stringData':{'.dockerconfigjson':json.dumps(docker)}})
        print('Refreshed GHCR pull credential for',namespace,'. Rotate it before its configured expiry.')


if __name__ == '__main__':
    main()
