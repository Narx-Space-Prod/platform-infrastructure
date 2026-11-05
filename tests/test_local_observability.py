"""Bootstrap safety and contracts on reused Helm render output; no installation."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('narx_observability', ROOT/'local/observability.py')
obs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(obs)


class BootstrapSafety(unittest.TestCase):
    def integration(self):
        return {'integration': {'namespaces': obs.ENVIRONMENTS.copy(),
                'scrapeConfigs': [{'job_name': j} for j in
                                 ['narx-http', 'narx-orders', 'narx-rollouts', 'narx-readiness', 'narx-argocd']],
                'ruleGroups': [], 'dashboards': {}}}

    def test_overlay_cannot_silently_omit_an_environment(self):
        value = self.integration()
        result = obs.monitoring_overlay(value)
        self.assertEqual(result['prometheus']['prometheusSpec']['additionalScrapeConfigs'], value['integration']['scrapeConfigs'])
        invalid = copy.deepcopy(value)
        invalid['integration']['namespaces'].remove('commerce-production')
        with self.assertRaises(ValueError):
            obs.monitoring_overlay(invalid)
        invalid = copy.deepcopy(value)
        invalid['integration']['scrapeConfigs'].append({'job_name': 'other-project'})
        with self.assertRaises(ValueError):
            obs.monitoring_overlay(invalid)

    def test_tampered_cached_chart_is_rejected_without_execution_or_download(self):
        record = json.loads((ROOT/'local/observability-charts.json').read_text())[0]
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            (cache/(record['chart']+'-'+record['version']+'.tgz')).write_bytes(b'tampered')
            with patch.object(obs, 'run') as command, self.assertRaises(ValueError):
                obs.chart_archive(record, cache)
            command.assert_not_called()

    def test_insufficient_host_memory_blocks_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'meminfo'
            path.write_text('MemAvailable: 512000 kB\n')
            with self.assertRaises(ValueError):
                obs.require_capacity(path)
            obs.require_capacity(path, minimum_mb=300)

    def test_grafana_password_is_preserved_and_invalid_webhook_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'webhook'
            file.write_text('https://hooks.slack.com/services/test-only/fixture/value')
            calls = []
            def command(*args, **kwargs):
                calls.append((args, kwargs))
                return 'secret/narx-monitoring-grafana' if 'get' in args and 'secret' in args else ''
            with patch.object(obs, 'run', side_effect=command), patch.object(obs.secrets, 'token_urlsafe') as generate:
                obs.prepare_credentials(['kubectl', '--context', 'kind-narx-commerce'], file)
                generate.assert_not_called()
            objects = [json.loads(k['input']) for _, k in calls if 'input' in k]
            self.assertFalse(any(d['kind']=='Secret' and d['metadata']['name']=='narx-monitoring-grafana' for d in objects))
            self.assertTrue(all(d['metadata'].get('namespace', d['metadata']['name'])=='monitoring' for d in objects))
            file.write_text('http://example.invalid/not-a-slack-hook')
            with patch.object(obs, 'run') as command, self.assertRaises(ValueError):
                obs.prepare_credentials(['kubectl'], file)
            command.assert_not_called()

    def test_network_permissions_are_scoped_to_monitoring_roles(self):
        documents = list(yaml.safe_load_all((ROOT/'local/monitoring-network.yaml').read_text()))
        self.assertTrue(all(d['metadata']['namespace']=='monitoring' for d in documents))
        api = next(d for d in documents if d['metadata']['name']=='narx-monitoring-api')
        self.assertEqual(api['spec']['endpointSelector']['matchLabels'], {'narx.space/kubernetes-api-access':'true'})
        self.assertEqual(api['spec']['egress'][0]['toEntities'], ['kube-apiserver'])

    def test_existing_unrelated_monitoring_namespace_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'webhook'
            file.write_text('https://hooks.slack.com/services/test-only/fixture/value')
            other = json.dumps({'metadata': {'labels': {'app.kubernetes.io/part-of': 'another-project'}}})
            with patch.object(obs, 'run', return_value=other) as command, self.assertRaises(ValueError):
                obs.prepare_credentials(['kubectl'], file)
            self.assertEqual(command.call_count, 1)


class RenderedPlatform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(os.environ.get('NARX_PLATFORM_RENDER_DIR', '/tmp/narx-platform-render'))
        if not (folder/'narx-monitoring.yaml').exists():
            raise unittest.SkipTest('Render the pinned charts first; CI reuses that output')
        cls.docs = {name: [d for d in yaml.load_all((folder/(name+'.yaml')).read_text(), Loader=yaml.BaseLoader) if d]
                    for name in ['narx-metrics-server', 'narx-probes', 'narx-monitoring']}

    def test_metrics_api_verifies_its_serving_certificate(self):
        docs = self.docs['narx-metrics-server']
        api = next(d for d in docs if d['kind']=='APIService')
        secret = next(d for d in docs if d['kind']=='Secret')
        self.assertEqual(api['spec'].get('insecureSkipTLSVerify', 'false'), 'false')
        self.assertEqual(api['spec']['caBundle'], secret['data']['tls.crt'])
        self.assertIn(b'BEGIN CERTIFICATE', base64.b64decode(api['spec']['caBundle']))

    def test_grafana_uses_existing_secret_instead_of_a_committed_password(self):
        docs = self.docs['narx-monitoring']
        deployment = next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='narx-monitoring-grafana')
        containers = deployment['spec']['template']['spec']['containers']
        env = {e['name']: e for c in containers for e in c.get('env', [])}
        self.assertEqual(env['GF_SECURITY_ADMIN_PASSWORD']['valueFrom']['secretKeyRef']['name'], 'narx-monitoring-grafana')
        self.assertFalse(any(d['kind']=='Secret' and d['metadata']['name']=='narx-monitoring-grafana' for d in docs))

    def test_alertmanager_mounts_the_webhook_secret_without_embedding_its_value(self):
        docs = self.docs['narx-monitoring']
        manager = next(d for d in docs if d['kind']=='Alertmanager')
        self.assertIn('narx-monitoring-slack', manager['spec']['secrets'])
        secret = next(d for d in docs if d['kind']=='Secret' and 'alertmanager.yaml' in d.get('data', {}))
        config = yaml.safe_load(base64.b64decode(secret['data']['alertmanager.yaml']))
        receiver = next(r for r in config['receivers'] if r['name']=='narx-slack')
        slack = receiver['slack_configs'][0]
        self.assertIn('api_url_file', slack)
        self.assertNotIn('api_url', slack)

    def test_admission_jobs_have_api_access_before_they_run(self):
        docs = self.docs['narx-monitoring']
        jobs = [d for d in docs if d['kind']=='Job' and 'admission' in d['metadata']['name']]
        self.assertEqual(len(jobs), 2)
        policies = [d for d in docs if d['kind']=='CiliumNetworkPolicy']
        for job in jobs:
            labels = job['spec']['template']['metadata']['labels']
            policy = next(p for p in policies if all(labels.get(k)==v for k,v in p['spec']['endpointSelector']['matchLabels'].items()))
            self.assertIn('kube-apiserver', policy['spec']['egress'][0]['toEntities'])
            self.assertEqual(policy['metadata']['annotations']['helm.sh/hook-weight'], '-5')


if __name__ == '__main__':
    unittest.main()
