"""The node's Blink kernels, compiled as C++ by the stand-in for Blink (tests/blink) and checked against the Python
reference (rayfield/reference.py) on the same inputs, and the light map's shadows checked against the stand-in room's
exact geometry. Needs g++ (the tests skip without it)."""

import os
import shutil
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, 'blink'))

from rayfield import reference as ref, standin                    # noqa: E402
from rayfield.lightmath import BIG                               # noqa: E402

HAVE_CXX = shutil.which('g++') is not None
if HAVE_CXX:
    import pipeline                                              # noqa: E402

W, H = 240, 100
SUN = dict(intensity=6.0, light_k=5000.0, interior=True, aim=(-150.0, 0.0, -250.0))
SMALL = dict(lm_n=256, lm_steps=160, steps=32)
_CACHE = {}


def rendered(view='wide', settings=None, cuc=None, key=None, f=1001, **over):
    k = key or (view, repr(sorted((settings or SUN).items())), f, repr(sorted(over.items())))
    if k not in _CACHE:
        shot = standin.StandinShot(view, W, H)
        o = dict(SMALL)
        o.update(over)
        res = o.pop('res', None)
        _CACHE[k] = (shot, pipeline.render(shot, f, settings or SUN, quality='final', cuc=cuc, onset=True,
                                           lm_space=o['lm_n'], res=res, **o))
    return _CACHE[k]


def f64(x):
    return np.asarray(x, np.float64)


def lit_fraction(shot, o, n=4000, seed=3):
    """Points in the air the camera sees: lit by the light map vs lit exactly (the room's boxes)."""
    p = ref._vec(o['params'])
    surf, fr, lm = f64(o['surf']), f64(o['info']), f64(o['lmap'])
    L = ref.Lighting(p, fr, lm, np.ones((4, 4, 4)))
    rs = np.random.RandomState(seed)
    px, py = rs.uniform(0, W, n), rs.uniform(0, H, n)
    s = surf[py.astype(int), px.astype(int)]
    ok = (s[:, 1] > 0.5) & (s[:, 0] > 0)
    d = ref.ray_dir(p, px, py, W, H)
    X = (p['cam_pos'] + d * (s[:, 0] * rs.uniform(0.02, 0.98, n))[:, None])[ok]
    lu, lv, lt, _ = L.lt.coords(X)
    tx, ty = L.texel(lu, lv)
    got = L.shadow(tx, ty, lt) > 0.5
    exact = ~shot.blocked(X, L.lt.L)
    return got, exact


