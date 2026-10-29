# Builds the promotional scene for Better Ragdoll and renders the listing media.
#
#   blender -b --factory-startup --python promo/showcase.py -- [preview|icon|full]
#
# preview: low resolution stills of key frames to check the framing.
# icon:    only the 256x256 icon.
# full:    video (MP4), featured image, preview stills and icon in promo/output.

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import addon_utils
import bmesh
import bpy
from mathutils import Matrix, Vector

import better_ragdoll
from better_ragdoll.model import build_model

MODE = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "preview"
OUT = os.path.join(HERE, "output")
os.makedirs(OUT, exist_ok=True)

FPS = 30
TITLE = (1, 60)
ZERO_G = (61, 225)
STAIRS = (226, 450)

ORANGE = (0.93, 0.42, 0.05, 1.0)
STEEL = (0.42, 0.50, 0.62, 1.0)
LIGHT = (0.80, 0.80, 0.82, 1.0)
DARK = (0.06, 0.06, 0.07, 1.0)
WHITE = (0.95, 0.95, 0.95, 1.0)

better_ragdoll.register()
try:
    addon_utils.enable("rigify")
except Exception:
    pass

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS
scene.frame_start = TITLE[0]
scene.frame_end = STAIRS[1]


def material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.roughness = 0.5
    return mat


def link(ob, col=None):
    (col or scene.collection).objects.link(ob)
    return ob


def capsule_mesh(name, radius, half):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=28, v_segments=16, radius=radius)
    for v in bm.verts:
        if v.co.z > 1e-6:
            v.co.z += half
        elif v.co.z < -1e-6:
            v.co.z -= half
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return me


def make_character(name, location, mode, color):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.armature_human_metarig_add()
    arm = bpy.context.active_object
    arm.name = name
    arm.location = location
    arm.show_in_front = False
    arm.hide_render = True
    bpy.context.view_layer.update()
    bpy.ops.better_ragdoll.detect()
    s = arm.better_ragdoll
    s.limit_mode = mode
    model = build_model(arm, s)

    mat = material(name + "_mat", color)
    visor = material("visor", DARK)
    for body in model.bodies:
        rot = body.rest_rot
        a = body.com + rot @ body.seg_a
        b = body.com + rot @ body.seg_b
        axis = b - a
        half = axis.length * 0.5
        center = (a + b) * 0.5
        quat = axis.to_track_quat('Z', 'Y') if half > 1e-5 else rot
        ob = link(bpy.data.objects.new(name + "_" + body.primary,
                                       capsule_mesh(body.primary, body.radius, half)))
        ob.data.materials.append(mat)
        world = Matrix.LocRotScale(center, quat, None)
        bone = arm.data.bones[body.primary]
        ob.parent = arm
        ob.parent_type = 'BONE'
        ob.parent_bone = body.primary
        ob.matrix_parent_inverse = (arm.matrix_world @ bone.matrix_local
                                    @ Matrix.Translation((0.0, bone.length, 0.0))).inverted()
        ob.matrix_basis = world
        if body.role == 'HEAD':
            vz = link(bpy.data.objects.new(name + "_visor", capsule_mesh("visor", body.radius * 0.45, body.radius * 0.35)))
            vz.data.materials.append(visor)
            vz.parent = arm
            vz.parent_type = 'BONE'
            vz.parent_bone = body.primary
            vz.matrix_parent_inverse = ob.matrix_parent_inverse.copy()
            pos = body.com + model.forward * body.radius * 0.72 + Vector((0, 0, body.radius * 0.15))
            vz.matrix_basis = Matrix.LocRotScale(pos, Vector((1, 0, 0)).to_track_quat('Z', 'Y'), Vector((1.0, 0.55, 1.0)))
    return arm


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
    return ob


def text(body, location, size, color=WHITE, rot=(math.radians(90), 0, 0)):
    cu = bpy.data.curves.new("txt", 'FONT')
    cu.body = body
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.size = size
    ob = link(bpy.data.objects.new("txt", cu))
    ob.location = location
    ob.rotation_euler = rot
    cu.materials.append(material("txt_%d" % int(color[0] * 100), color))
    return ob


