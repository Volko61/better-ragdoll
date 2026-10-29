# Narrated demo video of Better Ragdoll with the Mixamo character "Remy".
#
# On GPUs where EEVEE shadows come out garbled with Vulkan (seen on Snapdragon),
# add "--gpu-backend opengl" before -b.
#
#   blender -b --factory-startup --python promo/demo.py -- build  <path/to/Remy.fbx>
#   blender -b promo/demo.blend --python promo/demo.py -- stills
#   blender -b promo/demo.blend --python promo/demo.py -- frames  (resumable)
#   blender -b promo/demo.blend --python promo/demo.py -- edit
#
# build:  imports the character, builds every shot, bakes the ragdolls, saves demo.blend
# stills: half resolution check frames in promo/output/demo_check
# frames: renders the 3D shots as JPEG frames (skips frames already rendered)
# edit:   adds titles and the voice-over (promo/voice) and encodes the final MP4,
#         plus the featured image and preview stills for the listing

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import bmesh
import bpy
from mathutils import Matrix, Vector

import better_ragdoll

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["stills"]
MODE = ARGS[0]
OUT = os.path.join(HERE, "output")
FRAMES = os.path.join(HERE, "frames")
VOICE = os.path.join(HERE, "voice")
FPS = 30
LEAD = 12          # frames of picture before each voice line
TAIL = 24          # frames after it
SPACING = 70.0     # distance between shot sets
HEIGHT = 1.78      # character height in meters
SLOWMO = 2.5       # slow motion factor of the impact shot

if not hasattr(bpy.types.Object, "better_ragdoll"):
    better_ragdoll.register()


# --------------------------------------------------------------------- timeline
def voice_durations():
    scene = bpy.data.scenes.new("probe")
    scene.render.fps = FPS
    ed = scene.sequence_editor_create()
    out = []
    i = 1
    while os.path.exists(os.path.join(VOICE, "line_%d.mp3" % i)):
        s = ed.strips.new_sound("l%d" % i, os.path.join(VOICE, "line_%d.mp3" % i), 1, 1)
        out.append(int(s.frame_duration))
        i += 1
    bpy.data.scenes.remove(scene)
    return out


def shot_table():
    """[(start, end, voice_start)] for every shot, 1-based frames."""
    shots = []
    f = 1
    for i, d in enumerate(voice_durations()):
        tail = TAIL * 2 if i == 6 else TAIL
        start = f
        end = f + LEAD + d + tail - 1
        shots.append((start, end, start + LEAD))
        f = end + 1
    return shots


# ------------------------------------------------------------------- materials
def principled(name, color, roughness=0.5, specular=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = specular
    return mat, bsdf


def concrete_material():
    mat, bsdf = principled("Concrete", (0.42, 0.42, 0.43, 1.0), 0.75)
    nt = mat.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 18.0
    noise.inputs["Detail"].default_value = 8.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.30, 0.30, 0.31, 1.0)
    ramp.color_ramp.elements[1].color = (0.52, 0.51, 0.50, 1.0)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def studio_material():
    mat, _bsdf = principled("Cyclorama", (0.30, 0.29, 0.285, 1.0), 0.45, 0.4)
    return mat


# ---------------------------------------------------------------------- geometry
def link(ob, col=None):
    (col or bpy.context.scene.collection).objects.link(ob)
    return ob


def cyclorama(x, z, mat, back=6.0):
    """Floor that curves up into a back wall, like a photo studio."""
    me = bpy.data.meshes.new("cyc")
    bm = bmesh.new()
    prof = [(y, 0.0) for y in (-16.0, -6.0, back - 0.01)]
    radius = 4.0
    for k in range(1, 13):
        a = (math.pi / 2) * k / 12
        prof.append((back + math.sin(a) * radius, radius - math.cos(a) * radius))
    prof.append((back + radius, 14.0))
    width = 56.0
    rows = []
    for y, h in prof:
        rows.append((bm.verts.new((x - width / 2, y, z + h)), bm.verts.new((x + width / 2, y, z + h))))
    for (a0, a1), (b0, b1) in zip(rows, rows[1:]):
        bm.faces.new((a0, a1, b1, b0))
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob = link(bpy.data.objects.new("Cyclorama", me))
    ob.data.materials.append(mat)
    ob.visible_shadow = False
    return ob


