# SPDX-License-Identifier: GPL-3.0-or-later
"""Sampling of the source animation, simulation loop and baking to an action."""

import json
import math
import random

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .model import RagdollError, build_model, neutral_pose, unit_world
from .solver import Params, Solver


def make_params(settings, scene):
    p = Params()
    if scene.use_gravity:
        g = Vector(scene.gravity)
    else:
        g = Vector((0.0, 0.0, -9.81))
    p.gravity = g * settings.gravity_scale
    p.soft = settings.limit_mode == 'SOFT'
    p.tension = settings.tension if settings.use_tension else 0.0
    p.tension_damping = settings.tension_damping
    p.soft_zone = settings.soft_zone
    p.soft_strength = settings.soft_strength
    p.soft_damping = settings.soft_damping
    p.joint_damping = settings.joint_damping
    p.friction = settings.friction
    p.self_collision = settings.self_collision
    p.use_ground = settings.use_ground
    p.ground_height = settings.ground_height
    p.drive_stiffness = settings.drive_stiffness
    p.linear_damping = settings.air_damping
    p.angular_damping = settings.air_damping * 2.0
    return p


def frame_range(scene, settings):
    if settings.use_scene_range:
        return scene.frame_start, scene.frame_end
    return settings.frame_start, max(settings.frame_end, settings.frame_start + 1)


def _skinned_objects(obj):
    out = set()
    for ob in bpy.data.objects:
        if ob.parent == obj:
            out.add(ob)
        for mod in getattr(ob, "modifiers", ()):
            if mod.type == 'ARMATURE' and mod.object == obj:
                out.add(ob)
    return out


def build_bvh(collection, depsgraph, exclude):
    if collection is None:
        return None
    verts = []
    tris = []
    for ob in collection.all_objects:
        if ob in exclude or ob.type not in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}:
            continue
        ev = ob.evaluated_get(depsgraph)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        if me is None:
            continue
        me.calc_loop_triangles()
        mw = ev.matrix_world
        base = len(verts)
        verts.extend(mw @ v.co for v in me.vertices)
        tris.extend(tuple(base + i for i in t.vertices) for t in me.loop_triangles)
        ev.to_mesh_clear()
    if not tris:
        return None
    return BVHTree.FromPolygons(verts, tris)


def restore_source(obj):
    """Put the original action and bone constraints back if a bake is showing."""
    rb = obj.better_ragdoll
    ad = obj.animation_data
    if ad is not None and rb.ragdoll_action is not None and ad.action == rb.ragdoll_action:
        ad.action = rb.original_action
    if rb.muted_constraints:
        try:
            items = json.loads(rb.muted_constraints)
        except ValueError:
            items = []
        for bone_name, con_name in items:
            pb = obj.pose.bones.get(bone_name)
            if pb is None:
                continue
            con = pb.constraints.get(con_name)
            if con is not None:
                con.mute = False
        rb.muted_constraints = ""


def sample_animation(scene, obj, frames, collider_collection=None, animated_colliders=False):
    samples = {}
    bvhs = {}
    exclude = _skinned_objects(obj) | {obj}
    for f in frames:
        scene.frame_set(f)
        omw = obj.matrix_world.copy()
        poses = {pb.name: pb.matrix.copy() for pb in obj.pose.bones}
        samples[f] = (omw, poses)
        if animated_colliders and collider_collection is not None:
            bvhs[f] = build_bvh(collider_collection, bpy.context.evaluated_depsgraph_get(), exclude)
    return samples, bvhs


def _anim_body_poses(model, sample):
    omw, poses = sample
    out = []
    for body in model.bodies:
        loc, rot = unit_world(omw @ poses[body.primary])
        out.append(model.body_pose_from_bone(body, loc, rot))
    return out


def _blend_weight(body, t, settings):
    start = settings.release_frame + (settings.leg_delay if body.lower_body else 0.0)
    if t < start:
        return 1.0
    if settings.blend_duration <= 0.0:
        return 0.0
    u = (t - start) / settings.blend_duration
    if u >= 1.0:
        return 0.0
    return 1.0 - u * u * (3.0 - 2.0 * u)


