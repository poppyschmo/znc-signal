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


def get_deprecated_hooks(on_hooks=None):
    if znc_version < (1, 7, 0):
        return None
    if not on_hooks:  # used by /tests/test_hooks.py
        on_hooks = {a for a in dir(znc.Module) if a.startswith("On")}
    depcands = {o.replace("TextMessage", "Msg")
                .replace("PlayMessage", "PlayLine")
                .replace("Message", "") for
                o in on_hooks if o.endswith("Message")}
    return on_hooks & depcands


def get_cmess_types():
    r"""Convenience helper for CMessage types

    >>> t = get_cmess_types()
    >>> mymsg = znc.CMessage(":irc.znc.in PONG irc.znc.in test_server")
    >>> t(mymsg.GetType())
    <CMessage::Type.Pong: 16>
    >>> t(16) == t.Pong == t["Pong"] == 16 == _
    True
    """
    # TODO find out what the significance of these categories are (since
    # they're often the same as commands; RFCs don't seem to list any similar
    # groupings; if irrelevant to learning ZNC, remove
    #
    # TODO (longterm) when learning about SWIG, see whether patching objects
    # like znc.CMessage with custom objects (like this enum) is doable
    # responsibly (likewise for wrappers to handle version-specific issues)
    #
    # Can't create global at import time because tests use fake znc with
    # limited hooks inventory.
    types = globals().get("_cmess_types")
    if types:
        return types
    from enum import IntEnum
    types = IntEnum("CMessage::Type", ((k.split("_", 1)[-1], v) for k, v in
                                       vars(znc.CMessage).items() if
                                       k.startswith("Type_")))
    globals()["_cmess_types"] = types
    return types


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


def get_first(data, *keys):
    """Retrieve a normalized data item, looking first in 'msg'
    """
    if "msg" in data:
        first, *rest = keys
        cand = data["msg"].get(first)
        if cand is not None:
            return cand
        keys = rest
    for key in keys:
        cand = data.get(key)
        if cand is not None:
            return cand


def normalize_onner(inst, name, args_dict, ensure_net=False):
    """Preprocess hook arguments

    Ignore hooks describing client-server business. Extract relevant
    info from others, and save them in a normalized fashion for
    later use.
    """
    from collections.abc import Sized  # has __len__
    out_dict = dict(args_dict)
    cmess_types = get_cmess_types()
    #
    def unempty(**kwargs):  # noqa: E306
        return {k: v for k, v in kwargs.items() if
                v is not None
                and (v or not isinstance(v, Sized))}
    #
    def extract(v):  # noqa: E306
        """Save anything relevant to conditions tests"""
        # TODO add CMessage::GetTime() when implemented. #1578
        #
        # NOTE CHTTPSock (and web templates) are a special case, just
        # ignore, for now (logger will complain of 'unhandled arg')
        if isinstance(v, str):
            return v
        elif isinstance(v, (znc.String, znc.CPyRetString)):
            return str(v)
        elif isinstance(v, znc.CClient):
            return v.GetFullName()
        elif isinstance(v, znc.CIRCNetwork):
            return unempty(name=v.GetName() or None,
                           away=v.IsIRCAway(),
                           client_count=len(v.GetClients()))
        elif isinstance(v, znc.CChan):
            return unempty(name=str(v.GetName()) or None,
                           detached=v.IsDetached())
        elif isinstance(v, znc.CNick):
            return unempty(nick=v.GetNick(),
                           ident=v.GetIdent(),
                           host=v.GetHost(),
                           perms=v.GetPermStr(),
                           hostmask=v.GetHostMask())
        elif isinstance(v, znc.MCString):
            if znc_version > (1, 7, 0):  # ZNC #1543
                return unempty(**v)
        # Covers CPartMessage, CTextMessage
        elif hasattr(znc, "CMessage") and isinstance(v, znc.CMessage):
            return unempty(type=cmess_types(v.GetType()).name,
                           nick=extract(v.GetNick()),
                           client=extract(v.GetClient()),
                           channel=extract(v.GetChan()),
                           command=v.GetCommand(),
                           params=((znc_version > (1, 7, 0) or None)
                                   and v.GetParams()),  # ZNC #1543
                           network=extract(v.GetNetwork()),
                           target=extract(getattr(v, "GetTarget",
                                                  None.__class__)()),
                           text=extract(getattr(v, "GetText",
                                                None.__class__)()),
                           tags=extract(v.GetTags()))
        elif v is not None:
            inst.logger.debug(f"Unhandled arg: {k!r}: {v!r}")
    #
    for k, v in args_dict.items():
        try:
            out_dict[k] = extract(v)
        except Exception:
            inst.print_traceback()
    #
    # Needed for common lookups (reckoning and expanding msg fmt vars)
    if ensure_net and not get_first(out_dict, "network", "Network"):
        net = inst.GetNetwork()
        if net:
            out_dict["network"] = extract(net)
    return out_dict


znc_version = get_version(znc.CZNC.GetVersion(),
                          getattr(znc, "VersionExtra", None))
deprecated_hooks = get_deprecated_hooks()
cmess_helpers = get_cmess_helpers()
