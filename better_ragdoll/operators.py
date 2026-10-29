# SPDX-License-Identifier: GPL-3.0-or-later

import time

import bpy

from . import detect
from .model import RagdollError, build_model
from .simulate import bake, preview_neutral, restore_source, simulate


def _armature(context):
    ob = context.active_object
    if ob is not None and ob.type == 'ARMATURE':
        return ob
    return None


class _ArmatureOperator:
    @classmethod
    def poll(cls, context):
        return _armature(context) is not None


class BRAGDOLL_OT_detect(_ArmatureOperator, bpy.types.Operator):
    """Detect humanoid bones from their names and hierarchy and load the anatomical presets"""
    bl_idname = "better_ragdoll.detect"
    bl_label = "Detect Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = _armature(context)
        roles = detect.detect_roles(ob)
        for pb in ob.pose.bones:
            rb = pb.better_ragdoll
            rb.role = roles.get(pb.name, 'NONE')
            rb.load_preset()
        if not roles:
            self.report({'WARNING'}, "No humanoid bones found, assign roles in the Bone properties")
            return {'CANCELLED'}
        try:
            model = build_model(ob, ob.better_ragdoll)
        except RagdollError as ex:
            self.report({'WARNING'}, str(ex))
            return {'FINISHED'}
        self.report({'INFO'}, "Ragdoll: %d bones mapped to %d bodies" % (len(roles), len(model.bodies)))
        return {'FINISHED'}


class BRAGDOLL_OT_clear(_ArmatureOperator, bpy.types.Operator):
    """Remove the ragdoll role of every bone"""
    bl_idname = "better_ragdoll.clear"
    bl_label = "Clear Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for pb in _armature(context).pose.bones:
            pb.better_ragdoll.role = 'NONE'
        return {'FINISHED'}


class BRAGDOLL_OT_load_preset(bpy.types.Operator):
    """Reset the joint limits and neutral angles of the active bone to the anatomical preset of its role"""
    bl_idname = "better_ragdoll.load_preset"
    bl_label = "Reset Limits to Preset"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_pose_bone is not None

    def execute(self, context):
        context.active_pose_bone.better_ragdoll.load_preset()
        return {'FINISHED'}


class BRAGDOLL_OT_preview_neutral(_ArmatureOperator, bpy.types.Operator):
    """Pose the armature in its neutral body posture (relaxed muscles), to check the joint setup"""
    bl_idname = "better_ragdoll.preview_neutral"
    bl_label = "Preview Neutral Pose"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = _armature(context)
        try:
            preview_neutral(context, ob, ob.better_ragdoll)
        except RagdollError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class BRAGDOLL_OT_reset_pose(_ArmatureOperator, bpy.types.Operator):
    """Clear the pose of all bones"""
    bl_idname = "better_ragdoll.reset_pose"
    bl_label = "Reset Pose"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for pb in _armature(context).pose.bones:
            pb.matrix_basis.identity()
        return {'FINISHED'}


class BRAGDOLL_OT_bake(_ArmatureOperator, bpy.types.Operator):
    """Simulate the ragdoll over the frame range and bake the result to a new action"""
    bl_idname = "better_ragdoll.simulate_bake"
    bl_label = "Simulate & Bake"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = _armature(context)
        settings = ob.better_ragdoll
        if context.mode != 'OBJECT' and context.mode != 'POSE':
            self.report({'ERROR'}, "Switch to Object or Pose mode first")
            return {'CANCELLED'}
        wm = context.window_manager
        wm.progress_begin(0, 200)
        t0 = time.time()
        try:
            model, samples, results = simulate(
                context, ob, settings, progress=lambda u: wm.progress_update(int(u * 150)))
            bake(ob, settings, model, samples, results,
                 progress=lambda u: wm.progress_update(150 + int(u * 50)))
        except RagdollError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        finally:
            wm.progress_end()
        context.scene.frame_set(context.scene.frame_current)
        self.report({'INFO'}, "Ragdoll baked: %d bodies, %d frames in %.1fs" % (
            len(model.bodies), len(results), time.time() - t0))
        return {'FINISHED'}


class BRAGDOLL_OT_restore(_ArmatureOperator, bpy.types.Operator):
    """Restore the original action and unmute the bone constraints"""
    bl_idname = "better_ragdoll.restore"
    bl_label = "Restore Animation"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = _armature(context)
        return ob is not None and ob.better_ragdoll.ragdoll_action is not None

    def execute(self, context):
        ob = _armature(context)
        restore_source(ob)
        if ob.animation_data is not None and ob.animation_data.action is None:
            for pb in ob.pose.bones:
                pb.matrix_basis.identity()
        context.scene.frame_set(context.scene.frame_current)
        return {'FINISHED'}


classes = (
    BRAGDOLL_OT_detect,
    BRAGDOLL_OT_clear,
    BRAGDOLL_OT_load_preset,
    BRAGDOLL_OT_preview_neutral,
    BRAGDOLL_OT_reset_pose,
    BRAGDOLL_OT_bake,
    BRAGDOLL_OT_restore,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
