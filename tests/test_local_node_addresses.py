"""Guard the read-only host-address plan before any operator reconnects a node."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('node_address_bootstrap', Path(__file__).resolve().parents[1]/'local/bootstrap.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class NodeAddressPlanning(unittest.TestCase):
    def fixture(self):
        network={'Id':'network-id','Name':'kind','Driver':'bridge',
                 'IPAM':{'Config':[{'Subnet':'172.18.0.0/16'},{'Subnet':'fc00:f853:ccd:e793::/64'}]},
                 'Containers':{}}
        containers=[];nodes={'kind-mega-local':[],'kind-narx-commerce':[]}
        for i,(name,(cluster,ctx)) in enumerate(b.NODE_CONTEXTS.items(),2):
            ipv4='172.18.0.'+str(i);ipv6='fc00:f853:ccd:e793::'+str(i)
            containers.append({'Id':'container-'+name,'Name':'/'+name,'State':{'Running':True},
                               'Config':{'Labels':{'io.x-k8s.kind.cluster':cluster}},
                               'NetworkSettings':{'Networks':{'kind':{'NetworkID':'network-id','IPAddress':ipv4,
                                  'GlobalIPv6Address':ipv6,'Aliases':['operator-alias']}}}})
            network['Containers'][name]={'Name':name}
            nodes[ctx].append({'metadata':{'name':name,'uid':'uid-'+name},'status':{
                'addresses':[{'type':'InternalIP','address':ipv4}],
                'conditions':[{'type':'Ready','status':'True'}]}})
        return containers,network,nodes

    def command(self, fixture):
        containers,network,nodes=fixture
        def run(*args,**kwargs):
            if args[:2]==('docker','inspect'):return json.dumps(containers)
            if args[:3]==('docker','network','inspect'):return json.dumps([network])
            if args[0]=='kubectl':return json.dumps({'items':nodes[args[2]]})
            self.fail('Unexpected command: '+repr(args))
        return run

    def plan(self, fixture, path):
        with patch.object(b,'command',side_effect=self.command(fixture)) as call, contextlib.redirect_stdout(io.StringIO()):
            result=b.plan_node_addresses('kind-narx-commerce','kind-mega-local',path)
        return result,call

    def test_plan_preserves_current_addresses_aliases_and_identity_without_network_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plan.json';result,call=self.plan(self.fixture(),path)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(len(result['nodes']),4)
            for node in result['nodes']:
                self.assertIn('--ip6',node['connect'])
                self.assertIn(node['ipv4'],node['connect'])
                self.assertIn('operator-alias',node['connect'])
                self.assertIn(node['name'],node['connect'])
                self.assertTrue(node['nodeUid'])
            self.assertFalse(any(c.args[:3] in [('docker','network','connect'),('docker','network','disconnect')] for c in call.call_args_list))

    def test_other_context_is_rejected_before_inspection(self):
        with patch.object(b,'command') as call,self.assertRaises(ValueError):
            b.plan_node_addresses('commerce-aws','kind-mega-local',Path('/tmp/unused-plan'))
        call.assert_not_called()

    def test_foreign_bridge_member_is_not_silently_ignored(self):
        fixture=self.fixture();fixture[1]['Containers']['other']={'Name':'unrelated-node'}
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.plan(fixture,Path(folder)/'plan')

    def test_duplicate_container_identity_is_rejected(self):
        fixture=self.fixture();fixture[0].append(fixture[0][0])
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.plan(fixture,Path(folder)/'plan')

    def test_wrong_cluster_owner_is_rejected(self):
        fixture=self.fixture();fixture[0][0]['Config']['Labels']['io.x-k8s.kind.cluster']='other'
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.plan(fixture,Path(folder)/'plan')

    def test_docker_kubernetes_address_drift_requires_recovery_first(self):
        fixture=self.fixture();fixture[2]['kind-mega-local'][0]['status']['addresses'][0]['address']='172.18.0.99'
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.plan(fixture,Path(folder)/'plan')

    def test_not_ready_node_and_outside_subnet_address_are_rejected(self):
        for field in ['readiness','address']:
            fixture=self.fixture()
            if field=='readiness':fixture[2]['kind-mega-local'][0]['status']['conditions'][0]['status']='False'
            else:fixture[0][0]['NetworkSettings']['Networks']['kind']['IPAddress']='192.0.2.8'
            with self.subTest(field=field),tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):
                self.plan(fixture,Path(folder)/'plan')

    def test_existing_plan_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plan';path.write_text('original')
            with self.assertRaises(FileExistsError):self.plan(self.fixture(),path)
            self.assertEqual(path.read_text(),'original')
