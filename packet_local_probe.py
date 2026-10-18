"""Optional packet-local opcode/cube probe based on an independently analyzed
reference implementation.  This is not a replacement for TCP reassembly.

It only feeds complete, validated candidate frames to CubeProtocol. It never
stores/exports traffic.  False positives are possible; use diagnostic counts.
"""
from collections import Counter
import struct
from aion_protocol_v11 import read_varint, SPAWN, REMOVE, OPEN_FINISHED, MAX_WIRE_FRAME

CANDIDATE_OPS = frozenset({SPAWN, REMOVE, OPEN_FINISHED, 0x3641, 0x3642, 0x8D6D})

class PacketLocalProbe:
    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.stats = Counter()

    def feed(self, data: bytes):
        if not data:
            return
        self.stats['segments_seen'] += 1
        emitted = set()
        # Search within packet boundaries only: candidate frames must be fully
        # present and contain a known opcode or a plausible LZ4 wrapper.
        # This avoids inventing stream boundaries during loss/retransmission.
        max_offset = min(len(data), 65536)
        for offset in range(max_offset):
            if data[offset] == 0:
                continue
            try:
                item = read_varint(data, offset)
            except ValueError:
                continue
            if item is None:
                continue
            encoded, width = item
            size = encoded + width - 4
            if not (width + 2 <= size <= MAX_WIRE_FRAME and offset + size <= len(data)):
                continue
            inner_at = offset + width
            if 0xf0 <= data[inner_at] <= 0xfe:
                inner_at += 1
            if inner_at + 2 > offset + size:
                continue
            opcode = struct.unpack_from('<H', data, inner_at)[0]
            if opcode not in CANDIDATE_OPS and opcode != 0xffff:
                continue
            key = (offset, size)
            if key in emitted:
                continue
            emitted.add(key)
            self.stats['candidate_frames'] += 1
            self.on_frame(bytes(data[offset:offset + size]))
