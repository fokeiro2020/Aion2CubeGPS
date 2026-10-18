"""Adapter around the exact network parser in the user-confirmed working radar.

No edits are made to working_aion_radar.py's PureStreamEngine.
Only a single capture engine runs at a time. Raw packets are not saved.
"""
from __future__ import annotations

import queue
import threading
import time
from collections import Counter

# Import the user-provided module, avoiding its `main()` UI entrypoint.
from working_aion_radar import RadarState, PureStreamEngine, Pure2DRadarApp

SERVER_PORTS = (13328, 13320)


class WorkingCapture:
    """Use the same frame/parser code as the user-confirmed working application."""

    def __init__(self, out: queue.Queue, character_name='', server_ports=None, server_host=None):
        self.out = out
        self.stop_event = threading.Event()
        self.thread = None
        self.ports = tuple(server_ports or SERVER_PORTS)
        self.server_host = server_host
        self.state = RadarState()
        # The source mini-radar guesses movement toward the nearest cube when
        # a reliable movement vector is missing. This creates phantom travel
        # and mismatched distances. Prefer last actual decoded coordinates.
        self.state.extrapolation_enabled = False
        self.state.target_char_name = character_name.strip()
        self.state.on_update_callback = self._publish_changes
        self.engine = PureStreamEngine(self.state)
        self.phase = 'unlabeled'
        self.phase_segments = Counter()
        self.port_directions = Counter()
        self.port_bytes = Counter()
        self.opcodes_not_claimed = True
        self.packet_count = 0
        self.last_cubes = {}
        self.last_player = None
        self.last_emit = 0.0
        self.last_stats = 0.0
        self.network_errors = 0

    def _emit(self, event):
        try:
            self.out.put_nowait(event)
        except queue.Full:
            pass

    def _publish_changes(self):
        # Callback fires after the original parser modifies state; do not call
        # Tk or audio APIs on the background capture thread.
        with self.state.lock:
            cubes = {eid:(c.npc_id,(c.x,c.y,c.z)) for eid,c in self.state.cubes.items()}
            pos = self.state.player_pos   # real received coordinates only
        old = self.last_cubes
        for eid,(template,xyz) in cubes.items():
            if eid not in old or old[eid] != (template,xyz):
                self._emit({'type':'cube','action':'spawn','id':eid,
                            'template':template,'xyz':xyz,'source':'working'})
        for eid in old.keys() - cubes.keys():
            self._emit({'type':'cube','action':'remove','id':eid,'source':'working'})
        self.last_cubes = cubes
        if pos is not None and pos != self.last_player:
            self.last_player = pos
            self._emit({'type':'player','xyz':pos})
        elif pos is None and self.last_player is not None:
            self.last_player = None
            self._emit({'type':'zone_reset'})

    def _packet(self, pkt):
        from scapy.layers.inet import IP, TCP
        if IP not in pkt or TCP not in pkt:
            return
        tcp = pkt[TCP]
        sport, dport = int(tcp.sport),int(tcp.dport)
        if sport in self.ports:
            port, direction = sport,'s2c'
        elif dport in self.ports:
            port, direction = dport,'c2s'
        else:
            return
        ip=pkt[IP]
        server_ip=str(ip.src if direction=='s2c' else ip.dst)
        if self.server_host and server_ip != self.server_host:
            return
        payload=bytes(tcp.payload)
        if not payload:
            return
        self.packet_count+=1
        self.phase_segments[self.phase]+=1
        self.port_directions[(port,direction)]+=1
        self.port_bytes[(port,direction)]+=len(payload)
        # Critical: route the exact four arguments into the original
        # working PureStreamEngine. No independent frame decoding here.
        self.engine.feed_payload(str(ip.src),sport,str(ip.dst),dport,payload)
        if self.packet_count % 50 == 0:
            self._emit({'type':'packets','count':self.packet_count})
            self._publish_stats()

    def feed_test_payload(self, src_ip, src_port, dst_ip, dst_port, payload):
        """Deterministic smoke-test entrypoint, independent of Scapy/Npcap."""
        self.engine.feed_payload(src_ip,src_port,dst_ip,dst_port,payload)

    def _publish_stats(self):
        report={
            'decoder_version': 'v13/user-confirmed-working-PureStreamEngine',
            'tcp_segments':self.packet_count,
            'network_cubes':len(self.last_cubes),
            'player_position_available':self.last_player is not None,
            'active_phase':self.phase,
            'no_raw_packet_storage':True,
            'note':'Source parser processes each TCP payload; frame-level opcodes are not counted or verified by this adapter.'
        }
        for p in self.ports:
            for dr in ('s2c','c2s'):
                report[f'port_{p}_{dr}_segments']=self.port_directions[(p,dr)]
                report[f'port_{p}_{dr}_bytes']=self.port_bytes[(p,dr)]
        for phase in ('walking','near','opening','unlabeled'):
            report[f'phase_{phase}_segments']=self.phase_segments[phase]
        self._emit({'type':'network_stats','stats':report})

    def set_phase(self, phase):
        if phase not in ('walking','near','opening','unlabeled'):
            raise ValueError('Invalid phase')
        self.phase=phase
        self._publish_stats()

    def build_bpf(self):
        condition=' or '.join(f'port {p}' for p in self.ports)
        result=f'tcp and ({condition})'
        if self.server_host:
            result+=f' and host {self.server_host}'
        return result

    def start(self, replay_path=None):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def run():
            try:
                if replay_path:
                    from scapy.utils import PcapReader
                    self._emit({'type':'info','text':'Working decoder: replaying PCAP'})
                    with PcapReader(replay_path) as reader:
                        for packet in reader:
                            if self.stop_event.is_set():
                                break
                            self._packet(packet)
                    self._emit({'type':'info','text':'Replay complete'})
                else:
                    from scapy.all import sniff
                    self._emit({'type':'info','text':'Working radar decoder, ports 13328 + 13320'})
                    while not self.stop_event.is_set():
                        sniff(filter=self.build_bpf(),prn=self._packet,store=False,timeout=1)
            except Exception as exc:
                self.network_errors+=1
                self._emit({'type':'error','text':f'Network capture: {exc}'})
            finally:
                self._emit({'type':'packets','count':self.packet_count})
                self._publish_stats()
                self._emit({'type':'network_stopped'})
        self.thread=threading.Thread(target=run,name='AionWorkingCapture',daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()


class EmbeddedNetworkRadar(Pure2DRadarApp):
    """Preserve the reference radar's UI. Closing this mini-window doesn't exit app."""
    def _on_close(self):
        self.root.destroy()
