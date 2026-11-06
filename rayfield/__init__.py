"""RayField: light shafts (godrays) and haze for a shot, added in comp from the shot's utility pass, with a paintable
cuc (gobo) projected through the light.

This package is the Python reference: the same maths as the node's BlinkScript kernels, in numpy, used to test the
kernels and to make the stand-in shots. The node itself (dist/RayField.nk) needs none of it.

    schema      every setting, in one table (drives the node's knobs and the docs)
    lightmath   the light: direction, frame, colour temperature, scattering
    reference   the renderer, step by step as the kernels do it
    standin     a built-in room with a window, made in memory as a utility pass would be
"""

__version__ = '0.1.0'
