# SPDX-License-Identifier: GPL-3.0-or-later
"""Small rigid body solver for ragdolls based on Extended Position Based Dynamics.

Reference: Mueller et al. 2020, "Detailed Rigid Body Simulation with Extended
Position Based Dynamics".

Besides classic hard joint limits, every joint supports:
  * Soft limits: inside a zone close to the minimum / maximum angles a spring
    with a progressive stiffness and a progressive damping slows the joint down
    before the hard limit is reached (muscles, ligaments and tendons stretching).
  * Neutral tension: a weak spring pulling every joint towards the neutral body
    posture (muscles at equilibrium).
"""

import math

from mathutils import Quaternion, Vector

from .model import Y_AXIS, closest_seg_seg, quat_to_rotvec, rotvec_to_quat

X_AXIS = Vector((1.0, 0.0, 0.0))
Z_AXIS = Vector((0.0, 0.0, 1.0))
MAX_SWING = math.radians(175.0)


class Params:
    def __init__(self):
        self.gravity = Vector((0.0, 0.0, -9.81))
        self.soft = True
        self.tension = 10.0
        self.tension_damping = 0.35
        self.soft_zone = 0.25
        self.soft_strength = 400.0
        self.soft_damping = 30.0
        self.joint_damping = 0.5
        self.friction = 0.7
        self.self_collision = True
        self.use_ground = True
        self.ground_height = 0.0
        self.drive_stiffness = 100.0
        self.linear_damping = 0.02
        self.angular_damping = 0.05
        self.max_linear_speed = 60.0
        self.max_angular_speed = 60.0


def _rotate(q, dr):
    """Integrate a small rotation vector into a quaternion."""
    dq = Quaternion((0.0, dr.x, dr.y, dr.z)) @ q
    out = Quaternion((q.w + 0.5 * dq.w, q.x + 0.5 * dq.x, q.y + 0.5 * dq.y, q.z + 0.5 * dq.z))
    out.normalize()
    return out


class Contact:
    __slots__ = ("body", "r_local", "normal", "lam")

    def __init__(self, body, r_local, normal, lam):
        self.body = body
        self.r_local = r_local
        self.normal = normal
        self.lam = lam