def _hit_body(model, obj, settings):
    name = settings.impact_bone
    if name:
        bone = obj.data.bones.get(name)
        while bone is not None:
            if bone.name in model.bone_body:
                return model.bone_body[bone.name]
            bone = bone.parent
    # Default: the heaviest spine body (chest), or the root.
    best = 0
    best_mass = -1.0
    for b in model.bodies:
        if b.role == 'SPINE' and b.mass > best_mass:
            best, best_mass = b.index, b.mass
    return best


def simulate(context, obj, settings, progress=None):
    scene = context.scene
    f0, f1 = frame_range(scene, settings)
    if f1 <= f0:
        raise RagdollError("The frame range is empty")
    fps = scene.render.fps / scene.render.fps_base

    restore_source(obj)
    model = build_model(obj, settings)
    params = make_params(settings, scene)
    solver = Solver(model, params)

    current = scene.frame_current
    samples, bvhs = sample_animation(
        scene, obj, range(f0 - 1, f1 + 1),
        settings.collider_collection, settings.animated_colliders)
    scene.frame_set(current)
    if not settings.animated_colliders:
        exclude = _skinned_objects(obj) | {obj}
        solver.bvh = build_bvh(settings.collider_collection, context.evaluated_depsgraph_get(), exclude)

    anim = {f: _anim_body_poses(model, s) for f, s in samples.items()}

    # Initial state, velocities inherited from the animation.
    for i in range(len(model.bodies)):
        x0, q0 = anim[f0 - 1][i]
        x1, q1 = anim[f0][i]
        v = (x1 - x0) * fps
        dq = q1 @ q0.conjugated()
        w = Vector((dq.x, dq.y, dq.z)) * (2.0 * fps)
        if dq.w < 0.0:
            w = -w
        solver.set_body(i, x1, q1, v, w)

    results = {f0: solver.poses()}
    n = max(1, settings.substeps)
    h = 1.0 / (fps * n)
    rng = random.Random(settings.seed)
    impact_frame = settings.release_frame + settings.impact_delay
    hit = _hit_body(model, obj, settings)
    direction = Vector(settings.impact_direction)
    bodies = model.bodies

    for f in range(f0, f1):
        if settings.animated_colliders:
            solver.bvh = bvhs.get(f)
        if settings.use_impact and f == impact_frame:
            solver.dynamic = [_blend_weight(b, f + 1e-4, settings) < 1.0 for b in bodies]
            solver.apply_impact(
                direction, settings.impact_speed, settings.impact_focus, hit,
                settings.limb_kick, settings.limb_kick_random, rng)
        a0 = anim[f]
        a1 = anim[f + 1]
        for k in range(n):
            a = (k + 1) / n
            t = f + a
            weights = [_blend_weight(b, t, settings) for b in bodies]
            targets = []
            for i, wgt in enumerate(weights):
                if wgt <= 0.0:
                    targets.append(None)
                else:
                    x0, q0 = a0[i]
                    x1, q1 = a1[i]
                    targets.append((x0.lerp(x1, a), q0.slerp(q1, a)))
            solver.substep(h, weights, targets)
        results[f + 1] = solver.poses()
        if progress is not None:
            progress((f + 1 - f0) / (f1 - f0))
    return model, samples, results


# ---------------------------------------------------------------------- output
def pose_matrices(obj, model, body_poses, sample):
    """Armature space pose matrix of every bone, given the world pose of every body."""
    omw, anim = sample
    omw_inv = omw.inverted()
    bones = obj.data.bones
    out = {}
    for name in model.bone_order:
        bi = model.bone_body.get(name)
        if bi is not None:
            x, q = body_poses[bi]
            bw = Matrix.LocRotScale(x, q, None) @ model.bodies[bi].offsets[name]
            loc, rot, _s = (omw_inv @ bw).decompose()
            _l, _r, scale = anim[name].decompose()
            out[name] = Matrix.LocRotScale(loc, rot, scale)
        else:
            parent = bones[name].parent
            if parent is None:
                out[name] = anim[name].copy()
            else:
                out[name] = out[parent.name] @ anim[parent.name].inverted_safe() @ anim[name]
    return out


