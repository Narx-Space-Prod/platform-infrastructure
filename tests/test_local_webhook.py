"""Check push-webhook identity, idempotence and private secret handling."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('webhook_bootstrap',Path(__file__).resolve().parents[1]/'local/bootstrap.py')
b=importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

class RepositoryWebhook(unittest.TestCase):
    def configure(self, existing=False, secret=True):
        calls=[]
        key='test-key-'+'a'*64
        def command(*args,input=None):
            calls.append((args,input))
            if '--slurp' in args:
                return json.dumps([[{'id':123,'config':{'url':'https://argocd.narx.space/api/webhook'}}] if existing else []])
            if 'get' in args and 'secret' in args:
                return json.dumps({'data':{'admin.password':'untouched',**({'webhook.github.secret':base64.b64encode(key.encode()).decode()} if secret else {})}})
            if args[0]=='gh':return json.dumps({'id':123})
            return 'patched'
        with patch.object(b,'command',side_effect=command), patch.object(b.secrets,'token_hex',return_value=key), contextlib.redirect_stdout(io.StringIO()) as output:
            b.configure_repository_webhook(['kubectl','--context','kind-narx-commerce'])
        return calls,key,output.getvalue()

    def test_first_install_uses_only_stdin_and_preserves_existing_argo_secret(self):
        calls,key,output=self.configure(secret=False)
        mutation=next((a,raw) for a,raw in calls if a[0]=='gh' and '--method' in a)
        self.assertIn('POST',mutation[0])
        payload=json.loads(mutation[1])
        self.assertEqual(payload['events'],['push'])
        self.assertEqual(payload['config']['insecure_ssl'],'0')
        self.assertEqual(payload['config']['secret'],key)
        secret_patch=json.loads(next(raw for a,raw in calls if 'patch' in a))
        self.assertEqual(secret_patch,{'stringData':{'webhook.github.secret':key}})
        self.assertNotIn(key,output)
        self.assertTrue(all(key not in ' '.join(a) for a,_ in calls))

    def test_existing_hook_is_updated_with_the_preserved_key(self):
        calls,key,_=self.configure(existing=True)
        a,raw=next((a,raw) for a,raw in calls if a[0]=='gh' and '--method' in a)
        self.assertIn('PATCH',a)
        self.assertIn('repos/Narx-Space-Prod/platform-gitops/hooks/123',a)
        self.assertEqual(json.loads(raw)['config']['secret'],key)

    def test_unknown_existing_secret_requires_explicit_rotation_review(self):
        with self.assertRaisesRegex(ValueError,'review rotation'):
            self.configure(existing=True,secret=False)

    def test_non_narx_context_is_rejected_before_any_write(self):
        with patch.object(sys,'argv',['bootstrap.py','configure-repository-webhook','--context','kind-mega-local']), patch.object(b,'command') as command, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            b.main()
        command.assert_not_called()
