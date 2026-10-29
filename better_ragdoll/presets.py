# SPDX-License-Identifier: GPL-3.0-or-later
"""Anatomical presets: joint ranges, neutral body posture and mass distribution.

All angles are in degrees and expressed for the LEFT side of the body:
  flex  - flexion (+) / extension (-)
  abd   - abduction away from the body midline (+) / adduction (-)
          (lateral bending to the character's left for central bones)
  twist - axial rotation around the bone

Each entry is (minimum, maximum, neutral). Right side bones are mirrored
automatically when the ragdoll is built.

The neutral angles loosely follow the NASA "Neutral Body Posture" observed in
microgravity: hips and knees bent, shoulders relaxed and rolled forward,
elbows bent, feet slightly pointed and head tilted forward.
"""

ROLE_ITEMS = (
    ('NONE', "None", "Bone is not simulated, it follows its parent"),
    ('PELVIS', "Pelvis", "Root of the ragdoll (hips)"),
    ('SPINE', "Spine", "Spine / chest segment"),
    ('NECK', "Neck", "Neck segment"),
    ('HEAD', "Head", "Head"),
    ('CLAVICLE', "Clavicle", "Clavicle / shoulder blade"),
    ('UPPER_ARM', "Upper Arm", "Upper arm (shoulder joint)"),
    ('FOREARM', "Forearm", "Forearm (elbow joint)"),
    ('HAND', "Hand", "Hand (wrist joint)"),
    ('THIGH', "Thigh", "Thigh (hip joint)"),
    ('SHIN', "Shin", "Shin (knee joint)"),
    ('FOOT', "Foot", "Foot (ankle joint)"),
    ('TOE', "Toe", "Toes, rigidly attached to the foot and extending its collision"),
)

CENTER_ROLES = {'PELVIS', 'SPINE', 'NECK', 'HEAD'}
SIDE_ROLES = {'CLAVICLE', 'UPPER_ARM', 'FOREARM', 'HAND', 'THIGH', 'SHIN', 'FOOT', 'TOE'}

# Roles where consecutive bones of the same role (twist / segment bones)
# are merged into one rigid body.
MERGE_ROLES = {'NECK', 'CLAVICLE', 'UPPER_ARM', 'FOREARM', 'HAND', 'THIGH', 'SHIN', 'FOOT'}

LOWER_BODY_ROLES = {'PELVIS', 'THIGH', 'SHIN', 'FOOT', 'TOE'}

# Direction the bone points to when every angle is zero.
#   DOWN   - straight down (limb hanging along the body)
#   PARENT - continuing the parent segment (straight elbow / knee)
#   REST   - the rest pose direction of the bone
ZERO_DIRECTION = {
    'SPINE': 'REST',
    'NECK': 'REST',
    'HEAD': 'REST',
    'CLAVICLE': 'REST',
    'UPPER_ARM': 'DOWN',
    'FOREARM': 'PARENT',
    'HAND': 'REST',
    'THIGH': 'DOWN',
    'SHIN': 'PARENT',
    'FOOT': 'REST',
}

# Where a positive flexion moves the end of the bone.
FLEX_DIRECTION = {
    'SPINE': 'FORWARD',
    'NECK': 'FORWARD',
    'HEAD': 'FORWARD',
    'CLAVICLE': 'FORWARD',
    'UPPER_ARM': 'FORWARD',
    'FOREARM': 'FORWARD',
    'HAND': 'FORWARD',
    'THIGH': 'FORWARD',
    'SHIN': 'BACKWARD',
    'FOOT': 'UP',
}

LIMITS = {
    'SPINE': {'flex': (-20.0, 35.0, 4.0), 'abd': (-20.0, 20.0, 0.0), 'twist': (-20.0, 20.0, 0.0)},
    'NECK': {'flex': (-40.0, 50.0, 12.0), 'abd': (-30.0, 30.0, 0.0), 'twist': (-45.0, 45.0, 0.0)},
    'HEAD': {'flex': (-30.0, 35.0, 10.0), 'abd': (-20.0, 20.0, 0.0), 'twist': (-35.0, 35.0, 0.0)},
    'CLAVICLE': {'flex': (-15.0, 20.0, 6.0), 'abd': (-10.0, 30.0, 0.0), 'twist': (-10.0, 10.0, 0.0)},
    'UPPER_ARM': {'flex': (-50.0, 170.0, 38.0), 'abd': (-30.0, 165.0, 42.0), 'twist': (-70.0, 70.0, 10.0)},
    'FOREARM': {'flex': (0.0, 145.0, 65.0), 'abd': (-4.0, 4.0, 0.0), 'twist': (-80.0, 80.0, 0.0)},
    'HAND': {'flex': (-70.0, 70.0, 0.0), 'abd': (-20.0, 30.0, 5.0), 'twist': (-8.0, 8.0, 0.0)},
    'THIGH': {'flex': (-20.0, 125.0, 48.0), 'abd': (-20.0, 45.0, 10.0), 'twist': (-35.0, 35.0, 5.0)},
    'SHIN': {'flex': (0.0, 145.0, 50.0), 'abd': (-4.0, 4.0, 0.0), 'twist': (-8.0, 8.0, 0.0)},
    'FOOT': {'flex': (-50.0, 20.0, -20.0), 'abd': (-15.0, 15.0, 0.0), 'twist': (-20.0, 20.0, 0.0)},
}

# Fraction of the total body mass (Winter, Biomechanics and Motor Control of
# Human Movement). Spine and neck fractions are shared between all bodies of
# that role.
MASS_FRACTION = {
    'PELVIS': 0.142,
    'SPINE': 0.335,
    'NECK': 0.012,
    'HEAD': 0.069,
    'CLAVICLE': 0.01,
    'UPPER_ARM': 0.028,
    'FOREARM': 0.016,
    'HAND': 0.006,
    'THIGH': 0.100,
    'SHIN': 0.0465,
    'FOOT': 0.0145,
}
SHARED_MASS_ROLES = {'SPINE', 'NECK'}

# Collision radius as a fraction of the segment length, used when no skinned
# mesh is available to measure the body thickness.
RADIUS_RATIO = {
    'PELVIS': 0.9,
    'SPINE': 0.8,
    'NECK': 0.45,
    'HEAD': 0.5,
    'CLAVICLE': 0.3,
    'UPPER_ARM': 0.2,
    'FOREARM': 0.17,
    'HAND': 0.3,
    'THIGH': 0.17,
    'SHIN': 0.13,
    'FOOT': 0.25,
}

# Absolute minimum / maximum radius, relative to the character height.
RADIUS_HEIGHT_RANGE = {
    'PELVIS': (0.05, 0.11),
    'SPINE': (0.05, 0.11),
    'NECK': (0.025, 0.05),
    'HEAD': (0.05, 0.075),
    'CLAVICLE': (0.02, 0.045),
    'UPPER_ARM': (0.022, 0.05),
    'FOREARM': (0.018, 0.04),
    'HAND': (0.015, 0.035),
    'THIGH': (0.03, 0.07),
    'SHIN': (0.022, 0.05),
    'FOOT': (0.018, 0.04),
}
