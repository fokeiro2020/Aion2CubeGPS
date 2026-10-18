"""Aion 2 Global passive Npcap capture, stream alignment and diagnostics.

Server-to-client bytes only enter the decoder. The network layer never
transmits packets, uploads raw captures, or stores player content on disk.
"""
from __future__ import annotations

import queue
import threading
from collections import Counter

from packet_local_probe import PacketLocalProbe

from aion_protocol_v11 import (
    AlignedFrameStream, CubeProtocol, HEARTBEAT, SPAWN, REMOVE,
    read_varint, pack_varint, pack_frame, CUBE_TEMPLATES,
)

SERVER_PORTS = (13328, 13320)
MAX_PENDING = 1024 * 1024


class TCPFlow:
    """Reassemble segments by TCP sequence, drop retransmissions, hold gaps."""

    def __init__(self, on_frame):
        self.next_seq = None
        self.fragments = {}
        self.decoder = AlignedFrameStream(on_frame)
        self.gap_segments = 0
        self.retransmits = 0
        self.pending_overflows = 0

    def feed(self, seq, data):
        if not data:
            return
        if self.next_seq is None:
            self.next_seq = seq
        if seq + len(data) <= self.next_seq:
            self.retransmits += 1
            return
        if seq > self.next_seq:
            self.gap_segments += 1
            # Preserve the longest segment when retransmissions overlap.
            old = self.fragments.get(seq, b'')
            if len(data) > len(old):
                self.fragments[seq] = data
            if sum(map(len, self.fragments.values())) > MAX_PENDING:
                self.fragments.clear()
                self.pending_overflows += 1
            return
        if seq < self.next_seq:
            data = data[self.next_seq - seq:]
        self.decoder.feed(data)
        self.next_seq += len(data)
        while self.fragments:
            first = min(self.fragments)
            if first > self.next_seq:
                break
            chunk = self.fragments.pop(first)
            if first + len(chunk) <= self.next_seq:
                self.retransmits += 1
                continue
            self.decoder.feed(chunk[self.next_seq - first:])
            self.next_seq = first + len(chunk)


