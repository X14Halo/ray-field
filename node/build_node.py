"""Builds dist/RayField.nk: the whole tool as one Group node to paste or drag into a Nuke 15 script.

Nothing to install and nothing written to disk: the node carries its kernels (BlinkScript, which plain Nuke runs but
cannot edit) and its Python (in a hidden knob, run from memory). The knobs come from rayfield/schema.py.

    python3 node/build_node.py [out.nk]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from rayfield import __version__, schema       # noqa: E402
from node import blinklib as bl, nk             # noqa: E402

# ---------------------------------------------------------------------------------------------------------------------
#  The internal graph
# ---------------------------------------------------------------------------------------------------------------------
# kernel node: (kernel file, space (w, h) for a Constant, the name of another node to use as the space, or None;
#               inputs in the kernel's image order, after the space)
GRAPH = [
    ('rf_facts', 'facts', (3, 1), ['rf_pos', 'rf_depth']),
    ('rf_surface', 'surface', None, ['rf_pos', 'rf_depth', 'rf_facts']),
    ('rf_frame', 'frame', (4, 1), ['rf_surface']),
    ('rf_blocks', 'blocks', 'rf_low8', ['rf_surface', 'rf_frame']),
    ('rf_openings', 'openings', None, ['rf_blocks']),
    ('rf_lightmap', 'lightmap', (bl.LM_MAX, bl.LM_MAX), ['rf_surface', 'rf_frame', 'rf_openings']),
    ('rf_noise', 'noise', (bl.NOISE_W, bl.NOISE_W), []),
    ('rf_march', 'march', 'rf_low', ['rf_surface', 'rf_frame', 'rf_lightmap', 'rf_cuc', 'rf_noise']),
    ('rf_up', 'up', None, ['rf_surface', 'rf_march', 'rf_frame']),
    ('rf_onset', 'onset', None, ['rf_surface', 'rf_nrm', 'rf_frame', 'rf_lightmap', 'rf_cuc']),
]

UNITS_EXPR = 'parent.units==0?0.01:parent.units==1?1:parent.units==2?0.001:parent.units==3?0.0254:0.3048'
VEC3 = {'aim': ('aim', 'xyz'), 'ambient_rgb': ('ambient_rgb', 'rgb')}
CAM = ('cam_pos', 'cam_right', 'cam_up', 'cam_back')
QUALITY = {   # hidden knob: expression of rf_q (0 preview, 1 final, 2 best), as reference.QUALITY
    'rf_res': 'rf_q==0?0.25:rf_q==1?0.5:1',
    'rf_steps': 'rf_q==0?48:rf_q==1?96:128',
    'rf_lm': 'rf_q==0?512:1024',
    'rf_lm_steps': 'rf_q==0?160:rf_q==1?224:256',
    'rf_oct': 'rf_q==0?1:2',
}
PARAM_FROM = {'light_dist': 'distance', 'lm_n': 'rf_lm', 'lm_steps': 'rf_lm_steps', 'steps': 'rf_steps', 'octaves': 'rf_oct'}


def expression(param):
    """The expression a kernel param is linked to (a string, or one per component)."""
    if param == 'frame':
        return 'frame'
    if param == 'su':
        return UNITS_EXPR
    if param in CAM:
        return ['parent.%s.%s' % (param, c) for c in 'xyz']
    if param in VEC3:
        knob, comps = VEC3[param]
        return ['parent.%s.%s' % (knob, c) for c in comps]
    if param == 'light_col':
        return ['parent.light_rgb.%s*parent.intensity*pow(2,parent.exposure)' % c for c in 'rgb']
    if param in ('p_premult', 'z_kind', 'z_premult'):
        return 'parent.%s-1' % param
    if param == 'use_cuc':
        return 'parent.cuc_on*parent.rf_has_cuc'
    if param == 'cuc_aspect':
        return 'parent.rf_cuc_aspect'
    if param in PARAM_FROM:
        return 'parent.' + PARAM_FROM[param]
    return 'parent.' + param


# ---------------------------------------------------------------------------------------------------------------------
#  The node's knobs
# ---------------------------------------------------------------------------------------------------------------------
B = schema.BY_KEY

# knobs that are not settings in the schema: name -> (type, default, label, help, options)
EXTRA = {
    'p_premult': ('enum', 0, 'Positions premultiplied', 'Whether the position layer was premultiplied by coverage. '
                  'auto = worked out from the pass (by reprojecting edge pixels).', ['auto', 'no', 'yes']),
    'z_kind': ('enum', 0, 'Depth is distance along the view axis', 'auto = worked out by comparing with the '
               'positions; no = distance along each pixel\'s ray.', ['auto', 'no', 'yes']),
    'z_premult': ('enum', 0, 'Depth premultiplied', 'Whether the depth layers were premultiplied by coverage. auto '
                  '= worked out from the pass.', ['auto', 'no', 'yes']),
    'shutter': ('float', 180.0, 'Shutter angle', 'Read from the pass header (for motion blur, in a later version).',
                None),
    'shutter_mode': ('enum', 0, 'Shutter', 'Read from the pass header.', ['backward', 'centred', 'forward']),
    'shutter_shape': ('enum', 0, 'Shutter shape', 'Read from the pass header.', ['backwardsShape', 'box']),
}

TABS = [
    ('RayField', [
        ('status',),
        ('buttons', [('read_camera', 'Read camera'), ('check_shot', 'Check shot')]),
        ('div', 'Light'),
        'light_type', 'aim_xy', 'aim', 'light_az', 'light_el', 'distance', 'cone', 'cone_soft',
        'intensity', 'exposure', 'light_rgb', 'light_k',
        ('div', 'Air'),
        'haze', 'glow', 'ambient', 'fog', 'fog_height', 'fog_falloff', 'breakup', 'breakup_size', 'drift',
        ('div', 'Cuc'),
        'cuc_on', 'cuc_from', 'cuc_size', 'roll', 'cuc_soft', 'cuc_outside',
        ('div', 'Output'),
        'output_mode', 'alpha_out', 'view', 'viewer_quality', 'render_quality', 'use_gpu',
        ('report',),
    ]),
    ('More', [
        ('div', 'Light & air'), 'falloff', 'fade', 'ambient_rgb', 'drift_dir', 'seed', 'reach',
        ('div', 'Shadows'), 'shadows', 'interior', 'thick',
    ]),
    ('Shot', [
        ('div', 'Frames and units'), 'first', 'last', 'fps', 'units',
        ('div', 'Layers of the utility pass'),
        ('link', 'layer_pos', 'Position', 'rf_pos.in'),
        ('link', 'layer_cov', 'Coverage', 'rf_pos.in2'),
        ('link', 'layer_depth', 'Depth', 'rf_depth.in'),
        ('link', 'layer_zraw', 'Unfiltered depth', 'rf_depth.in2'),
        ('link', 'layer_nrm', 'Normals', 'rf_nrm.in'),
        ('buttons', [('find_layers', 'Find layers')]),
        'p_premult', 'z_kind', 'z_premult',
        ('div', 'Camera (read from the pass header)'),
        ('cam',),
        'shutter', 'shutter_mode', 'shutter_shape',
        ('buttons', [('repair', 'Repair node')]),
        ('version',),
    ]),
]

HIDDEN = [('rf_cam_src', 'string', ''), ('rf_layers_set', 'bool', False), ('rf_shutter_read', 'bool', False),
          ('rf_aim_set', 'bool', False), ('rf_has_cuc', 'int', 0), ('rf_version', 'string', '')]

LOADER = '''import sys, types, nuke
def _rf(grp):
    src = grp['rf_py'].value()
    m = sys.modules.get('_rayfield_node')
    if m is None or getattr(m, '_rf_src', None) != src:
        m = types.ModuleType('_rayfield_node')
        exec(compile(src, 'RayField', 'exec'), m.__dict__)
        m._rf_src = src
        sys.modules['_rayfield_node'] = m
    return m
'''

KNOB_CHANGED = ('inputChange', 'showPanel', 'aim_xy', 'light_type', 'cuc_on', 'units')


def _tooltip(help_, unit):
    return help_ + (' (%s)' % unit if unit else '')


def knob_lines(key):
    """addUserKnob line(s) and value line for one setting."""
    if key in EXTRA:
        t, default, label, help_, opts = EXTRA[key]
        soft = (0, 360) if t == 'float' else None
    else:
        p = B[key]
        t, default, label, help_, opts = p.type, p.default, p.label, _tooltip(p.help, p.unit), p.options
        soft = p.soft
    head = '%s l %s t %s' % (key, nk.word(label), nk.q(help_))
    if t == 'float':
        lo, hi = soft if soft else (0, 1)
        return ['addUserKnob {7 %s R %s %s}' % (head, nk.num(lo), nk.num(hi)), '%s %s' % (key, nk.num(default))]
    if t == 'int':
        return ['addUserKnob {3 %s}' % head, '%s %d' % (key, int(default))]
    if t == 'bool':
        return ['addUserKnob {6 %s +STARTLINE}' % head, '%s %s' % (key, 'true' if default else 'false')]
    if t == 'enum':
        menu = ' '.join(nk.word(o) for o in opts)
        idx = default if isinstance(default, int) else opts.index(default)
        return ['addUserKnob {4 %s M {%s}}' % (head, menu), '%s %s' % (key, nk.word(opts[idx]))]
    if t == 'xyz':
        return ['addUserKnob {13 %s}' % head, '%s {%s}' % (key, ' '.join(nk.num(v) for v in default))]
    if t == 'rgb':
        return ['addUserKnob {18 %s}' % head, '%s {%s}' % (key, ' '.join(nk.num(v) for v in default))]
    if t == 'xy':
        return ['addUserKnob {12 %s}' % head, '%s {%s}' % (key, ' '.join(nk.num(v) for v in default))]
    raise ValueError('no knob type for %s (%s)' % (key, t))


def button_cmd(which):
    return LOADER + "_rf(nuke.thisNode()).button(nuke.thisNode(), %r)\n" % which


def group_knobs(py_source):
    out = []
    for tab, items in TABS:
        out.append('addUserKnob {20 %s l %s}' % (nk.word('tab_' + tab.lower()), nk.word(tab)))
        div = 0
        for it in items:
            if isinstance(it, str):
                out += knob_lines(it)
            elif it[0] == 'div':
                div += 1
                out.append('addUserKnob {26 div_%s_%d l %s}' % (tab[:4].lower(), div, nk.q('<b>%s</b>' % it[1])))
            elif it[0] == 'status':
                out.append('addUserKnob {26 rf_status l "" +STARTLINE T %s}' %
                           nk.q('connect the utility pass to the <b>utility</b> input'))
            elif it[0] == 'report':
                out.append('addUserKnob {26 rf_report l "" +STARTLINE T ""}')
            elif it[0] == 'buttons':
                for i, (key, label) in enumerate(it[1]):
                    out.append('addUserKnob {22 %s l %s T %s%s}' % (key, nk.word(label), nk.q(button_cmd(key)),
                                                                   ' +STARTLINE' if i == 0 else ''))
            elif it[0] == 'link':
                _, key, label, target = it
                out.append('addUserKnob {41 %s l %s T %s}' % (key, nk.word(label), target))
            elif it[0] == 'cam':
                for key, label in (('cam_pos', 'Position'), ('cam_right', 'Right'), ('cam_up', 'Up'),
                                   ('cam_back', 'Back')):
                    out.append('addUserKnob {13 %s l %s}' % (key, nk.word(label)))
                out += ['cam_pos {0 150 400}', 'cam_right {1 0 0}', 'cam_up {0 1 0}', 'cam_back {0 0 1}']
                out.append('addUserKnob {7 cam_th l "tan(half view angle)" R 0 2}')
                out.append('cam_th 0.5')
                for key, label in (('hdr_focal', 'Focal length (mm)'), ('hdr_film', 'Film back width (mm)'),
                                   ('hdr_fstop', 'f-stop'), ('hdr_focus', 'Focus distance'),
                                   ('hdr_cateye', 'Cat-eye'), ('hdr_anamorphic', 'Anamorphic aspect'),
                                   ('hdr_field_curv', 'Field curvature'), ('hdr_fstop_full', 'Full-aperture f-stop')):
                    out.append('addUserKnob {7 %s l %s R 0 100}' % (key, nk.word(label)))
                out.append('addUserKnob {3 hdr_blades l "Blade count"}')
            elif it[0] == 'version':
                out.append('addUserKnob {26 rf_about l "" +STARTLINE T %s}' %
                           nk.q('RayField %s: light shafts and haze in comp from the utility pass. Nothing to '
                                'install; it writes no files.' % __version__))
    for key, t, default in HIDDEN:
        code = {'string': 1, 'bool': 6, 'int': 3}[t]
        out.append('addUserKnob {%d %s +INVISIBLE}' % (code, key))
        if t == 'string':
            out.append('%s %s' % (key, nk.q(default)))
        elif t == 'bool':
            out.append('%s %s' % (key, 'true' if default else 'false'))
        else:
            out.append('%s %d' % (key, default))
    out.append('addUserKnob {7 rf_cuc_aspect +INVISIBLE}')
    out.append('rf_cuc_aspect 1')
    # quality: the viewer's in the GUI, the render's otherwise ($gui is 0 when Nuke renders)
    out.append('addUserKnob {3 rf_q +INVISIBLE}')
    out.append('rf_q {{$gui?viewer_quality:render_quality}}')
    for key, expr in QUALITY.items():
        out.append('addUserKnob {7 %s +INVISIBLE}' % key)
        out.append('%s {{%s}}' % (key, expr))
    out.append('addUserKnob {1 rf_py +INVISIBLE}')
    out.append('rf_py ' + nk.q(py_source))
    return out


def python_source():
    links, kernels, wires = {}, {}, {}
    for node, kfile, space, inputs in GRAPH:
        src = bl.source(kfile)
        kernels[node] = bl.kernel_name(src)
        imgs = bl.images(src)[:-1]
        full = (['rf_space_' + kfile] if isinstance(space, tuple) else [space] if space else []) + list(inputs)
        assert len(imgs) == len(full), (node, imgs, full)
        wires[node] = full
        lk = {}
        for t, p in bl.params(src):
            lk[p] = expression(p)
        links[node] = lk
    wires.update({
        'rf_fmt': ['utility'], 'rf_pos': ['rf_fmt'], 'rf_depth': ['rf_fmt'], 'rf_nrm': ['rf_fmt'],
        'rf_low8': ['rf_surface'], 'rf_low': ['rf_surface'],
        'rf_cuc_a': ['cuc'], 'rf_cuc_from': ['cuc', 'rf_cuc_a'], 'rf_cuc_sq': ['rf_cuc_from'],
        'rf_cuc_soft': ['rf_cuc_sq'], 'rf_cuc': ['rf_cuc_soft'],
        'rf_crop': ['rf_up'], 'rf_alpha': ['rf_crop'], 'rf_over': ['plate', 'rf_crop'], 'rf_plus': ['plate', 'rf_alpha'],
        'rf_result': ['rf_alpha', 'rf_over', 'rf_plus'], 'rf_view': ['rf_result', 'rf_onset'],
        'Output1': ['rf_view']})
    text = open(os.path.join(HERE, 'nodepy.py')).read()
    text = text.replace("VERSION = '@VERSION@'", 'VERSION = %r' % __version__)
    for name, val in (('LINKS', links), ('KERNELS', kernels), ('WIRES', wires)):
        old = '%s = {}' % name
        assert old in text, name
        text = text.replace(old, '%s = %r' % (name, val), 1)
    return text


def blink_node(name, kfile, n_inputs, xpos, ypos):
    src = bl.source(kfile)
    on_create = LOADER + ("_g = nuke.thisGroup()\n"
                          "try:\n"
                          "    _rf(_g).link_kernel(_g, %r)\n"
                          "except Exception:\n"
                          "    pass\n" % name)
    return ['BlinkScript {',
            ' inputs %d' % n_inputs,
            ' kernelSource ' + nk.q(src),
            ' rebuild ""',
            ' rebuild_finalise ""',
            ' useGPUIfAvailable {{parent.use_gpu}}',
            ' name ' + name,
            ' onCreate ' + nk.q(on_create),
            ' xpos %d' % xpos,
            ' ypos %d' % ypos,
            '}']


def constant(name, w, h, xpos, ypos, color='0 0 0 0'):
    return ['Constant {', ' inputs 0', ' channels rgba', ' color {%s}' % color,
            ' format "%d %d 0 0 %d %d 1 %s_fmt"' % (w, h, w, h, name), ' name ' + name,
            ' xpos %d' % xpos, ' ypos %d' % ypos, '}']


def shuffle(name, src_in, in2, mapping, xpos, ypos):
    r, g, b, a = mapping
    return ['Shuffle {', ' in ' + src_in, ' in2 ' + in2, ' red %s' % r, ' green %s' % g, ' blue %s' % b,
            ' alpha %s' % a, ' name ' + name, ' xpos %d' % xpos, ' ypos %d' % ypos, '}']


def crop_to_format(name, xpos, ypos, w=None, h=None):
    """A Crop to the input's format (or a fixed size): with intersect off, the bounding box becomes exactly the format,
    so the kernels can take the image's bounds as its size."""
    bw = '{{input.width}}' if w is None else str(w)
    bh = '{{input.height}}' if h is None else str(h)
    return ['Crop {', ' box {0 0 %s %s}' % (bw, bh), ' crop true', ' name ' + name, ' xpos %d' % xpos,
            ' ypos %d' % ypos, '}']


