# SPDX-License-Identifier: GPL-3.0-or-later

import math

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import presets


def _angle(name, description):
    return FloatProperty(
        name=name, description=description, subtype='ANGLE', unit='ROTATION',
        min=-math.pi, max=math.pi, default=0.0)


class BRAGDOLL_PG_bone(bpy.types.PropertyGroup):
    role: EnumProperty(
        name="Role", items=presets.ROLE_ITEMS, default='NONE',
        description="Body part this bone represents in the ragdoll")
    radius: FloatProperty(
        name="Radius", subtype='DISTANCE', unit='LENGTH', min=0.0, default=0.0,
        description="Collision radius, 0 to measure it from the skinned mesh automatically")

    flex_min: _angle("Flexion Min", "Maximum extension (negative flexion)")
    flex_max: _angle("Flexion Max", "Maximum flexion")
    flex_neutral: _angle("Flexion Neutral", "Flexion of the relaxed neutral body posture")
    abd_min: _angle("Abduction Min", "Maximum adduction (towards the body midline)")
    abd_max: _angle("Abduction Max", "Maximum abduction (away from the body midline)")
    abd_neutral: _angle("Abduction Neutral", "Abduction of the relaxed neutral body posture")
    twist_min: _angle("Twist Min", "Minimum rotation around the bone")
    twist_max: _angle("Twist Max", "Maximum rotation around the bone")
    twist_neutral: _angle("Twist Neutral", "Twist of the relaxed neutral body posture")

    def load_preset(self):
        lim = presets.LIMITS.get(self.role)
        if lim is None:
            for axis in ("flex", "abd", "twist"):
                for suffix in ("_min", "_max", "_neutral"):
                    setattr(self, axis + suffix, 0.0)
            return
        for axis in ("flex", "abd", "twist"):
            lo, hi, neu = lim[axis]
            setattr(self, axis + "_min", math.radians(lo))
            setattr(self, axis + "_max", math.radians(hi))
            setattr(self, axis + "_neutral", math.radians(neu))


