# SPDX-License-Identifier: GPL-3.0-or-later
"""Better Ragdoll: ragdoll simulation with soft joint limits and neutral body posture tension."""

from . import operators, properties, ui

_modules = (properties, operators, ui)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
