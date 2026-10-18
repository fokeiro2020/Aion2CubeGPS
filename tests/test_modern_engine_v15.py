import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ui_config import load, save
from modern_engine import DetectionEngine, margin_for_slider

class TestModernEngine(unittest.TestCase):
    def setUp(self):
        with patch('modern_engine.read_glow_settings',return_value=(None,40)):
            self.engine=DetectionEngine(start_audio=False,start_screen=False)
    def tearDown(self):self.engine.shutdown()
    def test_audio_margin(self):
        self.assertAlmostEqual(margin_for_slider(0),14.)
        self.assertAlmostEqual(margin_for_slider(100),1.5)
    def test_spawn_position_and_removal(self):
        self.engine.netq.put({'type':'cube','action':'spawn','id':777,'template':1200039,'xyz':(3000.,4000.,500.),'source':'working'})
        self.engine.netq.put({'type':'player','xyz':(0.,0.,0.)})
        self.engine.process_network_events()
        target=self.engine.nearest_cube()
        self.assertEqual(len(self.engine.netcubes),1)
        self.assertAlmostEqual(target['horizontal'],50.)
        self.assertAlmostEqual(target['height'],5.)
        self.engine.netq.put({'type':'cube','action':'remove','id':777,'source':'working'})
        self.engine.process_network_events()
        self.assertEqual(len(self.engine.netcubes),0)
    def test_demo_and_clear(self):
        self.engine.demo_cube()
        self.assertEqual(len(self.engine.netcubes),1)
        self.assertGreater(self.engine.nearest_cube()['distance3d'],0)
        self.engine.clear_cubes()
        self.assertEqual(len(self.engine.netcubes),0)
    def test_ui_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ui.json'
            config=load(path)
            config['hud_opacity']=72
            config['radar_mode']='World'
            save(config,path)
            restored=load(path)
            self.assertEqual(restored['hud_opacity'],72)
            self.assertEqual(restored['radar_mode'],'World')
    def test_invalid_ui_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'broken.json'
            path.write_text('{"hud_opacity":999,"radar_mode":"bogus"}',encoding='utf-8')
            restored=load(path)
            self.assertEqual(restored['hud_opacity'],100)
            self.assertEqual(restored['radar_mode'],'Auto')

if __name__=='__main__':unittest.main()
