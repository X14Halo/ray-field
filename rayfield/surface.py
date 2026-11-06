"""What each pixel of one frame sees, made safe to use: coverage, world position (divided by coverage where the pass
was premultiplied), the distance to the surface for holdouts, and which pixels are a single clean surface.
Taken from MoteField (motefield/shot.py), unchanged: it is the Python twin of the facts and surface kernels.
"""

import numpy as np

class Surface(object):
    """What each pixel of one frame sees, made safe to use (see the module notes). All arrays are (H, W[, 3]).

        cov      coverage 0..1
        P        world position (scene units), divided by coverage where the pass was premultiplied; 0 where empty
        dist     distance from the camera to the surface, for holdouts (0 = nothing there)
        clean    a single surface fills the pixel: safe to use as a 3D point
        info     how it was worked out (for the shot check)
    """

    def __init__(self, W, H, cam, cov, P, dist, clean, info):
        self.W, self.H, self.cam = W, H, cam
        self.cov, self.P, self.dist, self.clean, self.info = cov, P, dist, clean, info

    def points(self, step=1):
        """(N, 3) clean world points, every step-th pixel."""
        m = self.clean[::step, ::step]
        return self.P[::step, ::step][m]


def _reproj_error(cam, P, W, H, mask, limit=20000):
    """Median distance, in pixels, from where each masked pixel's position projects to the pixel itself."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    if len(ys) > limit:
        pick = np.linspace(0, len(ys) - 1, limit).astype(np.intp)
        ys, xs = ys[pick], xs[pick]
    px, py, z = cam.project(P[ys, xs].astype(np.float64), W, H)
    err = np.hypot(px - (xs + 0.5), py - (ys + 0.5))
    err = np.where(z > 0, err, 1e9)
    return float(np.median(err))


def _depth_jumps(d, rel=0.04):
    """Pixels whose depth differs from a neighbour by more than rel: edges, where two surfaces meet."""
    j = np.zeros(d.shape, bool)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = d[max(dy, 0):d.shape[0] + min(dy, 0) or None, max(dx, 0):d.shape[1] + min(dx, 0) or None]
        b = d[max(-dy, 0):d.shape[0] + min(-dy, 0) or None, max(-dx, 0):d.shape[1] + min(-dx, 0) or None]
        big = np.abs(a - b) > rel * np.maximum(np.minimum(a, b), 1e-6)
        j[max(dy, 0):d.shape[0] + min(dy, 0) or None, max(dx, 0):d.shape[1] + min(dx, 0) or None] |= big
        j[max(-dy, 0):d.shape[0] + min(-dy, 0) or None, max(-dx, 0):d.shape[1] + min(-dx, 0) or None] |= big
    return j


def build_surface(cam, W, H, P=None, Z=None, Zraw=None, A=None):
    """A Surface from the raw layers of one frame (any may be None except one of P, Z, Zraw)."""
    info = {}
    f64 = np.float64
    if A is not None:
        cov = np.clip(A, 0.0, 1.0).astype(np.float32)
        info['coverage'] = 'alpha'
    else:
        have = np.zeros((H, W), bool)
        if P is not None:
            have |= np.abs(P).sum(-1) > 0
        for d in (Z, Zraw):
            if d is not None:
                have |= np.isfinite(d) & (d > 0)
        cov = have.astype(np.float32)
        info['coverage'] = 'none in the pass: taken as 1 wherever there is position or depth'
    some = cov > 0
    edge = (cov > 0.02) & (cov < 0.98)
    info['edge_pixels'] = int(edge.sum())
    info['empty_fraction'] = float(1.0 - some.mean())
    safe_cov = np.maximum(cov, 1e-6)[..., None]
    if P is not None:
        P = P.astype(np.float32)
        premult = False
        if edge.sum() >= 20:
            e_raw = _reproj_error(cam, P, W, H, edge)
            e_div = _reproj_error(cam, P / safe_cov, W, H, edge)
            info['edge_reprojection_px'] = dict(as_stored=e_raw, divided_by_coverage=e_div)
            premult = e_div is not None and e_raw is not None and e_div < e_raw
        info['position_premultiplied'] = premult
        if premult:
            P = np.where(some[..., None], P / safe_cov, 0.0).astype(np.float32)
        else:
            P = np.where(some[..., None], P, 0.0).astype(np.float32)
        ray = np.linalg.norm(P.astype(f64) - cam.pos, axis=-1)
    else:
        ray = None
    full = cov >= 0.98

    def as_distance(d, name):
        """A depth layer as distance along each pixel's ray: works out whether it was stored along the ray or along
        the view axis, and whether it was premultiplied, by comparing with the positions."""
        d = np.where(np.isfinite(d), d, 0.0).astype(f64)
        if ray is None:
            info[name + '_kind'] = 'assumed distance along the ray (no position layer to check against)'
            return np.where(some, np.maximum(d, 0.0), 0.0)
        m = full & (d > 0) & (ray > 0)
        kind = 'ray'
        if m.sum() >= 20:
            rays = cam.rays(W, H)
            cosang = np.abs(rays @ cam.back)                # 1 at the centre, less toward the corners
            along = np.median(np.abs(d[m] / ray[m] - 1))
            zdepth = np.median(np.abs(d[m] / (ray[m] * cosang[m]) - 1))
            if zdepth < along:
                kind = 'view axis'
                d = d / np.maximum(cosang, 1e-6)
        info[name + '_kind'] = 'distance along the ray' if kind == 'ray' else 'depth along the view axis (converted)'
        if edge.sum() >= 20:
            mm = edge & (ray > 0)
            raw_err = np.median(np.abs(d[mm] / ray[mm] - 1))
            div_err = np.median(np.abs(d[mm] / cov[mm] / ray[mm] - 1))
            if div_err < raw_err:
                info[name + '_premultiplied'] = True
                d = d / np.maximum(cov, 1e-6)
            else:
                info[name + '_premultiplied'] = False
        return np.where(some, np.maximum(d, 0.0), 0.0)

    zraw = as_distance(Zraw, 'unfiltered_depth') if Zraw is not None else None
    zf = as_distance(Z, 'depth') if Z is not None else None
    if zraw is not None:
        dist = zraw
        info['holdouts_from'] = 'unfiltered depth'
    elif zf is not None:
        dist = zf
        info['holdouts_from'] = 'depth'
    else:
        dist = np.where(some, ray, 0.0)
        info['holdouts_from'] = 'world position'
    if P is None:                                           # positions from depth and the camera
        P = (cam.pos + cam.rays(W, H) * dist[..., None]).astype(np.float32)
        P[~some] = 0
        ray = dist
        info['position_from'] = 'depth and the camera'
    # clean pixels: fully covered by one surface
    clean = full & (ray > 0)
    if zraw is not None:
        mixed = full & (np.abs(zraw - ray) > 0.02 * np.maximum(ray, 1e-6))
        info['mixed_by_unfiltered_depth'] = float(mixed.sum() / max(full.sum(), 1))
        clean &= ~mixed
    jumps = _depth_jumps(np.where(some, ray, 0.0))
    clean &= ~jumps
    info['clean_fraction'] = float(clean.sum() / max(some.sum(), 1))
    return Surface(W, H, cam, cov, P, dist.astype(np.float32), clean, info)


# ---------------------------------------------------------------------------------------------------------------------
#  The shot
