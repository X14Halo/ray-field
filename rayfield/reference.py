"""The reference renderer: the node's kernels, step by step, in numpy (float64). The kernel tests run the BlinkScript
kernels (as C++) and these functions on the same inputs and compare.

Images here are as the kernels see them: arrays [y, x, channel] with row 0 at the BOTTOM (Nuke's y axis points up).

The stages, as in the node:
    frame(surf, p)                         a few numbers about the set and the light's frame (4 x 1 pixels)
    blocks(surf, fr, w, h), openings(bl)   how far away the windows and other openings are (1/8 size)
    lightmap(surf, fr, p, opn, size)       the light's view of the set: how far light gets before something blocks it
    noise_atlas(seed)                      a tiling 3D noise for the haze's breakup (64^3, in a 512 x 512 image)
    march(w, h, surf, fr, lm, cuc, nz, p)  the air along every pixel's ray: light scattered toward the camera
    upsample(surf, mar, fr, p)             back to full resolution, keeping edges where the depth jumps
    onset(surf, nrm, fr, lm, cuc, p)       the light painted onto the set (for aiming)

p is a dict of the kernels' params (see node/blinklib.PARAMS and params() below).
"""

import math

import numpy as np

from . import rng
from .lightmath import BIG, HAZE_K, Light, hg, kelvin_rgb, smooth01, unit

NV = 64            # noise volume: 64^3 voxels
NT = 8             # tiles per side of the atlas (8 x 8 tiles of 64 x 64 = 512 x 512)
NCELL = 8          # voxels per noise cell
JIT = rng.JITTER


# ---------------------------------------------------------------------------------------------------------------------
#  The camera, as lib_cam.blink has it (y up, pixel centres at .5)
# ---------------------------------------------------------------------------------------------------------------------
def project(p, X, W, H):
    d = np.asarray(X, np.float64) - p['cam_pos']
    x, y, z = d @ p['cam_right'], d @ p['cam_up'], -(d @ p['cam_back'])
    zs = np.where(z > 1e-9, z, 1e-9)
    th = p['cam_th']
    tv = th * H / float(W)
    return (x / zs / th * 0.5 + 0.5) * W, (y / zs / tv * 0.5 + 0.5) * H, z


def ray_dir(p, px, py, W, H):
    th = p['cam_th']
    tv = th * H / float(W)
    a = (np.asarray(px, np.float64) / W * 2 - 1) * th
    b = (np.asarray(py, np.float64) / H * 2 - 1) * tv
    d = a[..., None] * p['cam_right'] + b[..., None] * p['cam_up'] - p['cam_back']
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def _vec(p):
    q = dict(p)
    for k in ('cam_pos', 'cam_right', 'cam_up', 'cam_back', 'aim', 'light_col', 'ambient_rgb'):
        if k in q:
            q[k] = np.asarray(q[k], np.float64)
    return q


# ---------------------------------------------------------------------------------------------------------------------
#  Frame: the set's box, how far the haze reaches, and the sun's light-map frame
# ---------------------------------------------------------------------------------------------------------------------
def _grid(W, H, gx, gy):
    sx = ((np.arange(gx) + 0.5) * W / float(gx)).astype(np.int64)
    sy = ((np.arange(gy) + 0.5) * H / float(gy)).astype(np.int64)
    return np.meshgrid(sx, sy)


