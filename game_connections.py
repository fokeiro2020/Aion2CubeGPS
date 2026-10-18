"""Non-invasive connection discovery for Aion2. Uses OS socket metadata only."""
from __future__ import annotations
from dataclasses import dataclass

DEFAULT_PORTS = (13328, 13320)

@dataclass(frozen=True)
class GameEndpoint:
    host: str
    port: int
    process_name: str


def discover_game_endpoints(processes=None):
    """Find remote established TCP sockets held by Aion2; no memory inspection.

    When psutil is unavailable or access is denied, returns an empty list so
    live capture can still fall back to the documented ports.
    `processes` supports unit-test fakes.
    """
    if processes is None:
        try:
            import psutil
            processes = psutil.process_iter(['name'])
        except Exception:
            return []
    results = []
    for proc in processes:
        try:
            name = str(getattr(proc, 'info', {}).get('name') or proc.name() or '')
            if 'aion2' not in name.lower().replace(' ', ''):
                continue
            connections = proc.net_connections(kind='tcp')
            for conn in connections:
                if conn.status != 'ESTABLISHED' or not conn.raddr:
                    continue
                addr = conn.raddr
                host, port = (addr.ip, addr.port) if hasattr(addr, 'ip') else addr[:2]
                port = int(port)
                if port in (80,443) or not 1 <= port <= 65535:
                    continue
                if host.startswith(('127.', '::1')):
                    continue
                item = GameEndpoint(str(host), port, name)
                if item not in results:
                    results.append(item)
        except Exception:
            continue
    return sorted(results, key=lambda x: (x.port not in DEFAULT_PORTS, x.port, x.host))
