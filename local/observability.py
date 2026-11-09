#!/usr/bin/env python3
"""Render or install checksum-pinned Narx platform Helm releases on local kind.

Rendering is the default and makes no cluster changes. Installation is explicit.
Workload delivery remains owned by Argo; cluster-wide platform controllers use Helm.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parent
ENVIRONMENTS = ['commerce-dev', 'commerce-qa', 'commerce-production']


def run(*args, input=None):
    return subprocess.check_output(args, input=input, text=True).strip()


def chart_archive(record, cache):
    target = cache / (record['chart'] + '-' + record['version'] + '.tgz')
    if not target.exists():
        if record.get('url'):
            url = urlparse(record['url'])
            if url.scheme != 'https' or url.hostname != 'github.com':
                raise ValueError('Chart archive must come from its reviewed HTTPS release URL')
            with urlopen(record['url'], timeout=60) as response:
                content = response.read(25 * 1024 * 1024 + 1)
            if len(content) > 25 * 1024 * 1024:
                raise ValueError('Unexpected chart archive size')
            target.write_bytes(content)
        else:
            source = record.get('oci', record['chart'])
            args = ['helm', 'pull', source, '--version', record['version'], '--destination', str(cache)]
            if record.get('repository'):
                args += ['--repo', record['repository']]
            run(*args)
    if hashlib.sha256(target.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('Chart checksum mismatch: ' + target.name)
    return target


def monitoring_overlay(integration):
    data = integration['integration']
    if set(data['namespaces']) != set(ENVIRONMENTS):
        raise ValueError('Monitoring integration must cover exactly the three Narx environments')
    jobs = data['scrapeConfigs']
    if {j['job_name'] for j in jobs} != {'narx-http', 'narx-orders', 'narx-rollouts', 'narx-readiness', 'narx-argocd'}:
        raise ValueError('Unexpected scrape integration')
    for job in jobs:
        for discovery in job.get('kubernetes_sd_configs', []):
            if discovery.get('role') != 'pod' or set(discovery.get('namespaces', {}).get('names', [])) != set(ENVIRONMENTS):
                raise ValueError('Pod discovery must stay scoped to the three Narx environments')
    return {
        'prometheus': {'prometheusSpec': {'additionalScrapeConfigs': jobs}},
        'additionalPrometheusRulesMap': {'narx-commerce': {'groups': data['ruleGroups']}},
        'grafana': {'dashboards': {'default': {
            name: {'json': json.dumps(value)} for name, value in data['dashboards'].items()
        }}},
    }


def require_capacity(meminfo=Path('/proc/meminfo'), minimum_mb=900):
    available = next(int(line.split()[1]) for line in meminfo.read_text().splitlines()
                     if line.startswith('MemAvailable:'))
    if available < minimum_mb * 1024:
        raise ValueError(f'Less than {minimum_mb} MiB host memory available; free capacity before installation')


def prepare_credentials(kubectl, webhook_file):
    url = webhook_file.read_text().strip()
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'hooks.slack.com', 'hooks.slack-gov.com'} or parsed.username or parsed.password or not parsed.path.startswith('/services/'):
        raise ValueError('Provide the dedicated Narx Slack webhook file')
    current = run(*kubectl, 'get', 'namespace', 'monitoring', '--ignore-not-found', '-o', 'json')
    if current and json.loads(current)['metadata'].get('labels', {}).get('app.kubernetes.io/part-of') != 'narx-commerce':
        raise ValueError('The monitoring namespace belongs to another installation; refusing adoption')
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
        'name': 'monitoring', 'labels': {'app.kubernetes.io/part-of': 'narx-commerce',
                                       'pod-security.kubernetes.io/enforce': 'privileged'}}}
    # Node exporter needs host mounts. This does not relax workload namespaces.
    run(*kubectl, 'apply', '--server-side', '--field-manager=narx-observability', '-f', '-', input=json.dumps(namespace))
    existing = run(*kubectl, '-n', 'monitoring', 'get', 'secret', 'narx-monitoring-grafana', '--ignore-not-found', '-o', 'name')
    if not existing:
        secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'narx-monitoring-grafana', 'namespace': 'monitoring'},
                  'stringData': {'admin-user': 'admin', 'admin-password': secrets.token_urlsafe(32)}}
        run(*kubectl, 'apply', '--server-side', '--field-manager=narx-observability', '-f', '-', input=json.dumps(secret))
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'narx-monitoring-slack', 'namespace': 'monitoring'},
              'stringData': {'webhook-url': url}}
    run(*kubectl, 'apply', '--server-side', '--field-manager=narx-observability', '-f', '-', input=json.dumps(secret))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True, choices=['kind-narx-commerce'])
    parser.add_argument('--management-context', choices=['kind-narx-commerce'])
    parser.add_argument('--integration-values', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=ROOT.parents[1] / '.tools/platform-charts')
    parser.add_argument('--slack-webhook-file', type=Path)
    parser.add_argument('--render-dir', type=Path)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if args.install and (not args.management_context or not args.slack_webhook_file):
        parser.error('Installation needs explicit management context and the dedicated Slack file')
    overlay = monitoring_overlay(yaml.safe_load(args.integration_values.read_text()))
    records = json.loads((ROOT / 'observability-charts.json').read_text())
    args.cache.mkdir(parents=True, exist_ok=True)
    os.chmod(args.cache, 0o700)
    with tempfile.TemporaryDirectory(prefix='narx-observability-') as folder:
        folder = Path(folder)
        extra = folder / 'integration.yaml'
        extra.write_text(yaml.safe_dump(overlay))
        os.chmod(extra, 0o600)
        prepared = []
        for record in records:
            archive = chart_archive(record, args.cache)
            values = ['-f', str(ROOT / record['values'])]
            if record['release'] == 'narx-monitoring':
                values += ['-f', str(extra)]
            run('helm', 'lint', '--strict', str(archive), *values)
            rendered = run('helm', 'template', record['release'], str(archive), '-n', record['namespace'],
                           '--kube-version', '1.34.0', '--include-crds', *values)
            # Count upstream schema documents without YAML 1.1 scalar coercion.
            objects = [d for d in yaml.load_all(rendered, Loader=yaml.BaseLoader) if d]
            if args.render_dir:
                args.render_dir.mkdir(parents=True, exist_ok=True)
                os.chmod(args.render_dir, 0o700)
                rendered_file = args.render_dir / (record['release'] + '.yaml')
                rendered_file.write_text(rendered)
                os.chmod(rendered_file, 0o600)
            print(record['release'] + ': checksum verified; ' + str(len(objects)) + ' rendered resources')
            prepared.append((record, archive, values))
        if not args.install:
            print('Render-only validation complete; no cluster resources changed.')
            return
        installed = all(any(item.get('status') == 'deployed' for item in json.loads(
            run('helm', 'list', '--kube-context', args.context, '-n', r['namespace'],
                '--filter', '^' + r['release'] + '$', '-o', 'json'))) for r in records)
        require_capacity(minimum_mb=300 if installed else 900)
        kubectl = ['kubectl', '--context', args.context]
        # Never replace a metrics API registered by another release/project.
        current = run(*kubectl, 'get', 'apiservice', 'v1beta1.metrics.k8s.io', '--ignore-not-found', '-o', 'json')
        if current and json.loads(current)['spec']['service'].get('name') != 'narx-metrics-server':
            raise ValueError('An independently owned metrics API already exists; refusing replacement')
        prepare_credentials(kubectl, args.slack_webhook_file)
        run(*kubectl, 'apply', '--server-side', '--field-manager=narx-observability', '-f', str(ROOT / 'monitoring-network.yaml'))
        run('kubectl', '--context', args.management_context, 'apply', '--server-side',
            '--field-manager=narx-observability', '-f', str(ROOT / 'argocd-metrics.yaml'))
        for record, archive, values in prepared:
            print('Installing/upgrading ' + record['release'])
            # Do not print rendered manifests or credentials. Helm owns release state.
            run('helm', 'upgrade', '--install', record['release'], str(archive), '--kube-context', args.context,
                '-n', record['namespace'], '--atomic', '--wait', '--timeout', '10m', '--history-max', '5', *values)
        print('Platform releases installed. Verify targets, rules, storage, Slack and metrics API before enabling HPA.')


if __name__ == '__main__':
    main()
