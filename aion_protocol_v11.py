"""Local-only Aion 2 (Global) stream and cube parser.

Independently implemented from published wire observations in dr89mh's
FINDINGS.md and gyu98-mun's protocol notes. Does not transmit game traffic.
The server protocol can change; live Global compatibility is unverified.
"""
from __future__ import annotations

from collections import Counter
import math
import struct
import time

# On-wire opcode order is little endian: 34 36 = 0x3634.
HEARTBEAT = 0x3600
SPAWN = 0x3634
REMOVE = 0x3635
OPEN_STARTED = 0x3638
OPEN_FINISHED = 0x363A
MAP_LOAD = 0x3621
CHARACTER_NAME = 0x3633
CAST_POSITION = 0x382A
ALT_SPAWN = 0x3641
ALT_REMOVE = 0x3642
GATHER_COMPLETE = 0x8D6D
MOVE_OPS = frozenset({0x382A, 0x382B, 0x382C, 0x3804})
ZONE_TELEPORT = 0x561E
MAX_WIRE_FRAME = 1024 * 1024
MAX_BUFFER = 2 * MAX_WIRE_FRAME
MAX_PLAIN = 8 * 1024 * 1024
VERIFIED_TEMPLATES = frozenset({1200039, 1200041})  # verified from Oct 13 Verteron captures
HEARTBEAT_PREFIX = bytes.fromhex('0e 00 36')
# These are documented template candidates, not all independently verified.
CUBE_TEMPLATES = {
    1000295, 1000548, 1000556, 1000568, 1000566, 1000567,
    1100056, 1100094, 1200018, 1200036, 1200037, 1200039,
    1200040, 1200041, 1200667, 1200707, 1201054, 1201055,
    1300081, 1300082, 1300754, 1301199, 1301200, 1401335,
    1401336, 3682560, 1201502, 1201505, 1300083, 1301242, 1301245,
}


def read_varint(data: bytes | bytearray, offset=0):
    """(value, encoded width), None if incomplete, ValueError if malformed."""
    value = 0
    for i in range(5):
        if offset + i >= len(data):
            return None
        b = data[offset + i]
        value |= (b & 0x7f) << (7 * i)
        if not b & 0x80:
            return value, i + 1
    raise ValueError('varint longer than five bytes')


def pack_varint(value: int):
    if value < 0:
        raise ValueError('negative')
    out = bytearray()
    while value >= 128:
        out.append((value & 0x7f) | 0x80)
        value >>= 7
    return bytes(out + bytes((value,)))


def pack_frame(opcode: int, payload: bytes = b'', *, flag=None) -> bytes:
    """Build a *synthetic* game frame for offline unit tests."""
    inner = (bytes((flag,)) if flag is not None else b'') + struct.pack('<H', opcode) + payload
    # The game defines total wire size as `encoded_length + varint_width - 4`.
    # Therefore encoded_length = len(body) + 4 (prefix bytes cancel).
    return pack_varint(len(inner) + 4) + inner


def plausible_heartbeat(data, start):
    if len(data) < start + 11 or data[start:start + 3] != HEARTBEAT_PREFIX:
        return False
    timestamp_ms = struct.unpack_from('<Q', data, start + 3)[0]
    # Meaningful date check prevents matching a random 0E 00 36 substring.
    return 1_700_000_000_000 <= timestamp_ms <= 2_400_000_000_000


