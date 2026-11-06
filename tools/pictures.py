"""Renders the stand-in room through the node's kernels (the C++ stand-in for Blink) and writes PNGs, for looking at
the look and for the docs. Nothing here goes into the node.

    python3 tools/pictures.py [out_folder]
"""
import os
import struct
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests', 'blink'))
import pipeline                                  # noqa: E402
from rayfield import standin                     # noqa: E402


def to8(img, exposure=1.0):
    """Scene-linear to 8-bit for looking: exposure, a soft shoulder, then sRGB-ish gamma."""
    x = np.clip(np.asarray(img, np.float64) * exposure, 0, None)
    x = x / (1.0 + 0.35 * x)
    x = x / (1.0 / (1.0 + 0.35))
    return (np.clip(x, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)


def save_png(path, img, exposure=1.0):
    img = to8(img[..., :3], exposure)
    h, w = img.shape[:2]
    raw = b''.join(b'\x00' + img[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + \
        chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')
    open(path, 'wb').write(png)


def window_cuc(n=256, bars=3, frame=0.06):
    """A window-frame cuc: panes with mullions (white = light through)."""
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    img = np.ones((n, n, 3), np.float32)
    edge = (x < frame) | (x > 1 - frame) | (y < frame) | (y > 1 - frame)
    mull = np.zeros_like(edge)
    for k in range(1, bars):
        mull |= np.abs(x - k / float(bars)) < frame * 0.4
        mull |= np.abs(y - k / float(bars)) < frame * 0.4
    img[edge | mull] = 0.0
    return img


def blinds_cuc(n=256, slats=14, open_=0.55):
    y, x = (np.mgrid[0:n, 0:n] + 0.5) / n
    img = np.ones((n, n, 3), np.float32)
    img[((y * slats) % 1.0) > open_] = 0.0
    return img


def shot_and_comp(view, W, H, f, settings, cuc=None, quality='final'):
    shot = standin.StandinShot(view, W, H)
    o = pipeline.render(shot, f, settings, quality=quality, cuc=cuc, onset=True)
    rgba = pipeline.up(o['rgba'])
    plate = shot.plate(f)
    return dict(plate=plate, atmo=rgba[..., :3], alpha=rgba[..., 3], plus=plate + rgba[..., :3],
                over=plate * (1 - rgba[..., 3:4]) + rgba[..., :3], onset=pipeline.up(o['onset'])[..., :3], out=o)


SUN = dict(intensity=6.0, light_k=5000.0, interior=True)


def main(folder):
    os.makedirs(folder, exist_ok=True)
    W, H = 960, 402
    looks = [
        ('wide', 'wide', dict(SUN, aim=(-150.0, 0.0, -250.0)), None),
        ('side', 'side', dict(SUN, aim=(-150.0, 0.0, -250.0)), None),
        ('closeup', 'close-up', dict(SUN, aim=(-150.0, 0.0, -250.0)), None),
        ('blinds', 'side', dict(SUN, aim=(-260.0, 0.0, -250.0), cuc_size=3.2, roll=0.0), blinds_cuc()),
        ('spot', 'side', dict(intensity=40.0, light_k=3200.0, light_type='spot', aim=(-50.0, 78.0, -285.0),
                              light_az=-120.0, light_el=60.0, distance=2.2, cone=50.0, haze=0.5),
         window_cuc()),
    ]
    for name, view, s, cuc in looks:
        r = shot_and_comp(view, W, H, 1001, s, cuc)
        save_png(os.path.join(folder, name + '_plus.png'), r['plus'])
        save_png(os.path.join(folder, name + '_atmo.png'), r['atmo'], 2.0)
        save_png(os.path.join(folder, name + '_onset.png'), r['onset'], 3.0)
        save_png(os.path.join(folder, name + '_plate.png'), r['plate'])
        print(name, 'atmo max %.3f mean %.3f' % (r['atmo'].max(), r['atmo'].mean()))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'out'))
