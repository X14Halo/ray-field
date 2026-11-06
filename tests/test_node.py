"""The drop-in node (dist/RayField.nk, built by node/build_node.py), checked without Nuke: the script reads back as
Nuke would read it, every kernel's source survives the quoting, the internal wiring is right, every kernel param is
linked to a knob that exists, and the Python inside the node finds the layers, reads the camera from the header,
aims the light from the Lands here handle and notices the cuc."""

import json
import math
import os
import re
import shutil
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'blink'))

import nkload                                     # noqa: E402
from node import blinklib, build_node            # noqa: E402
from rayfield import reference as ref, standin   # noqa: E402

TEXT = build_node.build()
HAVE_CXX = shutil.which('g++') is not None
W, H = 320, 134


def header_for(cam):
    """EXR-header-style metadata for a camera, the way Nuke shows it (exr/ prefix): world-to-camera as a list,
    lens values, and lens extras inside a JSON attribute next to a decoy camera."""
    M = np.eye(4)
    M[0, :3], M[1, :3], M[2, :3], M[3, :3] = cam.right, cam.up, cam.back, cam.pos
    w2c = np.linalg.inv(M).reshape(16).tolist()
    info = {'default': {'fStop': 5.6, 'bladeCount': 0}, 'main': {'fStop': cam.fstop, 'bladeCount': 7,
                                                                    'catEye': 0.3}}
    return {'exr/worldToCamera': w2c, 'exr/cameraFocalLength': cam.focal, 'exr/cameraFilmBackWidth': cam.film,
            'exr/cameraFStop': cam.fstop, 'exr/cameraFocusDistance': cam.focus,
            'exr/renderInfo': json.dumps(info), 'exr/shutterAngle': 180.0}


class Loaded(object):
    """The node loaded into stand-in nodes, connected to a stand-in utility Read."""

    def __init__(self, view='wide', frames=(1001, 1048), cuc=None):
        self.shot = standin.StandinShot(view, W, H)
        util = nkload.Node('Read', None)
        util._knobs['name'].setValue('Read1')
        util._channels = ['rgba.red', 'rgba.green', 'rgba.blue', 'rgba.alpha', 'P.x', 'P.y', 'P.z',
                          'N.x', 'N.y', 'N.z', 'depth.Z', 'depthNoFilter.Z', 'crypto.red']
        util._first, util._last = frames
        self.util = util
        ins = {0: util}
        if cuc is not None:
            c = nkload.Node('RotoPaint', None)
            c._knobs['name'].setValue('RotoPaint1')
            c._size = cuc
            ins[2] = c
        self.sc = nkload.load(TEXT, outside_inputs=ins)
        util.script = self.sc
        for n in ins.values():
            n.script = self.sc
        self.g = self.sc.root.children['RayField1']
        shot = self.shot
        self.frame = frames[0]
        self.sc.metadata = lambda node, f: header_for(shot.camera(f if f is not None else frames[0]))
        self.cache = {}
        self.sc.size = lambda node: getattr(node, '_size', (shot.W, shot.H))
        self.sc.sample = self.sample
        sys.modules['nuke'] = nkload.fake_nuke(self.sc)

    def images(self):
        """The facts, surface and frame images, from the kernels run in the C++ stand-in for Blink."""
        if not self.cache:
            import pipeline
            o = pipeline.render(self.shot, self.frame, dict(interior=True), lm_space=64, lm_n=64, steps=4,
                                lm_steps=16)
            self.cache.update(rf_surface=o['surf'], rf_facts=o['facts'], rf_frame=o['info'])
        return self.cache

    def sample(self, node, chan, x, y):
        if node.name() not in ('rf_surface', 'rf_facts', 'rf_frame'):
            return 0.0
        img = self.images()[node.name()]
        c = ('red', 'green', 'blue', 'alpha').index(chan.split('.')[1])
        return float(img[int(y), int(x), c])

    def run(self, node_name, knob_name, knob=None):
        n = self.g if node_name is None else self.g.node(node_name)
        nkload.run_python(n, n[knob_name].value(), knob if knob is not None else n[knob_name], group=self.g)

    def connect(self):
        self.run(None, 'knobChanged', knob=nkload.Knob('inputChange'))

    def module(self):
        return sys.modules['_rayfield_node']