class AlignedFrameStream:
    """Decode complete *wire frames*, retaining their varint prefixes.

    Synchronize at a timestamp-validated 11-byte heartbeat. This allows
    starting capture after the TCP connection is already established.
    """

    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.buffer = bytearray()
        self.synced = False
        self.stats = Counter()

    def _seek_heartbeat(self):
        offset = 0
        while True:
            idx = self.buffer.find(HEARTBEAT_PREFIX, offset)
            if idx < 0:
                # Retain at most 10 trailing bytes of an incomplete heartbeat.
                keep = min(10, len(self.buffer))
                self.stats['sync_discarded_bytes'] += len(self.buffer) - keep
                del self.buffer[:len(self.buffer) - keep]
                return False
            if len(self.buffer) < idx + 11:
                if idx:
                    self.stats['sync_discarded_bytes'] += idx
                    del self.buffer[:idx]
                return False
            if plausible_heartbeat(self.buffer, idx):
                self.stats['sync_discarded_bytes'] += idx
                del self.buffer[:idx]
                self.synced = True
                self.stats['stream_syncs'] += 1
                return True
            offset = idx + 1

    def feed(self, chunk: bytes):
        if not chunk:
            return
        self.buffer.extend(chunk)
        if len(self.buffer) > MAX_BUFFER:
            self.stats['buffer_overflows'] += 1
            self.synced = False
            self.buffer = self.buffer[-min(len(self.buffer), 8192):]
        while self.buffer:
            if not self.synced and not self._seek_heartbeat():
                return
            if not self.buffer:
                return
            if self.buffer[0] == 0:
                self.stats['padding_bytes'] += 1
                del self.buffer[0]
                continue
            try:
                info = read_varint(self.buffer)
            except ValueError:
                self.stats['bad_frame_headers'] += 1
                self.stats['frame_resyncs'] += 1
                self.synced = False
                del self.buffer[0]
                continue
            if info is None:
                return
            encoded, prefix_len = info
            total = encoded + prefix_len - 4  # INCLUDE the prefix: v10 did not.
            if total < prefix_len + 2 or total > MAX_WIRE_FRAME:
                self.stats['bad_frame_headers'] += 1
                self.stats['frame_resyncs'] += 1
                self.synced = False
                del self.buffer[0]
                continue
            if len(self.buffer) < total:
                return
            frame = bytes(self.buffer[:total])
            del self.buffer[:total]
            self.stats['framed_messages'] += 1
            self.on_frame(frame)


def iter_nested_frames(data: bytes):
    """Yield complete wire frames from a decompressed LZ4 block."""
    off = 0
    while off < len(data):
        if data[off] == 0:
            off += 1
            continue
        try:
            result = read_varint(data, off)
        except ValueError:
            return
        if result is None:
            return
        encoded, width = result
        size = encoded + width - 4
        if size < width + 2 or size > MAX_WIRE_FRAME or off + size > len(data):
            return
        yield data[off:off + size]
        off += size


def valid_xyz(xyz):
    # Large negative coordinates are valid in the game.
    return len(xyz) == 3 and all(math.isfinite(n) and abs(n) < 1_000_000 for n in xyz)