class Solver:
    def __init__(self, model, params):
        self.model = model
        self.p = params
        n = len(model.bodies)
        self.x = [b.com.copy() for b in model.bodies]
        self.q = [b.rest_rot.copy() for b in model.bodies]
        self.v = [Vector() for _ in range(n)]
        self.w = [Vector() for _ in range(n)]
        self.xp = [b.com.copy() for b in model.bodies]
        self.qp = [b.rest_rot.copy() for b in model.bodies]
        self.mass_inv = [b.inv_mass for b in model.bodies]
        self.inertia_inv = [b.inv_inertia for b in model.bodies]
        self.dynamic = [True] * n
        self.zone = [[0.0, 0.0, 0.0] for _ in model.joints]
        self.contacts = []
        self.bvh = None
        self.samples = []
        for b in model.bodies:
            seg = b.seg_b - b.seg_a
            ln = seg.length
            if ln < 1e-5:
                pts = [(b.seg_a + b.seg_b) * 0.5]
            else:
                count = max(2, min(5, int(ln / max(b.radius, 1e-4)) + 1))
                pts = [b.seg_a + seg * (k / (count - 1)) for k in range(count)]
            self.samples.append(pts)

    # ------------------------------------------------------------------ helpers
    def _im(self, i):
        return self.mass_inv[i] if (i >= 0 and self.dynamic[i]) else 0.0

    def _iinv(self, i, vec):
        """World inverse inertia of body i applied to vec."""
        if i < 0 or not self.dynamic[i]:
            return Vector()
        q = self.q[i]
        ii = self.inertia_inv[i]
        lv = q.conjugated() @ vec
        return q @ Vector((lv.x * ii.x, lv.y * ii.y, lv.z * ii.z))

    def _pos_correction(self, a, b, ra, rb, corr, compliance, h):
        """Move the point ra of body a by corr relative to point rb of body b (-1 = world)."""
        c = corr.length
        if c < 1e-9:
            return 0.0
        n = corr / c
        w = 0.0
        if a >= 0 and self.dynamic[a]:
            rn = ra.cross(n)
            w += self.mass_inv[a] + rn.dot(self._iinv(a, rn))
        if b >= 0 and self.dynamic[b]:
            rn = rb.cross(n)
            w += self.mass_inv[b] + rn.dot(self._iinv(b, rn))
        w += compliance / (h * h)
        if w <= 1e-12:
            return 0.0
        lam = c / w
        p = n * lam
        if a >= 0 and self.dynamic[a]:
            self.x[a] += p * self.mass_inv[a]
            self.q[a] = _rotate(self.q[a], self._iinv(a, ra.cross(p)))
        if b >= 0 and self.dynamic[b]:
            self.x[b] -= p * self.mass_inv[b]
            self.q[b] = _rotate(self.q[b], -self._iinv(b, rb.cross(p)))
        return lam

    def _ang_correction(self, a, b, dphi, compliance, h):
        """Rotate body a by the rotation vector dphi relative to body b."""
        ang = dphi.length
        if ang < 1e-9:
            return
        n = dphi / ang
        w = n.dot(self._iinv(a, n)) + n.dot(self._iinv(b, n)) + compliance / (h * h)
        if w <= 1e-12:
            return
        p = n * (ang / w)
        if a >= 0 and self.dynamic[a]:
            self.q[a] = _rotate(self.q[a], self._iinv(a, p))
        if b >= 0 and self.dynamic[b]:
            self.q[b] = _rotate(self.q[b], -self._iinv(b, p))

    def _ang_velocity_impulse(self, a, b, axis, dv):
        """Change the relative angular velocity of a vs b along axis by dv."""
        w = axis.dot(self._iinv(a, axis)) + axis.dot(self._iinv(b, axis))
        if w <= 1e-12:
            return
        p = axis * (dv / w)
        if a >= 0 and self.dynamic[a]:
            self.w[a] += self._iinv(a, p)
        if b >= 0 and self.dynamic[b]:
            self.w[b] -= self._iinv(b, p)

    def _vel_impulse(self, i, r, impulse):
        if not self.dynamic[i]:
            return
        self.v[i] += impulse * self.mass_inv[i]
        self.w[i] += self._iinv(i, r.cross(impulse))

    # ---------------------------------------------------------------- joints
    def joint_angles(self, j):
        qp = self.q[j.parent] @ j.frame_p
        qc = self.q[j.child] @ j.frame_c
        rel = qp.conjugated() @ qc
        if rel.w < 0.0:
            rel = Quaternion((-rel.w, -rel.x, -rel.y, -rel.z))
        tl = math.hypot(rel.w, rel.y)
        if tl < 1e-6:
            tw = Quaternion()
            tau = 0.0
        else:
            tw = Quaternion((rel.w / tl, 0.0, rel.y / tl, 0.0))
            tau = 2.0 * math.atan2(rel.y, rel.w)
            if tau > math.pi:
                tau -= 2.0 * math.pi
            elif tau < -math.pi:
                tau += 2.0 * math.pi
        sw = rel @ tw.conjugated()
        s = quat_to_rotvec(sw)
        return qp, qc, s.x, s.z, tau

    def _solve_joint_positions(self, h):
        x, q = self.x, self.q
        for j in self.model.joints:
            c, p = j.child, j.parent
            if not (self.dynamic[c] or self.dynamic[p]):
                continue
            ra = q[c] @ j.anchor_c
            rb = q[p] @ j.anchor_p
            corr = (x[p] + rb) - (x[c] + ra)
            self._pos_correction(c, p, ra, rb, corr, 0.0, h)

    def _solve_joint_angles(self, h):
        prm = self.p
        for ji, j in enumerate(self.model.joints):
            c, p = j.child, j.parent
            if not (self.dynamic[c] or self.dynamic[p]):
                continue
            zone = self.zone[ji]
            if prm.soft:
                # Neutral tension: spring on the geodesic distance to the neutral
                # posture, so it derives from a potential and never adds energy.
                if prm.tension > 0.0:
                    qp, qc, _sx, _sz, _tau = self.joint_angles(j)
                    self._rotate_joint_to(j, qp, qc, j.flex[2], j.abd[2], j.twist[2],
                                          1.0 / (prm.tension * j.i_eff), h)
                # Soft limits: inside the zone near a limit, pull back to the zone
                # border with a stiffness growing with the depth in the zone.
                qp, qc, sx, sz, tau = self.joint_angles(j)
                target = [sx, sz, tau]
                depth = 0.0
                for k, (lo, hi, _neu) in enumerate((j.flex, j.abd, j.twist)):
                    val = target[k]
                    width = (hi - lo) * prm.soft_zone
                    zone[k] = 0.0
                    if width <= 1e-6:
                        continue
                    if val > hi - width:
                        zone[k] = min(1.0, (val - (hi - width)) / width)
                        target[k] = hi - width
                    elif val < lo + width:
                        zone[k] = min(1.0, ((lo + width) - val) / width)
                        target[k] = lo + width
                    depth = max(depth, zone[k])
                if depth > 0.0 and prm.soft_strength > 0.0:
                    self._rotate_joint_to(j, qp, qc, target[0], target[1], target[2],
                                          1.0 / (prm.soft_strength * j.i_eff * depth), h)
            # Hard limits (exact correction).
            qp, qc, sx, sz, tau = self.joint_angles(j)
            nx = min(j.flex[1], max(j.flex[0], sx))
            nz = min(j.abd[1], max(j.abd[0], sz))
            nt = min(j.twist[1], max(j.twist[0], tau))
            mag = math.hypot(nx, nz)
            if mag > MAX_SWING:
                nx *= MAX_SWING / mag
                nz *= MAX_SWING / mag
            if abs(nx - sx) + abs(nz - sz) + abs(nt - tau) < 1e-6:
                continue
            self._rotate_joint_to(j, qp, qc, nx, nz, nt, 0.0, h)

    def _rotate_joint_to(self, j, qp, qc, flex, abd, twist, compliance, h):
        """Rotate the child of joint j towards the given joint angles."""
        target = qp @ (rotvec_to_quat(Vector((flex, 0.0, abd))) @ Quaternion(Y_AXIS, twist))
        dq = target @ qc.conjugated()
        self._ang_correction(j.child, j.parent, quat_to_rotvec(dq), compliance, h)

    def _joint_damping(self, h):
        prm = self.p
        base = prm.joint_damping
        tension_rate = 2.0 * prm.tension_damping * math.sqrt(max(prm.tension, 0.0)) if prm.soft else 0.0
        for ji, j in enumerate(self.model.joints):
            c, p = j.child, j.parent
            if not (self.dynamic[c] or self.dynamic[p]):
                continue
            qp = self.q[p] @ j.frame_p
            qc = self.q[c] @ j.frame_c
            axes = (qp @ X_AXIS, qp @ Z_AXIS, qc @ Y_AXIS)
            zone = self.zone[ji]
            for k in range(3):
                rate = base + tension_rate
                if prm.soft:
                    rate += prm.soft_damping * zone[k]
                if rate <= 0.0:
                    continue
                # Implicit damper scaled by the inertia carried by the joint, like
                # the springs, so light links holding heavy parts are damped too.
                axis = axes[k]
                w = axis.dot(self._iinv(c, axis)) + axis.dot(self._iinv(p, axis))
                if w <= 1e-12:
                    continue
                rel = (self.w[c] - self.w[p]).dot(axis)
                chw = rate * j.i_eff * h * w
                self._ang_velocity_impulse(c, p, axis, -rel * chw / (1.0 + chw))

    # ------------------------------------------------------------ collisions
    def _solve_collisions(self, h):
        prm = self.p
        contacts = self.contacts
        bvh = self.bvh
        for i, body in enumerate(self.model.bodies):
            if not self.dynamic[i]:
                continue
            r = body.radius
            for s_local in self.samples[i]:
                s = self.x[i] + self.q[i] @ s_local
                if prm.use_ground:
                    depth = prm.ground_height + r - s.z
                    if depth > 0.0:
                        n = Z_AXIS
                        ra = (s - n * r) - self.x[i]
                        lam = self._pos_correction(i, -1, ra, None, n * depth, 0.0, h)
                        contacts.append(Contact(i, self.q[i].conjugated() @ ra, n, lam))
                        s = self.x[i] + self.q[i] @ s_local
                if bvh is not None:
                    loc, nrm, _idx, dist = bvh.find_nearest(s, r * 2.0)
                    if loc is None:
                        continue
                    diff = s - loc
                    if nrm.length < 1e-9:
                        continue
                    nrm = nrm.normalized()
                    if diff.dot(nrm) < 0.0:
                        n = nrm
                        depth = r + dist
                    else:
                        if dist >= r:
                            continue
                        n = diff / dist if dist > 1e-9 else nrm
                        depth = r - dist
                    ra = (s - n * r) - self.x[i]
                    lam = self._pos_correction(i, -1, ra, None, n * depth, 0.0, h)
                    contacts.append(Contact(i, self.q[i].conjugated() @ ra, n.copy(), lam))

    def _solve_self_collisions(self, h):
        bodies = self.model.bodies
        x, q = self.x, self.q
        for i, k in self.model.collision_pairs:
            if not (self.dynamic[i] or self.dynamic[k]):
                continue
            bi, bk = bodies[i], bodies[k]
            reach = bi.length * 0.5 + bk.length * 0.5 + bi.radius + bk.radius
            if (x[i] - x[k]).length_squared > reach * reach:
                continue
            pi0 = x[i] + q[i] @ bi.seg_a
            pi1 = x[i] + q[i] @ bi.seg_b
            pk0 = x[k] + q[k] @ bk.seg_a
            pk1 = x[k] + q[k] @ bk.seg_b
            c1, c2 = closest_seg_seg(pi0, pi1, pk0, pk1)
            d = c1 - c2
            dist = d.length
            rsum = bi.radius + bk.radius
            if dist >= rsum:
                continue
            n = d / dist if dist > 1e-9 else Z_AXIS
            ra = (c1 - n * bi.radius) - x[i]
            rb = (c2 + n * bk.radius) - x[k]
            self._pos_correction(i, k, ra, rb, n * (rsum - dist), 0.0, h)

    def _contact_velocities(self, h):
        mu = self.p.friction
        for ct in self.contacts:
            i = ct.body
            if not self.dynamic[i] or ct.lam <= 0.0:
                continue
            n = ct.normal
            r = self.q[i] @ ct.r_local
            vel = self.v[i] + self.w[i].cross(r)
            vn = vel.dot(n)
            if vn < 0.0:
                rn = r.cross(n)
                wn = self.mass_inv[i] + rn.dot(self._iinv(i, rn))
                self._vel_impulse(i, r, n * (-vn / wn))
                vel = self.v[i] + self.w[i].cross(r)
                vn = vel.dot(n)
            vt = vel - n * vn
            speed = vt.length
            if speed < 1e-9:
                continue
            t = vt / speed
            rt = r.cross(t)
            wt = self.mass_inv[i] + rt.dot(self._iinv(i, rt))
            imp = min(speed / wt, mu * ct.lam / h)
            self._vel_impulse(i, r, t * (-imp))

    # ------------------------------------------------------------------ drives
    def _solve_drives(self, h, weights, targets):
        omega = self.p.drive_stiffness
        for i, s in enumerate(weights):
            if s <= 0.0 or not self.dynamic[i] or targets[i] is None:
                continue
            tx, tq = targets[i]
            body = self.model.bodies[i]
            k_lin = body.mass * (s * omega) ** 2
            self._pos_correction(i, -1, Vector(), None, tx - self.x[i], 1.0 / k_lin, h)
            inertia = (body.inertia.x + body.inertia.y + body.inertia.z) / 3.0
            k_ang = inertia * (s * omega) ** 2
            dq = tq @ self.q[i].conjugated()
            self._ang_correction(i, -1, quat_to_rotvec(dq), 1.0 / k_ang, h)

    # ------------------------------------------------------------------- step
    def substep(self, h, weights, targets):
        """Advance by h seconds.

        weights[i]: 1 = body follows targets[i] kinematically, 0 = fully simulated,
        in between = simulated but driven towards targets[i].
        """
        prm = self.p
        x, q, v, w = self.x, self.q, self.v, self.w
        n = len(x)
        lin_keep = max(0.0, 1.0 - prm.linear_damping * h)
        ang_keep = max(0.0, 1.0 - prm.angular_damping * h)
        for i in range(n):
            self.xp[i] = x[i].copy()
            self.qp[i] = q[i].copy()
            if weights[i] >= 1.0 and targets[i] is not None:
                self.dynamic[i] = False
                x[i] = targets[i][0].copy()
                q[i] = targets[i][1].copy()
                continue
            self.dynamic[i] = True
            v[i] = (v[i] + prm.gravity * h) * lin_keep
            # Gyroscopic term, keeps the angular momentum of elongated bodies.
            qi = q[i]
            inertia = self.model.bodies[i].inertia
            ii = self.inertia_inv[i]
            wl = qi.conjugated() @ w[i]
            lw = Vector((wl.x * inertia.x, wl.y * inertia.y, wl.z * inertia.z))
            tau = lw.cross(wl)
            wl += Vector((tau.x * ii.x, tau.y * ii.y, tau.z * ii.z)) * h
            w[i] = (qi @ wl) * ang_keep
            sp = v[i].length
            if sp > prm.max_linear_speed:
                v[i] *= prm.max_linear_speed / sp
            sp = w[i].length
            if sp > prm.max_angular_speed:
                w[i] *= prm.max_angular_speed / sp
            x[i] = x[i] + v[i] * h
            q[i] = _rotate(q[i], w[i] * h)

        self.contacts = []
        self._solve_joint_positions(h)
        self._solve_joint_angles(h)
        self._solve_drives(h, weights, targets)
        if prm.self_collision:
            self._solve_self_collisions(h)
        self._solve_collisions(h)
        self._solve_joint_positions(h)

        inv_h = 1.0 / h
        for i in range(n):
            v[i] = (x[i] - self.xp[i]) * inv_h
            dq = q[i] @ self.qp[i].conjugated()
            wv = Vector((dq.x, dq.y, dq.z)) * (2.0 * inv_h)
            w[i] = -wv if dq.w < 0.0 else wv

        self._joint_damping(h)
        self._contact_velocities(h)

    # ---------------------------------------------------------------- impulses
    def apply_impact(self, direction, speed, focus, hit_body, kick, kick_random, rng):
        """Push the body like a hit / explosion.

        Besides the linear push, the shoulders and hips get a rotational impulse:
        arms are thrown along the push while legs swing the opposite way (the feet
        resist the impact), with some randomness so limbs do not move identically.
        """
        if direction.length < 1e-9:
            return
        d = direction.normalized()
        model = self.model
        total = sum(b.mass for b in model.bodies)
        for i, body in enumerate(model.bodies):
            if not self.dynamic[i]:
                continue
            self.v[i] += d * (speed * (1.0 - focus))
        if 0 <= hit_body < len(model.bodies) and self.dynamic[hit_body]:
            self.v[hit_body] += d * (speed * focus * total / model.bodies[hit_body].mass)

        if kick <= 0.0:
            return
        for i, body in enumerate(model.bodies):
            if body.kick is None or not self.dynamic[i] or body.joint is None:
                continue
            j = model.joints[body.joint]
            limb = (self.q[i] @ (body.seg_b - body.seg_a))
            if limb.length < 1e-6:
                limb = self.q[i] @ Y_AXIS
            limb.normalize()
            axis = limb.cross(d) if body.kick == 'ARM' else d.cross(limb)
            if axis.length < 1e-3:
                axis = limb.orthogonal()
            axis.normalize()
            jitter = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
            axis = (axis + jitter * (0.6 * kick_random)).normalized()
            mag = kick * max(0.1, 1.0 + kick_random * rng.uniform(-0.6, 0.6))
            omega = axis * mag
            anchor = self.x[i] + self.q[i] @ j.anchor_c
            self.w[i] += omega
            self.v[i] += omega.cross(self.x[i] - anchor)

    def set_body(self, i, x, q, v=None, w=None):
        self.x[i] = x.copy()
        self.q[i] = q.copy()
        self.xp[i] = x.copy()
        self.qp[i] = q.copy()
        if v is not None:
            self.v[i] = v.copy()
        if w is not None:
            self.w[i] = w.copy()

    def poses(self):
        return [(self.x[i].copy(), self.q[i].copy()) for i in range(len(self.x))]