class Script(unittest.TestCase):
    def setUp(self):
        self.L = Loaded()

    def test_dist_file_is_current(self):
        with open(os.path.join(ROOT, 'dist', 'RayField.nk'), encoding='utf-8') as fh:
            self.assertEqual(fh.read(), TEXT, 'run: python3 node/build_node.py')

    def test_kernels_survive_the_quoting(self):
        n = 0
        for node in self.L.g.children.values():
            if node.cls == 'BlinkScript':
                kfile = dict((g[0], g[1]) for g in build_node.GRAPH)[node.name()]
                self.assertEqual(node.source, blinklib.source(kfile), node.name())
                n += 1
        self.assertEqual(n, len(build_node.GRAPH))

    def test_wiring_on_the_stack_is_the_intended_wiring(self):
        g = self.L.g
        wires = None
        for line in build_node.python_source().splitlines():
            if line.startswith('WIRES = '):
                wires = eval(line[len('WIRES = '):])
        self.assertTrue(wires)
        for name, inputs in wires.items():
            n = g.node(name)
            self.assertIsNotNone(n, name)
            for i, src in enumerate(inputs):
                if src is None:
                    continue
                self.assertIsNotNone(n.input(i), (name, i))
                self.assertEqual(n.input(i).name(), src, (name, i))

    def test_knobs(self):
        g = self.L.g
        for key in ('light_type', 'aim_xy', 'aim', 'haze', 'glow', 'cuc_on', 'cuc_outside', 'output_mode',
                    'alpha_out', 'view', 'viewer_quality', 'render_quality', 'interior', 'thick', 'units', 'cam_pos',
                    'cam_th', 'hdr_focal', 'rf_py', 'rf_q', 'rf_res', 'layer_pos', 'shutter'):
            self.assertIsNotNone(g.knob(key), key)
        self.assertEqual(g['layer_zraw'].target, 'rf_depth.in2')
        self.assertEqual(g['units'].options[g['units'].value()], 'centimetres')
        self.assertEqual(g['light_type'].options, ['sun', 'spot'])
        self.assertEqual(g['rf_q'].expr[0], '$gui?viewer_quality:render_quality')

    def test_every_expression_names_a_knob_that_exists(self):
        L = self.L
        L.run('Output1', 'onCreate')
        g = L.g
        names = set(g.knobs())
        exprs = []
        for node, links in L.module().LINKS.items():
            for p, e in links.items():
                exprs += e if isinstance(e, list) else [e]
        exprs += [k.expr[0] for k in g.knobs().values() if 0 in getattr(k, 'expr', {})]
        for n in g.children.values():
            for k in n.knobs().values():
                exprs += list(getattr(k, 'expr', {}).values())
        self.assertGreater(len(exprs), 100)
        for e in exprs:
            for ref_ in re.findall(r'parent\.(\w+)', e):
                self.assertIn(ref_, names, e)
            if 'parent.' not in e:
                for word in re.findall(r'[a-z_][a-z_0-9]*', e):
                    if word in ('frame', 'gui', 'input', 'width', 'height', 'pow'):
                        continue
                    self.assertIn(word, names, e)

    def test_created_links_every_kernel_param(self):
        L = self.L
        L.run('Output1', 'onCreate')
        mod = L.module()
        self.assertEqual(mod.setup(L.g), {})
        for node, links in mod.LINKS.items():
            n = L.g.node(node)
            for param, expr in links.items():
                k = n['%s_%s' % (n.kernel, param)]
                if isinstance(expr, list):
                    self.assertEqual([k.expr[i] for i in range(len(expr))], expr)
                else:
                    self.assertEqual(k.expr[0], expr)
            self.assertEqual(n['useGPUIfAvailable'].expr.get(0), 'parent.use_gpu')
        m = L.g.node('rf_march')
        self.assertEqual(m['RFMarch_light_col'].expr[0], 'parent.light_rgb.r*parent.intensity*pow(2,parent.exposure)')
        self.assertEqual(m['RFMarch_steps'].expr[0], 'parent.rf_steps')
        self.assertEqual(m['RFMarch_use_cuc'].expr[0], 'parent.cuc_on*parent.rf_has_cuc')

    def test_kernel_params_match_the_reference(self):
        """Every kernel param has a value in reference.params (so the kernel tests cover what the node links)."""
        p, res = ref.params({}, standin.camera(1001), 1001)
        for kfile in blinklib.KERNELS:
            for t, name in blinklib.params(blinklib.source(kfile)):
                self.assertIn(name, p, (kfile, name))


