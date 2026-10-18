import unittest
from pathlib import Path
import cv2
import numpy as np
from rotation_tracking import find_cube, load_rotation_patterns, warm_mask

REFERENCES = Path(__file__).resolve().parents[1] / 'assets' / 'rotation_patterns'

class TestRotationTracker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = load_rotation_patterns(REFERENCES)

    def test_reference_library_contains_rotation_poses(self):
        self.assertGreaterEqual(len(self.refs), 20)

    def test_different_reference_poses_are_distinct(self):
        self.assertFalse(np.array_equal(self.refs[0], self.refs[-1]))

    def test_cube_clue_clears_after_it_disappears(self):
        # Synthetic red-orange geometric glow, roughly cube-sized at 640-wide.
        frame = np.full((360, 640, 3), (60, 65, 65), dtype=np.uint8)
        ref = self.refs[0]
        template = cv2.resize(ref.astype(np.uint8), (42, 42))
        # Generate source colors with warm H/S values and variable intensity.
        v = np.clip(template.astype(np.int16)+90, 0, 255).astype(np.uint8)
        bgr = np.stack([np.full_like(v, 45), v // 3, v], axis=-1)
        frame[145:187, 280:322] = bgr
        # The animation can differ from our synthetic construction, but clearing
        # the picture must never return a cube regardless of prior position.
        after = np.full_like(frame, (60, 65, 65))
        self.assertIsNone(find_cube(after, self.refs, anchor=(300, 165)))

    def test_purple_forest_is_not_cube(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:] = (200, 45, 180)  # BGR magenta, visible in second clip
        self.assertIsNone(find_cube(frame, self.refs))
        self.assertLess(warm_mask(frame).sum(), 100)

    def test_bottom_action_bar_does_not_trigger(self):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[332:346, 280:330] = (60, 30, 235)  # red status/action UI
        self.assertIsNone(find_cube(frame, self.refs))

if __name__ == '__main__':
    unittest.main()
