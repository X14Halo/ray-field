# RayField in Nuke 15

RayField is one node. You paste it into a script and use it. There's nothing to install, no `NUKE_PATH`, nothing in
`.nuke`, and it never writes a file. It works in plain Nuke 15 as well as NukeX.

Its output is the atmosphere as an ordinary image: light shafts and haze, shadowed and held out by the set. Look at it
in the viewer, then **plus** it onto the comp. To **over** it instead (so the haze also thins what's behind it), set
*Alpha* to *matte*.

## Get the node into a script

Pick one:

- Drag `dist/RayField.nk` from a file browser into the Node Graph.
- Open `dist/RayField.nk` in a text editor, copy all of it, and paste it into the Node Graph.
- Use *File > Import Script*.

If a Read is selected when you paste, it becomes the node's **utility** input. To keep the node handy, put it in a
ToolSet or a shared template script. That's still nothing to install.

## Inputs

- **utility** (required): the utility pass Read. The node uses position, unfiltered depth (or depth), coverage and
  normals, and reads the camera from the EXR header on every frame.
- **plate** (optional): the comp or beauty, only for judging the look with *Output: over plate* or *plus plate*.
- **cuc** (optional): any image to project through the light, such as a RotoPaint, a Roto, a texture Read, a Noise or
  a Grid. White lets light through, black blocks it, and colours tint it.

## Use it

1. **Connect the utility pass** Read. The node then:
   - finds the layers (position, normals, depth, unfiltered depth, coverage);
   - takes the frame range from the Read;
   - reads the camera from the header on every frame, keyed if it moves;
   - aims the light at the set in the middle of the frame.

   The line at the top of the panel says what it found.
2. **Press Check shot.** It reports:
   - the layers it used and how it read the pass (premultiplied or not, depth along the ray or the view axis);
   - the camera;
   - the size of the set (so wrong *Scene units* stand out);
   - where the light is aimed;
   - whether *Light only through openings* looks right for this shot.
3. **Aim the light.**
   - With the panel open, drag the **Lands here** handle in the viewer onto the set, where the light should land.
     The node reads the point under it from the pass. A spot points at it; the sun's cuc is centred on it.
   - Set **Heading** and **Elevation** for the direction the light comes from.
   - For a **spot**, also set *Distance* (from the aim point back toward the light), *Cone angle* and *Cone
     softness*.
   - **View: light on set** shows the light, its shadows and its cuc painted onto the set, like a grey card, so you
     can see where it lands while you aim. Switch back to *result* to see the air.
4. **Tune the air:**
   - *Haze* (how thick the air is);
   - *Glow toward light* (brighter looking into the light);
   - *Ambient haze* (haze in shadow too);
   - *Ground fog*, *Fog height* and *Fog falloff*;
   - *Breakup*, *Breakup size* and *Drift* (patchy, slowly moving air).

   *Intensity*, *Exposure*, *Colour* and *Temperature* set the light.
5. **A cuc.** Connect any image to the **cuc** input.
   - Paint white for light and black for shadow. A RotoPaint should update the rays as you paint (one of the
     things to check, below).
   - For a Roto shape, set *Cuc from* to *alpha*.
   - *Cuc size* (sun) sets how wide it is where it lands. *Cuc roll* turns it, and *Cuc softness* blurs it.
   - *Around the cuc*: *dark* treats the cuc as a board with holes, *light* means only its own shapes block, and
     *repeat* tiles it (good for foliage breakup on the sun).
6. **Comp it:** Merge (plus) the node onto your comp. Or set *Alpha* to *matte* and Merge (over).

## Rooms: Light only through openings

The pass only shows what the camera sees. Without help, light leaks in through walls and ceilings the camera can't
see, such as the wall behind the camera. For rooms, turn on **Light only through openings** (on the *More* tab).
Light then only counts as getting in once its path has been outside a window, door or gap the camera sees as sky or
the far outside.

It works when the opening is in frame. On the stand-in room, the light map agrees with the room's exact shadows at
99% of points in the wide view and 96% in the side-on view. When the window the light comes through is out of frame
(the close-up looking up the beam), only about half the lit air is found.

For those shots, you can:

- turn it off and use a cuc to shape the light;
- or use the USD geometry input when it comes (phase 3).

*Thickness* is how thick things are taken to be behind the surfaces the camera sees.

## Quality

- *Viewer quality* (default *preview*) is used in the viewer; *Render quality* (default *final*) is used when
  rendering (Write nodes, the farm, `nuke -x`).
- *preview*: a quarter-resolution march with fewer steps and a 512 light map.
- *final*: a half-resolution march and a 1024 light map.
- *best*: a full-resolution march and the most steps.
- *Use GPU* is on by default. The result is the same either way, apart from floating-point rounding.

Rough speed, from the kernels compiled as plain C++ on a 2-core cloud machine (no SIMD; Nuke's Blink on a workstation
should be much faster, and the GPU faster again):

- **A full HD frame:** about 2 s in preview and 9 s in final.
- **When the light hasn't moved**, the light map stays cached, so only the march and upsample re-run: about 1 s in
  preview, 6 s in final.

## The Shot tab

- **Layers:** if a layer was picked wrong, choose it here, or press *Find layers* to look again.
- **Pass handling:** *Positions premultiplied*, *Depth is distance along the view axis* and *Depth premultiplied*
  are worked out from the pass (*auto*). Override them if Check shot says something surprising.
- **Camera:** the knobs show what was read from the header, keyed per frame if the camera moves. *Read camera* reads
  it again. The node also checks this when you open its panel.
- **Repair node:** relinks the internal kernels to the knobs. You shouldn't need it.

## First time in Nuke: what to check

None of this has been run in Nuke yet: the kernels have only run as C++ in the test rig, and the node's script and
Python only in a stand-in for Nuke. Please try these first, and tell me what you see:

1. **It compiles.** Paste the node, connect a utility pass, and view it. If a BlinkScript inside fails to compile,
   Nuke shows the error on that node: open the group (Ctrl+Enter) and look for a red node. Send me the message.
2. **GPU and CPU agree.** Toggle *Use GPU* and compare.
3. **The handle.** With the panel open, does *Lands here* show in the viewer, and does dragging it update *Aim
   point*?
4. **Live cuc.** Connect a RotoPaint to *cuc* and paint while viewing RayField. Do the rays update during the stroke
   or only at the end?
5. **Quality switch.** Render a frame with a Write: is it the *final* quality (the `$gui` switch)?
6. **Partial data windows.** If your EXRs have a data window smaller than the frame, check that the result lines up
   with the plate (an internal Crop is meant to make the bounding box exactly the format).
7. **Speed** at preview and final, on GPU and CPU.

## Limits for now

- **No depth of field or motion blur yet** (phase 6), and holdout edges are hard. The plate's own blurred edges
  can show a thin line (phase 5).
- **Shadows only know what the camera sees on the current frame**, plus *Thickness* behind it. USD geometry
  (phase 3) adds the rest.
- **Lights:** sun and spot. A light pasted from Houdini comes in phase 2.
- **Colour:** the temperature-to-RGB conversion assumes Rec.709 primaries. Tell me your working space (ACEScg or
  linear Rec.709) and it can match.
