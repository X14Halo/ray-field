"""Runs the node's kernels in the order the node does, through the C++ stand-in for Blink (tests and pictures only).
Images are row 0 at the bottom (Nuke's), as the kernels see them.

    out = render(shot, frame_no, settings, quality='final', cuc=None)
    out['rgba'] (full res), out['march'], out['lmap'], out['surf'], out['info'], out['onset'] (if asked), ...
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import run                                    # noqa: E402
from node import blinklib as bl               # noqa: E402
from rayfield import reference                # noqa: E402


def up(img):
    """Row 0 at the top -> row 0 at the bottom (and back)."""
    return np.ascontiguousarray(img[::-1])


def pass_images(shot, f):
    """What the node's shuffles make from the utility pass: pos (P, coverage), depth (depth, unfiltered), normals."""
    W, H = shot.resolution(f)
    P, A, Zr, N = shot.read(f, 'P'), shot.read(f, 'A'), shot.read(f, 'Zraw'), shot.read(f, 'N')
    pos = np.zeros((H, W, 4), np.float32)
    pos[..., :3] = P
    pos[..., 3] = A
    depth = np.zeros((H, W, 4), np.float32)
    depth[..., 1] = Zr
    nrm = np.zeros((H, W, 4), np.float32)
    nrm[..., :3] = N
    return up(pos), up(depth), up(nrm)


def low_size(W, H, res):
    """The size Nuke's Reformat (type scale) gives the march image."""
    return max(int(round(W * res)), 1), max(int(round(H * res)), 1)


def kernel(name, p, inputs, space=None):
    src = bl.source(name)
    names = [n for t, n in bl.params(src)]
    pp = {}
    for n in names:
        v = p[n]
        pp[n] = list(v) if isinstance(v, (list, tuple, np.ndarray)) else v
    ins = dict(inputs)
    if space is not None:
        ins = dict([('space', np.zeros((space[1], space[0], 4), np.float32))] + list(ins.items()))
    return run.run(name, pp, ins)


def render(shot, f, settings=None, quality='final', cuc=None, onset=False, lm_space=None, res=None, **over):
    """settings: schema keys; cuc: an (H, W, 3/4) image row 0 at the TOP (as you would paint it), or None."""
    settings = dict(settings or {})
    if cuc is not None:
        settings['_cuc'] = True
        settings['_cuc_aspect'] = cuc.shape[1] / float(cuc.shape[0])
    cam = shot.camera(f)
    p, qres = reference.params(settings, cam, f, quality, **over)
    res = res or qres
    pos, depth, nrm = pass_images(shot, f)
    H, W = pos.shape[:2]
    out = dict(params=p)
    facts = kernel('facts', p, {'pos': pos, 'depth': depth}, (3, 1))
    surf = kernel('surface', p, {'pos': pos, 'depth': depth, 'facts': facts})
    info = kernel('frame', p, {'surf': surf}, (4, 1))
    bw, bh = low_size(W, H, 0.125)
    blocks = kernel('blocks', p, {'surf': surf, 'info': info}, (bw, bh))
    opn = kernel('openings', p, {'blocks': blocks})
    n = lm_space or bl.LM_MAX
    lmap = kernel('lightmap', p, {'surf': surf, 'info': info, 'opn': opn}, (n, n))
    noise = kernel('noise', p, {}, (bl.NOISE_W, bl.NOISE_W))
    cimg = np.ones((16, 16, 4), np.float32) if cuc is None else up(cuc_square(cuc))
    w, h = low_size(W, H, res)
    mar = kernel('march', p, {'surf': surf, 'info': info, 'lmap': lmap, 'cuc': cimg, 'noise': noise}, (w, h))
    rgba = kernel('up', p, {'surf': surf, 'mar': mar, 'info': info})
    out.update(facts=facts, surf=surf, info=info, blocks=blocks, opn=opn, lmap=lmap, noise=noise, cuc=cimg, march=mar, rgba=rgba, nrm=nrm)
    if onset:
        out['onset'] = kernel('onset', p, {'surf': surf, 'nrm': nrm, 'info': info, 'lmap': lmap, 'cuc': cimg})
    return out


def cuc_square(img, n=None):
    """What the node does to the cuc input: stretched to a square (Reformat, distort), rgb kept. Nearest-neighbour
    here, which is enough for tests."""
    n = n or bl.CUC_W
    H, W = img.shape[:2]
    ys = np.minimum(((np.arange(n) + 0.5) * H / n).astype(int), H - 1)
    xs = np.minimum(((np.arange(n) + 0.5) * W / n).astype(int), W - 1)
    sq = img[ys][:, xs]
    out = np.zeros((n, n, 4), np.float32)
    out[..., :min(sq.shape[2], 4)] = sq[..., :4]
    if sq.shape[2] == 3:
        out[..., 3] = 1.0
    return out
