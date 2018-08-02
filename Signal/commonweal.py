# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.
"""
Disembodied methods and standalone functions used by the main ZNC module,
mini modules (like "inspect_hooks"), and tests

Some of these are meant to be bound to a class as single-serving mix-ins. No
scope in this file should import anything from elsewhere in the Signal package.
Needed objects can be reached via instance args ("self").
"""
from . import znc

# TODO see if it's feasible to move what remains of this file to __init__.py,
# since most everything else is now part of extras/inspect_hooks


def get_version(version_string, extra=None):
    """Return ZNC version as tuple, e.g., (1, 7, 0)"""
    # Unsure of the proper way to get the third ("revision") component in
    # major.minor.revision and whether this is synonymous with VERSION_PATCH
    #
    # TODO learn ZNC's versioning system; For now, prefer manual feature tests
    # instead of comparing last component; <https://wiki.znc.in/Branches>
    #
    if extra is not None:  # see test_version for an example
        version_string = version_string.replace(extra, "", 1)
    from math import inf
    return tuple(int(d) if d.isdigit() else inf for
                 d in version_string.partition("-")[0].split(".", 2))


def update_module_attributes(inst, argstr, namespace=None):
    """Check environment and argstring for valid attrs

    To prevent collisions, envvars must be in all caps and prefixed with
    the module's name + ``MOD_``.

    Null values aren't recognized. If the corresponding default is None,
    the new value is left as a string. Otherwise, it's converted to
    that of the existing attr.
    """
    import os
    import shlex
    from configparser import RawConfigParser
    #
    bools = RawConfigParser.BOOLEAN_STATES
    if not namespace:
        namespace = "%smod_" % inst.__class__.__name__.lower()
    #
    def adopt(k, v):  # noqa: E306
        default = getattr(inst, k)
        try:
            if isinstance(default, bool):
                casted = bools.get(v.lower(), False)  # true/false
            elif isinstance(default, (int, float)):
                casted = type(default)(v)
            elif isinstance(default, (type(None), str)):
                casted = v
            else:
                raise TypeError("Cannot assign to default attribute of type "
                                f"{type(default)}")
        except Exception:
            casted = default
        setattr(inst, k, casted)
    #
    for key, val in os.environ.items():
        key = key.lower()
        if not val or not key.startswith(namespace):
            continue
        key = key.replace(namespace, "", 1)
        if not hasattr(inst, key):
            continue
        adopt(key, val)
    #
    if not str(argstr):
        return
    args = (a.split("=") for a in shlex.split(str(argstr)))
    for key, val in args:
        key = key.lower()
        if not val or not hasattr(inst, key):
            continue
        adopt(key, val)


znc_version = get_version(znc.CZNC.GetVersion(),
                          getattr(znc, "VersionExtra", None))