def camera(name, location, target, lens=35.0):
    cam = link(bpy.data.objects.new(name, bpy.data.cameras.new(name)))
    cam.location = location
    cam.data.lens = lens
    d = Vector(target) - Vector(location)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return cam


def setup_common(arm, release, frame_range):
    s = arm.better_ragdoll
    s.release_frame = release
    s.use_scene_range = False
    s.frame_start = frame_range[0]
    s.frame_end = frame_range[1]
    s.substeps = 12


# ---------------------------------------------------------------- title shot
TX = -30.0
title_char = make_character("TitleDoll", (TX + 1.7, 0.0, 0.0), 'SOFT', ORANGE)
bpy.context.view_layer.objects.active = title_char
bpy.ops.better_ragdoll.preview_neutral()
title_char.rotation_euler = (0.0, 0.0, math.radians(-20))
text("Better Ragdoll", (TX - 0.9, 0.0, 1.25), 0.42)
text("soft joint limits  ·  neutral body posture  ·  rotational impacts",
     (TX - 0.9, 0.0, 0.85), 0.085, (0.85, 0.85, 0.85, 1.0))
cam_title = camera("CamTitle", (TX, -6.2, 1.0), (TX, 0.0, 1.0), 40)

# ---------------------------------------------------------------- zero gravity
ZX = 30.0
hard_z = make_character("HardZeroG", (ZX - 1.15, 0.0, 0.0), 'HARD', STEEL)
soft_z = make_character("SoftZeroG", (ZX + 1.15, 0.0, 0.0), 'SOFT', ORANGE)
for arm in (hard_z, soft_z):
    setup_common(arm, ZERO_G[0] + 10, (TITLE[0], STAIRS[1]))
    s = arm.better_ragdoll
    s.gravity_scale = 0.0
    s.use_ground = False
    s.use_impact = True
    s.impact_direction = (0.0, 1.0, 0.1)
    s.impact_speed = 0.12
    s.impact_focus = 0.2
    s.limb_kick = 1.5
    s.limb_kick_random = 0.3
text("Zero gravity", (ZX, 0.0, 2.45), 0.2)
text("Hard limits (classic)", (ZX - 1.15, 0.0, -0.15), 0.11, (0.75, 0.80, 0.9, 1.0))
text("Soft limits + neutral tension", (ZX + 1.15, 0.0, -0.15), 0.11, (1.0, 0.7, 0.45, 1.0))
cam_zero = camera("CamZeroG", (ZX, -7.2, 1.1), (ZX, 0.0, 1.1), 32)

# ---------------------------------------------------------------- stairs
stairs_col = bpy.data.collections.new("Stairs")
scene.collection.children.link(stairs_col)
grey = material("stairs", LIGHT)
STEP_D, STEP_H, STEPS = 0.34, 0.2, 9
for i, x0 in enumerate((-1.4, 1.4)):
    box("landing_%d" % i, (x0 - 1.2, -0.45, -3.0), (x0 + 1.2, 1.2, 0.0), grey, stairs_col)
    for k in range(STEPS):
        y1 = -0.45 - STEP_D * k
        box("step_%d_%d" % (i, k), (x0 - 1.2, y1 - STEP_D, -3.0), (x0 + 1.2, y1, -STEP_H * (k + 1)), grey, stairs_col)
floor_z = -STEP_H * STEPS
box("floor", (-6, -12, floor_z - 1.0), (6, -0.45 - STEP_D * STEPS + 0.01, floor_z), grey, stairs_col)

hard_s = make_character("HardStairs", (-1.4, 0.0, 0.0), 'HARD', STEEL)
soft_s = make_character("SoftStairs", (1.4, 0.0, 0.0), 'SOFT', ORANGE)
for arm in (hard_s, soft_s):
    setup_common(arm, STAIRS[0] + 15, (TITLE[0], STAIRS[1]))
    s = arm.better_ragdoll
    s.use_ground = False
    s.collider_collection = stairs_col
    s.use_impact = True
    s.impact_direction = (0.0, -1.0, 0.25)
    s.impact_speed = 2.6
    s.impact_bone = "spine.003"
    s.impact_focus = 0.45
    s.limb_kick = 6.0
    s.limb_kick_random = 0.5
    s.seed = 3
