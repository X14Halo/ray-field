"""The node's Blink kernels: reads node/kernels/*.blink and fills in what they share (from MoteField's blinklib).

A kernel's source can say:

    //@include NAME      the code of node/kernels/NAME.blink goes here (helper functions)
    //@params a b c ...  (one or more lines) the params this kernel takes, from PARAMS below
    //@decl              where their declarations go (in the param: section)
    //@define            where their defineParam calls go (in define())
    @NAME@               a constant from CONSTS

so every kernel declares a shared param with the same name, type and default, and the node links each one to the
same expression.
"""
import os
import re

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kernels')

LM_MAX = 1024             # the light map's image (only lm_n x lm_n of it is used)
NOISE_W = 512             # the noise atlas: 8 x 8 tiles of 64 x 64
CUC_W = 1024              # the cuc, reformatted to a square
HAZE_K = 0.05            # extinction per metre at Haze 1 (rayfield/lightmath.HAZE_K)
CONSTS = dict(JITTER=0x4A495454, NOISE=0x4E4F4953, HAZE_K='%.6ff' % HAZE_K)

# name: (Blink type, default). The node drives them all by expression.
PARAMS = {
    # time and units
    'frame': ('float', 1001.0), 'fps': ('float', 24.0), 'su': ('float', 0.01),
    # the camera on the frame (th = tan of half the horizontal view angle)
    'cam_pos': ('float3', (0.0, 150.0, 400.0)), 'cam_right': ('float3', (1.0, 0.0, 0.0)),
    'cam_up': ('float3', (0.0, 1.0, 0.0)), 'cam_back': ('float3', (0.0, 0.0, 1.0)), 'cam_th': ('float', 0.5),
    # the utility pass (what the node worked out about it, or what the user set; -1 = auto)
    'p_premult': ('int', -1), 'z_kind': ('int', -1), 'z_premult': ('int', -1),
    # the light
    'light_type': ('int', 0), 'aim': ('float3', (0.0, 0.0, 0.0)), 'light_az': ('float', 25.0),
    'light_el': ('float', 33.0), 'roll': ('float', 0.0), 'light_dist': ('float', 4.0), 'cone': ('float', 40.0),
    'cone_soft': ('float', 0.2), 'falloff': ('float', 1.0), 'light_k': ('float', 5600.0),
    'light_col': ('float3', (1.0, 1.0, 1.0)),
    # the air
    'haze': ('float', 0.3), 'glow': ('float', 0.5), 'ambient': ('float', 0.02),
    'ambient_rgb': ('float3', (0.85, 0.92, 1.0)), 'fade': ('float', 0.0), 'fog': ('float', 0.0),
    'fog_height': ('float', 0.5), 'fog_falloff': ('float', 0.5), 'breakup': ('float', 0.5),
    'breakup_size': ('float', 0.6), 'drift': ('float', 0.05), 'drift_dir': ('float', 0.0), 'seed': ('int', 1),
    'reach': ('float', 0.0),
    # the cuc
    'use_cuc': ('int', 0), 'cuc_size': ('float', 3.0), 'cuc_aspect': ('float', 1.0), 'cuc_outside': ('int', 0),
    # shadows
    'shadows': ('int', 0), 'interior': ('int', 0), 'thick': ('float', 0.4),
    # quality
    'lm_n': ('int', 1024), 'lm_steps': ('int', 224), 'steps': ('int', 96), 'octaves': ('int', 2),
}


def _literal(t, v):
    if t == 'int':
        return str(int(v))
    if t == 'float':
        return _f(v)
    return '%s(%s)' % (t, ', '.join(_f(x) for x in v))


def _f(x):
    s = repr(float(x))
    if 'e' in s or 'E' in s:
        s = '%.9f' % float(x)
    return s + 'f'


def source(name):
    """The full source of kernel `name` (node/kernels/NAME.blink), includes and params filled in."""
    text = open(os.path.join(HERE, name + '.blink')).read()

    def inc(m):
        return source(m.group(1)).rstrip('\n')
    text = re.sub(r'^//@include (\w+)\s*$', inc, text, flags=re.M)
    pm = re.search(r'^//@params((?:[ \t]+\w+)+(?:\n//@params(?:[ \t]+\w+)+)*)\s*$', text, flags=re.M)
    if pm:
        names = re.findall(r'\w+', pm.group(1).replace('//@params', ' '))
        names = [n for n in names if n != 'params']
        for n in names:
            if n not in PARAMS:
                raise KeyError('%s: unknown param %s' % (name, n))
        if len(set(names)) != len(names):
            raise KeyError('%s: a param is listed twice' % name)
        decl = '\n'.join('    %s %s;' % (PARAMS[n][0], n) for n in names)
        define = '\n'.join('    defineParam(%s, "%s", %s);' % (n, n, _literal(*PARAMS[n])) for n in names)
        text = text[:pm.start()] + text[pm.end():]
        text = re.sub(r'^\s*//@decl\s*$', decl, text, count=1, flags=re.M)
        text = re.sub(r'^\s*//@define\s*$', define, text, count=1, flags=re.M)
    text = re.sub(r'@(\w+)@', lambda m: str(CONSTS[m.group(1)]), text)
    return text


def kernel_name(src):
    return re.search(r'kernel\s+(\w+)\s*:', src).group(1)


def params(src):
    """(type, name) of each param, in order."""
    m = re.search(r'param\s*:(.*?)(?:local\s*:|void\s+define)', src, re.S)
    return re.findall(r'(\w+)\s+(\w+)\s*;', m.group(1)) if m else []


def images(src):
    """Names of the kernel's images in order (the inputs, then the output)."""
    return re.findall(r'Image\s*<[^>]*>\s*(\w+)\s*;', src)


KERNELS = ('facts', 'surface', 'frame', 'blocks', 'openings', 'lightmap', 'noise', 'march', 'up', 'onset')