def box(name, lo, hi, mat, col):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = link(bpy.data.objects.new(name, me), col)
    ob.location = (Vector(lo) + Vector(hi)) * 0.5
    ob.scale = Vector(hi) - Vector(lo)
    ob.data.materials.append(mat)
    bev = ob.modifiers.new("Bevel", 'BEVEL')
    bev.width = 0.012
    bev.segments = 3
    return ob


# --------------------------------------------------------------------- character
class Remy:
    template = None

    @classmethod
    def load(cls, path):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=path)
        new = [o for o in bpy.data.objects if o not in before]
        arm = next(o for o in new if o.type == 'ARMATURE')
        meshes = [o for o in new if o.type == 'MESH']
        heads = [arm.matrix_world @ b.head_local for b in arm.data.bones]
        tails = [arm.matrix_world @ b.tail_local for b in arm.data.bones]
        zs = [v.z for v in heads + tails]
        arm.scale = arm.scale * (HEIGHT / (max(zs) - min(zs)))
        cls.template = (arm, meshes)
        # Keep the template out of the render.
        arm.location = (0.0, 0.0, -100.0)
        for o in [arm] + meshes:
            o.hide_render = True
            o.hide_viewport = True

    @classmethod
    def spawn(cls, name, location, rot_z=0.0):
        arm0, meshes0 = cls.template
        arm = arm0.copy()
        arm.name = name
        arm.animation_data_clear()
        link(arm)
        arm.location = location
        arm.rotation_euler.z += rot_z
        arm.hide_render = True
        arm.hide_viewport = False
        for m0 in meshes0:
            m = m0.copy()
            m.name = name + "_" + m0.name
            link(m)
            m.parent = arm
            m.hide_render = False
            m.hide_viewport = False
            for mod in m.modifiers:
                if mod.type == 'ARMATURE':
                    mod.object = arm
        bpy.context.view_layer.update()
        bpy.context.view_layer.objects.active = arm
        bpy.ops.better_ragdoll.detect()
        return arm


def ragdoll(arm, mode, frames, release, **settings):
    s = arm.better_ragdoll
    s.limit_mode = mode
    s.use_scene_range = False
    s.frame_start, s.frame_end = frames
    s.release_frame = release
    s.substeps = 12
    for k, v in settings.items():
        setattr(s, k, v)


def camera(name, path, target, lens=40.0, fstop=4.0):
    """Camera moving linearly along path[0] -> path[1] (with frames) looking at target."""
    cam = link(bpy.data.objects.new(name, bpy.data.cameras.new(name)))
    cam.data.lens = lens
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = fstop
    (f0, p0, t0), (f1, p1, t1) = path[0] + (target[0],), path[1] + (target[1],)
    for f, p, t in ((f0, p0, t0), (f1, p1, t1)):
        cam.location = p
        d = Vector(t) - Vector(p)
        cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        cam.data.dof.focus_distance = d.length
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        cam.data.keyframe_insert("dof.focus_distance", frame=f)
    for data in (cam, cam.data):
        ad = data.animation_data
        if ad and ad.action:
            _ease(ad.action)
    return cam


def _fcurves(action):
    try:
        return list(action.fcurves)
    except AttributeError:
        out = []
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    out.extend(cb.fcurves)
        return out


def _ease(action):
    for fc in _fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = 'SINE'
            kp.easing = 'EASE_IN_OUT'


