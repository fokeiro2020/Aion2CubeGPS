import math
import unittest
from radar_geometry import project_cube

class TestWorldProjection(unittest.TestCase):
    def test_source_orientation_y_right_x_up(self):
        origin=(1000,2000,300)
        self.assertGreater(project_cube(origin,(1000,3000,300)).screen_x,140)
        self.assertLess(project_cube(origin,(2000,2000,300)).screen_y,140)
        self.assertLess(project_cube(origin,(1000,1000,300)).screen_x,140)
        self.assertGreater(project_cube(origin,(0,2000,300)).screen_y,140)
    def test_world_scale_and_distance(self):
        p=project_cube((0,0,0),(0,10000,3300))
        self.assertAlmostEqual(p.flat_m,100)
        self.assertAlmostEqual(p.height_m,33)
        self.assertAlmostEqual(p.distance_3d_m, math.sqrt(10000+1089))
        self.assertAlmostEqual(p.screen_x,140+112/150*100)
        self.assertFalse(p.off_scale)
    def test_clips_radially_not_independently(self):
        p=project_cube((0,0,0),(10000,10000,0),range_m=100)
        self.assertTrue(p.off_scale)
        self.assertLessEqual(math.hypot(p.screen_x-140,p.screen_y-140),112.00001)
        self.assertAlmostEqual(abs(p.screen_x-140),abs(p.screen_y-140))
    def test_source_radar_projection_same_signs(self):
        # Compare to Pure2DRadarApp's literal x=+cdy, y=-cdx axes.
        player=(1200,2100,40)
        cube=(5120,-1300,340)
        p=project_cube(player,cube,center=(125,125),radius_px=112,margin_px=16,range_m=150)
        cdx=(cube[0]-player[0])/100
        cdy=(cube[1]-player[1])/100
        self.assertAlmostEqual(p.screen_x,125+cdy*96/150)
        self.assertAlmostEqual(p.screen_y,125-cdx*96/150)
    def test_invalid_range(self):
        with self.assertRaises(ValueError):project_cube((0,0,0),(0,0,0),range_m=0)

if __name__=='__main__':unittest.main()
