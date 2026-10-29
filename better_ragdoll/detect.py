# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic detection of humanoid bone roles from bone names and hierarchy."""

import math
import re

from . import presets

_PREFIX_RE = re.compile(
    r"^(mixamorig\d*[:_]|def[-_.]|org[-_.]|bip0?1[ _]|bip[ _]|cc_base_|j_|jnt_|bn_|b_|c_)"
)
_SIDE_PATTERNS = (
    (re.compile(r"(^|[^a-z])left|left($|[^a-z])|^left"), 'LEFT'),
    (re.compile(r"(^|[^a-z])right|right($|[^a-z])|^right"), 'RIGHT'),
    (re.compile(r"([._\- ]l|[._\- ]l\.\d+)$|^l[._\- ]|[._\-]l[._\-]"), 'LEFT'),
    (re.compile(r"([._\- ]r|[._\- ]r\.\d+)$|^r[._\- ]|[._\-]r[._\-]"), 'RIGHT'),
)
# Matched anywhere in the name.
_EXCLUDE_SUBSTRINGS = (
    "thumb", "index", "middle", "ring", "pinky", "finger", "little", "palm", "metacarpal",
    "eye", "jaw", "tongue", "teeth", "tooth", "brow", "breast", "tail", "hair",
    "weapon", "pole", "target", "ctrl", "control", "tweak", "mch", "properties",
    "heel", "master", "socket", "attach", "cheek", "nose", "chin", "skirt", "cloth",
)
# Short words only matched as whole words ("ear" must not exclude "forearm").
_EXCLUDE_TOKENS = ("ik", "fk", "end", "tip", "nub", "vis", "root", "ear", "lip", "prop")

# (role, keywords) in matching order.
_ROLE_KEYWORDS = (
    ('TOE', ("toe", "ball")),
    ('FOOT', ("foot", "ankle")),
    ('HAND', ("hand", "wrist")),
    ('FOREARM', ("forearm", "lowerarm", "lower_arm", "lowarm", "elbow")),
    ('CLAVICLE', ("clavicle", "collar", "shoulder", "scapula")),
    ('UPPER_ARM', ("upperarm", "upper_arm", "uparm", "arm")),
    ('THIGH', ("thigh", "upleg", "upperleg", "upper_leg", "up_leg", "femur")),
    ('SHIN', ("shin", "calf", "lowerleg", "lower_leg", "knee", "crus", "leg")),
    ('HEAD', ("head",)),
    ('NECK', ("neck",)),
    ('PELVIS', ("pelvis", "hips", "hip")),
    ('SPINE', ("spine", "chest", "torso", "abdomen", "waist", "belly", "ribcage")),
)


def _strip(name):
    n = name.lower()
    for _ in range(2):
        n = _PREFIX_RE.sub("", n)
    return n


def name_side(name):
    n = _strip(name)
    for pattern, side in _SIDE_PATTERNS:
        if pattern.search(n):
            return side
    return None


def _excluded(n):
    tokens = set(re.split(r"[^a-z]+", n))
    if any(word in tokens for word in _EXCLUDE_TOKENS):
        return True
    return any(word in n for word in _EXCLUDE_SUBSTRINGS)


def name_role(name):
    n = _strip(name)
    if _excluded(n):
        return 'NONE'
    for role, words in _ROLE_KEYWORDS:
        for w in words:
            if w in n:
                if role == 'UPPER_ARM' and ("forearm" in n or "lowerarm" in n):
                    continue
                return role
    return 'NONE'


def _ancestors(bone):
    p = bone.parent
    while p is not None:
        yield p
        p = p.parent


def detect_roles(obj):
    """Return {bone_name: role} for the armature object."""
    arm = obj.data
    mw = obj.matrix_world
    up_heads = {b.name: mw @ b.head_local for b in arm.bones}

    # Lateral axis: assume the character is roughly symmetric around the
    # median X (in world space) of all bones.
    xs = sorted(h.x for h in up_heads.values())
    mid_x = xs[len(xs) // 2] if xs else 0.0
    zs = [h.z for h in up_heads.values()]
    height = (max(zs) - min(zs)) if zs else 1.0
    threshold = max(height * 0.015, 1e-4)

    def side_of(bone):
        s = name_side(bone.name)
        if s is not None:
            return s
        dx = up_heads[bone.name].x - mid_x
        if abs(dx) < threshold:
            return 'CENTER'
        # Characters in Blender face -Y, so their left side is +X.
        return 'LEFT' if dx > 0 else 'RIGHT'

    def classify(bones):
        out = {}
        for b in bones:
            role = name_role(b.name)
            if role == 'NONE':
                continue
            side = side_of(b)
            if role in presets.CENTER_ROLES and side != 'CENTER':
                continue
            if role in presets.SIDE_ROLES and side == 'CENTER':
                continue
            out[b.name] = role
        return out

    roles = classify(arm.bones)
    deform = [b for b in arm.bones if b.use_deform]
    roles_deform = classify(deform)
    if len(roles_deform) >= 6:
        roles = roles_deform

    bones = arm.bones

    # Keep a single pelvis, the top-most one; otherwise promote the top-most spine.
    pelvises = [n for n, r in roles.items() if r == 'PELVIS']
    if pelvises:
        pelvises.sort(key=lambda n: sum(1 for _ in _ancestors(bones[n])))
        for n in pelvises[1:]:
            roles[n] = 'SPINE'
    else:
        spines = [n for n, r in roles.items() if r == 'SPINE']
        if spines:
            spines.sort(key=lambda n: sum(1 for _ in _ancestors(bones[n])))
            roles[spines[0]] = 'PELVIS'

    # Drop bones whose mapped ancestry does not lead to the pelvis.
    pelvis = next((n for n, r in roles.items() if r == 'PELVIS'), None)
    if pelvis is not None:
        for n in list(roles):
            if n == pelvis:
                continue
            if not any(a.name == pelvis for a in _ancestors(bones[n])):
                del roles[n]

    # Central chain: rigs like Rigify name neck and head bones "spine.00x".
    if pelvis is not None:
        chain = [pelvis]
        cur = bones[pelvis]
        while True:
            nxt = None
            for c in cur.children_recursive:
                if roles.get(c.name) in ('SPINE', 'NECK', 'HEAD'):
                    mapped_parent = next((a for a in _ancestors(c) if a.name in roles), None)
                    if mapped_parent is not None and mapped_parent.name == cur.name:
                        nxt = c
                        break
            if nxt is None:
                break
            chain.append(nxt.name)
            cur = nxt
        chain_roles = [roles[n] for n in chain]
        if len(chain) >= 3 and 'HEAD' not in chain_roles:
            roles[chain[-1]] = 'HEAD'
            chain_roles[-1] = 'HEAD'
        if len(chain) >= 4 and 'NECK' not in chain_roles:
            # The neck starts above the bone the arms are attached to.
            attach = None
            for n, r in roles.items():
                if r in ('CLAVICLE', 'UPPER_ARM'):
                    for a in _ancestors(bones[n]):
                        if a.name in chain:
                            idx = chain.index(a.name)
                            attach = idx if attach is None else max(attach, idx)
                            break
            if attach is not None:
                for i in range(attach + 1, len(chain) - 1):
                    roles[chain[i]] = 'NECK'

    return roles


def mirrored(limits, side):
    """Mirror (min, max, neutral) of abduction/twist for the right side."""
    if side != 'RIGHT':
        return limits
    lo, hi, neu = limits
    return (-hi, -lo, -neu)


def degrees_to_radians(triple):
    return tuple(math.radians(v) for v in triple)
