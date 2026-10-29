# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the ragdoll description (rigid bodies + anatomical joints) from an armature."""

import math

from mathutils import Matrix, Quaternion, Vector

from . import presets
from .detect import mirrored

UP = Vector((0.0, 0.0, 1.0))
Y_AXIS = Vector((0.0, 1.0, 0.0))


class RagdollError(Exception):
    pass


class Body:
    def __init__(self, index, primary, role):
        self.index = index
        self.primary = primary
        self.role = role
        self.bones = [primary]
        self.parent = -1
        self.side = 'CENTER'
        self.head = None          # world rest position of the segment start
        self.end = None           # world rest position of the segment end
        self.rest_rot = None      # world rest orientation (primary bone)
        self.com = None           # world rest center of mass
        self.radius = 0.05
        self.length = 0.1
        self.seg_a = Vector()     # local capsule segment
        self.seg_b = Vector()
        self.mass = 1.0
        self.inertia = Vector((1.0, 1.0, 1.0))
        self.offsets = {}         # bone name -> body local matrix of the bone (unit scale)
        self.primary_offset_inv = Matrix()
        self.lower_body = False
        self.kick = None          # 'ARM' or 'LEG'
        self.joint = None

    @property
    def inv_mass(self):
        return 1.0 / self.mass

    @property
    def inv_inertia(self):
        i = self.inertia
        return Vector((1.0 / i.x, 1.0 / i.y, 1.0 / i.z))


class Joint:
    def __init__(self, child, parent):
        self.child = child
        self.parent = parent
        self.anchor_c = Vector()
        self.anchor_p = Vector()
        self.frame_c = Quaternion()
        self.frame_p = Quaternion()
        # (min, max, neutral) in radians, already mirrored for the body side.
        self.flex = (0.0, 0.0, 0.0)
        self.abd = (0.0, 0.0, 0.0)
        self.twist = (0.0, 0.0, 0.0)
        self.i_eff = 1.0


class Model:
    def __init__(self):
        self.bodies = []
        self.joints = []
        self.bone_body = {}       # bone name -> body index
        self.bone_order = []      # all bones, parents first
        self.forward = Vector((0.0, -1.0, 0.0))
        self.left = Vector((1.0, 0.0, 0.0))
        self.height = 1.8
        self.total_mass = 70.0
        self.collision_pairs = []

    def body_pose_from_bone(self, body, loc, rot):
        """World (x, q) of a body from the unit-scale world transform of its primary bone."""
        m = Matrix.LocRotScale(loc, rot, None) @ body.primary_offset_inv
        return m.to_translation(), m.to_quaternion()


def bone_order(arm):
    order = []

    def visit(b):
        order.append(b.name)
        for c in b.children:
            visit(c)

    for b in arm.bones:
        if b.parent is None:
            visit(b)
    return order


def unit_world(mat):
    return mat.to_translation(), mat.to_3x3().normalized().to_quaternion()


def _skinned_meshes(obj):
    out = []
    for ob in obj.children_recursive if hasattr(obj, "children_recursive") else obj.children:
        if ob.type != 'MESH':
            continue
        for mod in ob.modifiers:
            if mod.type == 'ARMATURE' and mod.object == obj:
                out.append(ob)
                break
    return out


