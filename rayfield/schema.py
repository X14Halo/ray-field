"""Every setting of the node, in one table: its knob type, default, label, help, unit and slider range.

node/build_node.py makes the node's knobs from this table, docs/SETTINGS.md is generated from it, and the reference
renderer takes its defaults from it, so the three never disagree.

    python -m rayfield.schema        rewrite docs/SETTINGS.md
"""

import os


class Setting(object):
    def __init__(self, key, type, default, label, help, unit='', soft=None, options=None):
        self.key, self.type, self.default, self.label, self.help = key, type, default, label, help
        self.unit, self.soft, self.options = unit, soft, options


S = Setting
SETTINGS = [
    # ---- the light
    S('light_type', 'enum', 'sun', 'Light', 'Sun: parallel light from far away (through windows, trees, clouds). '
      'Spot: a lamp with a cone, placed Distance away from the aim point.', options=['sun', 'spot']),
    S('aim_xy', 'xy', (960.0, 540.0), 'Lands here', 'Drag this handle in the viewer onto the set, where the light '
      'should land. The node reads the point under it from the utility pass and sets the Aim point.', 'pixels'),
    S('aim', 'xyz', (0.0, 0.0, 0.0), 'Aim point', 'Where the light is aimed, in the scene (set by the Lands here '
      'handle). The cuc is centred on it, and a spot points at it.', 'scene units'),
    S('light_az', 'float', 25.0, 'Heading', 'The compass direction the light comes from, in degrees (0: the light '
      'travels toward +X).', 'degrees', (-180, 180)),
    S('light_el', 'float', 33.0, 'Elevation', 'How high the light is, in degrees above the horizon.', 'degrees',
      (-90, 90)),
    S('distance', 'float', 4.0, 'Distance', 'Spot: how far the light is from the aim point, along the light\'s '
      'direction.', 'metres', (0.2, 30)),
    S('cone', 'float', 40.0, 'Cone angle', 'Spot: the full width of the light\'s cone.', 'degrees', (1, 170)),
    S('cone_soft', 'float', 0.2, 'Cone softness', 'Spot: how soft the cone\'s edge is (0 = hard, 1 = soft all the '
      'way in).', '', (0, 1)),
    S('intensity', 'float', 1.0, 'Intensity', 'How bright the light is (linear).', '', (0, 20)),
    S('exposure', 'float', 0.0, 'Exposure', 'Brightness in stops, on top of Intensity.', 'stops', (-6, 6)),
    S('light_rgb', 'rgb', (1.0, 1.0, 1.0), 'Colour', 'The light\'s colour (times its temperature).'),
    S('light_k', 'float', 5600.0, 'Temperature', 'The light\'s colour temperature.', 'kelvin', (1500, 12000)),
    # ---- the air
    S('haze', 'float', 0.3, 'Haze', 'How thick the air is. More haze: brighter shafts, and more of the background '
      'hidden (with Alpha set to matte).', '', (0, 2)),
    S('glow', 'float', 0.5, 'Glow toward light', 'How much brighter the air is when you look toward the light '
      '(forward scattering). 0 = the same from every side.', '', (0, 0.95)),
    S('ambient', 'float', 0.02, 'Ambient haze', 'Haze lit by the rest of the scene, in shadow too, as a fraction '
      'of the light.', '', (0, 1)),
    S('fog', 'float', 0.0, 'Ground fog', 'Extra haze low down, thinning out above Fog height.', '', (0, 5)),
    S('fog_height', 'float', 0.5, 'Fog height', 'Height (world Y) below which the ground fog is thickest.',
      'metres', (-5, 20)),
    S('fog_falloff', 'float', 0.5, 'Fog falloff', 'How quickly the ground fog thins out above its height.',
      'metres', (0.01, 10)),
    S('breakup', 'float', 0.5, 'Breakup', 'How patchy the haze is (0 = even).', '', (0, 1)),
    S('breakup_size', 'float', 0.6, 'Breakup size', 'The size of the patches.', 'metres', (0.02, 10)),
    S('drift', 'float', 0.05, 'Drift', 'How fast the patches drift.', 'metres per second', (0, 2)),
    # ---- the cuc
    S('cuc_on', 'bool', True, 'Use cuc', 'Project the image on the cuc input through the light: white lets light '
      'through, black blocks it, colours tint it.'),
    S('cuc_from', 'enum', 'rgb', 'Cuc from', 'Which channels of the cuc input to use: rgb (RotoPaint, a texture), '
      'or alpha (a Roto shape).', options=['rgb', 'alpha']),
    S('cuc_size', 'float', 3.0, 'Cuc size', 'Sun: how wide the cuc is where it lands, centred on the aim point. '
      '(A spot\'s cuc always fills its cone.)', 'metres', (0.1, 50)),
    S('roll', 'float', 0.0, 'Cuc roll', 'Turns the cuc about the light\'s direction.', 'degrees', (-180, 180)),
    S('cuc_soft', 'float', 0.0, 'Cuc softness', 'Blurs the cuc, as a percentage of its width.', '%', (0, 10)),
    S('cuc_outside', 'enum', 'dark', 'Around the cuc', 'Sun: what the light does outside the cuc image: dark (the '
      'cuc is a board with holes), light (only the cuc\'s own shapes block), or repeat (tile it).',
      options=['dark', 'light', 'repeat']),
    # ---- output
    S('output_mode', 'enum', 'atmosphere', 'Output', 'What the node puts out: the atmosphere alone (to plus or over '
      'in your comp), or over / plus the plate input, to judge it.', options=['atmosphere', 'over plate',
                                                                            'plus plate']),
    S('alpha_out', 'enum', 'none', 'Alpha', 'none: rgb only, to plus onto the comp. matte: alpha is how much the '
      'haze hides what is behind it, so over gives fog that also thins the background.', options=['none', 'matte']),
    S('view', 'enum', 'result', 'View', 'result: the atmosphere. light on set: the light (with its shadows and '
      'cuc) painted onto the set, to aim it.', options=['result', 'light on set']),
    S('viewer_quality', 'enum', 'preview', 'Viewer quality', 'Quality in the viewer. preview: quarter resolution, '
      'fewer steps (fast to tune). final: half resolution. best: full resolution, most steps.',
      options=['preview', 'final', 'best']),
    S('render_quality', 'enum', 'final', 'Render quality', 'Quality when rendering (Write nodes, the farm).',
      options=['preview', 'final', 'best']),
    S('use_gpu', 'bool', True, 'Use GPU', 'Render on the GPU when there is one (much faster). The result is the '
      'same either way.'),
    # ---- light & air, more
    S('falloff', 'float', 1.0, 'Distance falloff', 'Spot: how the light dims with distance. 1 = as a real lamp '
      '(inverse square, as bright as set at the aim point), 0 = not at all.', '', (0, 1)),
    S('fade', 'float', 0.0, 'Shaft fade', 'Shafts fade out over about this distance after they enter the set '
      '(0 = only as the haze dims them).', 'metres', (0, 30)),
    S('ambient_rgb', 'rgb', (0.85, 0.92, 1.0), 'Ambient colour', 'The colour of the ambient haze.'),
    S('drift_dir', 'float', 0.0, 'Drift heading', 'Which way the patches drift, in degrees (0 = toward +X).',
      'degrees', (-180, 180)),
    S('seed', 'int', 1, 'Seed', 'Picks a different pattern of patches.'),
    S('reach', 'float', 0.0, 'Haze reaches', 'How far from the camera the haze goes. 0 = automatic: a bit past most '
      'of the set, and where the camera sees sky, to where its ray leaves the set (so the outside seen through a '
      'window keeps the haze it has in the plate).', 'metres', (0, 200)),
    # ---- shadows
    S('shadows', 'enum', 'from the pass', 'Shadows', 'Where the shadows in the air come from: the set as the '
      'utility pass shows it, or none.', options=['from the pass', 'none']),
    S('interior', 'bool', False, 'Light only through openings', 'For rooms: the pass only shows what the camera '
      'sees, so light only gets in where its path leaves the set through what the camera sees as sky or the far '
      'outside (a window, a door). Turn it on when light leaks in from walls the camera cannot see.'),
    S('thick', 'float', 0.4, 'Thickness', 'How thick things are taken to be behind the surfaces the camera sees, '
      'when they block light.', 'metres', (0.02, 3)),
    # ---- shot
    S('first', 'int', 1001, 'First frame', 'The shot\'s first frame (from the utility Read when connected).'),
    S('last', 'int', 1048, 'Last frame', 'The shot\'s last frame.'),
    S('fps', 'float', 24.0, 'Frames per second', 'For the drift speed.', '', (1, 60)),
    S('units', 'enum', 'centimetres', 'Scene units', 'What one unit in the utility pass is.',
      options=['centimetres', 'metres', 'millimetres', 'inches', 'feet']),
]

BY_KEY = dict((s.key, s) for s in SETTINGS)
UNIT_METRES = {'centimetres': 0.01, 'metres': 1.0, 'millimetres': 0.001, 'inches': 0.0254, 'feet': 0.3048}


def defaults():
    """{key: default}, enums as their option text."""
    return dict((s.key, s.default) for s in SETTINGS)


def markdown():
    out = ['# RayField settings', '', 'Generated from `rayfield/schema.py`. Lengths are in metres unless the table '
           'says otherwise; the node converts them with *Scene units*.', '',
           '| Knob | Default | What it does |', '|---|---|---|']
    for s in SETTINGS:
        d = s.default
        if isinstance(d, (tuple, list)):
            d = ' '.join('%g' % v for v in d)
        elif isinstance(d, bool):
            d = 'on' if d else 'off'
        elif isinstance(d, float):
            d = '%g' % d
        extra = (' (%s)' % s.unit) if s.unit else ''
        opts = (' Options: %s.' % ', '.join(s.options)) if s.options else ''
        out.append('| %s | %s%s | %s%s |' % (s.label, d, extra, s.help.replace('|', '/'), opts))
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'SETTINGS.md')
    open(path, 'w').write(markdown())
    print(path)