@unittest.skipUnless(HAVE_CXX, 'needs g++ to compile the kernels')
class Behaviour(unittest.TestCase):
    def test_connecting_finds_layers_reads_the_camera_and_aims(self):
        L = Loaded()
        L.connect()
        g = L.g
        self.assertEqual(g.node('rf_pos')['in'].value(), 'P')
        self.assertEqual(g.node('rf_depth')['in'].value(), 'depth')
        self.assertEqual(g.node('rf_depth')['in2'].value(), 'depthNoFilter')
        self.assertEqual(g.node('rf_nrm')['in'].value(), 'N')
        self.assertEqual((g['first'].value(), g['last'].value()), (1001, 1048))
        cam = L.shot.camera(1001)
        a = g['cam_pos'].animation(0)
        self.assertEqual(len(a.keys()), 48)
        self.assertAlmostEqual(a.k[1001], cam.pos[0], places=4)
        self.assertAlmostEqual(g['hdr_focal'].value(), cam.focal)
        # a first aim, at the set in the middle of the frame
        self.assertTrue(g['rf_aim_set'].value())
        aim = np.array(g['aim'].value())
        self.assertGreater(np.linalg.norm(aim - cam.pos), 100)
        self.assertIn('sun', g['rf_status'].value())

    def test_lands_here_aims_at_the_point_under_it(self):
        L = Loaded()
        L.connect()
        g = L.g
        mod = L.module()
        surf = L.images()['rf_surface']
        # a point on the floor, near the bottom of the frame
        x, y = W * 0.3, H * 0.1
        cam = L.shot.camera(1001)                                   # the stand-in knobs: the frame's values
        for k, v in (('cam_pos', cam.pos), ('cam_right', cam.right), ('cam_up', cam.up), ('cam_back', cam.back)):
            g[k].setValue(list(v))
        g['cam_th'].setValue(math.tan(cam.hfov / 2))
        g['aim_xy'].setValue([x, y])
        L.run(None, 'knobChanged', knob=g['aim_xy'])
        aim = np.array(g['aim'].value())
        P = L.shot.read(1001, 'P')[H - 1 - int(y), int(x)]          # row 0 at the top there
        self.assertLess(np.linalg.norm(aim - P), 1.0)
        # on the sky: the aim stays, and the status says so
        sky = np.argwhere(surf[..., 1] <= 0.02)
        yy, xx = sky[len(sky) // 2]
        g['aim_xy'].setValue([xx + 0.5, yy + 0.5])
        L.run(None, 'knobChanged', knob=g['aim_xy'])
        self.assertLess(np.linalg.norm(np.array(g['aim'].value()) - aim), 1e-6)
        self.assertIn('sky', g['rf_status'].value())

    def test_the_cuc_input_is_noticed_with_its_shape(self):
        L = Loaded(cuc=(1920, 1080))
        L.run('Output1', 'onCreate')
        self.assertEqual(L.g['rf_has_cuc'].value(), 1)
        self.assertAlmostEqual(L.g['rf_cuc_aspect'].value(), 1920 / 1080.0)
        L2 = Loaded()
        L2.run('Output1', 'onCreate')
        self.assertEqual(L2.g['rf_has_cuc'].value(), 0)

    def test_check_shot_report(self):
        L = Loaded()
        L.connect()
        L.run(None, 'check_shot')
        rep = L.g['rf_report'].value()
        for word in ('Layers', 'Camera', 'The pass', 'The set', 'Aim'):
            self.assertIn(word, rep)
        self.assertNotIn('PROBLEM', rep)

    def test_opening_the_panel_rereads_a_changed_camera(self):
        L = Loaded()
        L.connect()
        before = L.g['cam_pos'].animation(0).k[1001]
        L.run(None, 'knobChanged', knob=nkload.Knob('showPanel'))
        self.assertEqual(L.g['cam_pos'].animation(0).k[1001], before)
        shot = L.shot
        L.sc.metadata = lambda node, f: header_for(shot.camera((f or 1001) + 5))
        L.run(None, 'knobChanged', knob=nkload.Knob('showPanel'))
        self.assertNotAlmostEqual(L.g['cam_pos'].animation(0).k[1001], before, places=3)


if __name__ == '__main__':
    unittest.main()