def _vertex_points(obj, bone_names):
    """bone name -> list of world positions of vertices strongly weighted to it."""
    points = {}
    for me_ob in _skinned_meshes(obj):
        mesh = me_ob.data
        names = {vg.index: vg.name for vg in me_ob.vertex_groups if vg.name in bone_names}
        if not names:
            continue
        mw = me_ob.matrix_world
        verts = mesh.vertices
        stride = max(1, len(verts) // 40000)
        for i in range(0, len(verts), stride):
            v = verts[i]
            for g in v.groups:
                if g.weight >= 0.5:
                    n = names.get(g.group)
                    if n is not None:
                        points.setdefault(n, []).append(mw @ v.co)
    return points


def _dist_point_segment(p, a, b):
    ab = b - a
    denom = ab.dot(ab)
    t = 0.0 if denom < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def _closest_seg_seg(p1, q1, p2, q2):
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = d1.dot(d1)
    e = d2.dot(d2)
    f = d2.dot(r)
    eps = 1e-12
    if a <= eps and e <= eps:
        return p1, p2
    if a <= eps:
        s = 0.0
        t = min(1.0, max(0.0, f / e))
    else:
        c = d1.dot(r)
        if e <= eps:
            t = 0.0
            s = min(1.0, max(0.0, -c / a))
        else:
            b = d1.dot(d2)
            denom = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom > eps else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = min(1.0, max(0.0, (b - c) / a))
    return p1 + d1 * s, p2 + d2 * t


closest_seg_seg = _closest_seg_seg


def _limits(rb, name, side):
    tri = (getattr(rb, name + "_min"), getattr(rb, name + "_max"), getattr(rb, name + "_neutral"))
    lo, hi, neu = tri
    if lo > hi:
        lo, hi = hi, lo
    neu = min(hi, max(lo, neu))
    if name != 'flex':
        return mirrored((lo, hi, neu), side)
    return (lo, hi, neu)


def _forward_axis(obj, settings, bodies):
    mode = settings.forward_axis
    fixed = {
        'NEG_Y': Vector((0.0, -1.0, 0.0)),
        'POS_Y': Vector((0.0, 1.0, 0.0)),
        'NEG_X': Vector((-1.0, 0.0, 0.0)),
        'POS_X': Vector((1.0, 0.0, 0.0)),
    }
    if mode in fixed:
        return fixed[mode]
    acc = Vector()
    for b in bodies:
        if b.role == 'FOOT':
            d = b.rest_rot @ Y_AXIS
            d.z = 0.0
            acc += d
    if acc.length > 1e-3:
        return acc.normalized()
    d = obj.matrix_world.to_3x3() @ Vector((0.0, -1.0, 0.0))
    d.z = 0.0
    if d.length > 1e-3:
        return d.normalized()
    return Vector((0.0, -1.0, 0.0))


def build_model(obj, settings):
    if obj is None or obj.type != 'ARMATURE':
        raise RagdollError("Active object is not an armature")
    arm = obj.data
    mw = obj.matrix_world
    roles = {}
    for pb in obj.pose.bones:
        r = pb.better_ragdoll.role
        if r != 'NONE':
            roles[pb.name] = r
    if not roles:
        raise RagdollError("No ragdoll bones assigned, run 'Detect Bones' first")

    model = Model()
    model.bone_order = bone_order(arm)

    rest = {}
    for b in arm.bones:
        loc, rot = unit_world(mw @ b.matrix_local)
        rest[b.name] = (mw @ b.head_local, mw @ b.tail_local, rot)
    zs = [h.z for h, _t, _r in rest.values()] + [t.z for _h, t, _r in rest.values()]
    model.height = max(0.1, max(zs) - min(zs))

    has_pelvis = 'PELVIS' in roles.values()
    bodies = model.bodies
    body_of = model.bone_body

    for name in model.bone_order:
        role = roles.get(name)
        if role is None:
            continue
        bone = arm.bones[name]
        anc = bone.parent
        while anc is not None and anc.name not in body_of:
            anc = anc.parent
        pidx = body_of[anc.name] if anc is not None else -1

        if role == 'TOE':
            if pidx >= 0 and bodies[pidx].role == 'FOOT':
                bodies[pidx].bones.append(name)
                bodies[pidx].end = rest[name][1].copy()
                body_of[name] = pidx
            continue

        if pidx < 0 and bodies:
            # Only one root: bones that are not below the root are ignored.
            continue
        if pidx < 0 and has_pelvis and role != 'PELVIS':
            continue

        if (pidx >= 0 and role in presets.MERGE_ROLES and bodies[pidx].role == role
                and bodies[pidx].bones[-1] == anc.name):
            body = bodies[pidx]
            body.bones.append(name)
            body.end = rest[name][1].copy()
            body_of[name] = pidx
            continue

        body = Body(len(bodies), name, role)
        body.parent = pidx
        body.head = rest[name][0].copy()
        body.end = rest[name][1].copy()
        body.rest_rot = rest[name][2].copy()
        bodies.append(body)
        body_of[name] = body.index

    if not bodies:
        raise RagdollError("Could not build any rigid body from the assigned bones")

    model.forward = _forward_axis(obj, settings, bodies)
    model.left = UP.cross(model.forward).normalized()
    root_head = bodies[0].head

    # Geometry -------------------------------------------------------------
    points = _vertex_points(obj, set(body_of.keys()))
    for body in bodies:
        lat = (body.head - root_head).dot(model.left)
        if body.role in presets.SIDE_ROLES:
            body.side = 'LEFT' if lat >= 0.0 else 'RIGHT'
        else:
            body.side = 'CENTER'
        body.lower_body = body.role in presets.LOWER_BODY_ROLES
        if body.role == 'UPPER_ARM':
            body.kick = 'ARM'
        elif body.role == 'THIGH':
            body.kick = 'LEG'

        seg = body.end - body.head
        body.length = max(seg.length, 1e-4)
        rb = obj.pose.bones[body.primary].better_ragdoll
        lo_r, hi_r = presets.RADIUS_HEIGHT_RANGE.get(body.role, (0.01, 0.1))
        lo_r *= model.height
        hi_r *= model.height
        if rb.radius > 0.0:
            radius = rb.radius
        else:
            pts = []
            for bn in body.bones:
                pts.extend(points.get(bn, ()))
            if len(pts) >= 8:
                ds = sorted(_dist_point_segment(p, body.head, body.end) for p in pts)
                radius = ds[int(len(ds) * 0.5)]
                radius = min(hi_r * 1.3, max(lo_r * 0.7, radius))
            else:
                radius = presets.RADIUS_RATIO.get(body.role, 0.2) * body.length
                radius = min(hi_r, max(lo_r, radius))
        body.radius = radius

        body.com = (body.head + body.end) * 0.5
        qinv = body.rest_rot.conjugated()
        a = qinv @ (body.head - body.com)
        b = qinv @ (body.end - body.com)
        half = body.length * 0.5
        if half > radius:
            u = (b - a).normalized()
            body.seg_a = a + u * radius
            body.seg_b = b - u * radius
        else:
            body.seg_a = Vector()
            body.seg_b = Vector()

        brest = Matrix.LocRotScale(body.com, body.rest_rot, None)
        brest_inv = brest.inverted()
        for bn in body.bones:
            h, _t, r = rest[bn]
            body.offsets[bn] = brest_inv @ Matrix.LocRotScale(h, r, None)
        body.primary_offset_inv = body.offsets[body.primary].inverted()

    # Masses -----------------------------------------------------------------
    model.total_mass = settings.total_mass
    counts = {}
    for body in bodies:
        counts[body.role] = counts.get(body.role, 0) + 1
    fracs = []
    for body in bodies:
        f = presets.MASS_FRACTION.get(body.role, 0.01)
        if body.role in presets.SHARED_MASS_ROLES:
            f /= counts[body.role]
        fracs.append(f)
    total = sum(fracs)
    for body, f in zip(bodies, fracs):
        m = max(0.05, settings.total_mass * f / total)
        body.mass = m
        r = body.radius
        ln = max(body.length, 2.0 * r)
        ip = m * (3.0 * r * r + ln * ln) / 12.0
        ia = 0.5 * m * r * r
        body.inertia = Vector((ip, ia, ip))

    # Joints -------------------------------------------------------------------
    fwd = model.forward
    children = {i: [] for i in range(len(bodies))}
    for body in bodies:
        if body.parent >= 0:
            children[body.parent].append(body.index)

    def subtree(i):
        out = [i]
        for c in children[i]:
            out.extend(subtree(c))
        return out

    for body in bodies:
        if body.parent < 0:
            continue
        parent = bodies[body.parent]
        j = Joint(body.index, parent.index)
        anchor = body.head
        j.anchor_c = body.rest_rot.conjugated() @ (anchor - body.com)
        j.anchor_p = parent.rest_rot.conjugated() @ (anchor - parent.com)

        d_rest = (body.rest_rot @ Y_AXIS).normalized()
        zero_mode = presets.ZERO_DIRECTION.get(body.role, 'REST')
        if zero_mode == 'DOWN':
            z0 = -UP
        elif zero_mode == 'PARENT':
            z0 = (parent.rest_rot @ Y_AXIS).normalized()
        else:
            z0 = d_rest.copy()

        flex_dir = presets.FLEX_DIRECTION.get(body.role, 'FORWARD')
        target = {'FORWARD': fwd, 'BACKWARD': -fwd, 'UP': UP}[flex_dir]
        x_axis = z0.cross(target)
        if x_axis.length < 0.25:
            alt = UP if flex_dir != 'UP' else fwd
            if flex_dir == 'BACKWARD':
                alt = -alt
            x_axis = z0.cross(alt)
        y_axis = z0.normalized()
        x_axis = (x_axis - y_axis * x_axis.dot(y_axis)).normalized()
        z_axis = x_axis.cross(y_axis)
        pw = Matrix((x_axis, y_axis, z_axis)).transposed().to_quaternion()
        swing_rest = y_axis.rotation_difference(d_rest)
        cw = swing_rest @ pw
        j.frame_p = parent.rest_rot.conjugated() @ pw
        j.frame_c = body.rest_rot.conjugated() @ cw

        rb = obj.pose.bones[body.primary].better_ragdoll
        j.flex = _limits(rb, "flex", body.side)
        j.abd = _limits(rb, "abd", body.side)
        j.twist = _limits(rb, "twist", body.side)

        ieff = 0.0
        for k in subtree(body.index):
            bk = bodies[k]
            ieff += bk.mass * (bk.com - anchor).length_squared
            ieff += (bk.inertia.x + bk.inertia.y + bk.inertia.z) / 3.0
        j.i_eff = max(ieff, 1e-6)
        body.joint = len(model.joints)
        model.joints.append(j)

    # Self collision pairs: skip direct relatives and bodies touching at rest.
    for i in range(len(bodies)):
        for k in range(i + 1, len(bodies)):
            bi, bk = bodies[i], bodies[k]
            if bi.parent == k or bk.parent == i:
                continue
            pi0 = bi.com + bi.rest_rot @ bi.seg_a
            pi1 = bi.com + bi.rest_rot @ bi.seg_b
            pk0 = bk.com + bk.rest_rot @ bk.seg_a
            pk1 = bk.com + bk.rest_rot @ bk.seg_b
            c1, c2 = _closest_seg_seg(pi0, pi1, pk0, pk1)
            if (c1 - c2).length < (bi.radius + bk.radius) * 1.1:
                continue
            model.collision_pairs.append((i, k))

    return model


def neutral_pose(model, root_pose):
    """World (x, q) of every body with all joints at their neutral angles."""
    poses = [None] * len(model.bodies)
    for body in model.bodies:
        if body.parent < 0:
            poses[body.index] = root_pose(body)
            continue
        j = model.joints[body.joint]
        xp, qp = poses[body.parent]
        pw = qp @ j.frame_p
        qr = rotvec_to_quat(Vector((j.flex[2], 0.0, j.abd[2]))) @ Quaternion(Y_AXIS, j.twist[2])
        cw = pw @ qr
        qc = cw @ j.frame_c.conjugated()
        qc.normalize()
        anchor = xp + qp @ j.anchor_p
        xc = anchor - qc @ j.anchor_c
        poses[body.index] = (xc, qc)
    return poses


def rotvec_to_quat(v):
    angle = v.length
    if angle < 1e-9:
        q = Quaternion((1.0, v.x * 0.5, v.y * 0.5, v.z * 0.5))
        q.normalize()
        return q
    return Quaternion(v / angle, angle)


def quat_to_rotvec(q):
    w, x, y, z = q.w, q.x, q.y, q.z
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    s = math.sqrt(x * x + y * y + z * z)
    if s < 1e-9:
        return Vector((2.0 * x, 2.0 * y, 2.0 * z))
    angle = 2.0 * math.atan2(s, w)
    f = angle / s
    return Vector((x * f, y * f, z * f))