def _rest_relative(bones):
    rel = {}
    for b in bones:
        if b.parent is None:
            rel[b.name] = b.matrix_local.inverted_safe()
        else:
            rel[b.name] = (b.parent.matrix_local.inverted_safe() @ b.matrix_local).inverted_safe()
    return rel


def basis_matrices(obj, mats, rest_rel=None):
    bones = obj.data.bones
    if rest_rel is None:
        rest_rel = _rest_relative(bones)
    out = {}
    for name, m in mats.items():
        parent = bones[name].parent
        if parent is None:
            out[name] = rest_rel[name] @ m
        else:
            out[name] = rest_rel[name] @ mats[parent.name].inverted_safe() @ m
    return out


def _set_channels(pb, basis, prev):
    loc, rot, scale = basis.decompose()
    pb.location = loc
    pb.scale = scale
    mode = pb.rotation_mode
    if mode == 'QUATERNION':
        last = prev.get(pb.name)
        if last is not None and last.dot(rot) < 0.0:
            rot.negate()
        pb.rotation_quaternion = rot
        prev[pb.name] = rot
        return 'rotation_quaternion'
    if mode == 'AXIS_ANGLE':
        axis, angle = rot.to_axis_angle()
        pb.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
        return 'rotation_axis_angle'
    last = prev.get(pb.name)
    eul = rot.to_euler(mode, last) if last is not None else rot.to_euler(mode)
    pb.rotation_euler = eul
    prev[pb.name] = eul
    return 'rotation_euler'


def bake(obj, settings, model, samples, results, progress=None):
    rb = obj.better_ragdoll
    ad = obj.animation_data_create()
    src = ad.action
    if src is not None and src == rb.ragdoll_action:
        src = rb.original_action
    rb.original_action = src
    old = rb.ragdoll_action
    ad.action = None
    rb.ragdoll_action = None
    if old is not None and old != src and old.users == 0:
        bpy.data.actions.remove(old)

    if settings.mute_constraints:
        muted = []
        for pb in obj.pose.bones:
            for con in pb.constraints:
                if not con.mute:
                    con.mute = True
                    muted.append((pb.name, con.name))
        rb.muted_constraints = json.dumps(muted)

    rest_rel = _rest_relative(obj.data.bones)
    pose_bones = obj.pose.bones
    prev = {}
    frames = sorted(results)
    for idx, f in enumerate(frames):
        mats = pose_matrices(obj, model, results[f], samples[f])
        basis = basis_matrices(obj, mats, rest_rel)
        for name in model.bone_order:
            pb = pose_bones[name]
            rot_path = _set_channels(pb, basis[name], prev)
            pb.keyframe_insert("location", frame=f, group=name)
            pb.keyframe_insert(rot_path, frame=f, group=name)
            pb.keyframe_insert("scale", frame=f, group=name)
        if progress is not None:
            progress((idx + 1) / len(frames))

    act = ad.action
    if act is not None:
        act.name = obj.name + "_Ragdoll"
        rb.ragdoll_action = act
    return act


def preview_neutral(context, obj, settings):
    """Pose the armature in the neutral body posture (no keyframes)."""
    model = build_model(obj, settings)
    omw = obj.matrix_world.copy()
    anim = {pb.name: pb.matrix.copy() for pb in obj.pose.bones}

    def root_pose(body):
        loc, rot = unit_world(omw @ anim[body.primary])
        return model.body_pose_from_bone(body, loc, rot)

    poses = neutral_pose(model, root_pose)
    mats = pose_matrices(obj, model, poses, (omw, anim))
    basis = basis_matrices(obj, mats)
    for name in model.bone_order:
        obj.pose.bones[name].matrix_basis = basis[name]
    return model


def joint_report(model, solver):
    """Angles of every joint in degrees, for debugging."""
    out = []
    for j in model.joints:
        _qp, _qc, sx, sz, tau = solver.joint_angles(j)
        out.append((model.bodies[j.child].primary, math.degrees(sx), math.degrees(sz), math.degrees(tau)))
    return out
