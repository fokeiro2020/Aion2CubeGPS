import struct
import unittest
from aion_protocol_v11 import CubeProtocol, pack_frame, SPAWN, REMOVE, pack_varint
from packet_local_probe import PacketLocalProbe
from test_protocol_v11 import CUBE_BODY, HB

class HybridTests(unittest.TestCase):
    def test_packet_local_spawn_without_heartbeat(self):
        events=[]
        proto=CubeProtocol(events.append)
        probe=PacketLocalProbe(proto.decode)
        probe.feed(pack_frame(SPAWN,CUBE_BODY))
        self.assertEqual(proto.stats['cube_spawns'],1)
        self.assertEqual(events[0]['id'],65509)

    def test_probe_ignores_wrong_template_and_arbitrary_data(self):
        events=[]; proto=CubeProtocol(events.append); probe=PacketLocalProbe(proto.decode)
        altered=bytearray(CUBE_BODY)
        struct.pack_into('<I',altered,5,99999999)
        probe.feed(b'abc'+pack_frame(SPAWN,bytes(altered))+b'xyz')
        self.assertFalse([e for e in events if e.get('type')=='cube'])

    def test_probe_finds_complete_frame_inside_segment(self):
        events=[]; proto=CubeProtocol(events.append); probe=PacketLocalProbe(proto.decode)
        probe.feed(b'junk-prefix'+pack_frame(SPAWN,CUBE_BODY)+b'junk-suffix')
        self.assertEqual(proto.stats['cube_spawns'], 1)

    def test_probe_handles_split_frame_conservatively(self):
        events=[]; proto=CubeProtocol(events.append); probe=PacketLocalProbe(proto.decode)
        msg=pack_frame(SPAWN,CUBE_BODY)
        probe.feed(msg[:12]); probe.feed(msg[12:])
        self.assertFalse(events)

    def test_secondary_spawn_layout(self):
        events=[]; p=CubeProtocol(events.append)
        # varint entity + five unspecified bytes + template + two bytes + xyz
        body=pack_varint(87654)+bytes(5)+struct.pack('<I',1200039)+bytes(2)+struct.pack('<fff',1000.,2000.,3000.)
        p.decode(pack_frame(0x3641, body))
        self.assertEqual(events[0]['template'], 1200039)
        self.assertEqual(events[0]['xyz'], (1000.,2000.,3000.))

    def test_gather_without_player_does_not_remove(self):
        events=[]; p=CubeProtocol(events.append)
        p.decode(pack_frame(SPAWN,CUBE_BODY))
        p.decode(pack_frame(0x8d6d,b''))
        self.assertEqual(p.stats['cube_removals'],0)

    def test_gather_with_confirmed_player_position_removes_nearby(self):
        events=[]; p=CubeProtocol(events.append)
        p.decode(pack_frame(SPAWN,CUBE_BODY))
        xyz = p.cubes[65509][1]
        p.player_id=123; p.player_xyz=xyz
        p.decode(pack_frame(0x8d6d,b''))
        self.assertEqual(p.stats['cube_removals'],1)

    def test_movement_rejects_foreign_entity(self):
        events=[]; p=CubeProtocol(events.append); p.player_id=1234
        msg=pack_varint(6666)+b'prefix'+struct.pack('<fff',2.,3.,4.)
        p.decode(pack_frame(0x382b,msg))
        self.assertFalse([e for e in events if e['type']=='player'])

    def test_movement_for_confirmed_id(self):
        events=[]; p=CubeProtocol(events.append); p.player_id=1234
        msg=pack_varint(1234)+b'prefix'+struct.pack('<fff',2000.,3000.,4000.)
        p.decode(pack_frame(0x382b,msg))
        self.assertEqual(p.player_xyz,(2000.,3000.,4000.))
        self.assertEqual(p.stats['movement_positions'],1)

if __name__=='__main__': unittest.main()
