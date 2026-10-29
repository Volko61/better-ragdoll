# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from . import presets

ROLE_NAMES = {item[0]: item[1] for item in presets.ROLE_ITEMS}


def _armature(context):
    ob = context.active_object
    if ob is not None and ob.type == 'ARMATURE':
        return ob
    return None


class BRAGDOLL_PT_main(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Ragdoll"
    bl_label = "Better Ragdoll"

    def draw(self, context):
        layout = self.layout
        ob = _armature(context)
        if ob is None:
            layout.label(text="Select an armature", icon='INFO')
            return
        s = ob.better_ragdoll
        mapped = sum(1 for pb in ob.pose.bones if pb.better_ragdoll.role != 'NONE')

        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("better_ragdoll.detect", icon='ARMATURE_DATA')
        row.operator("better_ragdoll.clear", text="", icon='X')
        col.label(text="%d bones mapped" % mapped)

        layout.prop(s, "limit_mode", text="")
        row = layout.row(align=True)
        row.operator("better_ragdoll.preview_neutral", icon='OUTLINER_OB_ARMATURE')
        row.operator("better_ragdoll.reset_pose", text="", icon='LOOP_BACK')

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("better_ragdoll.simulate_bake", icon='PHYSICS')
        if s.ragdoll_action is not None:
            layout.operator("better_ragdoll.restore", icon='ACTION')


class _SubPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Ragdoll"
    bl_parent_id = "BRAGDOLL_PT_main"

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None


class BRAGDOLL_PT_bones(_SubPanel, bpy.types.Panel):
    bl_label = "Bones"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        ob = _armature(context)
        layout = self.layout
        layout.prop(ob.better_ragdoll, "forward_axis")
        layout.prop(ob.better_ragdoll, "total_mass")
        col = layout.column(align=True)
        for pb in ob.pose.bones:
            role = pb.better_ragdoll.role
            if role == 'NONE':
                continue
            row = col.row(align=True)
            row.label(text=pb.name, icon='BONE_DATA')
            row.label(text=ROLE_NAMES[role])
        layout.label(text="Edit roles and limits in Bone properties", icon='INFO')


class BRAGDOLL_PT_joints(_SubPanel, bpy.types.Panel):
    bl_label = "Joints"

    def draw(self, context):
        s = _armature(context).better_ragdoll
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        soft = s.limit_mode == 'SOFT'
        col = layout.column(heading="Soft Limits")
        col.active = soft
        col.prop(s, "soft_zone")
        col.prop(s, "soft_strength", text="Stiffness")
        col.prop(s, "soft_damping", text="Damping")
        col = layout.column()
        col.active = soft
        col.prop(s, "use_tension")
        sub = col.column()
        sub.active = soft and s.use_tension
        sub.prop(s, "tension", text="Strength")
        sub.prop(s, "tension_damping", text="Damping")
        layout.prop(s, "joint_damping")


class BRAGDOLL_PT_world(_SubPanel, bpy.types.Panel):
    bl_label = "World & Collision"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = _armature(context).better_ragdoll
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "gravity_scale")
        layout.prop(s, "air_damping")
        layout.prop(s, "use_ground")
        sub = layout.column()
        sub.active = s.use_ground
        sub.prop(s, "ground_height")
        layout.prop(s, "collider_collection")
        layout.prop(s, "animated_colliders")
        layout.prop(s, "friction")
        layout.prop(s, "self_collision")


class BRAGDOLL_PT_release(_SubPanel, bpy.types.Panel):
    bl_label = "Release"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = _armature(context).better_ragdoll
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "release_frame")
        layout.prop(s, "blend_duration")
        layout.prop(s, "leg_delay")
        sub = layout.column()
        sub.active = s.blend_duration > 0.0 or s.leg_delay > 0.0
        sub.prop(s, "drive_stiffness")


class BRAGDOLL_PT_impact(_SubPanel, bpy.types.Panel):
    bl_label = "Impact"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(_armature(context).better_ragdoll, "use_impact", text="")

    def draw(self, context):
        ob = _armature(context)
        s = ob.better_ragdoll
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.active = s.use_impact
        layout.prop(s, "impact_delay")
        layout.prop(s, "impact_direction")
        layout.prop(s, "impact_speed")
        layout.prop_search(s, "impact_bone", ob.data, "bones")
        layout.prop(s, "impact_focus")
        col = layout.column(heading="Shoulders & Hips")
        col.prop(s, "limb_kick")
        col.prop(s, "limb_kick_random")
        col.prop(s, "seed")


class BRAGDOLL_PT_bake(_SubPanel, bpy.types.Panel):
    bl_label = "Simulation"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = _armature(context).better_ragdoll
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(s, "substeps")
        layout.prop(s, "use_scene_range")
        if not s.use_scene_range:
            col = layout.column(align=True)
            col.prop(s, "frame_start")
            col.prop(s, "frame_end")
        layout.prop(s, "mute_constraints")


class BRAGDOLL_PT_bone(bpy.types.Panel):
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "bone"
    bl_label = "Ragdoll"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.active_pose_bone is not None

    def draw(self, context):
        rb = context.active_pose_bone.better_ragdoll
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(rb, "role")
        if rb.role == 'NONE':
            return
        layout.prop(rb, "radius")
        if rb.role in {'PELVIS', 'TOE'}:
            return
        for axis, label in (("flex", "Flexion"), ("abd", "Abduction"), ("twist", "Twist")):
            col = layout.column(align=True, heading=label)
            col.prop(rb, axis + "_min", text="Min")
            col.prop(rb, axis + "_max", text="Max")
            col.prop(rb, axis + "_neutral", text="Neutral")
        layout.operator("better_ragdoll.load_preset", icon='FILE_REFRESH')


classes = (
    BRAGDOLL_PT_main,
    BRAGDOLL_PT_bones,
    BRAGDOLL_PT_joints,
    BRAGDOLL_PT_world,
    BRAGDOLL_PT_release,
    BRAGDOLL_PT_impact,
    BRAGDOLL_PT_bake,
    BRAGDOLL_PT_bone,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
