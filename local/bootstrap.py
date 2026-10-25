#!/usr/bin/env python3
"""Prepare only the new local namespaces and short-lived ECR pull credentials.

Run with an explicit kube context and AWS profile. No production namespace support,
no secret files, no automatic password rotation, and no AWS provisioning.
"""
import argparse
import base64
import json
from pathlib import Path
import secrets
import subprocess


def command(*args, input=None):
    return subprocess.check_output(args, input=input, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'refresh-registry', 'configure-observer'])
    parser.add_argument('--context', required=True)
    parser.add_argument('--environment', choices=['dev', 'qa'])
    parser.add_argument('--aws-profile')
    parser.add_argument('--account-id')
    parser.add_argument('--region')
    parser.add_argument('--app-id')
    parser.add_argument('--installation-id')
    parser.add_argument('--private-key-file', type=Path)
    parser.add_argument('--notifications-file', type=Path)
    args = parser.parse_args()
    if not args.context.startswith('kind-'):
        parser.error('This helper is only for an explicitly named local kind cluster')
    base = ['kubectl', '--context', args.context]
    def apply(value):
        command(*base, 'apply', '--server-side', '--field-manager=narx-local-bootstrap', '-f', '-', input=json.dumps(value))
    if args.operation == 'configure-observer':
        if not (args.app_id and args.app_id.isdecimal() and args.installation_id and args.installation_id.isdecimal()
                and args.private_key_file and args.notifications_file):
            parser.error('Observer configuration needs numeric --app-id/--installation-id, --private-key-file and --notifications-file')
        data = json.loads(args.notifications_file.read_text())['data']
        if not data or any(not k.startswith(('trigger.narx-', 'template.narx-')) or not isinstance(v, str) for k, v in data.items()):
            parser.error('Notification patch may contain only Narx templates and triggers')
        service = f'appID: {args.app_id}\ninstallationID: {args.installation_id}\nprivateKey: $narx-github-privateKey\n'
        current = json.loads(command(*base, '-n', 'argocd', 'get', 'configmap', 'argocd-notifications-cm', '-o', 'json'))
        existing = current.get('data', {}).get('service.github')
        if existing and existing != service:
            parser.error('An existing GitHub notification integration needs operator review; it will not be overwritten')
        key = args.private_key_file.read_text()
        if not key.startswith(('-----BEGIN RSA PRIVATE KEY-----', '-----BEGIN PRIVATE KEY-----')):
            parser.error('Provide an unencrypted GitHub App PEM key file stored outside the repository')
        patch = {'stringData': {'narx-github-privateKey': key}}
        exists = command(*base, '-n', 'argocd', 'get', 'secret', 'argocd-notifications-secret', '--ignore-not-found', '-o', 'name')
        if exists:
            command(*base, '-n', 'argocd', 'patch', 'secret', 'argocd-notifications-secret', '--type=merge', '--patch-file=/dev/stdin', input=json.dumps(patch))
        else:
            apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'argocd-notifications-secret', 'namespace': 'argocd'}, **patch})
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
        if not args.aws_profile or not args.account_id or not args.region:
            parser.error('Registry refresh needs --aws-profile, --account-id and --region')
        identity = json.loads(command('aws','--profile',args.aws_profile,'sts','get-caller-identity'))
        if identity['Account'] != args.account_id:
            parser.error('AWS profile belongs to another account')
        password = command('aws','--profile',args.aws_profile,'ecr','get-login-password','--region',args.region)
        registry = f'{args.account_id}.dkr.ecr.{args.region}.amazonaws.com'
        docker = {'auths':{registry:{'auth':base64.b64encode(('AWS:'+password).encode()).decode()}}}
        apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'ecr-pull','namespace':namespace},
               'type':'kubernetes.io/dockerconfigjson','stringData':{'.dockerconfigjson':json.dumps(docker)}})
        print('Refreshed short-lived registry credential for',namespace,'(ECR tokens expire after 12 hours).')


if __name__ == '__main__':
    main()