@unittest.skipUnless(HAVE_CXX, 'needs g++ to compile the kernels')
class Stages(unittest.TestCase):
    """Each kernel against its reference, from the same inputs."""

    def test_frame(self):
        shot, o = rendered()
        want = ref.frame(f64(o['surf']), o['params'])
        np.testing.assert_allclose(o['info'][0, :3], want[0, :3], rtol=2e-4, atol=0.05)

    def test_openings(self):
        shot, o = rendered()
        h, w = o['blocks'].shape[:2]
        bl = ref.blocks(f64(o['surf']), f64(o['info']), w, h)
        np.testing.assert_allclose(o['blocks'][..., 0], bl[..., 0], rtol=1e-6)
        op = ref.openings(f64(o['blocks']))
        np.testing.assert_allclose(o['opn'][..., :2], op[..., :2], rtol=1e-5, atol=1e-3)
        self.assertGreater((op[..., 1] > 0.5).mean(), 0.99)        # every block knows how far its opening is

    def test_light_map(self):
        for view, s in (('wide', SUN), ('side', SUN), ('wide', dict(SUN, interior=False)),
                        ('side', dict(SUN, light_type='spot', aim=(-50.0, 78.0, -285.0), light_az=-120.0,
                                      light_el=60.0, distance=2.2, cone=50.0))):
            shot, o = rendered(view, s)
            n = o['params']['lm_n']
            want = ref.lightmap(f64(o['surf']), f64(o['info']), o['params'], f64(o['opn']))
            got = o['lmap']
            g, w_ = got[:n, :n, 0], want[:n, :n, 0]
            same = ((g >= BIG * 0.5) & (w_ >= BIG * 0.5)) | (np.abs(g - w_) < 1.0)
            self.assertGreater(same.mean(), 0.995, (view, s.get('light_type'), same.mean()))
            self.assertGreater((got[:n, :n, 2] == want[:n, :n, 2]).mean(), 0.995)

    def test_noise(self):
        shot, o = rendered()
        want = ref.noise_atlas(o['params']['seed'])
        np.testing.assert_allclose(o['noise'][..., :2], want[..., :2], atol=2e-6)
        self.assertGreater(want[..., 0].std(), 0.05)
        self.assertTrue(0.4 < want[..., 0].mean() < 0.6)

    def test_march(self):
        for view, s, cuc in (('wide', SUN, None), ('side', dict(SUN, fog=1.0, breakup=0.8), None),
                             ('side', dict(SUN, light_type='spot', aim=(-50.0, 78.0, -285.0), light_az=-120.0,
                                           light_el=60.0, distance=2.2, cone=50.0), 'window')):
            img = None
            if cuc == 'window':
                sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
                import pictures
                img = pictures.window_cuc(64)
            shot, o = rendered(view, s, cuc=img)
            h, w = o['march'].shape[:2]
            want = ref.march(w, h, f64(o['surf']), f64(o['info']), f64(o['lmap']), f64(o['cuc']), f64(o['noise']),
                             o['params'])
            got = f64(o['march'])
            scale = max(want[..., :3].max(), 1e-6)
            err = np.abs(got - want)[..., :3] / scale
            self.assertLess(np.percentile(err, 99), 0.02, view)
            self.assertLess(abs(got[..., :3].mean() - want[..., :3].mean()) / max(want[..., :3].mean(), 1e-9), 0.01)
            np.testing.assert_allclose(got[..., 3], want[..., 3], atol=2e-4)

    def test_upsample(self):
        shot, o = rendered()
        want = ref.upsample(f64(o['surf']), f64(o['march']), f64(o['info']), o['params'])
        np.testing.assert_allclose(o['rgba'], want, rtol=2e-4, atol=2e-5)

    def test_light_on_set(self):
        shot, o = rendered()
        want = ref.onset(f64(o['surf']), f64(o['nrm']), f64(o['info']), f64(o['lmap']), f64(o['cuc']), o['params'])
        err = np.abs(f64(o['onset']) - want)[..., :3]
        self.assertLess((err > 1e-3).mean(), 0.003)


@unittest.skipUnless(HAVE_CXX, 'needs g++ to compile the kernels')
class Shadows(unittest.TestCase):
    """The light map's shadows against the room's exact geometry."""

    def test_through_the_window(self):
        for view, need in (('wide', 0.97), ('side', 0.93)):
            shot, o = rendered(view)
            got, exact = lit_fraction(shot, o)
            self.assertGreater((got == exact).mean(), need, view)
            self.assertLess((got & ~exact).mean(), 0.02, view)          # hardly any light where there should be none

    def test_openings_matter_indoors(self):
        """Without 'Light only through openings', light leaks in through walls the camera cannot see."""
        shot, o = rendered('wide', dict(SUN, interior=False))
        got, exact = lit_fraction(shot, o)
        self.assertGreater((got & ~exact).mean(), 0.3)

    def test_light_on_set_matches_the_plate(self):
        """Where the plate (exact shadows) has sun on the floor, the light-on-set view does too."""
        shot, o = rendered('wide')
        on = pipeline.up(o['onset'])[..., :3].mean(-1)
        plate = shot.plate(1001)
        C = shot.read(1001, 'C')
        sunlit = (plate.mean(-1) > C.mean(-1) * 2.0) & (shot.read(1001, 'A') > 0)
        lum = on > np.percentile(on[shot.read(1001, 'A') > 0], 50) * 2.0
        both = (sunlit == lum)[shot.read(1001, 'A') > 0].mean()
        self.assertGreater(both, 0.95)


