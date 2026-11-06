"""The light, in numpy: the same formulas as node/kernels/lib_light.blink.

Directions follow MoteField: heading and elevation give the unit vector pointing TOWARD the light (Y up; heading 0
means the light travels toward +X). The light's frame is (right, up, fwd), with fwd the way the light travels.
"""

import math

import numpy as np

HAZE_K = 0.05           # extinction per metre at Haze 1 (node/blinklib.HAZE_K)
BIG = 1e20              # "no blocker" in the light map
DEG = math.pi / 180.0


def unit(v):
    v = np.asarray(v, np.float64)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def light_dir(az, el):
    """Unit vector toward the light."""
    a, e = az * DEG, el * DEG
    return np.array([-math.cos(a) * math.cos(e), math.sin(e), -math.sin(a) * math.cos(e)])


def light_from_direction(L):
    """(heading, elevation) in degrees for a unit vector pointing toward the light: the inverse of light_dir."""
    L = unit(L)
    el = math.degrees(math.asin(max(-1.0, min(1.0, L[1]))))
    az = math.degrees(math.atan2(-L[2], -L[0]))
    return az, el


def basis(az, el, roll):
    """(right, up, fwd) of the light: fwd is the way the light travels; roll turns right and up about it."""
    F = -light_dir(az, el)
    ref = np.array([0.0, 1.0, 0.0]) if abs(F[1]) < 0.999 else np.array([0.0, 0.0, -1.0])
    r0 = unit(np.cross(F, ref))
    u0 = np.cross(r0, F)
    ca, sa = math.cos(roll * DEG), math.sin(roll * DEG)
    return r0 * ca + u0 * sa, u0 * ca - r0 * sa, F


class Light(object):
    """Everything the kernels work out about the light in init(), from the params."""

    def __init__(self, p):
        self.kind = int(p['light_type'])                  # 0 sun, 1 spot
        self.aim = np.asarray(p['aim'], np.float64)
        self.R, self.U, self.F = basis(p['light_az'], p['light_el'], p['roll'])
        self.L = -self.F
        self.pos = self.aim + self.L * (p['light_dist'] / p['su'])
        self.tanc = math.tan(min(max(p['cone'], 1.0), 170.0) * 0.5 * DEG)

    def coords(self, X):
        """Light-space coordinates of world points X (..., 3): lu, lv, lt and a valid mask.
        Sun: lu, lv across the light (scene units, from the aim point), lt along it. Spot: lu, lv in the cone
        (-1..1 at its edge), lt = distance from the light."""
        X = np.asarray(X, np.float64)
        if self.kind == 0:
            q = X - self.aim
            return q @ self.R, q @ self.U, q @ self.F, np.ones(X.shape[:-1], bool)
        q = X - self.pos
        z = q @ self.F
        ok = z > 1e-6
        zs = np.where(ok, z, 1.0) * self.tanc
        return np.where(ok, (q @ self.R) / zs, 0.0), np.where(ok, (q @ self.U) / zs, 0.0), \
            np.linalg.norm(q, axis=-1), ok


def kelvin_rgb(K):
    """Approximate black-body colour, linear, normalised to luminance 1 (Rec.709 weights)."""
    t = K / 100.0
    if t <= 66:
        r, g = 255.0, 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r, g = 329.698727446 * (t - 60) ** -0.1332047592, 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    c = np.array([min(max(v, 0.0), 255.0) / 255.0 for v in (r, g, b)]) ** 2.2
    return c / (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])


def hg(c, g):
    """Henyey-Greenstein phase, scaled so it is 1 everywhere at g = 0 (c = cosine of the scattering angle)."""
    return (1.0 - g * g) / np.power(np.maximum(1.0 + g * g - 2.0 * g * c, 1e-4), 1.5)


def smooth01(x):
    c = np.clip(x, 0.0, 1.0)
    return c * c * (3.0 - 2.0 * c)


def luminance(c):
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