def reformat_scale(name, expr, xpos, ypos):
    return ['Reformat {', ' type scale', ' scale {{%s} {%s}}' % (expr, expr), ' name ' + name, ' xpos %d' % xpos,
            ' ypos %d' % ypos, '}']


def build():
    py = python_source()
    on_created = LOADER + "_n = nuke.thisNode()\ntry:\n    _rf(_n).created(_n)\nexcept Exception:\n    pass\n"
    kc = LOADER + ("_n = nuke.thisNode()\n_k = nuke.thisKnob()\nif _k.name() in %r:\n    _rf(_n).knob_changed(_n, _k)\n"
                   % (KNOB_CHANGED,))
    L = ['set cut_paste_input [stack 0]', 'version 15.0 v1', 'push 0', 'push 0', 'push $cut_paste_input', 'Group {',
         ' inputs 3',
         ' name RayField1',
         ' tile_color 0xb08a3aff',
         ' label "\\[value light_type]"',
         ' note_font "Verdana Bold"',
         ' help %s' % nk.q('RayField %s: light shafts (godrays) and haze for comp, from the shot\'s utility pass '
                          '(position, depth, normals; the camera from the EXR header), shadowed by the set and held '
                          'out by it, with a paintable cuc projected through the light. Plus or over it on the comp. '
                          'Inputs: utility (the utility pass Read), plate (optional, to judge the look), cuc '
                          '(optional: any image to project through the light, such as a RotoPaint).' % __version__),
         ' onCreate ' + nk.q(on_created),
         ' knobChanged ' + nk.q(kc),
         ]
    L += [' ' + line for line in group_knobs(py)]
    L.append('}')
    # inside the group
    L += ['Input {', ' inputs 0', ' name cuc', ' number 2', ' xpos 700', ' ypos -900', '}', 'set Ncuc [stack 0]',
          'Input {', ' inputs 0', ' name plate', ' number 1', ' xpos 1000', ' ypos -900', '}', 'set Nplate [stack 0]',
          'Input {', ' inputs 0', ' name utility', ' xpos 0', ' ypos -900', '}', 'set Nutility [stack 0]']
    L += crop_to_format('rf_fmt', 0, -840) + ['set Nrf_fmt [stack 0]']
    L += shuffle('rf_pos', 'none', 'rgba', ('red', 'green', 'blue', 'alpha2'), 0, -780) + ['set Nrf_pos [stack 0]']
    L += ['push $Nrf_fmt'] + shuffle('rf_depth', 'none', 'none', ('red', 'red2', 'black', 'black'), 120, -780) + \
        ['set Nrf_depth [stack 0]']
    L += ['push $Nrf_fmt'] + shuffle('rf_nrm', 'none', 'none', ('red', 'green', 'blue', 'black'), 240, -780) + \
        ['set Nrf_nrm [stack 0]']
    # the cuc: rgb or alpha, stretched to a square, softened, its bounding box made exactly the square
    L += ['push $Ncuc'] + shuffle('rf_cuc_a', 'rgba', 'none', ('alpha', 'alpha', 'alpha', 'alpha'), 800, -840) + \
        ['set Nrf_cuc_a [stack 0]']
    L += ['push $Nrf_cuc_a', 'push $Ncuc', 'Switch {', ' inputs 2', ' which {{parent.cuc_from}}', ' name rf_cuc_from',
          ' xpos 700', ' ypos -780', '}', 'set Nrf_cuc_from [stack 0]']
    L += ['Reformat {', ' format "%d %d 0 0 %d %d 1 rf_cuc_square"' % ((bl.CUC_W,) * 4), ' resize distort',
          ' name rf_cuc_sq', ' xpos 700', ' ypos -720', '}', 'set Nrf_cuc_sq [stack 0]']
    L += ['Blur {', ' size {{parent.cuc_soft*%g}}' % (bl.CUC_W / 100.0), ' name rf_cuc_soft', ' xpos 700',
          ' ypos -660', '}', 'set Nrf_cuc_soft [stack 0]']
    L += crop_to_format('rf_cuc', 700, -600, bl.CUC_W, bl.CUC_W) + ['set Nrf_cuc [stack 0]']
    y = -600
    for node, kfile, space, inputs in GRAPH:
        # Nuke takes a node's inputs off the stack with input 0 on top: push the last input first
        if isinstance(space, tuple):
            full = inputs
        elif space:
            full = inputs
        else:
            full = inputs[1:]
        for src in reversed(full):
            L.append('push $N' + src)
        n_in = len(inputs) + (1 if space else 0)
        if isinstance(space, tuple):
            L += constant('rf_space_' + kfile, space[0], space[1], -250, y)
            L.append('set Nrf_space_%s [stack 0]' % kfile)
        elif space:
            L.append('push $Nrf_surface')
            L += reformat_scale(space, '0.125' if space == 'rf_low8' else 'parent.rf_res', -250, y)
            L.append('set N%s [stack 0]' % space)
        else:
            L.append('push $N' + inputs[0])
        L += blink_node(node, kfile, n_in, 0, y)
        L.append('set N%s [stack 0]' % node)
        y += 60
    L += ['push $Nrf_up'] + crop_to_format('rf_crop', 0, y) + ['set Nrf_crop [stack 0]']
    y += 60
    L += ['Multiply {', ' channels alpha', ' value {{parent.alpha_out}}', ' name rf_alpha', ' xpos 0',
          ' ypos %d' % y, '}', 'set Nrf_alpha [stack 0]']
    y += 60
    L += ['push $Nrf_crop', 'push $Nplate', 'Merge2 {', ' inputs 2', ' operation over', ' name rf_over',
          ' xpos 200', ' ypos %d' % y, '}', 'set Nrf_over [stack 0]']
    L += ['push $Nrf_alpha', 'push $Nplate', 'Merge2 {', ' inputs 2', ' operation plus', ' name rf_plus',
          ' xpos 400', ' ypos %d' % y, '}', 'set Nrf_plus [stack 0]']
    y += 60
    L += ['push $Nrf_plus', 'push $Nrf_over', 'push $Nrf_alpha', 'Switch {', ' inputs 3',
          ' which {{parent.output_mode}}', ' name rf_result', ' xpos 0', ' ypos %d' % y, '}',
          'set Nrf_result [stack 0]']
    y += 60
    L += ['push $Nrf_onset', 'push $Nrf_result', 'Switch {', ' inputs 2', ' which {{parent.view}}',
          ' name rf_view', ' xpos 0', ' ypos %d' % y, '}']
    y += 60
    L += ['Output {', ' name Output1', ' onCreate ' + nk.q(
        LOADER + "_g = nuke.thisGroup()\ntry:\n    _rf(_g).created(_g)\nexcept Exception:\n    pass\n"),
        ' xpos 0', ' ypos %d' % y, '}', 'end_group', '']
    return '\n'.join(L)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'dist', 'RayField.nk')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    text = build()
    open(out, 'w').write(text)
    print('%s (%d KB)' % (out, len(text) // 1024))
