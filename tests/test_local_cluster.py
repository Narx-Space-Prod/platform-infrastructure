"""Test cluster identity and credential boundaries without creating a cluster."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('bootstrap_cluster', Path(__file__).resolve().parents[1] / 'local/bootstrap.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class ClusterRegistration(unittest.TestCase):
    def run_registration(self, target='kind-narx-commerce', manager='kind-narx-commerce', token=True):
        calls = []

        def command(*args, input=None):
            calls.append((args, input))
            if 'config' in args:
                return json.dumps({'clusters':[{'cluster':{'certificate-authority-data':'test-ca'}}]})
            if 'get' in args and 'secret' in args:
                return json.dumps({'data':{'token':base64.b64encode(b'test-bearer').decode()}} if token else {})
            return 'ok'

        argv = ['bootstrap.py', 'register-cluster', '--context', target, '--management-context', manager]
        with patch.object(sys, 'argv', argv), patch.object(b, 'command', side_effect=command), \
                patch.object(b.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()):
            b.main()
        return calls, output.getvalue()

    def test_registration_uses_remote_namespace_permissions_and_private_stdin(self):
        calls, output = self.run_registration()
        writes = [(args, json.loads(value)) for args, value in calls if value is not None]
        remote = [doc for args, doc in writes if args[args.index('--context')+1] == 'kind-narx-commerce']
        self.assertFalse(any(doc['kind'] in {'ClusterRole','ClusterRoleBinding'} for doc in remote))
        roles = [doc for doc in remote if doc['kind'] == 'Role']
        self.assertEqual({r['metadata']['namespace'] for r in roles}, {'commerce-dev','commerce-qa','commerce-production'})
        registrations = [doc for args, doc in writes if doc['metadata']['name'] == 'narx-local-cluster']
        self.assertEqual(len(registrations), 1)
        data = registrations[0]['stringData']
        self.assertEqual(data['server'], 'https://narx-commerce-control-plane:6443')
        self.assertEqual(data['project'], 'narx-commerce-local')
        self.assertEqual(data['clusterResources'], 'false')
        self.assertEqual(set(data['namespaces'].split(',')), {r['metadata']['namespace'] for r in roles})
        self.assertFalse(json.loads(data['config'])['tlsClientConfig']['insecure'])
        self.assertNotIn('test-bearer', output)
        for args, _ in calls:
            self.assertNotIn('test-bearer', ' '.join(args))

    def test_boutique_target_is_rejected_before_any_write(self):
        for target, manager in [('kind-mega-local','kind-other')]:
            with patch.object(b, 'command') as command:
                with patch.object(sys, 'argv', ['bootstrap.py','register-cluster','--context',target,'--management-context',manager]), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    b.main()
                command.assert_not_called()

    def test_standalone_registration_preserves_namespace_scoping(self):
        calls, output = self.run_registration(manager='kind-narx-commerce')
        writes = [json.loads(value) for _, value in calls if value is not None]
        registration = next(doc for doc in writes if doc['metadata']['name'] == 'narx-local-cluster')
        self.assertEqual(registration['stringData']['clusterResources'], 'false')
        self.assertFalse(any(doc['kind'] in {'ClusterRole', 'ClusterRoleBinding'} for doc in writes))
        self.assertNotIn('test-bearer', output)

    def test_unpopulated_token_never_registers_an_empty_credential(self):
        with self.assertRaisesRegex(SystemExit, 'registration was not written'):
            self.run_registration(token=False)


if __name__ == '__main__':
    unittest.main()