# ------------------------------------------------------------------------- build
def build(fbx_path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Object, "better_ragdoll"):
        better_ragdoll.register()
    scene = bpy.context.scene
    scene.name = "Shots"
    scene.render.fps = FPS
    shots = shot_table()
    scene.frame_start = 1
    scene.frame_end = shots[-1][1]

    Remy.load(fbx_path)
    studio = studio_material()
    concrete = concrete_material()
    cams = []

    def rel(i, t):
        return shots[i][0] + int(t * FPS)

    # 1. Title: soft ragdoll collapsing backwards ---------------------------------
    i, x = 0, 0 * SPACING
    cyclorama(x, 0.0, studio)
    a = Remy.spawn("S1_Soft", (x, 0.0, 0.0))
    ragdoll(a, 'SOFT', shots[i][:2], rel(i, 2.2), use_impact=True,
            impact_direction=(0.0, 1.0, 0.25), impact_speed=1.1, impact_focus=0.3,
            limb_kick=3.0, seed=1)
    cams.append(camera("Cam1", ((shots[i][0], (x - 2.6, -5.2, 1.5)), (shots[i][1], (x - 1.6, -4.0, 1.0))),
                       ((x, 0.2, 0.95), (x, 0.7, 0.35)), 45, 2.8))

    # 2-3. Collapse from standing: hard, then soft ----------------------------------
    for i, mode in ((1, 'HARD'), (2, 'SOFT')):
        x = i * SPACING
        cyclorama(x, 0.0, studio)
        a = Remy.spawn("S%d_%s" % (i + 1, mode.title()), (x, 0.0, 0.0))
        ragdoll(a, mode, shots[i][:2], rel(i, 1.6), use_impact=True,
                impact_direction=(0.15, 1.0, 0.1), impact_speed=0.7, impact_focus=0.3,
                limb_kick=2.0, seed=4)
        cams.append(camera("Cam%d" % (i + 1),
                           ((shots[i][0], (x + 3.4, -4.4, 1.6)), (shots[i][1], (x + 2.5, -3.4, 0.9))),
                           ((x, 0.3, 0.9), (x, 0.9, 0.25)), 40, 2.8))

    # 4. Zero gravity: hard vs soft ------------------------------------------------
    i, x = 3, 3 * SPACING
    cyclorama(x, -1.0, studio)
    for dx, mode in ((-1.25, 'HARD'), (1.25, 'SOFT')):
        a = Remy.spawn("S4_%s" % mode.title(), (x + dx, 0.0, 0.25))
        ragdoll(a, mode, shots[i][:2], rel(i, 1.0), gravity_scale=0.0, use_ground=False,
                use_impact=True, impact_direction=(0.0, 1.0, 0.0), impact_speed=0.05,
                impact_focus=0.0, limb_kick=0.0, seed=2)
    cams.append(camera("Cam4", ((shots[i][0], (x, -7.6, 1.35)), (shots[i][1], (x, -6.6, 1.25))),
                       ((x, 0.0, 1.15), (x, 0.0, 1.15)), 38, 5.6))

    # 5. Stairs: hard vs soft --------------------------------------------------------
    i, x = 4, 4 * SPACING
    step_d, step_h, steps = 0.34, 0.2, 9
    floor_z = -step_h * steps
    cyclorama(x, floor_z, studio, back=1.6)
    stairs = bpy.data.collections.new("Stairs")
    scene.collection.children.link(stairs)
    for k, x0 in enumerate((x - 1.4, x + 1.4)):
        box("landing", (x0 - 1.15, -0.45, floor_z - 1.0), (x0 + 1.15, 1.6, 0.0), concrete, stairs)
        for n in range(steps):
            y1 = -0.45 - step_d * n
            box("step", (x0 - 1.15, y1 - step_d, floor_z - 1.0), (x0 + 1.15, y1, -step_h * (n + 1)), concrete, stairs)
    for dx, mode in ((-1.4, 'HARD'), (1.4, 'SOFT')):
        a = Remy.spawn("S5_%s" % mode.title(), (x + dx, 0.0, 0.0))
        ragdoll(a, mode, shots[i][:2], rel(i, 0.8), use_ground=True, ground_height=floor_z,
                collider_collection=stairs, use_impact=True, impact_direction=(0.0, -1.0, 0.25),
                impact_speed=2.6, impact_bone="mixamorig:Spine2", impact_focus=0.45,
                limb_kick=6.0, limb_kick_random=0.5, seed=3)
    cams.append(camera("Cam5", ((shots[i][0], (x + 3.6, -9.6, 1.9)), (shots[i][1], (x + 2.4, -8.6, 1.2))),
                       ((x, -1.6, -0.6), (x, -2.6, -1.1)), 30, 6.0))

    # 6. Impact with rotational kick -------------------------------------------------
    i, x = 5, 5 * SPACING
    cyclorama(x, 0.0, studio, back=7.0)
    a = Remy.spawn("S6_Soft", (x, 0.0, 0.0))
    ragdoll(a, 'SOFT', shots[i][:2], rel(i, 2.0), use_impact=True,
            impact_direction=(0.0, 1.0, 0.3), impact_speed=3.0, impact_focus=0.5,
            limb_kick=9.0, limb_kick_random=0.6, seed=5)
    a["demo_slowmo"] = SLOWMO
    cams.append(camera("Cam6", ((shots[i][0], (x + 3.4, -4.6, 1.3)), (shots[i][1], (x + 3.4, -2.0, 1.2))),
                       ((x, 0.3, 0.9), (x + 0.2, 1.8, 0.3)), 42, 4.0))

    # 7. Outro: three ragdolls, orbiting camera ------------------------------------
    i, x = 6, 6 * SPACING
    cyclorama(x, 0.0, studio)
    for k, (dx, dy) in enumerate(((-1.6, 0.6), (0.0, -0.2), (1.6, 0.6))):
        a = Remy.spawn("S7_Soft%d" % k, (x + dx, dy, 0.0))
        ragdoll(a, 'SOFT', shots[i][:2], rel(i, 0.8 + 0.5 * k), use_impact=True,
                impact_direction=((-0.4, 0.0, 0.4)[k], 1.0, 0.15), impact_speed=1.4 + 0.4 * k,
                impact_focus=0.35, limb_kick=4.0, limb_kick_random=0.6, seed=10 + k)
    cams.append(camera("Cam7", ((shots[i][0], (x - 2.5, -6.2, 1.8)), (shots[i][1], (x + 2.8, -5.4, 2.2))),
                       ((x, 0.2, 0.7), (x, 0.4, 0.3)), 35, 5.6))

    for (start, _end, _v), cam in zip(shots, cams):
        scene.timeline_markers.new(cam.name, frame=start).camera = cam
    scene.camera = cams[0]

    # Lights ---------------------------------------------------------------------------
    sun = link(bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN')))
    sun.data.energy = 3.2
    sun.data.angle = math.radians(4.0)
    sun.data.color = (1.0, 0.93, 0.84)
    sun.rotation_euler = (math.radians(48), 0.0, math.radians(32))
    # One rim and one fill light, jumping to the set of the current shot so only
    # two area lights ever cast shadows.
    rim = link(bpy.data.objects.new("Rim", bpy.data.lights.new("Rim", 'AREA')))
    rim.data.energy = 900.0
    rim.data.size = 4.0
    rim.data.color = (0.75, 0.85, 1.0)
    fill = link(bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", 'AREA')))
    fill.data.energy = 220.0
    fill.data.size = 6.0
    fill.data.use_shadow = False
    for k, (start, _e, _v) in enumerate(shots):
        x = k * SPACING
        for light, offset in ((rim, (-3.5, 3.5, 4.0)), (fill, (-4.0, -5.0, 2.5))):
            light.location = Vector((x, 0.0, 0.0)) + Vector(offset)
            light.rotation_euler = (Vector((x, 0.0, 0.8)) - light.location).to_track_quat('-Z', 'Y').to_euler()
            light.keyframe_insert("location", frame=start)
            light.keyframe_insert("rotation_euler", frame=start)
    for light in (rim, fill):
        for fc in _fcurves(light.animation_data.action):
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'

    # World: studio HDRI for lighting and reflections -----------------------------------
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    scene.world = world
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    hdri_dir = bpy.utils.system_resource('DATAFILES', path="studiolights/world")
    hdri = os.path.join(hdri_dir, "interior.exr")
    if os.path.exists(hdri):
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.25
    # The camera sees a plain studio grey instead of the HDRI.
    plain = nt.nodes.new("ShaderNodeBackground")
    plain.inputs["Color"].default_value = (0.2, 0.2, 0.2, 1.0)
    path = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(bg.outputs["Background"], mix.inputs[1])
    nt.links.new(plain.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], nt.nodes["World Output"].inputs["Surface"])

    # Render settings -------------------------------------------------------------------
    r = scene.render
    r.engine = 'BLENDER_EEVEE'
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
    r.use_motion_blur = True
    if hasattr(r, "motion_blur_shutter"):
        r.motion_blur_shutter = 0.4
    ee = scene.eevee
    ee.taa_render_samples = 32
    for attr, val in (("use_raytracing", True), ("use_shadows", True), ("shadow_pool_size", '512'),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8),
                      ("use_fast_gi", True), ("fast_gi_resolution", '2'),
                      ("use_volumetric_shadows", False)):
        if hasattr(ee, attr):
            try:
                setattr(ee, attr, val)
            except (TypeError, ValueError):
                pass
    scene.view_settings.view_transform = 'AgX'
    looks = [i.identifier for i in scene.view_settings.bl_rna.properties["look"].enum_items_static] \
        if hasattr(scene.view_settings.bl_rna.properties["look"], "enum_items_static") else []
    for wanted in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            scene.view_settings.look = wanted
            break
        except TypeError:
            continue

    # Bake every ragdoll -------------------------------------------------------------------
    for ob in list(scene.objects):
        if ob.type == 'ARMATURE' and ob.name[0] == 'S':
            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            # Slow motion: simulate a shorter time step per frame.
            scene.render.fps = int(FPS * ob.get("demo_slowmo", 1.0))
            res = bpy.ops.better_ragdoll.simulate_bake()
            scene.render.fps = FPS
            print("baked", ob.name, res)

    with open(os.path.join(HERE, "demo_shots.json"), "w") as f:
        json.dump(shots, f)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "demo.blend"))


