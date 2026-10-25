"""No real cluster or Slack calls: credential scope and config preservation checks."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('local_bootstrap',Path(__file__).resolve().parents[1]/'local/bootstrap.py')
b=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(b)


class DeliveryNotifications(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.file=Path(self.directory.name)/'notifications.json'
        self.service='url: $narx-slack-webhook\nheaders: []\n'
        self.file.write_text(json.dumps({'data':{'service.webhook.slack':self.service,'trigger.narx-slack-deployed':'fixture','template.narx-slack-deployed':'fixture','trigger.narx-healthy':'github-only'}}))
        self.webhook='https://hooks.slack.com/services/unit-test-placeholder'
        self.current={'data':{'service.slack':'token: $existing-token'}}
        self.calls=[]

    def command(self,*args,input=None):
        self.calls.append((args,input))
        if 'get' in args:
            if 'configmap' in args:return json.dumps(self.current)
            if 'monitoring' in args:return json.dumps({'data':{'slack_webhook':base64.b64encode(self.webhook.encode()).decode(),'grafana_password':base64.b64encode(b'unrelated').decode()}})
            return 'secret/argocd-notifications-secret'
        return 'patched'

    def execute(self):
        argv=['bootstrap.py','configure-delivery-notifications','--context','kind-mega-local','--notifications-file',str(self.file)]
        with patch.object(sys,'argv',argv),patch.object(b,'command',side_effect=self.command),contextlib.redirect_stdout(io.StringIO()) as output,contextlib.redirect_stderr(io.StringIO()):
            b.main()
        return output.getvalue()

    def test_only_slack_key_is_transferred_via_stdin_and_legacy_config_is_preserved(self):
        output=self.execute()
        self.assertNotIn(self.webhook,output)
        for args,_ in self.calls:self.assertNotIn(self.webhook,' '.join(args))
        writes=[(args,json.loads(value)) for args,value in self.calls if value is not None]
        secret=next(v for args,v in writes if 'secret' in args)
        self.assertEqual(secret,{'stringData':{'narx-slack-webhook':self.webhook}})
        config=next(v for args,v in writes if 'configmap' in args)
        self.assertEqual(set(config['data']),{'service.webhook.slack','trigger.narx-slack-deployed','template.narx-slack-deployed'})
        self.assertNotIn('service.slack',config['data'])

    def test_existing_different_webhook_service_is_not_overwritten(self):
        self.current['data']['service.webhook.slack']='url: $another-project-key\n'
        with self.assertRaises(SystemExit):self.execute()
        self.assertFalse(any(value is not None for _,value in self.calls))

    def test_non_slack_secret_cannot_be_forwarded(self):
        self.webhook='https://example.invalid/collect'
        with self.assertRaises(SystemExit):self.execute()
        self.assertFalse(any(value is not None for _,value in self.calls))


if __name__=='__main__':unittest.main()
