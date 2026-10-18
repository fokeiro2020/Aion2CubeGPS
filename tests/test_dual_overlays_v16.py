"""Regression tests for independent audio/network overlay state and alerts."""
import ast
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from modern_engine import DetectionEngine
from ui_config import load, save


class TestDualOverlaySettings(unittest.TestCase):
    def test_dual_overlay_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            c = load(Path(td) / 'missing.json')
            self.assertTrue(c['hud_visible'])
            self.assertTrue(c['audio_hud_visible'])
            self.assertTrue(c['network_alert_enabled'])
            self.assertTrue(c['sound_detection_enabled'])

    def test_separate_position_opacity_and_visibility_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'settings.json'
            c = load(path)
            c.update(hud_visible=False, audio_hud_visible=True,
                     hud_x=175, hud_y=91, audio_hud_x=840, audio_hud_y=490,
                     hud_opacity=66, audio_hud_opacity=79,
                     hud_clickthrough=True, audio_hud_clickthrough=False,
                     network_alert_enabled=True, sound_detection_enabled=False)
            save(c,path)
            r = load(path)
            for key in ['hud_visible', 'audio_hud_visible','hud_x','hud_y',
                        'audio_hud_x','audio_hud_y','hud_opacity','audio_hud_opacity',
                        'hud_clickthrough','audio_hud_clickthrough',
                        'network_alert_enabled','sound_detection_enabled']:
                self.assertEqual(c[key],r[key],key)

    def test_out_of_bounds_settings_clamped(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'settings.json'
            path.write_text('{"audio_hud_opacity":999,"audio_hud_scale":5}')
            r=load(path)
            self.assertEqual(r['audio_hud_opacity'],100)
            self.assertEqual(r['audio_hud_scale'],70)


class TestIndependentDetectors(unittest.TestCase):
    def setUp(self):
        with patch('modern_engine.read_glow_settings',return_value=(None,40)):
            self.e=DetectionEngine(start_audio=False,start_screen=False)

    def tearDown(self):
        self.e.shutdown()

    def test_audio_detection_not_hidden_by_network_cube(self):
        self.e.netq.put({'type':'cube','action':'spawn','id':42,'template':1200039,
                         'xyz':(100.,100.,0.),'source':'working'})
        self.e.netq.put({'type':'player','xyz':(0.,0.,0.)})
        self.e.process_network_events()
        self.e.audioq.put((-45.,-0.35))
        self.e.process_audio()
        self.assertTrue(self.e.netcubes)
        self.assertTrue(self.e.sound_detected)
        self.assertGreater(self.e.proximity,0)
        self.assertLess(self.e.balance,0)

    def test_network_beep_setting_independent_from_audio_sensor(self):
        self.e.sound_enabled=False
        self.e.network_alert_enabled=True
        self.e.last_alert=0
        self.e._play_alert()
        self.assertGreater(self.e.last_alert,0)
        previous=self.e.last_alert
        self.e.network_alert_enabled=False
        self.e.last_alert=0
        self.e._play_alert()
        self.assertEqual(self.e.last_alert,0)

    def test_audio_without_network(self):
        self.e.network_enabled=False
        self.e.audioq.put((-40., .25))
        self.e.process_audio()
        self.assertTrue(self.e.sound_detected)
        self.assertFalse(self.e.netcubes)

    def test_sound_disable_does_not_turn_off_network_alert(self):
        self.e.sound_enabled=False
        self.e.network_alert_enabled=True
        self.e.audioq.put((-40., .25))
        self.e.process_audio()
        self.assertFalse(self.e.sound_detected)
        self.assertTrue(self.e.network_alert_enabled)

    def test_audio_disconnection_clears_stale_indicator(self):
        self.e.audioq.put((-40., .1))
        self.e.process_audio()
        self.e.last_audio_reading=time.monotonic()-2
        self.e.process_audio()
        self.assertFalse(self.e.sound_detected)

    def test_separate_painter_classes_without_qt_dependency(self):
        # Source structure assertion, usable even when Qt is not available
        text=(Path(__file__).resolve().parents[1] / 'dual_overlays.py').read_text()
        module=ast.parse(text)
        names={n.name for n in module.body if isinstance(n,ast.ClassDef)}
        self.assertIn('NetworkHud',names)
        self.assertIn('SoundHud',names)
        self.assertIn('GlassOverlay',names)
        audio_node=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='SoundHud')
        audio_source=ast.get_source_segment(text,audio_node)
        self.assertIn('e.proximity',audio_source)
        self.assertIn('e.sound_trend()',audio_source)
        self.assertNotIn('e.netcubes',audio_source)


if __name__=='__main__':unittest.main()
