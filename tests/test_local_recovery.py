"""Failure-only dispatch contracts; no cluster writes or real GitHub requests."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery_dispatcher', ROOT/'local/recovery_dispatcher.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RecoveryDispatcher(unittest.TestCase):
    ready = {"content": base64.b64encode(b"types: [recovery-requested]").decode()}
    def app(self, env='qa', health='Degraded'):
        return {'metadata': {'name': 'narx-commerce-' + env,
                             'labels': {'delivery.narx.space/environment': env}},
                'spec': {'project': 'narx-commerce-local'},
                'status': {'health': {'status': health}, 'operationState': {
                    'phase': 'Succeeded', 'syncResult': {'revision': 'a'*40}}}}

    def status(self, state='failure', identity=True, status_id=42):
        return {'id': status_id, 'context': 'narx/deploy-qa', 'state': state,
                'creator': {'login': r.OBSERVER if identity else 'other[bot]', 'id': r.OBSERVER_ID}}

    def test_healthy_and_dev_never_contact_github(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'api') as api:
            r.check({'items': [self.app(health='Healthy'), self.app('dev')]}, Path(folder)/'state.json', {})
            api.assert_not_called()

    def test_reject_foreign_project_and_invalid_revision(self):
        other = self.app(); other['spec']['project'] = 'default'
        bad = self.app(); bad['status']['operationState']['syncResult']['revision'] = 'main'
        self.assertEqual(list(r.candidates({'items': [other, bad]})), [])

    def test_newer_success_pending_or_spoof_blocks_historical_failure(self):
        for first in (self.status('success'), self.status('pending'), self.status(identity=False)):
            self.assertIsNone(r.trusted_failure([first, self.status()], 'qa'))
        impostor = self.status(); impostor['creator']['id'] = 1
        self.assertIsNone(r.trusted_failure([impostor], 'qa'))
        self.assertIsNone(r.trusted_failure([self.status(status_id=True)], 'qa'))

    def test_dry_run_never_mints_token_dispatches_or_records_success(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'api', return_value=[self.status()]) as api, patch.object(r, 'installation_token') as token:
            state = Path(folder)/'state.json'
            r.check({'items': [self.app()]}, state, {})
            self.assertFalse(state.exists()); token.assert_not_called(); self.assertEqual(api.call_count, 1)

    def test_dispatch_once_and_persist_only_success(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'api', side_effect=[[self.status()], self.ready, None, [self.status()]]) as api, patch.object(r, 'installation_token', return_value='test-only'):
            state = Path(folder)/'state.json'
            r.check({'items': [self.app()]}, state, {}, True)
            self.assertEqual(json.loads(state.read_text())['qa']['statusId'], 42)
            r.check({'items': [self.app()]}, state, {}, True)
            writes = [c for c in api.call_args_list if len(c.args) == 3]
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0].args[2]['event_type'], 'recovery-requested')
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)

    def test_transport_failure_retries_next_tick_without_saving(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'api', side_effect=[[self.status()], self.ready, OSError('transport')]), patch.object(r, 'installation_token', return_value='test-only'):
            state = Path(folder)/'state.json'
            with self.assertRaises(OSError): r.check({'items': [self.app()]}, state, {}, True)
            self.assertFalse(state.exists())

    def test_observer_lag_can_be_seen_on_next_tick(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'api', side_effect=[[], [self.status()], self.ready, None]) as api, patch.object(r, 'installation_token', return_value='test-only'):
            state = Path(folder)/'state.json'
            r.check({'items': [self.app()]}, state, {}, True)
            self.assertFalse(state.exists())
            r.check({'items': [self.app()]}, state, {}, True)
            self.assertTrue(state.exists())

    def test_migration_never_drops_an_event_before_workflow_is_ready(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r, 'api', side_effect=[[self.status()], {'content': base64.b64encode(b'on: status').decode()}]) as api, patch.object(r, 'installation_token') as token:
            state = Path(folder)/'state.json'
            r.check({'items': [self.app()]}, state, {}, True)
            self.assertFalse(state.exists())
            token.assert_not_called()
