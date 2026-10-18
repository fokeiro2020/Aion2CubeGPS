"""Tests include real byte examples transcribed from public research (not private user packets)."""
import queue
import struct
import unittest

from aion_protocol_v11 import (
    AlignedFrameStream, CubeProtocol, HEARTBEAT, SPAWN, REMOVE, OPEN_FINISHED,
    pack_frame, read_varint, pack_varint, plausible_heartbeat,
)

HB = bytes.fromhex('0e 00 36 b9 38 96 34 a1 01 00 00')
# Verified Verteron cube entity 65509, template 1200039 and coordinates.
CUBE_BODY = bytes.fromhex('e5 ff 03 04 00 a7 4f 12 00 00 1d 44 c7 80 a5 f6 47 00 64 71 46')
REMOVE_BODY = bytes.fromhex('e5 ff 03 04 03 00')
FINISH_BODY = bytes.fromhex('e5 ff 03 dc 47 01 00 00 00 23 c5 9a 25')


class ProtocolTests(unittest.TestCase):
    def build(self):
        result = []
        p = CubeProtocol(result.append)
        decoder = AlignedFrameStream(p.decode)
        return result, p, decoder

    def test_published_heartbeat_is_timestamp_valid(self):
        self.assertTrue(plausible_heartbeat(HB, 0))
        self.assertEqual(read_varint(HB), (14, 1))
        self.assertEqual(len(HB), 14 + 1 - 4)

    def test_sync_with_midstream_garbage_and_split_heartbeat(self):
        events, p, stream = self.build()
        stream.feed(b'garbage' + HB[:4])
        self.assertEqual(stream.stats['stream_syncs'], 0)
        stream.feed(HB[4:] + HB)
        self.assertEqual(stream.stats['stream_syncs'], 1)
        self.assertEqual(p.stats['valid_heartbeats'], 2)
        self.assertEqual(stream.stats['framed_messages'], 2)
        self.assertGreaterEqual(stream.stats['sync_discarded_bytes'], 7)

    def test_cube_spawn_real_published_layout(self):
        events, p, stream = self.build()
        stream.feed(HB + pack_frame(SPAWN, CUBE_BODY))
        detected = [e for e in events if e['type'] == 'cube']
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0]['id'], 65509)
        self.assertEqual(detected[0]['template'], 1200039)
        self.assertAlmostEqual(detected[0]['xyz'][0], -50205.0, places=1)
        self.assertAlmostEqual(detected[0]['xyz'][1], 126283.0, places=1)
        self.assertAlmostEqual(detected[0]['xyz'][2], 15449.0, places=1)
        self.assertEqual(p.stats['known_cube_templates'], 1)

    def test_real_removal_and_open_finished(self):
        events, p, stream = self.build()
        stream.feed(HB + pack_frame(SPAWN, CUBE_BODY) + pack_frame(OPEN_FINISHED, FINISH_BODY))
        self.assertEqual([e['action'] for e in events if e['type'] == 'cube'], ['spawn', 'remove'])
        stream.feed(pack_frame(SPAWN, CUBE_BODY) + pack_frame(REMOVE, REMOVE_BODY))
        self.assertEqual(p.stats['cube_removals'], 2)

    def test_multiple_frames_and_two_byte_length(self):
        events, p, stream = self.build()
        big = pack_frame(0x4455, b'\x11' * 290)
        self.assertEqual(len(pack_varint(296)), 2)
        for chunk in [HB, big[:1], big[1:200], big[200:] + HB]:
            stream.feed(chunk)
        self.assertEqual(p.opcodes[0x4455], 1)
        self.assertEqual(p.stats['valid_heartbeats'], 2)

    def test_flagged_opcode(self):
        events, p, stream = self.build()
        stream.feed(HB + pack_frame(0x6655, b'hello', flag=0xF0))
        self.assertEqual(p.opcodes[0x6655], 1)
        self.assertEqual(p.stats['flagged_frames'], 1)

    def test_lz4_embedded_frames(self):
        import lz4.block
        events, p, stream = self.build()
        inner = pack_frame(SPAWN, CUBE_BODY) + pack_frame(0x1234, b'abc')
        comp = lz4.block.compress(inner, store_size=False)
        outer = pack_frame(0xFFFF, struct.pack('<I', len(inner)) + comp)
        stream.feed(HB + outer)
        self.assertEqual(p.stats['lz4_bundles'], 1)
        self.assertEqual(p.stats['lz4_ok'], 1)
        self.assertEqual(p.stats['cube_spawns'], 1)
        self.assertEqual(p.opcodes[0x1234], 1)

    def test_no_false_cube_from_other_template(self):
        events, p, stream = self.build()
        body = bytearray(CUBE_BODY)
        struct.pack_into('<I', body, 5, 987654321)
        stream.feed(HB + pack_frame(SPAWN, bytes(body)))
        self.assertEqual(p.stats['cube_spawns'], 0)
        self.assertEqual(p.stats['object_spawns'], 1)

    def test_no_false_cube_from_wrong_object_kind(self):
        events, p, stream = self.build()
        body = bytearray(CUBE_BODY)
        struct.pack_into('<H', body, 3, 12)
        stream.feed(HB + pack_frame(SPAWN, bytes(body)))
        self.assertEqual(p.stats['cube_spawns'], 0)

    def test_name_exact_match_then_cast_position(self):
        events = []
        p = CubeProtocol(events.append, 'Mira')
        stream = AlignedFrameStream(p.decode)
        nick = pack_varint(9180) + b'abcde' + pack_varint(4) + b'Mira'
        pos = b'not-a-real-game-preamble' + pack_varint(9180) + b'\x01\x00' + struct.pack('<fff', 5000., -1000., 50.)
        stream.feed(HB + pack_frame(0x3633, nick) + pack_frame(0x382A, pos))
        self.assertEqual(p.player_id, 9180)
        self.assertEqual([e['xyz'] for e in events if e['type'] == 'player'], [(5000., -1000., 50.)])

    def test_no_player_position_from_unidentified_entity(self):
        events, p, stream = self.build()
        stream.feed(HB + pack_frame(0x382A, pack_varint(9180) + b'\x01\x00' + struct.pack('<fff', 1,2,3)))
        self.assertFalse(any(e['type'] == 'player' for e in events))

    def test_partial_cubes_not_reported(self):
        events, p, stream = self.build()
        stream.feed(HB + pack_frame(SPAWN, CUBE_BODY[:-10]))
        self.assertEqual(p.stats['cube_spawns'], 0)

    def test_padding_between_frames(self):
        events, p, stream = self.build()
        stream.feed(HB + b'\x00\x00' + HB)
        self.assertEqual(p.stats['valid_heartbeats'], 2)
        self.assertEqual(stream.stats['padding_bytes'], 2)

    def test_sync_resets_on_invalid_size(self):
        events, p, stream = self.build()
        stream.feed(HB + b'\x01' + HB)
        self.assertEqual(p.stats['valid_heartbeats'], 2)
        self.assertEqual(stream.stats['stream_syncs'], 2)


if __name__ == '__main__': unittest.main()