# ------------------------------------------------------------------------ render
def shots_from_file():
    with open(os.path.join(HERE, "demo_shots.json")) as f:
        return [tuple(s) for s in json.load(f)]


def render_still(scene, frame, path, scale=100):
    scene.frame_set(frame)
    r = scene.render
    r.resolution_percentage = scale
    r.image_settings.media_type = 'IMAGE'
    r.image_settings.file_format = 'PNG'
    r.filepath = path
    bpy.ops.render.render(write_still=True, scene=scene.name)


def stills(frames=None):
    scene = bpy.data.scenes["Shots"]
    shots = shots_from_file()
    d = os.path.join(OUT, "demo_check")
    os.makedirs(d, exist_ok=True)
    if frames is None:
        frames = []
        for s, e, _v in shots:
            frames += [s + 5, (s + e) // 2, e - 5]
    for f in frames:
        render_still(scene, f, os.path.join(d, "f%04d.png" % f), 50)


def frames():
    scene = bpy.data.scenes["Shots"]
    os.makedirs(FRAMES, exist_ok=True)
    r = scene.render
    r.resolution_percentage = 100
    r.image_settings.media_type = 'IMAGE'
    r.image_settings.file_format = 'JPEG'
    r.image_settings.quality = 95
    r.filepath = os.path.join(FRAMES, "f")
    r.use_overwrite = False
    r.use_placeholder = True
    bpy.context.window.scene = scene if bpy.context.window else None
    bpy.ops.render.render(animation=True, scene=scene.name)


# -------------------------------------------------------------------------- edit
WHITE = (1.0, 1.0, 1.0, 1.0)
ORANGE = (1.0, 0.62, 0.25, 1.0)
GREY = (0.78, 0.82, 0.9, 1.0)


def edit():
    shots = shots_from_file()
    total = shots[-1][1]
    scene = bpy.data.scenes.get("Edit") or bpy.data.scenes.new("Edit")
    scene.render.fps = FPS
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.render.resolution_percentage = 100
    scene.frame_start, scene.frame_end = 1, total
    ed = scene.sequence_editor_create()
    for s in list(ed.strips):
        ed.strips.remove(s)

    files = sorted(fn for fn in os.listdir(FRAMES) if fn.endswith(".jpg"))
    img = ed.strips.new_image("Shots", os.path.join(FRAMES, files[0]), 1, 1)
    for fn in files[1:]:
        img.elements.append(fn)

    for i, (_s, _e, v) in enumerate(shots):
        snd = ed.strips.new_sound("Voice%d" % (i + 1), os.path.join(VOICE, "line_%d.mp3" % (i + 1)), 2, v)
        snd.volume = 1.0

    def text(t, start, end, x, y, size, color=WHITE, anchor='CENTER', box=True, bold=False, ch=4):
        st = ed.strips.new_effect("T", 'TEXT', ch, start, length=end - start)
        st.text = t
        st.font_size = size
        st.color = color
        st.location = (x, y)
        st.anchor_x = anchor
        st.alignment_x = anchor
        st.anchor_y = 'CENTER'
        st.use_shadow = True
        st.shadow_color = (0, 0, 0, 0.6)
        st.shadow_blur = 0.4
        st.use_bold = bold
        if box:
            st.use_box = True
            st.box_color = (0.02, 0.02, 0.025, 0.55)
            st.box_margin = 0.012
            if hasattr(st, "box_roundness"):
                st.box_roundness = 0.6
        fade = 8
        try:
            st.blend_alpha = 0.0
            st.keyframe_insert("blend_alpha", frame=start)
            st.blend_alpha = 1.0
            st.keyframe_insert("blend_alpha", frame=start + fade)
            st.keyframe_insert("blend_alpha", frame=end - fade)
            st.blend_alpha = 0.0
            st.keyframe_insert("blend_alpha", frame=end)
        except (TypeError, RuntimeError, AttributeError):
            st.blend_alpha = 1.0
        return st

    s = shots
    # Title
    text("Better Ragdoll", s[0][0] + 6, s[0][0] + 150, 0.07, 0.83, 120, WHITE, 'LEFT', False, True, 4)
    text("Ragdolls that fall like real bodies", s[0][0] + 20, s[0][0] + 150, 0.072, 0.73, 46, ORANGE, 'LEFT', False, False, 5)
    text("A free extension for Blender", s[0][0] + 150, s[0][1], 0.072, 0.83, 52, WHITE, 'LEFT', False, False, 4)
    # Hard / soft collapse
    text("Classic ragdoll  ·  hard limits", s[1][0] + 4, s[1][1], 0.5, 0.1, 50, GREY)
    text("Better Ragdoll  ·  soft limits", s[2][0] + 4, s[2][1], 0.5, 0.1, 50, ORANGE)
    # Zero gravity
    text("Zero gravity  ·  neutral body posture", s[3][0] + 4, s[3][1], 0.5, 0.9, 50)
    text("Classic ragdoll", s[3][0] + 20, s[3][1], 0.27, 0.12, 44, GREY, ch=5)
    text("Better Ragdoll", s[3][0] + 20, s[3][1], 0.73, 0.12, 44, ORANGE, ch=6)
    # Stairs
    text("Down the stairs", s[4][0] + 4, s[4][1], 0.5, 0.9, 50)
    text("Classic ragdoll", s[4][0] + 10, s[4][1], 0.25, 0.12, 44, GREY, ch=5)
    text("Better Ragdoll", s[4][0] + 10, s[4][1], 0.72, 0.12, 44, ORANGE, ch=6)
    # Impact
    text("Rotational impact  ·  arms with the push, legs against it", s[5][0] + 4, s[5][1], 0.5, 0.1, 46)
    text("Slow motion", s[5][0] + 4, s[5][1], 0.93, 0.92, 36, GREY, 'RIGHT', True, False, 5)
    # Outro: steps follow the narration
    v = s[6][2]
    text("1   Detect Bones", v + 40, s[6][1], 0.07, 0.76, 54, WHITE, 'LEFT', True, False, 4)
    text("2   Release frame & impact", v + 95, s[6][1], 0.07, 0.66, 54, WHITE, 'LEFT', True, False, 5)
    text("3   Simulate & Bake", v + 175, s[6][1], 0.07, 0.56, 54, WHITE, 'LEFT', True, False, 6)
    text("Better Ragdoll", v + 250, s[6][1], 0.5, 0.2, 96, ORANGE, 'CENTER', False, True, 7)
    text("github.com/Volko61/better-ragdoll  ·  Blender 4.2+  ·  GPL", v + 270, s[6][1], 0.5, 0.11, 40, WHITE, 'CENTER', False, False, 8)

    r = scene.render
    r.image_settings.media_type = 'VIDEO'
    r.image_settings.file_format = 'FFMPEG'
    r.ffmpeg.format = 'MPEG4'
    r.ffmpeg.codec = 'H264'
    r.ffmpeg.constant_rate_factor = 'HIGH'
    r.ffmpeg.ffmpeg_preset = 'GOOD'
    r.ffmpeg.audio_codec = 'AAC'
    r.ffmpeg.audio_bitrate = 192
    r.ffmpeg.audio_channels = 'STEREO'
    r.ffmpeg.audio_mixrate = 48000
    r.filepath = os.path.join(OUT, "better_ragdoll_demo.mp4")
    r.use_overwrite = True
    bpy.ops.render.render(animation=True, scene=scene.name)

    # Listing images from the edited frames.
    r.image_settings.media_type = 'IMAGE'
    r.image_settings.file_format = 'PNG'
    for name, frame in (("featured_1920x1080.png", s[4][0] + 75),
                        ("preview_zero_gravity.png", s[3][1] - 30),
                        ("preview_stairs.png", s[4][0] + 120),
                        ("preview_impact.png", s[5][2] + 95),
                        ("preview_title.png", s[0][0] + 100)):
        scene.frame_set(frame)
        r.filepath = os.path.join(OUT, name)
        bpy.ops.render.render(write_still=True, scene=scene.name)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "demo.blend"))


if MODE == "build":
    build(ARGS[1])
elif MODE == "stills":
    stills([int(a) for a in ARGS[1:]] or None)
elif MODE == "frames":
    frames()
elif MODE == "edit":
    edit()
print("DEMO DONE", MODE)