def frame(surf, p):
    p = _vec(p)
    H, W = surf.shape[:2]
    su = p['su']
    # how far the set goes: the 95th percentile of what the camera sees (a coarse grid, by bisection)
    X, Y = _grid(W, H, 96, 54)
    s = surf[Y, X]
    has = (s[..., 1] >= 0.5) & (s[..., 0] > 0)
    d = s[..., 0][has]
    n = len(d)
    if n:
        lo, hi = 0.0, float(d.max())
        for _ in range(14):
            mid = 0.5 * (lo + hi)
            if (d <= mid).sum() >= 0.95 * n:
                hi = mid
            else:
                lo = mid
        auto = max(hi * 1.15, 1.0 / su)
    else:
        auto = 20.0 / su
    reach = p['reach'] / su if p['reach'] > 0 else auto
    # the box of the set (clean surface within reach) and the light-space extent of everything the rays cross
    X, Y = _grid(W, H, 192, 108)
    s = surf[Y, X].reshape(-1, 4)
    D = ray_dir(p, X.reshape(-1) + 0.5, Y.reshape(-1) + 0.5, W, H)
    has = (s[:, 1] >= 0.5) & (s[:, 0] > 0)
    inbox = has & (s[:, 0] <= reach)
    dist = np.where(inbox, s[:, 0], reach)
    P = p['cam_pos'] + D * dist[:, None]
    if inbox.any():
        lo, hi = P[inbox].min(0), P[inbox].max(0)
        npts = int(inbox.sum())
    else:
        lo, hi, npts = p['cam_pos'] - 5.0 / su, p['cam_pos'] + 5.0 / su, 0
    lo, hi = np.minimum(lo, p['cam_pos']), np.maximum(hi, p['cam_pos'])
    lt = Light(p)
    allp = np.concatenate([P, p['cam_pos'][None]], 0)
    lu = (allp - lt.aim) @ lt.R
    lv = (allp - lt.aim) @ lt.U
    ext = max(lu.max() - lu.min(), lv.max() - lv.min(), 0.1 / su)
    s_raw = ext / (p['lm_n'] - 4)
    step = 2.0 ** (math.ceil(math.log(s_raw) / math.log(2.0) * 4.0) / 4.0)
    u0 = (math.floor(lu.min() / step) - 1) * step
    v0 = (math.floor(lv.min() / step) - 1) * step
    out = np.zeros((1, 4, 4))
    out[0, 0] = [lo[0], lo[1], lo[2], npts]
    out[0, 1] = [hi[0], hi[1], hi[2], reach]
    out[0, 2] = [u0, v0, step, 0.0]
    return out


# ---------------------------------------------------------------------------------------------------------------------
#  Openings: the depth of windows and other gaps to the sky, at 1/8 of the frame's size
# ---------------------------------------------------------------------------------------------------------------------
def blocks(surf, fr, w, h):
    H, W = surf.shape[:2]
    reach = fr[0, 1, 3]
    out = np.zeros((h, w, 4))
    ok = (surf[..., 1] >= 0.5) & (surf[..., 0] > 0) & (surf[..., 0] <= reach)
    d = np.where(ok, surf[..., 0], 0.0)
    for cy in range(h):
        y0, y1 = (cy * H) // h, max(((cy + 1) * H) // h, (cy * H) // h + 1)
        for cx in range(w):
            x0, x1 = (cx * W) // w, max(((cx + 1) * W) // w, (cx * W) // w + 1)
            out[cy, cx, 0] = d[y0:y1, x0:x1].max()
    return out


DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def openings(bl):
    h, w = bl.shape[:2]
    d = bl[..., 0]
    out = np.zeros((h, w, 4))
    for cy in range(h):
        for cx in range(w):
            if d[cy, cx] > 0:
                out[cy, cx, :2] = d[cy, cx], 1.0
                continue
            acc = wsum = 0.0
            for dx, dy in DIRS:
                step = 1.41421356 if (dx and dy) else 1.0
                k = 1
                while True:
                    x, y = cx + dx * k, cy + dy * k
                    if x < 0 or y < 0 or x >= w or y >= h:
                        break
                    if d[y, x] > 0:
                        wt = 1.0 / (k * step)
                        acc += d[y, x] * wt
                        wsum += wt
                        break
                    k += 1
            if wsum > 0:
                out[cy, cx, :2] = acc / wsum, 1.0
    return out



