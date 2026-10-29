# Better Ragdoll: extensions.blender.org listing

Better Ragdoll is an extension that brings a more realistic radgoll in Blender.

Most ragdolls only have **hard joint limits**: a joint swings at full speed and stops dead at its limit, so the body flails and bounces off its own joints. Better Ragdoll adds two things:

**Soft limits:** Near the end of its range, each joint meets a progressive spring and extra damping, so it slows down before reaching the limit. This works like muscles, ligaments and tendons reaching their maximum stretch.

**Neutral body posture tension:** A gentle pull brings every joint toward a relaxed posture, loosely based on NASA's microgravity *Neutral Body Posture*: hips and knees bent, shoulders rolled forward, elbows bent, feet relaxed, head tilted forward. With gravity at 0, the character drifts into this pose. With gravity on, it gives the body weight and makes it settle in natural resting poses.

### How to use

1. Select your armature and open the **Ragdoll** tab in the 3D View sidebar.
2. Click **Detect Bones**, then **Preview Neutral Pose** to check the setup.
3. Pick a release frame, an optional impact and a collider collection.
4. Click **Simulate & Bake**.

### Features

- **One-click setup.** Bone roles are detected from names and hierarchy (Mixamo, Rigify metarig and deform bones, Unreal-style and generic names). The anatomical joint limits and neutral angles load automatically, and every value can be edited per bone.
- **Anatomical joints.** Flexion, abduction and twist are measured in the character's own frame, so presets work in both T-pose and A-pose and whatever the bone roll.
- **Classic mode** with hard limits only, for side-by-side comparison.
- **Impacts with rotational kick.** A push also spins the shoulders and hips: arms are thrown with the impact while legs swing the opposite way, with adjustable randomness.
- **Active ragdoll blend.** The character fades from its animation into the simulation, upper body first and legs after a delay, and keeps its momentum.
- **Collisions.** Collides with a ground plane, any meshes in a collection (static or animated), and itself, with friction.
- **Automatic body setup.** Masses follow human body-segment proportions, and capsule sizes are measured from the skinned mesh.
- **Clean bake.** The result goes to a new action. One click restores the original animation and bone constraints.


## Support URL

  https://github.com/Volko61/better-ragdoll/issues

## Initial Version: release notes (paste in "Write")

First release.

- Ragdoll solver based on extended position-based dynamics (XPBD), with soft joint limits and neutral body posture tension
- Classic hard-limits mode for comparison
- Automatic humanoid bone detection with anatomical presets
- Impacts with rotational shoulder and hip kicks
- Active ragdoll blend from animation, upper body first
- Ground, collection and self collisions
- Bakes to a new action; original animation can be restored

## Media (files in promo/output)

| Field | File |
| --- | --- |
| Icon (256×256 PNG) | `icon_256.png` |
| Featured image (1920×1080) | `featured_1920x1080.png` |
| Preview 1 (video) | `better_ragdoll_demo.mp4` |
| Preview 2 | `preview_zero_gravity.png` |
| Preview 3 | `preview_stairs.png` |
| Preview 4 | `preview_title.png` |

To regenerate the media, run `blender -b --factory-startup --python promo/showcase.py -- full` (the scene is also saved to `promo/showcase.blend`).