text("Falling down stairs", (0.0, 1.15, 1.75), 0.34)
text("Hard limits (classic)", (-1.4, 1.15, 1.2), 0.19, (0.75, 0.80, 0.9, 1.0))
text("Soft limits + neutral tension", (1.4, 1.15, 1.2), 0.19, (1.0, 0.7, 0.45, 1.0))
cam_stairs = camera("CamStairs", (3.2, -9.8, 2.2), (0.0, -2.2, -0.85), 26)

# ---------------------------------------------------------------- cameras over time
for frame, cam in ((TITLE[0], cam_title), (ZERO_G[0], cam_zero), (STAIRS[0], cam_stairs)):
    m = scene.timeline_markers.new(cam.name, frame=frame)
    m.camera = cam
scene.camera = cam_title

# ---------------------------------------------------------------- look
world = bpy.data.worlds.new("World")
world.color = (0.035, 0.037, 0.042)
scene.world = world
scene.render.engine = 'BLENDER_WORKBENCH'
sh = scene.display.shading
sh.light = 'STUDIO'
sh.color_type = 'MATERIAL'
sh.show_shadows = True
sh.shadow_intensity = 0.55
sh.show_cavity = True
sh.cavity_type = 'BOTH'
sh.show_specular_highlight = True
scene.display.light_direction = (0.45, -0.35, 0.82)
scene.display.shadow_shift = 0.05
scene.display.render_aa = '8'
scene.view_settings.view_transform = 'Standard'

# ---------------------------------------------------------------- bake
for arm in (hard_z, soft_z, hard_s, soft_s):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.better_ragdoll.simulate_bake()
    print("baked", arm.name)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "showcase.blend"))


def still(frame, path, w=1920, h=1080, cam=None):
    scene.frame_set(frame)
    if cam is not None:
        scene.camera = cam
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.image_settings.media_type = 'IMAGE'
    r.image_settings.file_format = 'PNG'
    r.filepath = path
    bpy.ops.render.render(write_still=True)


def render_icon():
    """Orange doll in its neutral posture on a dark background."""
    cam_icon = camera("CamIcon", (TX + 1.7 + 2.2, -2.6, 1.1), (TX + 1.7, 0.0, 0.98), 50)
    cam_icon.data.type = 'ORTHO'
    cam_icon.data.ortho_scale = 2.05
    fonts = [ob for ob in scene.objects if ob.type == 'FONT']
    for ob in fonts:
        ob.hide_render = True
    markers = [(m.name, m.frame, m.camera) for m in scene.timeline_markers]
    scene.timeline_markers.clear()
    still(30, os.path.join(OUT, "icon_256.png"), 256, 256, cam_icon)
    for ob in fonts:
        ob.hide_render = False
    for name, frame, cam in markers:
        scene.timeline_markers.new(name, frame=frame).camera = cam


def render_video():
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1080, 100
    r.image_settings.media_type = 'VIDEO'
    r.image_settings.file_format = 'FFMPEG'
    r.ffmpeg.format = 'MPEG4'
    r.ffmpeg.codec = 'H264'
    r.ffmpeg.constant_rate_factor = 'HIGH'
    r.ffmpeg.ffmpeg_preset = 'GOOD'
    r.filepath = os.path.join(OUT, "better_ragdoll_demo.mp4")
    scene.frame_start, scene.frame_end = TITLE[0], STAIRS[1]
    bpy.ops.render.render(animation=True)


if MODE == "preview":
    for f in (30, ZERO_G[0] + 5, ZERO_G[0] + 80, ZERO_G[1] - 5, STAIRS[0] + 5,
              STAIRS[0] + 45, STAIRS[0] + 90, STAIRS[1] - 5):
        still(f, os.path.join(OUT, "check_%03d.png" % f), 960, 540)
elif MODE == "icon":
    render_icon()
else:
    still(STAIRS[0] + 52, os.path.join(OUT, "featured_1920x1080.png"))
    still(ZERO_G[1] - 2, os.path.join(OUT, "preview_zero_gravity.png"))
    still(STAIRS[0] + 70, os.path.join(OUT, "preview_stairs.png"))
    still(30, os.path.join(OUT, "preview_title.png"))
    render_icon()
    render_video()
print("SHOWCASE DONE")
