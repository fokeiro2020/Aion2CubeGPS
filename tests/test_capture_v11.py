import queue
import sys
import types
import unittest
from unittest.mock import patch
from aion_protocol_v11 import pack_frame, SPAWN
from network_capture import CaptureWorker, TCPFlow
from test_protocol_v11 import HB, CUBE_BODY

class _TCP: pass
class _IP: pass
class _IPv6: pass
class _Packet:
    def __init__(self, sport, dport, payload, seq=100):
        self.tcp = types.SimpleNamespace(sport=sport, dport=dport, payload=payload, seq=seq, flags='PA')
        self.ip = types.SimpleNamespace(src='192.0.2.1', dst='192.0.2.2')
    def haslayer(self, layer): return layer is _TCP
    def __getitem__(self, layer): return self.tcp
    def getlayer(self, layer): return self.ip if layer is _IP else None

class CaptureTests(unittest.TestCase):
    def setUp(self):
        mods = {'scapy': types.ModuleType('scapy'), 'scapy.layers': types.ModuleType('scapy.layers'),
                'scapy.layers.inet': types.ModuleType('scapy.layers.inet'),
                'scapy.layers.inet6': types.ModuleType('scapy.layers.inet6')}
        mods['scapy.layers.inet'].IP = _IP
        mods['scapy.layers.inet'].TCP = _TCP
        mods['scapy.layers.inet6'].IPv6 = _IPv6
        patcher = patch.dict(sys.modules, mods)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_ports_both_directions_and_no_outbound_decode(self):
        worker = CaptureWorker(queue.Queue(maxsize=300))
        msg = HB + pack_frame(SPAWN, CUBE_BODY)
        worker._packet(_Packet(13328, 55555, msg))
        worker._packet(_Packet(55555, 13328, msg))
        worker._packet(_Packet(13320, 55555, HB))
        worker._publish_stats()
        stats = worker.last_stats
        self.assertEqual(stats['tcp_segments'], 3)
        self.assertEqual(stats['cube_spawns'], 1)
        self.assertEqual(stats['port_13328_s2c_segments'], 1)
        self.assertEqual(stats['port_13328_c2s_segments'], 1)
        self.assertEqual(stats['port_13320_s2c_segments'], 1)
        self.assertEqual(stats['valid_heartbeats'], 2)
        self.assertNotIn('192.0.2.1', str(stats))

    def test_reassembler_handles_out_of_order_later_segments(self):
        got=[]
        flow=TCPFlow(got.append)
        msg=HB + pack_frame(SPAWN, CUBE_BODY) + HB
        flow.feed(100, msg[:9]); flow.feed(119, msg[19:]); flow.feed(109, msg[9:19])
        self.assertEqual(len(got), 3)
        self.assertEqual(flow.gap_segments, 1)
        flow.feed(100, msg)
        self.assertEqual(len(got), 3)

    def test_phase_counts(self):
        w=CaptureWorker(queue.Queue())
        w.set_phase('walking'); w._packet(_Packet(13328, 50000, HB))
        w.set_phase('near'); w._packet(_Packet(13328, 50000, HB, seq=111))
        w.set_phase('opening'); w._packet(_Packet(50000, 13328, b'hello'))
        w._publish_stats(); s=w.last_stats
        self.assertEqual(s['phase_walking_segments'], 1)
        self.assertEqual(s['phase_near_segments'], 1)
        self.assertEqual(s['phase_opening_segments'], 1)
        self.assertEqual(s['decoded_opcodes'], 2)

    def test_bpf(self):
        self.assertEqual(CaptureWorker(queue.Queue()).build_bpf(), 'tcp and (port 13328 or port 13320)')

if __name__ == '__main__': unittest.main()
