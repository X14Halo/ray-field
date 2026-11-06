# RayField settings

Generated from `rayfield/schema.py`. Lengths are in metres unless the table says otherwise; the node converts them with *Scene units*.

| Knob | Default | What it does |
|---|---|---|
| Light | sun | Sun: parallel light from far away (through windows, trees, clouds). Spot: a lamp with a cone, placed Distance away from the aim point. Options: sun, spot. |
| Lands here | 960 540 (pixels) | Drag this handle in the viewer onto the set, where the light should land. The node reads the point under it from the utility pass and sets the Aim point. |
| Aim point | 0 0 0 (scene units) | Where the light is aimed, in the scene (set by the Lands here handle). The cuc is centred on it, and a spot points at it. |
| Heading | 25 (degrees) | The compass direction the light comes from, in degrees (0: the light travels toward +X). |
| Elevation | 33 (degrees) | How high the light is, in degrees above the horizon. |
| Distance | 4 (metres) | Spot: how far the light is from the aim point, along the light's direction. |
| Cone angle | 40 (degrees) | Spot: the full width of the light's cone. |
| Cone softness | 0.2 | Spot: how soft the cone's edge is (0 = hard, 1 = soft all the way in). |
| Intensity | 1 | How bright the light is (linear). |
| Exposure | 0 (stops) | Brightness in stops, on top of Intensity. |
| Colour | 1 1 1 | The light's colour (times its temperature). |
| Temperature | 5600 (kelvin) | The light's colour temperature. |
| Haze | 0.3 | How thick the air is. More haze: brighter shafts, and more of the background hidden (with Alpha set to matte). |
| Glow toward light | 0.5 | How much brighter the air is when you look toward the light (forward scattering). 0 = the same from every side. |
| Ambient haze | 0.02 | Haze lit by the rest of the scene, in shadow too, as a fraction of the light. |
| Ground fog | 0 | Extra haze low down, thinning out above Fog height. |
| Fog height | 0.5 (metres) | Height (world Y) below which the ground fog is thickest. |
| Fog falloff | 0.5 (metres) | How quickly the ground fog thins out above its height. |
| Breakup | 0.5 | How patchy the haze is (0 = even). |
| Breakup size | 0.6 (metres) | The size of the patches. |
| Drift | 0.05 (metres per second) | How fast the patches drift. |
| Use cuc | on | Project the image on the cuc input through the light: white lets light through, black blocks it, colours tint it. |
| Cuc from | rgb | Which channels of the cuc input to use: rgb (RotoPaint, a texture), or alpha (a Roto shape). Options: rgb, alpha. |
| Cuc size | 3 (metres) | Sun: how wide the cuc is where it lands, centred on the aim point. (A spot's cuc always fills its cone.) |
| Cuc roll | 0 (degrees) | Turns the cuc about the light's direction. |
| Cuc softness | 0 (%) | Blurs the cuc, as a percentage of its width. |
| Around the cuc | dark | Sun: what the light does outside the cuc image: dark (the cuc is a board with holes), light (only the cuc's own shapes block), or repeat (tile it). Options: dark, light, repeat. |
| Output | atmosphere | What the node puts out: the atmosphere alone (to plus or over in your comp), or over / plus the plate input, to judge it. Options: atmosphere, over plate, plus plate. |
| Alpha | none | none: rgb only, to plus onto the comp. matte: alpha is how much the haze hides what is behind it, so over gives fog that also thins the background. Options: none, matte. |
| View | result | result: the atmosphere. light on set: the light (with its shadows and cuc) painted onto the set, to aim it. Options: result, light on set. |
| Viewer quality | preview | Quality in the viewer. preview: quarter resolution, fewer steps (fast to tune). final: half resolution. best: full resolution, most steps. Options: preview, final, best. |
| Render quality | final | Quality when rendering (Write nodes, the farm). Options: preview, final, best. |
| Use GPU | on | Render on the GPU when there is one (much faster). The result is the same either way. |
| Distance falloff | 1 | Spot: how the light dims with distance. 1 = as a real lamp (inverse square, as bright as set at the aim point), 0 = not at all. |
| Shaft fade | 0 (metres) | Shafts fade out over about this distance after they enter the set (0 = only as the haze dims them). |
| Ambient colour | 0.85 0.92 1 | The colour of the ambient haze. |
| Drift heading | 0 (degrees) | Which way the patches drift, in degrees (0 = toward +X). |
| Seed | 1 | Picks a different pattern of patches. |
| Haze reaches | 0 (metres) | How far from the camera the haze goes. 0 = automatic: a bit past most of the set, and where the camera sees sky, to where its ray leaves the set (so the outside seen through a window keeps the haze it has in the plate). |
| Shadows | from the pass | Where the shadows in the air come from: the set as the utility pass shows it, or none. Options: from the pass, none. |
| Light only through openings | off | For rooms: the pass only shows what the camera sees, so light only gets in where its path leaves the set through what the camera sees as sky or the far outside (a window, a door). Turn it on when light leaks in from walls the camera cannot see. |
| Thickness | 0.4 (metres) | How thick things are taken to be behind the surfaces the camera sees, when they block light. |
| First frame | 1001 | The shot's first frame (from the utility Read when connected). |
| Last frame | 1048 | The shot's last frame. |
| Frames per second | 24 | For the drift speed. |
| Scene units | centimetres | What one unit in the utility pass is. Options: centimetres, metres, millimetres, inches, feet. |
