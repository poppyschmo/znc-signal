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

znc_version_str = znc.CZNC.GetVersion()
znc_version = tuple(map(int, znc_version_str.partition("-")[0].split(".")))


def get_deprecated_hooks():
    if znc_version < (1, 7, 0):
        return None
    on_hooks = {a for a in dir(znc.Module) if a.startswith("On")}
    depcands = {o.replace("TextMessage", "Msg")
                .replace("PlayMessage", "PlayLine")
                .replace("Message", "") for
                o in on_hooks if o.endswith("Message")}
    return on_hooks & depcands


def get_cmess_helpers():
    r"""Helpers for dealing with CMessage objects

    >>> mymsg = znc.CMessage(":irc.znc.in PONG irc.znc.in test_server")
    >>> mymsg.GetParams()  # doctest: +ELLIPSIS +SKIP
    (<Swig Object of type 'unknown' at 0x...>, <Swig Object ...>)
    >>> cmess_helpers.get_params(mymsg)
    ('irc.znc.in', 'test_server')
    >>> cmess_helpers.types(mymsg.GetType())
    <CMessage::Type.Pong: 16>
    >>> cmess_helpers.types(16) == cmess_helpers.types.Pong == \
    ...     cmess_helpers.types["Pong"] == _
    True

    Note: running the above without the ``+SKIP`` directive produces
    this log message::

        swig/python detected a memory leak of type 'unknown', ...
            no destructor found.

    Actually, the lack of log formatting suggests it's just dumped
    straight to the out stream.
    """
    if not hasattr(znc, "CMessage"):
        return None

    from collections import namedtuple
    cmess_helpers_NT = namedtuple("CMessageHelpers", "types get_params")
    cmess_helpers_NT.__doc__ += get_cmess_helpers.__doc__

    from enum import Enum
    types = Enum("CMessage::Type", ((k.split("_", 1)[-1], v) for k, v in
                                    vars(znc.CMessage).items() if
                                    k.startswith("Type_")))
    return cmess_helpers_NT(types, _get_params)


# Versions 1.7.0-rc1 to 1.7.1
def _get_params(cm):
    """Temporary kludge for CMessage.GetParams()"""
    # TODO verify this is no longer needed in 1.7.1. See docstring in
    # get_cmess_helpers, above, for explanation.
    params = cm.GetParams()
    vout = []
    for i, p in enumerate(params):
        p.disown()  # <- makes mem leak msg go away; no idea why
        vout.append(cm.GetParam(i))
    return tuple(vout)


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


deprecated_hooks = get_deprecated_hooks()
cmess_helpers = get_cmess_helpers()