class CubeProtocol:
    def __init__(self, emit, character_name=''):
        self.emit = emit
        self.character_name = character_name.strip().casefold()
        self.player_id = None
        self.cubes = {}
        self.player_xyz = None
        self.stats = Counter()
        self.opcodes = Counter()
        self.opcodes_by_phase = {}
        self.opcodes_by_port = {}
        self.templates = Counter()

    def decode(self, frame: bytes, port=13328, phase='unlabeled', depth=0):
        if depth > 2:
            self.stats['nested_depth_rejected'] += 1
            return
        info = read_varint(frame)
        if info is None:
            self.stats['bad_frames'] += 1
            return
        encoded, prefix = info
        if encoded + prefix - 4 != len(frame):
            self.stats['bad_frames'] += 1
            return
        offset = prefix
        if len(frame) <= offset + 1:
            self.stats['bad_frames'] += 1
            return
        if 0xf0 <= frame[offset] <= 0xfe:
            offset += 1
            self.stats['flagged_frames'] += 1
        if frame[offset:offset + 2] == b'\xff\xff':
            if len(frame) < offset + 6:
                self.stats['lz4_errors'] += 1
                return
            raw_size = struct.unpack_from('<I', frame, offset + 2)[0]
            self.stats['lz4_bundles'] += 1
            if not 0 < raw_size <= MAX_PLAIN:
                self.stats['lz4_bad_sizes'] += 1
                return
            try:
                import lz4.block
                decompressed = lz4.block.decompress(frame[offset + 6:], uncompressed_size=raw_size)
                if len(decompressed) != raw_size:
                    raise ValueError('decompressed size mismatch')
                self.stats['lz4_ok'] += 1
                for nested in iter_nested_frames(decompressed):
                    self.decode(nested, port=port, phase=phase, depth=depth + 1)
            except Exception:
                # Do not log bytes or private game contents.
                self.stats['lz4_errors'] += 1
            return
        op = struct.unpack_from('<H', frame, offset)[0]
        body = frame[offset + 2:]
        self.opcodes[op] += 1
        self.opcodes_by_port.setdefault(port, Counter())[op] += 1
        self.opcodes_by_phase.setdefault(phase, Counter())[op] += 1
        self.stats['decoded_opcodes'] += 1
        if op == HEARTBEAT:
            if len(body) >= 8 and plausible_heartbeat(frame, 0):
                self.stats['valid_heartbeats'] += 1
            return
        if op == SPAWN:
            self._spawn(body)
        elif op in (REMOVE, OPEN_FINISHED):
            self._remove(body, op)
        elif op == MAP_LOAD:
            self.stats['map_loads'] += 1
            self.cubes.clear()
            self.player_id = None
            self.player_xyz = None
            self.emit({'type': 'zone_reset'})
        elif op == CHARACTER_NAME:
            self._own_character(body)
        elif op == CAST_POSITION:
            self._cast_position(body)
            self._movement_position(body, op)
        elif op in MOVE_OPS or 0x3710 <= op <= 0x3750:
            self._movement_position(body, op)
        elif op == ALT_SPAWN:
            self._alt_spawn(body)
        elif op == ALT_REMOVE:
            self._remove(body, op)
        elif op == GATHER_COMPLETE:
            self._harvest_completed()
        elif op == ZONE_TELEPORT:
            self._teleport_position(body)

    def _spawn(self, body):
        self.stats['spawn_opcodes'] += 1
        info = read_varint(body)
        if info is None:
            self.stats['short_spawn_messages'] += 1
            return
        entity, offset = info
        # Publicly verified wire: entity varint, object kind u16 (4),
        # template u32 LE, x/y/z f32 LE.
        if len(body) < offset + 18:
            self.stats['short_spawn_messages'] += 1
            return
        kind, template = struct.unpack_from('<HI', body, offset)
        if kind != 4:
            return
        self.stats['object_spawns'] += 1
        self.templates[template] += 1
        if template not in CUBE_TEMPLATES:
            return
        xyz = struct.unpack_from('<fff', body, offset + 6)
        if not valid_xyz(xyz):
            self.stats['invalid_cube_coordinates'] += 1
            return
        self.stats['known_cube_templates'] += 1
        self.stats['cube_spawns'] += 1
        if template in VERIFIED_TEMPLATES:
            self.stats['verified_cube_spawns'] += 1
        else:
            self.stats['candidate_cube_spawns'] += 1
        self.cubes[entity] = (template, xyz)
        self.emit({'type':'cube', 'action':'spawn', 'id':entity,
                   'template':template, 'xyz':xyz,
                   'confidence':'published-verified' if template in VERIFIED_TEMPLATES else 'candidate'})

    def _remove(self, body, op):
        self.stats['remove_opcodes' if op in (REMOVE, ALT_REMOVE) else 'open_finished_opcodes'] += 1
        info = read_varint(body)
        if info is None:
            return
        entity, _ = info
        if entity in self.cubes:
            self.cubes.pop(entity, None)
            self.stats['cube_removals'] += 1
            self.emit({'type':'cube', 'action':'remove', 'id':entity})

    def _own_character(self, body):
        # Aion2 core observed [entity-varint][five-byte preamble]
        # [name-length varint][UTF8 nickname]. Only lock an EXACT nickname.
        if not self.character_name:
            return
        idv = read_varint(body)
        if idv is None:
            return
        entity, used = idv
        at = used + 5
        if at >= len(body):
            return
        length = read_varint(body, at)
        if length is None:
            return
        count, width = length
        if not 1 <= count <= 71 or at + width + count > len(body):
            return
        try:
            name = body[at + width:at + width + count].decode('utf-8').casefold()
        except UnicodeDecodeError:
            return
        if name == self.character_name:
            self.player_id = entity
            self.stats['player_identity_locked'] += 1
            self.emit({'type': 'info', 'text':'Character matched for position tracking'})

    def _cast_position(self, body):
        # Public observation: a recurring CAST_POSITION suffix has
        # [same entity varint][01 00][x,y,z floats], though not every
        # packet or every kind of spell uses that suffix.
        if self.player_id is None:
            return
        entity_token = pack_varint(self.player_id)
        suffix_size = len(entity_token) + 2 + 12
        if len(body) < suffix_size:
            return
        suffix = body[-suffix_size:]
        if not suffix.startswith(entity_token + b'\x01\x00'):
            return
        xyz = struct.unpack_from('<fff', suffix, len(entity_token) + 2)
        if valid_xyz(xyz):
            self.stats['player_positions'] += 1
            self.player_xyz = xyz
            self.emit({'type':'player', 'xyz':xyz})

    def _alt_spawn(self, body):
        """Experimental secondary entity spawn layout from user-supplied radar."""
        self.stats['alternative_spawn_opcodes'] += 1
        info = read_varint(body)
        if info is None:
            return
        eid, off = info
        if eid <= 100 or len(body) < off + 23:
            return
        template = struct.unpack_from('<I', body, off + 5)[0]
        if template not in CUBE_TEMPLATES:
            return
        xyz = struct.unpack_from('<fff', body, off + 11)
        if not valid_xyz(xyz):
            return
        self._register_cube(eid, template, xyz, source='secondary-candidate')

    def _register_cube(self, entity, template, xyz, source='candidate'):
        self.stats['known_cube_templates'] += 1
        self.stats['cube_spawns'] += 1
        if template in VERIFIED_TEMPLATES:
            self.stats['verified_cube_spawns'] += 1
        else:
            self.stats['candidate_cube_spawns'] += 1
        self.cubes[entity] = (template, xyz)
        self.emit({'type': 'cube', 'action': 'spawn', 'id': entity,
                   'template': template, 'xyz': xyz, 'confidence': source})

    def _harvest_completed(self):
        """Only retire a tracked cube if player's identity/position is known."""
        self.stats['gather_complete_opcodes'] += 1
        if self.player_id is None or self.player_xyz is None:
            return
        px, py, pz = self.player_xyz
        for entity, (_template, xyz) in list(self.cubes.items()):
            if sum((a-b)**2 for a, b in zip((px, py, pz), xyz)) <= 600 ** 2:
                self.cubes.pop(entity, None)
                self.stats['cube_removals'] += 1
                self.emit({'type': 'cube', 'action': 'remove', 'id': entity})

    def _movement_position(self, body, opcode):
        """Do not guess the player identity from arbitrary movement messages."""
        if self.player_id is None:
            return
        info = read_varint(body)
        if info is None:
            return
        eid, off = info
        if eid != self.player_id:
            return
        xyz = None
        if opcode in MOVE_OPS and len(body) >= off + 12:
            xyz = struct.unpack_from('<fff', body, len(body)-12)
        elif 0x3710 <= opcode <= 0x3750 and len(body) >= off + 14:
            xyz = struct.unpack_from('<fff', body, off + 2)
        if xyz is not None and valid_xyz(xyz):
            self.player_xyz = xyz
            self.stats['player_positions'] += 1
            self.stats['movement_positions'] += 1
            self.emit({'type': 'player', 'xyz': xyz})

    def _teleport_position(self, body):
        if self.player_id is None or len(body) < 29:
            return
        xyz = struct.unpack_from('<fff', body, 17)
        if valid_xyz(xyz):
            self.player_xyz = xyz
            self.stats['player_positions'] += 1
            self.stats['teleport_positions'] += 1
            self.emit({'type': 'player', 'xyz': xyz})
