from . import znc, znc_version

legacmess_hooks = {}


def degenerate_cm_hook_name(name):
    return (name.replace("TextMessage", "Msg")
            .replace("PlayMessage", "PlayLine")
            .replace("Message", ""))


def get_deprecated_hooks(on_hooks=None):
    """Create a set of all legacy hook names"""
    if znc_version < (1, 7, 0):
        return None
    if not on_hooks:  # used by /tests/test_hooks.py
        on_hooks = {a for a in dir(znc.Module) if a.startswith("On")}
    depcands = {degenerate_cm_hook_name(o) for
                o in on_hooks if o.endswith("Message")}
    return on_hooks & depcands


deprecated_hooks = get_deprecated_hooks()


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


def get_deprecated_hooks_map():
    """Return map of CMessage-hook names to their pre-1.7 counterparts
    """
    hooks = (a for a in dir(znc.Module) if a.startswith("On"))
    tenders = ((h, degenerate_cm_hook_name(h)) for
               h in hooks if h.endswith("Message"))
    return dict((k, v) for k, v in tenders if v in deprecated_hooks)


def is_channer(name):
    """Return True if hook is 'channel-related' (CMessage only)

    See #1587

    This is a temporary safety check for ``normalize_onner``, just in
    case the issue applies to more than just ``OnSendToClientMessage``.
    """
    #
    if name in ("OnSendToClientMessage",):
        return False
    if not legacmess_hooks:
        legacmess_hooks.update(get_deprecated_hooks_map())
    if name not in legacmess_hooks:
        return False
    onner = getattr(znc.Module, legacmess_hooks[name], None)
    if onner is None:
        return False
    from inspect import signature
    sig = signature(onner)
    return any("chan" in p.lower() for p in sig.parameters)


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
        """Save data items relevant to conditions tests or inspection"""
        # TODO add CMessage::GetTime() when implemented. #1578
        #
        # NOTE for now, the following are simply ignored. The logger, if
        # active, will complain of an 'unhandled arg':
        #
        #   - vChans (relatively common: OnJoinMessage, etc.)
        #   - CHTTPSock (and web templates)
        #
        # NOTE the msg object passed to OnUserJoinMessage can't be used to call
        # GetChan(). Use GetTarget() to retrieve the same sChannel string
        # passed to OnUserJoin.
        #
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
            if k == "msg" and not is_channer(name):
                return None
            return unempty(name=v.GetName() or None,
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
            k = None
            out_dict["network"] = extract(net)
    return out_dict