# ---------------------------------------------------------------------------------------------------------------------
#  The light map: for each pixel of the light's view, how far the light gets (r) and where it enters the set (g)
# ---------------------------------------------------------------------------------------------------------------------
def _blocked(p, surf, X, thick_su, bias):
    H, W = surf.shape[:2]
    px, py, z = project(p, X, W, H)
    on = (z > 0) & (px >= 0) & (py >= 0) & (px < W) & (py < H)
    xi = np.clip(np.where(on, px, 0).astype(np.int64), 0, W - 1)
    yi = np.clip(np.where(on, py, 0).astype(np.int64), 0, H - 1)
    s = surf[yi, xi]
    xd = np.linalg.norm(X - p['cam_pos'], axis=-1)
    return on & (s[..., 1] >= 0.5) & (s[..., 0] > 0) & (xd > s[..., 0] * 1.003 + bias) & (xd < s[..., 0] + thick_su)


def _slab(O, D, lo, hi):
    Ds = np.where(np.abs(D) < 1e-9, 1e-9, D)
    t1 = (lo - O) / Ds
    t2 = (hi - O) / Ds
    return np.minimum(t1, t2).max(-1), np.maximum(t1, t2).min(-1)


def light_rays(p, fr, n):
    """Origin and direction of the light ray through each light-map pixel (n x n), as the lightmap kernel has them."""
    lt = Light(p)
    j, i = np.mgrid[0:n, 0:n]
    if lt.kind == 0:
        u0, v0, step = fr[0, 2, :3]
        lu = u0 + (i + 0.5) * step
        lv = v0 + (j + 0.5) * step
        O = lt.aim + lu[..., None] * lt.R + lv[..., None] * lt.U
        D = np.broadcast_to(lt.F, O.shape)
    else:
        uu = (i + 0.5) / n * 2 - 1
        vv = (j + 0.5) / n * 2 - 1
        D = lt.F + (uu * lt.tanc)[..., None] * lt.R + (vv * lt.tanc)[..., None] * lt.U
        D = D / np.linalg.norm(D, axis=-1, keepdims=True)
        O = np.broadcast_to(lt.pos, D.shape)
    return lt, O, D


def lightmap(surf, fr, p, opn, size=None):
    p = _vec(p)
    n = int(p['lm_n'])
    size = size or n
    out = np.zeros((size, size, 4))
    out[..., 0] = BIG
    out[..., 1] = BIG
    if int(p['shadows']) == 1:
        return out
    su = p['su']
    H, W = surf.shape[:2]
    lt, O, D = light_rays(p, fr, n)
    lo, hi = fr[0, 0, :3], fr[0, 1, :3]
    pad = 0.01 * np.linalg.norm(hi - lo) + 0.01 / su
    lo2, hi2 = lo - pad, hi + pad
    tn, tf = _slab(O, D, lo2, hi2)
    if lt.kind == 1:
        tn = np.maximum(tn, 0.0)
    hit = tf > tn
    res = np.zeros((n, n, 4))
    res[..., 0] = BIG
    res[..., 1] = BIG
    res[..., 1] = np.where(hit, tn, BIG)
    inside = lt.kind == 1 and np.all(lt.pos > lo2) and np.all(lt.pos < hi2)
    openm = np.full((n, n), int(p['interior']) == 0 or inside)
    thick_su = p['thick'] / su
    bias = 0.005 / su
    reach = fr[0, 1, 3]
    N = int(p['lm_steps'])
    t0 = tn.copy()
    pre = ~openm
    t0 = np.where(pre, tn - (0.05 * np.linalg.norm(hi - lo) + thick_su), tn)
    if lt.kind == 1:
        t0 = np.maximum(t0, 0.0)
    oh, ow = opn.shape[:2]
    dt = (tf - t0) / N
    tb = np.full((n, n), BIG)
    found = np.zeros((n, n), bool)
    closed = np.zeros((n, n), bool)
    for k in range(N):
        act = hit & ~found & ~closed
        t = t0 + (k + 0.5) * dt
        X = O + D * t[..., None]
        px, py, z = project(p, X, W, H)
        on = act & (z > 0) & (px >= 0) & (py >= 0) & (px < W) & (py < H)
        xi = np.clip(np.where(on, px, 0).astype(np.int64), 0, W - 1)
        yi = np.clip(np.where(on, py, 0).astype(np.int64), 0, H - 1)
        sv = surf[yi, xi]
        xd = np.linalg.norm(X - p['cam_pos'], axis=-1)
        b = on & (sv[..., 1] >= 0.5) & (sv[..., 0] > 0) & (xd > sv[..., 0] * 1.003 + bias) & \
            (xd < sv[..., 0] + thick_su)
        tb = np.where(b, t, tb)
        found |= b
        rest = on & ~b & ~openm
        sky = (sv[..., 1] <= 0.02) | (sv[..., 0] <= 0) | (sv[..., 0] > reach)
        seen = sv[..., 0] > xd * 1.003 + bias
        oxi = np.clip((px * ow / W).astype(np.int64), 0, ow - 1)
        oyi = np.clip((py * oh / H).astype(np.int64), 0, oh - 1)
        o = opn[np.where(on, oyi, 0), np.where(on, oxi, 0)]
        beyond = (o[..., 1] < 0.5) | (xd > o[..., 0] * 1.003 + bias)
        newly = rest & sky & beyond
        openm = openm | newly
        seen = np.where(sky, ~beyond, seen)
        c = rest & ~newly & seen
        tb = np.where(c, t0, tb)
        closed |= c
    never = hit & ~openm
    tb = np.where(never, t0, tb)
    found = found & ~never
    a = np.maximum(tb - dt, t0)
    b = tb.copy()
    for _ in range(5):
        m = 0.5 * (a + b)
        bl = _blocked(p, surf, O + D * m[..., None], thick_su, bias)
        b = np.where(found & bl, m, b)
        a = np.where(found & ~bl, m, a)
    tb = np.where(found, b, tb)
    res[..., 0] = tb
    res[..., 2] = (hit & openm).astype(np.float64)
    out[:n, :n] = res
    return out