@unittest.skipUnless(HAVE_CXX, 'needs g++ to compile the kernels')
class Behaviour(unittest.TestCase):
    def test_held_out_by_the_set(self):
        """The air stops at the surfaces: with even haze, alpha is 1 - exp(-density x distance to the surface)."""
        from rayfield.lightmath import HAZE_K
        s = dict(SUN, breakup=0.0, haze=1.0)
        shot, o = rendered('wide', s, res=1.0)
        a = pipeline.up(o['rgba'])[..., 3]
        d = pipeline.up(o['surf'])[..., 0]
        reach = o['info'][0, 1, 3]
        has = (d > 0) & (d < reach)
        want = 1.0 - np.exp(-1.0 * HAZE_K * d * o['params']['su'])
        rel = np.abs(a[has] - want[has]) / want[has]
        self.assertLess(np.median(rel), 0.01)
        self.assertLess(np.percentile(rel, 95), 0.08)

    def test_black_cuc_blocks_the_light(self):
        s = dict(SUN, cuc_outside='dark')
        _, lit = rendered('wide', s)
        _, dark = rendered('wide', s, cuc=np.zeros((8, 8, 3), np.float32), key='black')
        _, white = rendered('wide', dict(s, cuc_outside='light'), cuc=np.ones((8, 8, 3), np.float32), key='white')
        self.assertLess(dark['rgba'][..., :3].mean(), lit['rgba'][..., :3].mean() * 0.3)
        np.testing.assert_allclose(white['rgba'], lit['rgba'], rtol=1e-4, atol=1e-5)

    def test_spot_lights_only_its_cone(self):
        s = dict(SUN, light_type='spot', aim=(-50.0, 78.0, -285.0), light_az=-120.0, light_el=60.0, distance=2.2,
                 cone=30.0, cone_soft=0.0, ambient=0.0)
        shot, o = rendered('side', s)
        p = ref._vec(o['params'])
        on = pipeline.up(o['onset'])[..., :3].mean(-1)
        d = pipeline.up(o['surf'])[..., 0]
        yy, xx = np.mgrid[0:H, 0:W]
        P = p['cam_pos'] + ref.ray_dir(p, xx + 0.5, (H - 1 - yy) + 0.5, W, H) * d[..., None]
        lu, lv, lt, ok = ref.Light(p).coords(P)
        outside = (np.sqrt(lu ** 2 + lv ** 2) > 1.05) | ~ok
        has = d > 0
        self.assertLess(on[outside & has].max(), on[~outside & has].max() * 0.1)

    def test_same_every_time(self):
        shot = standin.StandinShot('wide', W, H)
        a = pipeline.render(shot, 1010, SUN, quality='final', lm_space=256, **SMALL)['rgba']
        b = pipeline.render(shot, 1010, SUN, quality='final', lm_space=256, **SMALL)['rgba']
        np.testing.assert_array_equal(a, b)

    def test_ground_fog_sits_low(self):
        s = dict(SUN, haze=0.0, fog=2.0, fog_height=0.3, fog_falloff=0.2, breakup=0.0, ambient=0.2)
        shot, o = rendered('wide', s)
        p = ref._vec(o['params'])
        a = pipeline.up(o['rgba'])[..., 3]
        P = shot.read(1001, 'P')
        has = shot.read(1001, 'A') > 0
        low, high = has & (P[..., 1] < 20), has & (P[..., 1] > 200)
        self.assertGreater(a[low].mean(), a[high].mean() * 3)


@unittest.skipUnless(HAVE_CXX, 'needs g++ to compile the kernels')
class Surface(unittest.TestCase):
    def test_surface_matches_the_python_twin(self):
        shot, o = rendered()
        s = shot.surface(1001)
        surf = pipeline.up(o['surf'])
        np.testing.assert_allclose(surf[..., 0], s.dist, rtol=1e-4, atol=1e-3)
        np.testing.assert_allclose(surf[..., 1], s.cov, atol=1e-6)


if __name__ == '__main__':
    unittest.main()