class CaptureWorker:
    def __init__(self, out: queue.Queue, character_name='', server_ports=None, server_host=None):
        self.out = out
        self.stop_event = threading.Event()
        self.server_ports = tuple(server_ports or SERVER_PORTS)
        self.server_host = server_host
        self.thread = None
        self.protocol = CubeProtocol(self._emit, character_name)
        self.fallback = CubeProtocol(self._emit_fallback, character_name)
        self.local_probe = PacketLocalProbe(lambda frame: self.fallback.decode(frame))
        self.flows = {}
        self.packets = 0
        self.bytes = 0
        self.phase = 'unlabeled'
        self.phase_segments = Counter()
        self.port_direction_segments = Counter()
        self.port_direction_bytes = Counter()
        self.last_stats = {}
        self.server_syns = Counter()
        self.all_stats = Counter()

    def _emit(self, event):
        try:
            self.out.put_nowait(event)
        except queue.Full:
            # Never block the packet-capture callback if the UI is busy.
            self.all_stats['dropped_ui_events'] += 1

    def _emit_fallback(self, event):
        # A packet-local probe can be wrong. Only permit fully validated
        # template-matched spawn and known-entity removal events.
        if event.get('type') != 'cube':
            return
        self._emit(dict(event, source='packet-local'))

    def set_phase(self, phase):
        if phase not in {'unlabeled','walking','near','opening'}:
            raise ValueError('Invalid capture phase')
        self.phase = phase

    def _packet(self, packet):
        from scapy.layers.inet import IP, TCP
        from scapy.layers.inet6 import IPv6
        if not packet.haslayer(TCP):
            return
        tcp = packet[TCP]
        src_port, dst_port = int(tcp.sport), int(tcp.dport)
        if src_port in self.server_ports:
            port, direction = src_port, 's2c'
        elif dst_port in self.server_ports:
            port, direction = dst_port, 'c2s'
        else:
            return
        ip = packet.getlayer(IP) or packet.getlayer(IPv6)
        if ip is None:
            return
        server_ip = str(ip.src if direction == 's2c' else ip.dst)
        if self.server_host and server_ip != self.server_host:
            return
        data = bytes(tcp.payload)
        flags = str(tcp.flags)
        key = (str(ip.src), src_port, str(ip.dst), dst_port)
        if direction == 's2c' and 'S' in flags:
            self.server_syns[port] += 1
            self.flows.pop(key, None)
        if direction == 's2c' and ('F' in flags or 'R' in flags):
            self.flows.pop(key, None)
        if not data:
            return
        self.packets += 1
        self.bytes += len(data)
        self.port_direction_segments[(port, direction)] += 1
        self.port_direction_bytes[(port, direction)] += len(data)
        self.phase_segments[(self.phase, port, direction)] += 1
        if direction == 's2c':
            flow = self.flows.get(key)
            if flow is None:
                flow = TCPFlow(lambda frame, p=port: self.protocol.decode(frame, port=p, phase=self.phase))
                self.flows[key] = flow
            flow.feed(int(tcp.seq), data)
            # Secondary packet-local parser complements heartbeat sync for
            # self-contained frames; it is deliberately not authoritative.
            self.local_probe.feed(data)
        if self.packets % 100 == 0:
            self._emit({'type': 'packets', 'count': self.packets})
            self._publish_stats()

    def _publish_stats(self):
        totals = Counter()
        for flow in self.flows.values():
            totals.update(flow.decoder.stats)
            totals['tcp_gaps_detected'] += flow.gap_segments
            totals['tcp_retransmissions_skipped'] += flow.retransmits
            totals['pending_segment_overflows'] += flow.pending_overflows
        p = self.protocol
        diag = {
            'decoder_version': 'v12/hybrid-heartbeat-plus-local-probe',
            'tcp_segments': self.packets,
            'tcp_payload_bytes': self.bytes,
            'active_inbound_flows': len(self.flows),
            'current_phase': self.phase,
            'decoded_opcodes': p.stats['decoded_opcodes'],
            'framed_messages': totals['framed_messages'],
            'valid_heartbeats': p.stats['valid_heartbeats'],
            'stream_syncs': totals['stream_syncs'],
            'sync_discarded_bytes': totals['sync_discarded_bytes'],
            'framing_resyncs': totals['frame_resyncs'],
            'framing_buffered_bytes': sum(len(f.decoder.buffer) for f in self.flows.values()),
            'unverified_framing_warning': ('No timestamp-validated heartbeat acquired' if not totals['stream_syncs'] else 'none'),
            'tcp_gaps_detected': totals['tcp_gaps_detected'],
            'tcp_retransmissions_skipped': totals['tcp_retransmissions_skipped'],
            'lz4_bundles': p.stats['lz4_bundles'],
            'lz4_ok': p.stats['lz4_ok'],
            'lz4_errors': p.stats['lz4_errors'],
            'spawn_opcodes': p.stats['spawn_opcodes'],
            'object_spawns': p.stats['object_spawns'],
            'known_cube_templates': p.stats['known_cube_templates'],
            'cube_spawns': p.stats['cube_spawns'],
            'verified_cube_spawns': p.stats['verified_cube_spawns'],
            'candidate_cube_spawns': p.stats['candidate_cube_spawns'],
            'cube_removals': p.stats['cube_removals'],
            'alternative_spawn_opcodes': p.stats['alternative_spawn_opcodes'],
            'gather_complete_opcodes': p.stats['gather_complete_opcodes'],
            'movement_positions': p.stats['movement_positions'],
            'teleport_positions': p.stats['teleport_positions'],
            'packet_local_candidate_frames': self.local_probe.stats['candidate_frames'],
            'packet_local_cube_spawns': self.fallback.stats['cube_spawns'],
            'packet_local_cube_removals': self.fallback.stats['cube_removals'],
            'player_identity_locked': p.stats['player_identity_locked'],
            'player_positions': p.stats['player_positions'],
            'top_opcodes': [f'0x{k:04X}:{n}' for k,n in p.opcodes.most_common(30)],
            'distinct_opcodes': len(p.opcodes),
            'top_templates': [f'{k}:{n}' for k,n in p.templates.most_common(15)],
        }
        for port in self.server_ports:
            for direction in ('s2c', 'c2s'):
                label = f'port_{port}_{direction}'
                diag[f'{label}_segments'] = self.port_direction_segments[(port,direction)]
                diag[f'{label}_bytes'] = self.port_direction_bytes[(port,direction)]
            port_flows = [f for k, f in self.flows.items() if k[1] == port]
            diag[f'port_{port}_stream_syncs'] = sum(f.decoder.stats['stream_syncs'] for f in port_flows)
            diag[f'port_{port}_frames'] = sum(f.decoder.stats['framed_messages'] for f in port_flows)
            diag[f'port_{port}_heartbeat_opcodes'] = p.opcodes_by_port.get(port, Counter())[HEARTBEAT]
            diag[f'port_{port}_top_opcodes_s2c'] = [
                f'0x{k:04X}:{n}' for k,n in p.opcodes_by_port.get(port, Counter()).most_common(20)]
        for phase in ('walking', 'near', 'opening', 'unlabeled'):
            diag[f'phase_{phase}_segments'] = sum(
                self.phase_segments[(phase, port, direction)]
                for port in self.server_ports for direction in ('s2c','c2s'))
            diag[f'phase_{phase}_opcodes_s2c'] = [
                f'0x{k:04X}:{n}' for k,n in p.opcodes_by_phase.get(phase, Counter()).most_common(20)]
        self.last_stats = diag
        self._emit({'type':'network_stats', 'stats':diag})

    def build_bpf(self):
        expression = ' or '.join(f'port {port}' for port in self.server_ports)
        bpf = f'tcp and ({expression})'
        if self.server_host:
            bpf += f' and host {self.server_host}'
        return bpf

    def start(self, replay_path=None):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def run():
            try:
                if replay_path:
                    from scapy.utils import PcapReader
                    self._emit({'type':'info', 'text':'Offline replay started'})
                    with PcapReader(replay_path) as reader:
                        for pkt in reader:
                            if self.stop_event.is_set():
                                break
                            self._packet(pkt)
                    self._publish_stats()
                    self._emit({'type':'info', 'text':'Offline replay complete'})
                else:
                    from scapy.all import sniff
                    self._emit({'type':'info', 'text':'Listening on ports 13328 and 13320'})
                    while not self.stop_event.is_set():
                        sniff(filter=self.build_bpf(), prn=self._packet, store=False, timeout=2)
            except Exception as exc:
                self._emit({'type':'error', 'text':f'Capture error: {exc}'})
            finally:
                self._publish_stats()
                self._emit({'type':'network_stopped'})
        self.thread = threading.Thread(target=run, name='AionNetwork', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
