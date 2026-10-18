import unittest
import numpy as np

from glow_tracking import exclude_window, detect_glow


class TestGlowTracking(unittest.TestCase):
    def setUp(self):
        self.background = np.zeros((100, 150, 3), dtype=np.uint8)
        self.target_rgb = (255, 207, 60)
        self.target_bgr = (60, 207, 255)

    def test_cube_detected_before_opening_then_disappears(self):
        frame = self.background.copy()
        frame[35:47, 64:77] = self.target_bgr
        result = detect_glow(frame, self.target_rgb, 40)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 70, delta=4)
        self.assertAlmostEqual(result[1], 41, delta=4)
        after_opening = self.background.copy()
        self.assertIsNone(detect_glow(after_opening, self.target_rgb, 40, near=result[:2]))

    def test_own_radar_gold_dot_is_ignored(self):
        monitor = {"left": 0, "top": 0, "width": 600, "height": 400}
        frame = self.background.copy()
        # The 425x795 app window is partially outside this monitor. Matching
        # pixels representing its gold dot must be removed, even if bright.
        frame[25:34, 15:24] = self.target_bgr
        exclude_window(frame, monitor, scale=4, window_rect=(0, 0, 425, 795))
        self.assertIsNone(detect_glow(frame, self.target_rgb, 40))

    def test_app_window_is_ignored_but_game_glow_outside_it_is_kept(self):
        monitor = {"left": 0, "top": 0, "width": 600, "height": 400}
        frame = self.background.copy()
        frame[27:36, 15:24] = self.target_bgr  # app window
        frame[68:81, 120:133] = self.target_bgr  # game pixels outside
        exclude_window(frame, monitor, scale=4, window_rect=(0, 0, 425, 190), pad=0)
        result = detect_glow(frame, self.target_rgb, 40)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 126, delta=4)

    def test_isolated_colored_pixels_do_not_create_false_cube(self):
        frame = self.background.copy()
        # More than MIN_PIXELS globally, but never clustered locally.
        for y, x in ((5, 5), (20, 20), (35, 35), (50, 50),
                     (65, 65), (80, 80), (10, 100), (90, 125)):
            frame[y, x] = self.target_bgr
        self.assertIsNone(detect_glow(frame, self.target_rgb, 40))

    def test_tracker_does_not_jump_to_distant_similar_glow(self):
        frame = self.background.copy()
        frame[70:85, 110:125] = self.target_bgr
        self.assertIsNone(detect_glow(frame, self.target_rgb, 40,
                                      near=(14, 12), search_radius=30))
        self.assertIsNotNone(detect_glow(frame, self.target_rgb, 40, near=None))

    def test_handles_window_outside_capture_monitor(self):
        monitor = {"left": 1920, "top": 0, "width": 600, "height": 400}
        frame = self.background.copy()
        frame[22:32, 30:40] = self.target_bgr
        exclude_window(frame, monitor, scale=4, window_rect=(0, 0, 425, 795))
        self.assertIsNotNone(detect_glow(frame, self.target_rgb, 40))


if __name__ == "__main__":
    unittest.main()


class TestCubeImageAssistedTracking(unittest.TestCase):
    def test_close_cube_image_beats_unrelated_color_bar(self):
        import cv2
        from pathlib import Path
        from glow_tracking import load_references
        assets = Path(__file__).resolve().parents[1] / 'assets' / 'reference_cubes'
        refs = load_references(assets)
        self.assertEqual(len(refs), 2)
        frame = np.zeros((250, 400, 3), dtype=np.uint8)
        frame[:] = [33, 74, 61]
        close = cv2.imread(str(assets / 'cube_close.png'))
        frame[50:144, 180:276] = close
        frame[80:85, 0:100] = [90, 116, 208]   # spurious health/status bar
        result = detect_glow(frame, (208, 116, 90), 40, references=refs)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], 225, delta=25)
        self.assertAlmostEqual(result[1], 97, delta=25)

    def test_on_screen_position_is_not_distance(self):
        frame = np.zeros((120, 240, 3), dtype=np.uint8)
        frame[45:57, 145:157] = [60, 207, 255]
        result_far = detect_glow(frame, (255, 207, 60), 40)
        close = np.zeros_like(frame)
        close[39:63, 139:163] = [60, 207, 255]
        result_near = detect_glow(close, (255, 207, 60), 40)
        self.assertIsNotNone(result_near)
        self.assertIsNotNone(result_far)
        self.assertAlmostEqual(result_near[0], result_far[0], delta=2)
        self.assertAlmostEqual(result_near[1], result_far[1], delta=2)
        self.assertGreater(result_near[2], result_far[2])

    def test_simulated_collected_cube_clears_even_when_unrelated_pixels_remain(self):
        before = np.zeros((150, 250, 3), dtype=np.uint8)
        before[60:90, 95:125] = [60, 207, 255]
        before[20:23, 200:220] = [60, 207, 255]  # unrelated thin orange region
        detected = detect_glow(before, (255, 207, 60), 40, near=(110, 75), search_radius=35)
        self.assertIsNotNone(detected)
        after = before.copy()
        after[60:90, 95:125] = 0
        self.assertIsNone(detect_glow(after, (255, 207, 60), 40,
                                      near=detected[:2], search_radius=35))