class BRAGDOLL_PG_settings(bpy.types.PropertyGroup):
    # Joints ---------------------------------------------------------------
    limit_mode: EnumProperty(
        name="Joint Model",
        items=(
            ('SOFT', "Soft Limits + Tension",
             "Joints slow down approaching their limits and relax towards the neutral body posture"),
            ('HARD', "Hard Limits (Classic)",
             "Typical game ragdoll: joints move freely and stop abruptly at their limits"),
        ),
        default='SOFT')
    use_tension: BoolProperty(
        name="Neutral Tension", default=True,
        description="Pull every joint gently towards the neutral body posture")
    tension: FloatProperty(
        name="Tension Strength", min=0.0, soft_max=200.0, default=10.0,
        description="Stiffness of the pull towards the neutral posture "
                    "(squared natural frequency, independent of the character size)")
    tension_damping: FloatProperty(
        name="Tension Damping", min=0.0, soft_max=2.0, default=0.35,
        description="Damping ratio of the neutral tension spring")
    soft_zone: FloatProperty(
        name="Soft Zone", subtype='FACTOR', min=0.0, max=0.5, default=0.25,
        description="Part of each joint range, near its limits, where the joint starts to resist")
    soft_strength: FloatProperty(
        name="Soft Limit Stiffness", min=0.0, soft_max=3000.0, default=400.0,
        description="Stiffness of the soft limits, growing progressively inside the soft zone")
    soft_damping: FloatProperty(
        name="Soft Limit Damping", min=0.0, soft_max=200.0, default=30.0,
        description="Extra damping inside the soft zone, slowing the joint down near its limits")
    joint_damping: FloatProperty(
        name="Joint Friction", min=0.0, soft_max=20.0, default=0.5,
        description="Damping applied to every joint motion")

    # Body -------------------------------------------------------------------
    total_mass: FloatProperty(
        name="Total Mass", subtype='NONE', unit='MASS', min=1.0, soft_max=300.0, default=70.0,
        description="Mass of the whole character, distributed with anthropometric ratios")
    forward_axis: EnumProperty(
        name="Facing",
        items=(
            ('AUTO', "Auto", "Detect from the feet direction"),
            ('NEG_Y', "-Y", "Character faces -Y (Blender default)"),
            ('POS_Y', "+Y", "Character faces +Y"),
            ('NEG_X', "-X", "Character faces -X"),
            ('POS_X', "+X", "Character faces +X"),
        ),
        default='AUTO',
        description="Direction the character faces in its rest pose, used to orient the joints")

    # World ------------------------------------------------------------------
    gravity_scale: FloatProperty(
        name="Gravity", subtype='FACTOR', min=0.0, soft_max=2.0, default=1.0,
        description="Multiplier of the scene gravity (0 for a zero gravity test of the neutral posture)")
    air_damping: FloatProperty(
        name="Air Drag", min=0.0, soft_max=2.0, default=0.02,
        description="Linear and angular velocity damping")
    use_ground: BoolProperty(name="Ground Plane", default=True,
                             description="Collide with an infinite horizontal ground plane")
    ground_height: FloatProperty(name="Height", subtype='DISTANCE', unit='LENGTH', default=0.0,
                                 description="Height of the ground plane")
    collider_collection: PointerProperty(
        name="Colliders", type=bpy.types.Collection,
        description="Objects of this collection are used as static collision geometry")
    animated_colliders: BoolProperty(
        name="Animated Colliders", default=False,
        description="Re-evaluate the collision geometry on every frame (slower)")
    friction: FloatProperty(name="Friction", min=0.0, soft_max=2.0, default=0.7,
                            description="Friction coefficient against colliders")
    self_collision: BoolProperty(name="Self Collision", default=True,
                                 description="Body parts collide with each other")

    # Simulation --------------------------------------------------------------
    substeps: IntProperty(name="Substeps", min=1, soft_max=60, default=12,
                          description="Solver substeps per frame, higher is more accurate and slower")
    use_scene_range: BoolProperty(name="Use Scene Range", default=True)
    frame_start: IntProperty(name="Start", default=1)
    frame_end: IntProperty(name="End", default=250)

    # Release -------------------------------------------------------------------
    release_frame: IntProperty(
        name="Release Frame", default=1,
        description="Frame where the character stops following its animation and becomes a ragdoll")
    blend_duration: FloatProperty(
        name="Blend Duration", min=0.0, soft_max=60.0, default=0.0,
        description="Frames to fade from the animation to the full simulation (active ragdoll)")
    leg_delay: FloatProperty(
        name="Leg Delay", min=0.0, soft_max=60.0, default=0.0,
        description="Frames the legs and pelvis keep following the animation after the upper body")
    drive_stiffness: FloatProperty(
        name="Drive Strength", min=1.0, soft_max=400.0, default=100.0,
        description="How strongly bodies follow the animation while blending")

    # Impact ----------------------------------------------------------------------
    use_impact: BoolProperty(name="Impact", default=False,
                             description="Push the character when it is released")
    impact_delay: IntProperty(name="Delay", min=0, default=0,
                              description="Frames after the release frame when the impact happens")
    impact_direction: FloatVectorProperty(
        name="Direction", subtype='DIRECTION', size=3, default=(0.0, 0.96, 0.28),
        description="World direction of the push")
    impact_speed: FloatProperty(name="Speed", unit='VELOCITY',
                                min=0.0, soft_max=30.0, default=4.0,
                                description="Velocity given to the whole body")
    impact_focus: FloatProperty(
        name="Focus", subtype='FACTOR', min=0.0, max=1.0, default=0.35,
        description="Part of the impulse concentrated on the hit bone instead of the whole body")
    impact_bone: StringProperty(name="Hit Bone", default="",
                                description="Bone receiving the focused impulse (chest when empty)")
    limb_kick: FloatProperty(
        name="Limb Rotation", min=0.0, soft_max=30.0, default=6.0, subtype='NONE',
        description="Rotational impulse (rad/s) given to shoulders and hips: "
                    "arms are thrown along the push, legs the other way")
    limb_kick_random: FloatProperty(
        name="Randomness", subtype='FACTOR', min=0.0, max=1.0, default=0.5,
        description="Random variation of the limb rotation so limbs do not move identically")
    seed: IntProperty(name="Seed", default=0, min=0)

    # Bake ------------------------------------------------------------------------
    mute_constraints: BoolProperty(
        name="Mute Bone Constraints", default=True,
        description="Mute bone constraints after baking so the baked keys are visible "
                    "(restored with 'Restore Animation')")
    original_action: PointerProperty(type=bpy.types.Action)
    ragdoll_action: PointerProperty(type=bpy.types.Action)
    muted_constraints: StringProperty(default="", options={'HIDDEN'})


classes = (
    BRAGDOLL_PG_bone,
    BRAGDOLL_PG_settings,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.PoseBone.better_ragdoll = PointerProperty(type=BRAGDOLL_PG_bone)
    bpy.types.Object.better_ragdoll = PointerProperty(type=BRAGDOLL_PG_settings)


def unregister():
    del bpy.types.Object.better_ragdoll
    del bpy.types.PoseBone.better_ragdoll
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
