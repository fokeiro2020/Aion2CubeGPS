"""v17 sound-radar projection and integration regression tests."""
import ast
import math
import unittest
from pathlib import Path
from unittest.mock import patch
from sound_direction import stereo_marker, glow_marker, stereo_instruction, relative_strength
from modern_engine import DetectionEngine


class AudioRadarProjectionTests(unittest.TestCase):
    def test_sound_cursor_moves_only_left_right(self):
        for balance in (-10, -1, -.4, 0, .3, 1, 100):
            x,y=stereo_marker(balance, center=(100, 150), radius=80)
            self.assertEqual(y, 150)
            self.assertTrue(33 <= x <= 167)
        self.assertLess(stereo_marker(-.6)[0], stereo_marker(0)[0])
        self.assertGreater(stereo_marker(+.6)[0], stereo_marker(0)[0])

    def test_clamps_bad_values(self):
        self.assertEqual(stereo_marker(float('nan')), stereo_marker(0))
        self.assertEqual(stereo_marker(float('inf')), stereo_marker(0))
        self.assertEqual(stereo_marker(-100)[0], 160-74)

    def test_glow_cursor_can_point_up_and_down(self):
        up=glow_marker((.1, -.8))
        down=glow_marker((.1, .8))
        self.assertLess(up[1], 167)
        self.assertGreater(down[1], 167)
        self.assertIsNone(glow_marker(None))

    def test_glow_clamped_to_circle(self):
        for vector in [(-1,-1),(1,1),(-10,0),(0,10)]:
            x,y=glow_marker(vector)
            self.assertLessEqual(math.hypot(x-160, y-167), 74.000001)

    def test_audio_instruction_not_a_world_bearing(self):
        self.assertIn('LEFT',stereo_instruction(-.6, True))
        self.assertIn('RIGHT',stereo_instruction(.6, True))
        self.assertIn('LISTENING',stereo_instruction(0, False))

    def test_relative_strength_is_not_absolute_range(self):
        self.assertEqual(relative_strength(0,False),'SEARCHING FOR CUBE HUM')
        self.assertEqual(relative_strength(95,True),'VERY STRONG')

    def test_audio_does_not_depend_on_network_cubes(self):
        with patch('modern_engine.read_glow_settings', return_value=(None,40)):
            e=DetectionEngine(start_audio=False,start_screen=False)
        try:
            e.audioq.put((-45.,.45))
            e.process_audio()
            self.assertTrue(e.sound_detected)
            self.assertEqual(len(e.netcubes),0)
            self.assertGreater(stereo_marker(e.balance)[0], 160)
        finally:
            e.shutdown()

    def test_sound_overlay_never_inspects_network_cube_state(self):
        text=(Path(__file__).resolve().parents[1]/'dual_overlays.py').read_text(encoding='utf-8')
        source=ast.get_source_segment(text, next(n for n in ast.parse(text).body if isinstance(n,ast.ClassDef) and n.name=='SoundHud'))
        self.assertIn('stereo_marker(e.balance',source)
        self.assertIn('glow_marker(e.glow',source)
        self.assertNotIn('e.netcubes',source)
        self.assertNotIn('e.nearest_cube',source)

if __name__=='__main__':unittest.main()
