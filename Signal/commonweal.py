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
    # instead of comparing last component
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
    cm_util = cmess_helpers
    from collections.abc import Sized  # has __len__
    out_dict = dict(args_dict)
    #
    def unempty(**kwargs):  # noqa: E306
        return {k: v for k, v in kwargs.items() if
                v is not None
                and (v or not isinstance(v, Sized))}
    #
    def extract(v):  # noqa: E306
        """Save anything relevant to conditions tests"""
        # TODO monitor CMessage::GetTime; as of 1.7.0-rc1, it returns a
        # SWIG timeval ptr obj, which can't be dereferenced to a sys/time.h
        # timeval. If it were made usable, we could forgo calling time().
        #
        # NOTE originally, these were kept json-serializable for latent
        # logging with details not conveyed by reprs -- any attempt to
        # persist swig objects result(ed) in a crash once this frame was
        # popped, regardless of any disown/thisown stuff. After changing
        # logging/debugging approach, there's no longer any reason not to
        # include non-swig objects in "_hook_data".
        # XXX ^^^^^^^^^^^^^^^ move above ^^^^^^^^^^^^^^ to a commit message
        # NOTE CHTTPSock (and web templates) are a special case, just
        # ignore, for now (logger will complain of 'unhandled arg')
        if isinstance(v, str):
            return v
        elif isinstance(v, (znc.String, znc.CPyRetString)):
            return str(v)
        elif isinstance(v, znc.CClient):
            return str(v.GetFullName())
        elif isinstance(v, znc.CIRCNetwork):
            return unempty(name=str(v.GetName()) or None,
                           away=v.IsIRCAway(),
                           client_count=len(v.GetClients()))
        elif isinstance(v, znc.CChan):
            return unempty(name=str(v.GetName()) or None,
                           detached=v.IsDetached())
        elif isinstance(v, znc.CNick):
            # TODO see src to find out how nickmask differs from hostmask
            return unempty(nick=v.GetNick(),
                           ident=v.GetIdent(),
                           host=v.GetHost(),
                           perms=v.GetPermStr(),
                           nickmask=v.GetNickMask(),
                           hostmask=v.GetHostMask())
        # Covers CPartMessage, CTextMessage
        elif hasattr(znc, "CMessage") and isinstance(v, znc.CMessage):
            return unempty(type=cm_util.types(v.GetType()).name,
                           nick=extract(v.GetNick()),
                           client=extract(v.GetClient()),
                           channel=extract(v.GetChan()),
                           command=v.GetCommand(),
                           params=cm_util.get_params(v),
                           network=extract(v.GetNetwork()),
                           target=extract(getattr(v, "GetTarget",
                                                  None.__class__)()),
                           text=extract(getattr(v, "GetText",
                                                None.__class__)()))
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