# ---------------------------------------------------------------------------------------------------------------------
#  Noise
# ---------------------------------------------------------------------------------------------------------------------
def _fade(f):
    return f * f * f * (f * (f * 6.0 - 15.0) + 10.0)


def noise_atlas(seed):
    """r, g: two independent smooth noises (value noise, cell = 8 voxels, tiling every 64 voxels)."""
    y, x = np.mgrid[0:NV * NT, 0:NV * NT]
    i, j = x % NV, y % NV
    k = (y // NV) * NT + (x // NV)
    out = np.zeros((NV * NT, NV * NT, 4))
    vox = (i, j, k)
    cell = [v // NCELL for v in vox]
    w = [_fade((v % NCELL) / float(NCELL)) for v in vox]
    nc = NV // NCELL
    for c in range(2):
        acc = 0.0
        for dz in (0, 1):
            for dy in (0, 1):
                for dx in (0, 1):
                    cx, cy, cz = (cell[0] + dx) % nc, (cell[1] + dy) % nc, (cell[2] + dz) % nc
                    idx = cx + nc * (cy + nc * cz)
                    val = rng.uniform_np(rng.hash_np(np.full(idx.shape, seed & rng.M32, np.uint64), rng.NOISE, c,
                                                     idx.astype(np.uint32)))
                    wt = (w[0] if dx else 1 - w[0]) * (w[1] if dy else 1 - w[1]) * (w[2] if dz else 1 - w[2])
                    acc = acc + wt * val
        out[..., c] = acc
    return out


def _posmod(a, m):
    return ((a % m) + m) % m


def noise_sample(nz, q):
    """Trilinear, wrapping: the r and g noises at voxel coordinates q (..., 3)."""
    f = np.floor(q)
    i0 = _posmod(f.astype(np.int64), NV)
    i1 = (i0 + 1) % NV
    w = q - f
    acc = 0.0
    for dz in (0, 1):
        kz = i1[..., 2] if dz else i0[..., 2]
        for dy in (0, 1):
            jy = i1[..., 1] if dy else i0[..., 1]
            for dx in (0, 1):
                ix = i1[..., 0] if dx else i0[..., 0]
                v = nz[(kz // NT) * NV + jy, (kz % NT) * NV + ix, :2]
                wt = (w[..., 0] if dx else 1 - w[..., 0]) * (w[..., 1] if dy else 1 - w[..., 1]) * \
                    (w[..., 2] if dz else 1 - w[..., 2])
                acc = acc + wt[..., None] * v
    return acc


ROT = np.array([[0.8, -0.36, 0.48], [0.6, 0.48, -0.64], [0.0, 0.8, 0.6]])


# ---------------------------------------------------------------------------------------------------------------------
#  The light at points in the air (shared by the march and the light-on-set view)
# ---------------------------------------------------------------------------------------------------------------------
class Lighting(object):
    def __init__(self, p, fr, lm, cuc):
        self.p = p
        self.lt = Light(p)
        self.fr, self.lm, self.cuc = fr, lm, cuc
        self.col = p['light_col'] * kelvin_rgb(p['light_k'])
        self.n = int(p['lm_n'])

    def texel(self, lu, lv):
        if self.lt.kind == 0:
            u0, v0, step = self.fr[0, 2, :3]
            return (lu - u0) / step, (lv - v0) / step
        return (lu * 0.5 + 0.5) * self.n, (lv * 0.5 + 0.5) * self.n

    def shadow(self, tx, ty, t, bias=0.0):
        n = self.n
        out = (tx < 0) | (ty < 0) | (tx >= n) | (ty >= n)
        fx, fy = tx - 0.5, ty - 0.5
        x0, y0 = np.floor(fx), np.floor(fy)
        ax, ay = fx - x0, fy - y0
        x0, y0 = x0.astype(np.int64), y0.astype(np.int64)
        v = 0.0
        for b in (0, 1):
            for a in (0, 1):
                xi = np.clip(x0 + a, 0, n - 1)
                yi = np.clip(y0 + b, 0, n - 1)
                tb = self.lm[yi, xi, 0]
                w = (ax if a else 1 - ax) * (ay if b else 1 - ay)
                v = v + w * (t < tb + bias)
        return np.where(out, 1.0, v)

    def entry(self, tx, ty):
        n = self.n
        xi = np.clip(tx.astype(np.int64), 0, n - 1)
        yi = np.clip(ty.astype(np.int64), 0, n - 1)
        return self.lm[yi, xi, 1]

    def cuc_at(self, lu, lv):
        p = self.p
        if self.lt.kind == 1:
            cu, cv = lu * 0.5 + 0.5, lv * 0.5 * p['cuc_aspect'] + 0.5
        else:
            sz = p['cuc_size'] / p['su']
            cu, cv = lu / sz + 0.5, lv / sz * p['cuc_aspect'] + 0.5
        mode = int(p['cuc_outside'])
        H, W = self.cuc.shape[:2]
        px, py = cu * W - 0.5, cv * H - 0.5
        x0, y0 = np.floor(px), np.floor(py)
        ax, ay = px - x0, py - y0
        x0, y0 = x0.astype(np.int64), y0.astype(np.int64)
        v = 0.0
        for b in (0, 1):
            for a in (0, 1):
                if mode == 2:
                    xi, yi = _posmod(x0 + a, W), _posmod(y0 + b, H)
                else:
                    xi, yi = np.clip(x0 + a, 0, W - 1), np.clip(y0 + b, 0, H - 1)
                w = (ax if a else 1 - ax) * (ay if b else 1 - ay)
                v = v + w[..., None] * np.maximum(self.cuc[yi, xi, :3], 0.0)
        if mode != 2:
            outside = (cu < 0) | (cu > 1) | (cv < 0) | (cv > 1)
            v = np.where(outside[..., None], 0.0 if mode == 0 else 1.0, v)
        return v

    def weight(self, X, lu, lv, lt_, ok, tx, ty, haze_ext=True):
        """Everything but the shadow and the cuc: cone, distance falloff, fade along the light."""
        p = self.p
        w = ok.astype(np.float64)
        if self.lt.kind == 1:
            r = np.sqrt(lu * lu + lv * lv)
            soft = max(p['cone_soft'], 1e-4)
            w = w * (1.0 - smooth01((r - (1.0 - p['cone_soft'])) / soft))
            dm = np.maximum(lt_ * p['su'], 0.01)
            w = w * np.minimum(np.power(p['light_dist'] / dm, 2.0 * p['falloff']), 100.0)
        te = self.entry(tx, ty)
        run = np.where(te < BIG * 0.5, np.maximum(lt_ - te, 0.0), 0.0) * p['su']
        ext = p['haze'] * HAZE_K + (1.0 / p['fade'] if p['fade'] > 0 else 0.0)
        return w * np.exp(-run * ext)


# ---------------------------------------------------------------------------------------------------------------------
#  The march
# ---------------------------------------------------------------------------------------------------------------------
def pixel_jitter(mx, my):
    """Where each march pixel's steps start (0..1 of a step): stratified over every 4 x 4 block of pixels."""
    mx, my = np.asarray(mx, np.int64), np.asarray(my, np.int64)
    xa = (mx ^ my) & 3
    bay = ((xa & 1) << 3) | ((my & 1) << 2) | (((xa >> 1) & 1) << 1) | ((my >> 1) & 1)
    u = rng.uniform_np(rng.hash_np(np.full(np.shape(mx), JIT, np.uint64), mx.astype(np.uint32), my.astype(np.uint32)))
    return (bay + u) / 16.0


def density(p, nz, X):
    su = p['su']
    ym = X[..., 1] * su
    base = p['haze'] + p['fog'] * np.exp(-np.maximum(ym - p['fog_height'], 0.0) / max(p['fog_falloff'], 0.01))
    sig = base * HAZE_K
    if p['breakup'] > 0:
        a = p['drift_dir'] * math.pi / 180.0
        tsec = p['frame'] / p['fps']
        off = np.array([math.cos(a), 0.0, math.sin(a)]) * (p['drift'] * tsec)
        q = (X * su + off) / p['breakup_size'] * NCELL
        n1 = noise_sample(nz, q)[..., 0]
        if int(p['octaves']) > 1:
            q2 = (q @ ROT.T) * 2.17 + np.array([17.3, 5.1, 31.7])
            n = 0.62 * n1 + 0.38 * noise_sample(nz, q2)[..., 1]
        else:
            n = n1
        m = np.clip((n - 0.5) * 3.0 + 0.5, 0.0, 1.0)
        sig = sig * np.maximum(1.0 + p['breakup'] * (2.0 * m - 1.0), 0.0)
    return sig


def march(w, h, surf, fr, lm, cuc, nz, p):
    p = _vec(p)
    H, W = surf.shape[:2]
    su = p['su']
    sx, sy = W / float(w), H / float(h)
    yy, xx = np.mgrid[0:h, 0:w]
    ix = np.clip(((xx + 0.5) * sx).astype(np.int64), 0, W - 1)
    iy = np.clip(((yy + 0.5) * sy).astype(np.int64), 0, H - 1)
    s = surf[iy, ix]
    reach = fr[0, 1, 3]
    d = ray_dir(p, ix + 0.5, iy + 0.5, W, H)
    if p['reach'] > 0:
        sky = np.full((h, w), reach)
    else:
        lo, hi = fr[0, 0, :3], fr[0, 1, :3]
        pad = 0.01 * np.linalg.norm(hi - lo) + 0.01 / su
        tn, tf = _slab(np.broadcast_to(p['cam_pos'], d.shape), d, lo - pad, hi + pad)
        sky = np.minimum(np.where(tf > np.maximum(tn, 0.0), tf, 0.0), reach)
    D = np.where((s[..., 1] >= 0.02) & (s[..., 0] > 0), np.minimum(s[..., 0], reach), sky)
    jit = pixel_jitter(xx, yy)
    L = Lighting(p, fr, lm, cuc)
    lt = L.lt
    col = L.col
    amb = p['ambient'] * p['ambient_rgb'] * (0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2])
    N = int(p['steps'])
    dt = D / N
    T = np.ones((h, w))
    acc = np.zeros((h, w, 3))
    for k in range(N):
        t = (k + jit) * dt
        X = p['cam_pos'] + d * t[..., None]
        sig = density(p, nz, X)
        lu, lv, ltt, ok = lt.coords(X)
        tx, ty = L.texel(lu, lv)
        wgt = L.shadow(tx, ty, ltt) * L.weight(X, lu, lv, ltt, ok, tx, ty)
        if int(p['use_cuc']):
            cc = L.cuc_at(lu, lv)
        else:
            cc = 1.0
        if lt.kind == 0:
            Ld = np.broadcast_to(lt.F, X.shape)
        else:
            Ld = X - lt.pos
            Ld = Ld / np.maximum(np.linalg.norm(Ld, axis=-1, keepdims=True), 1e-12)
        ph = hg(-(Ld * d).sum(-1), p['glow'])
        li = col * cc * (wgt * ph)[..., None]
        a = 1.0 - np.exp(-sig * dt * su)
        acc += (T * a)[..., None] * (li + amb)
        T = T * (1.0 - a)
    out = np.zeros((h, w, 4))
    out[..., :3] = acc
    out[..., 3] = 1.0 - T
    return out


# ---------------------------------------------------------------------------------------------------------------------
#  Back to full resolution
# ---------------------------------------------------------------------------------------------------------------------
UP_SIGMA = 0.85


def upsample(surf, mar, fr, p):
    H, W = surf.shape[:2]
    h, w = mar.shape[:2]
    su = p['su']
    sx, sy = W / float(w), H / float(h)
    reach = fr[0, 1, 3]

    def depth(s):
        return np.where((s[..., 1] >= 0.02) & (s[..., 0] > 0), np.minimum(s[..., 0], reach), reach)
    Dp = depth(surf)
    yy, xx = np.mgrid[0:H, 0:W]
    lx = (xx + 0.5) / sx - 0.5
    ly = (yy + 0.5) / sy - 0.5
    i0 = np.floor(lx).astype(np.int64) - 1
    j0 = np.floor(ly).astype(np.int64) - 1
    acc = np.zeros((H, W, 4))
    wsum = np.zeros((H, W))
    best = np.zeros((H, W, 4))
    bestd = np.full((H, W), np.inf)
    eps = 0.01 / su
    for b in range(4):
        for a in range(4):
            iu, ju = i0 + a, j0 + b
            i, j = np.clip(iu, 0, w - 1), np.clip(ju, 0, h - 1)
            qx = np.clip(((i + 0.5) * sx).astype(np.int64), 0, W - 1)
            qy = np.clip(((j + 0.5) * sy).astype(np.int64), 0, H - 1)
            Dq = depth(surf[qy, qx])
            ws = np.exp(-0.5 * ((iu - lx) ** 2 + (ju - ly) ** 2) / (UP_SIGMA * UP_SIGMA))
            rel = (Dq - Dp) / (0.02 * Dp + eps)
            wt = ws * np.exp(-0.5 * rel * rel)
            m = mar[j, i]
            acc += wt[..., None] * m
            wsum += wt
            dd = np.abs(Dq - Dp)
            better = dd < bestd
            best = np.where(better[..., None], m, best)
            bestd = np.where(better, dd, bestd)
    return np.where((wsum > 1e-4)[..., None], acc / np.maximum(wsum, 1e-30)[..., None], best)


# ---------------------------------------------------------------------------------------------------------------------
#  The light on the set
# ---------------------------------------------------------------------------------------------------------------------
def onset(surf, nrm, fr, lm, cuc, p):
    p = _vec(p)
    H, W = surf.shape[:2]
    su = p['su']
    yy, xx = np.mgrid[0:H, 0:W]
    d = ray_dir(p, xx + 0.5, yy + 0.5, W, H)
    has = (surf[..., 1] >= 0.02) & (surf[..., 0] > 0)
    P = p['cam_pos'] + d * surf[..., 0:1]
    n = nrm[..., :3]
    hasn = np.linalg.norm(n, axis=-1) > 0.1
    Nn = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-12)
    L = Lighting(p, fr, lm, cuc)
    lt = L.lt
    lu, lv, ltt, ok = lt.coords(P)
    tx, ty = L.texel(lu, lv)
    if lt.kind == 0:
        texel_su = fr[0, 2, 2]
        to = np.broadcast_to(lt.L, P.shape)
    else:
        texel_su = ltt * 2.0 * lt.tanc / L.n
        to = lt.pos - P
        to = to / np.maximum(np.linalg.norm(to, axis=-1, keepdims=True), 1e-12)
    bias = 2.0 * texel_su + 0.02 / su
    wgt = L.shadow(tx, ty, ltt, bias) * L.weight(P, lu, lv, ltt, ok, tx, ty)
    cc = L.cuc_at(lu, lv) if int(p['use_cuc']) else 1.0
    ndl = np.where(hasn, np.maximum((Nn * to).sum(-1), 0.0), 1.0)
    light = L.col * cc * (wgt * ndl)[..., None]
    lum = 0.2126 * L.col[0] + 0.7152 * L.col[1] + 0.0722 * L.col[2]
    shade = 0.012 * lum * np.where(hasn, 0.55 + 0.45 * Nn[..., 1], 1.0)
    out = np.zeros((H, W, 4))
    out[..., :3] = np.where(has[..., None], 0.18 * light + shade[..., None], 0.0)
    out[..., 3] = 1.0
    return out


# ---------------------------------------------------------------------------------------------------------------------
#  Params from settings and a camera
# ---------------------------------------------------------------------------------------------------------------------
QUALITY = {'preview': dict(res=0.25, steps=48, lm_n=512, lm_steps=160, octaves=1),
           'final': dict(res=0.5, steps=96, lm_n=1024, lm_steps=224, octaves=2),
           'best': dict(res=1.0, steps=128, lm_n=1024, lm_steps=256, octaves=2)}


def params(settings, cam, frame_no, quality='final', **over):
    """Kernel params from a settings dict (schema keys, enums as text) and a camera (rayfield.camera.Camera)."""
    from . import schema
    s = schema.defaults()
    s.update(settings)
    su = schema.UNIT_METRES[s['units']]
    q = dict(QUALITY[quality])
    opt = lambda k: schema.BY_KEY[k].options.index(s[k]) if isinstance(s[k], str) else int(s[k])
    p = dict(frame=float(frame_no), fps=s['fps'], su=su,
             cam_pos=cam.pos, cam_right=cam.right, cam_up=cam.up, cam_back=cam.back, cam_th=math.tan(cam.hfov / 2),
             p_premult=-1, z_kind=-1, z_premult=-1,
             light_type=opt('light_type'), aim=np.asarray(s['aim'], np.float64), light_az=s['light_az'],
             light_el=s['light_el'], roll=s['roll'], light_dist=s['distance'], cone=s['cone'],
             cone_soft=s['cone_soft'], falloff=s['falloff'], light_k=s['light_k'],
             light_col=np.asarray(s['light_rgb'], np.float64) * s['intensity'] * 2.0 ** s['exposure'],
             haze=s['haze'], glow=s['glow'], ambient=s['ambient'], ambient_rgb=np.asarray(s['ambient_rgb']),
             fade=s['fade'], fog=s['fog'], fog_height=s['fog_height'], fog_falloff=s['fog_falloff'],
             breakup=s['breakup'], breakup_size=s['breakup_size'], drift=s['drift'], drift_dir=s['drift_dir'],
             seed=int(s['seed']), use_cuc=1 if (s['cuc_on'] and s.get('_cuc') is not None) else 0,
             cuc_size=s['cuc_size'], cuc_aspect=float(s.get('_cuc_aspect', 1.0)), cuc_outside=opt('cuc_outside'),
             shadows=opt('shadows'), interior=1 if s['interior'] else 0, thick=s['thick'], reach=s['reach'],
             lm_n=q['lm_n'], lm_steps=q['lm_steps'], steps=q['steps'], octaves=q['octaves'])
    p.update(over)
    return p, q['res']
