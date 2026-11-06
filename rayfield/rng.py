"""Randomness that comes out the same everywhere: an integer hash (PCG), in numpy and in the kernels.

The kernels do the hash in 16-bit halves (node/kernels/lib_hash.blink), so no integer ever overflows and every CPU
and GPU gives the same bits as these functions. Taken from MoteField (motefield/rng.py).
"""

import numpy as np

M32 = 0xFFFFFFFF
U24 = 1.0 / 16777216.0

NOISE = 0x4E4F4953       # 'NOIS': the breakup noise's lattice
JITTER = 0x4A495454      # 'JITT': where each pixel's march starts


def pcg(v):
    """PCG hash of a whole number, uint32 -> uint32 (plain Python ints)."""
    v = (v * 747796405 + 2891336453) & M32
    w = (((v >> ((v >> 28) + 4)) ^ v) * 277803737) & M32
    return ((w >> 22) ^ w) & M32


def hash_words(*words):
    """One uint32 from several: h = pcg(w0), then h = pcg(h + w) for each word after."""
    h = pcg(words[0] & M32)
    for w in words[1:]:
        h = pcg((h + w) & M32)
    return h


def uniform(h):
    """0 <= u < 1 from a hash, keeping 24 bits (exact in float32)."""
    return (h >> 8) * U24


_C1, _C2, _C3 = np.uint32(747796405), np.uint32(2891336453), np.uint32(277803737)


def pcg_np(v):
    """PCG hash of a uint32 array (wraps around like the GPU's uint)."""
    v = np.asarray(v, np.uint32)
    with np.errstate(over='ignore'):
        v = v * _C1 + _C2
        w = ((v >> ((v >> np.uint32(28)) + np.uint32(4))) ^ v) * _C3
    return (w >> np.uint32(22)) ^ w


def hash_np(words0, *words):
    """hash_words for arrays: words may be arrays or whole numbers."""
    # explicit types throughout: numpy 1.23 (Nuke 15) and numpy 2 promote mixed integer types differently
    h = pcg_np((np.asarray(words0).astype(np.uint64) & np.uint64(M32)).astype(np.uint32))
    with np.errstate(over='ignore'):
        for w in words:
            h = pcg_np(h + np.uint32(w) if np.isscalar(w) else h + np.asarray(w, np.uint32))
    return h


def uniform_np(h):
    return (np.asarray(h, np.uint32) >> np.uint32(8)).astype(np.float64) * U24
