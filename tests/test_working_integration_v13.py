import unittest,sys,struct,queue
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

try:
    import scapy.all
except ImportError:
    import types
    scapy=types.ModuleType('scapy'); all_mod=types.ModuleType('scapy.all')
    all_mod.sniff=lambda **kwargs: None
    all_mod.IP=object(); all_mod.TCP=object()
    all_mod.PcapReader=lambda _: None
    scapy.all=all_mod
    sys.modules['scapy']=scapy; sys.modules['scapy.all']=all_mod

from working_network_capture import WorkingCapture,EmbeddedNetworkRadar
from working_aion_radar import RadarState,PureStreamEngine


def varint(n):
    b=[]
    while n>127:
        b.append((n&127)|128);n>>=7
    return bytes(b+[n])

def packet(opcode,payload):
    body=struct.pack('<H',opcode)+payload
    return varint(len(body)+4)+body

class TestWorkingRadarIntegration(unittest.TestCase):
    def setUp(self):
        self.q=queue.Queue(maxsize=500)
        self.worker=WorkingCapture(self.q,'TestChar')
        # Deterministic tests must not start the real Windows alert/beep daemon.
        self.worker.state.sound_enabled=False
    def drain(self):
        out=[]
        while not self.q.empty():out.append(self.q.get_nowait())
        return out
    def test_user_source_is_preserved(self):
        self.assertTrue(issubclass(EmbeddedNetworkRadar, object))
        self.assertIsInstance(self.worker.engine,PureStreamEngine)
        self.assertEqual(self.worker.state.target_char_name,'TestChar')
        self.assertFalse(self.worker.state.extrapolation_enabled)
    def test_spawn_and_removal_go_to_app(self):
        eid=5033
        objid=1200039
        payload=varint(eid)+b'\0\0'+struct.pack('<Ifff',objid,2500.,500.,900.)
        self.worker.feed_test_payload('1.2.3.4',13328,'10.0.0.10',50111,packet(0x3634,payload))
        events=self.drain()
        cubes=[v for v in events if v.get('type')=='cube']
        self.assertEqual(len(cubes),1)
        self.assertEqual(cubes[0]['xyz'],(2500.,500.,900.))
        self.assertEqual(cubes[0]['source'],'working')
        self.worker.feed_test_payload('1.2.3.4',13328,'10.0.0.10',50111,packet(0x3635,varint(eid)))
        events=self.drain()
        self.assertEqual([v['action'] for v in events if v.get('type')=='cube'],['remove'])
    def test_player_location_propagates(self):
        eid=7003
        self.worker.state.set_player_id(eid)
        self.worker.feed_test_payload('1.2.3.4',13328,'10.0.0.10',50111,
           packet(0x382B,varint(eid)+b'\0\0'+struct.pack('<fff',1200.,2300.,400.)))
        events=self.drain()
        self.assertIn((1200.,2300.,400.),[e['xyz'] for e in events if e.get('type')=='player'])
    def test_port_filter_and_stats(self):
        self.assertIn('port 13320',self.worker.build_bpf())
        self.assertIn('port 13328',self.worker.build_bpf())
        self.worker.set_phase('near')
        self.worker._publish_stats()
        items=self.drain()
        self.assertEqual(items[-1]['stats']['active_phase'],'near')
        self.assertTrue(items[-1]['stats']['no_raw_packet_storage'])

if __name__=='__main__':unittest.main()
