import unittest
from types import SimpleNamespace
from game_connections import discover_game_endpoints, GameEndpoint

class FakeProcess:
    def __init__(self, name, rows):
        self.info = {'name':name}
        self.rows = rows
    def net_connections(self, kind):
        return self.rows

class ConnectionTests(unittest.TestCase):
    def test_find_live_game_endpoint(self):
        conn = lambda port: SimpleNamespace(status='ESTABLISHED', raddr=SimpleNamespace(ip='203.0.113.55', port=port))
        result = discover_game_endpoints([FakeProcess('Aion2.exe',[conn(443),conn(13328)]),FakeProcess('chrome.exe',[conn(13320)])])
        self.assertEqual(result,[GameEndpoint('203.0.113.55',13328,'Aion2.exe')])
    def test_no_match(self):
        self.assertEqual(discover_game_endpoints([FakeProcess('other.exe',[])]),[])

if __name__=='__main__': unittest.main()
