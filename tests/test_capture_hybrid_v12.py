import queue, unittest
from network_capture import CaptureWorker
from test_capture_v11 import _Packet, CaptureTests
from aion_protocol_v11 import pack_frame, SPAWN
from test_protocol_v11 import CUBE_BODY

class CaptureHybridTests(CaptureTests):
    def test_packet_local_mode_works_without_heartbeat(self):
        worker=CaptureWorker(queue.Queue(maxsize=300))
        msg=pack_frame(SPAWN,CUBE_BODY)
        worker._packet(_Packet(13328, 55555, msg))
        worker._publish_stats()
        self.assertEqual(worker.last_stats['packet_local_cube_spawns'],1)
        self.assertEqual(worker.last_stats['cube_spawns'],0)
        events=[]
        while not worker.out.empty():
            events.append(worker.out.get_nowait())
        hits=[e for e in events if e.get('type')=='cube']
        self.assertEqual(len(hits),1)
        self.assertEqual(hits[0]['source'],'packet-local')

    def test_packet_local_never_parses_outbound(self):
        worker=CaptureWorker(queue.Queue(maxsize=300))
        worker._packet(_Packet(55555,13328,pack_frame(SPAWN,CUBE_BODY)))
        worker._publish_stats()
        self.assertEqual(worker.last_stats['packet_local_cube_spawns'],0)

if __name__=='__main__': unittest.main()
