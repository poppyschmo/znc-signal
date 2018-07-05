# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from . import znc
from . import get_logger


class Signal(znc.Module):
    module_types = [znc.CModInfo.UserModule]
    description = "Interact with a local Signal endpoint"
    args_help_text = "DATADIR=<path> DEBUG=<bool> LOGFILE=<path>"
    has_args = True
    znc_version = None  # tuple, e.g. 1.7.0-rc1 -> (1, 7, 0)
    data_dir = None     # str, $DATADIR or path from CModule::GetSavePath()
    networks = None     # tuple, CIRCNetwork swig objects
    env = None          # dict, copy of environ w. SIGNALMOD_ prefixes dropped
    tz = None           # datetime.timezone
    config = None       # config_NT, members are BaseConfigDict subclasses
    debug = False
    log_raw = log_old_hooks = False     # from args/envvars: _RAW, _OLD_HOOKS
    logger = None                   # logging.Logger, for this CModule object
    last_traceback = None           # traceback, used by print_traceback
    last_config_selector = None     # str, used by cmd_update, cmd_select
    deprecated_hooks = None         # set, redundant, non-CMessage hooks, 1.7+
    approx = None               # cmdopts.AllParsed ~> argparse.ArgumentParser
    mod_commands = None         # dict, {cmd_<name> : method, ...}
    last_mod_cmd = None         # str, last cmd line passed to OnModCommand
    #
    active_hooks = """
        OnChanMsg       OnChanTextMessage
        OnChanAction    OnChanActionMessage
        OnPrivMsg       OnPrivTextMessage
        OnPrivAction    OnPrivActionMessage
    """

    def __new__(cls, *args, **kwargs):
        # TODO add comment/reminder of why this stuff isn't in __init__.
        # (Something to do with instance dict.) Also add test to justify, if
        # possible.
        new_self = super().__new__(cls, *args, **kwargs)
        new_self.__dict__.update(
            {m.lstrip("_"): getattr(new_self, m) for m in dir(new_self) if
             m.startswith("_On")}
        )
        new_self.active_hooks = tuple(new_self.active_hooks.split())
        return new_self

    def __getattribute__(self, name):
        """Intercept calls to On* methods for learning purposes

        Rationale: overriding all the base methods just to see how they
        behave is a hassle.
        """
        candidate = super().__getattribute__(name)
        if name.startswith("On"):
            try:
                return self.__dict__[name]
            except KeyError:
                return self._wrap_onner(candidate)
        return candidate

    def print_traceback(self, where=None):
        import sys
        self.last_traceback = sys.exc_info()[-1]
        if where is None and self.debug:
            self.logger.debug(znc.traceback.format_exc())
        elif hasattr(where, "write"):
            znc.traceback.print_exc(file=where)
        else:
            etype, value, tb = sys.exc_info()
            self.put_pretty(f"\x02{etype.__name__}\x02: {value}", where)

    def put_pretty(self, lines, where=None):
        """Call the appropriate client-facing ``Put*`` function

        Messages specifying IRC commands must already be formatted. A
        format string could be used in the future to apply line-wise
        formatting dynamically, but required fields would need to be
        provided (perhaps as part of a ``CMessage`` object).

        Format can be like that used by CBuffer and friends:

            '!watch@znc.in PRIVMSG {target} :{text}'

        """
        #
        # TODO add 'source' arg for PutClient; otherwise, no point in calling
        # this func if having to preformat every line beforehand
        putters = None
        where = where or "PutModule"
        #
        if where == "PutIRC":
            # TODO would have to pass network name/obj for this to work
            raise RuntimeError("'PutIRC' must be called manually")
        elif where == "PutClient":  # untried on 1.6.x
            # Callbacks usually want this sent to all clients, not just the
            # last to invoke a mod command
            putters = self.get_clients()
        elif where in ("PutUser", "PutStatus"):
            # CUser.PutStatus also works outside of On* hooks
            putters = self.networks
        elif self.last_mod_cmd and where in ("PutModule", "PutModNotice"):
            # Note: if needing to trigger OnSendToClientMessage or prefix with
            # a custom source, use PutClient instead
            client = self.GetClient()
            if client is None:
                # Probably not in an On* hook (fired from some callback)
                clients = self.get_clients(as_dict=True)
                client = clients[self.last_mod_cmd["client"]]
            # Callee handles splitting and line-wise formatting and adds status
            # prefix (leading *) to first arg (usually .GetModName())
            client.PutModule("Signal", lines)
            return
        elif where != "PutTest" and self.debug:
            clients = self.get_clients(just_names=True)
            self.logger.debug(f"where: {where}, "
                              f"last_mod_cmd: {self.last_mod_cmd}, "
                              f"clients: {clients}")
        if putters is None:
            putters = (self,)
        lines = "{}".format(lines).splitlines()
        for putter in putters:
            for line in lines:
                getattr(putter, where)(line or " ")

    def expand_string(self, string):
        string = self.ExpandString(string)
        if self.znc_version < (1, 7, 0):
            # Shouldn't be used in callbacks; only in module hooks
            try:
                network = self.GetNetwork().GetName()
            except AttributeError:
                network = "%network%"
            for pat, sub in (("%empty%", ""), ("%network%", network)):
                string = string.replace(pat, sub)
        return string

    def get_clients(self, just_names=False, as_dict=False):
        # Should be mod-type agnostic; GetAllClients call replaces
        #
        #   flatten_set(net.GetClients() for net in networks)
        #
        clients = self.GetUser().GetAllClients()
        if just_names:
            return tuple(c.GetFullName() for c in clients)
        elif as_dict:
            return {c.GetFullName(): c for c in clients}
        return tuple(clients)

    def reckon(self, data):
        """Run conditions checks against normalized hook data

        If multiple conditions exist, they're OR'd together following
        the config's ordering, though "default" aways runs last.
        Non-expressions-based options are collectively AND'd, .e.g.,
        "away_only", "timeout_*", etc. "x_policy" determines the
        global operation for expressions-based options like "source",
        "body", etc.
        """
        # XXX minimally tried, only basic tests, so far
        #
        # The time-based constraints were stolen from ZNC-Push, but they're
        # merely placeholders, for now. <https://wiki.znc.in/Push>
        #
        # NOTE tracebacks for any exceptions raised here immediately follow the
        # caller's ``normalize_onner`` dump in the log, so there's no need for
        # descriptive assertion messages.
        #
        def expressed(path, expr_key, string):
            from .lexpresser import expand_subs, eval_boolish_json
            if expr_key not in self.config.expressions:
                msg = ("{} refers to a nonexistent expression: {!r};"
                       "Disabling condition in loaded config")
                try:
                    cond_options["enabled"] = False
                except Exception:
                    pass
                raise KeyError(msg.format(path, expr_key))
            expr_val = self.config.expressions[expr_key]
            expr = expand_subs(expr_val, self.config.expressions)
            return eval_boolish_json(expr, string)
        #
        def wreck_one(name, cond):  # noqa: E306
            if self.debug:
                reason = data["reckoning"]
                reason.append(f"<{name}")
            #
            # Normal options (filters) ----------------------------------------
            #
            # enabled
            if not cond["enabled"]:
                if self.debug:
                    reason.append("enabled>")
                return REJECT
            # away
            if cond["away_only"] and not data["away"]:
                if self.debug:
                    reason.append("away_only>")
                return REJECT
            # scope
            channel = data["channel"]
            detached = data["detached"]
            if ((channel and (("detached" not in cond["scope"]
                               and detached) or
                              ("attached" not in cond["scope"]
                               and not detached))
                 or (not channel and "query" not in cond["scope"]))):
                if self.debug:
                    reason.append("scope>")
                return REJECT
            # clients
            client_count = data["client_count"]
            if client_count:
                max_clients = cond["max_clients"]  # 0 ~~> +inf
                if max_clients and max_clients < client_count:
                    if self.debug:
                        reason.append("max_clients>")
                    return REJECT
            #
            # Expression-based options ----------------------------------------
            #
            # base operation for aggregating expressions (otherwise FILTER)
            disposition = cond["x_policy"] in ("first", "any", "or")
            if self.debug:
                dism = disposition and "{}!>" or "!{}>"
            # network
            network = data["network"]
            if network:
                path = f"/conditions/{name}/network"
                expr_key = cond["network"]
                if disposition is expressed(path, expr_key, network):
                    if self.debug:
                        reason.append(dism.format("network"))
                    return disposition
            # channel
            channel = data["channel"]
            if channel is not None:
                path = f"/conditions/{name}/channel"
                expr_key = cond["channel"]
                if disposition is expressed(path, expr_key, channel):
                    if self.debug:
                        reason.append(dism.format("channel"))
                    return disposition
            # source
            source = data[cond["x_source"]]
            if source:
                path = f"/conditions/{name}/source"
                expr_key = cond["source"]
                if disposition is expressed(path, expr_key, source):
                    if self.debug:
                        reason.append(dism.format("source"))
                    return disposition
            # body (message body)
            body = data["body"]
            if body:
                path = f"/conditions/{name}/body"
                expr_key = cond["body"]
                if disposition is expressed(path, expr_key, body):
                    if self.debug:
                        reason.append(dism.format("body"))
                    return disposition
            #
            if disposition is FILTER:
                if self.debug:
                    reason.append("&>")  # FILTER
                return APPROVE
            if self.debug:
                reason.append("|>")  # FIRST
        #
        APPROVE = True
        REJECT = FILTER = False
        #
        if self.debug:
            data.setdefault("reckoning", []).clear()
        if not self.config:
            if self.debug:
                data["reckoning"] += ["No config loaded"]
            return False
        #
        for cond_name, cond_options in self.config.conditions.items():
            if wreck_one(cond_name, cond_options):
                data["template"] = cond_options["template"]
                return APPROVE  # <- conditions are OR'd together
        return REJECT

    def route_verdict(self, name, data):
        """Prepare and send outgoing ZNC-to-Signal messages"""
        # NOTE caller (Signal._wrap_onner) handles EModRet values
        from collections import defaultdict
        #
        relevant = self.get_relevant(data)
        #
        def format_message(rel_dict, template):  # noqa: E306
            """Expand vars in ``/templates/*/format``

            Valid expansions::
                context, nick, hostmask, body, network
            """
            # TODO add length truncation; append full body onto deque buffer at
            # _user_targets["backspool"]. User can retrieve (pop) later with:
            # /last <context>; or just use CBuffer to handle this
            #
            msgfmt = template["format"]
            msgfmt_args = defaultdict(str, **rel_dict)
            #
            if "{focus}" in msgfmt:
                msgfmt_args["focus"] = ""
            if (hasattr(self, "_session") and self._session["focus"] and
                    self._session["focus"] == msgfmt_args["context"]):
                from .ootil import unescape_unicode_char
                try:
                    focus = unescape_unicode_char(template["focus_char"])
                except ValueError:
                    self.print_traceback()
                else:
                    msgfmt_args["focus"] = focus
            #
            if "Action" in name:
                msgfmt_args["body"] = " ".join(("*", msgfmt_args["nick"],
                                                msgfmt_args["body"]))
            elif "CTCP" in name:
                msgfmt_args["body"] = msgfmt_args["body"].replace(
                    "ACTION", f"*{msgfmt_args['nick']}", 1
                )
            return msgfmt.format(**msgfmt_args)
        #
        # TODO learn basic ZNC/IRC facts; erase once convinced
        if self.debug:
            params = None
            if "msg" in data:
                # Likely unneeded fallback for target and text. If never used,
                # can disable altogether (not include in data.msg items).
                # XXX ^^^^^^^^^^^^^^^^^^^^^^^^^ what does this mean? Gibberish
                if "text" not in data["msg"]:
                    assert data["msg"]["type"] not in ("Text",
                                                       "Notice",
                                                       "Action")
                params = self.get_first(data, "params")
                if data["msg"]["type"] != "Action" and len(params) > 1:
                    assert relevant["body"] == " ".join(params[1:])
            if relevant.get("channel"):  # else params[0] is target (%nick%)
                # In OnSendToClient, ``channel["name"]`` sometimes contains
                # control chars like 'A\x03\x00 ... \x02' (PART command)
                assert relevant["channel"].startswith("#")
                if params:
                    assert params[0] == relevant["channel"]
                assert relevant["context"] == relevant["channel"]
            #
            if self.config:
                # Default must always run last
                assert list(self.config.conditions).pop() == "default"
                # Insertion ordering honors unsaved modifications
                list(self.manage_config("view")["conditions"]) == \
                    list(self.config.conditions)
        #
        noneso = defaultdict(type(None), relevant)
        verdict = ("DROP", "PUSH")[self.reckon(noneso)]
        if self.debug:
            reason = data["reckoning"] = noneso["reckoning"]
            self.logger.debug(f"Verdict: {verdict}, decision path: {reason}")
        if verdict == "DROP":
            return
        #
        template = self.config.templates[noneso["template"]]
        message = format_message(noneso, template)
        msg = None
        if not template["recipients"]:
            msg = ("Push aborted; reason: /templates/{}/recipients is empty"
                   .format(noneso["template"]))
        if not hasattr(self, "_connection") or self._connection.IsClosed():
            msg = ("Push aborted; reason: no connection to {!r}"
                   .format(self.config.settings.get("host", "null")))
        if msg:
            if self.debug:
                self.logger.debug(msg)
            else:
                # TODO remove this once the /conditions/*/timeout_* options
                # are up and running
                self.put_pretty(msg)
            return
        if len(template["recipients"]) == 1:
            recipients = template["recipients"][0]
        else:
            recipients = template["recipients"]
        #
        def callback(result, message):  # noqa: E306
            if result:
                info = dict(message=message, result=result)
                msg = f"Problem sending message:\n  {info!r}"
            else:
                if len(message) > 52:
                    message = "{}...".format(message[:49])
                msg = "SENT: {!r}".format(message)
            if self.debug:
                self.logger.debug(msg)
            else:
                self.put_pretty(msg)
        #
        cb = self.make_generic_callback(callback, message)
        payload = (message, [], recipients)
        self.do_send("Signal", "sendMessage", cb, payload)

    def get_first(self, data, *keys):
        """Retrieve a normalized data item, looking first in 'msg'
        """
        if "msg" in data:
            first, *rest = keys
            if self.debug:
                assert first.islower()
                assert not any(s.islower() for s in rest)
            cand = data["msg"].get(first)
            if cand is not None:
                return cand
            keys = rest
        for key in keys:
            cand = data.get(key)
            if cand is not None:
                return cand

    def get_relevant(self, data):
        """Narrow/flatten normalized data to zone of interest

        At this point, all data/data.msg values should (mostly) be
        primitives (strings and ints).
        """
        def narrow(lookups):
            common = {}
            from collections import MutableMapping
            for key, cands in lookups.items():
                wanted = self.get_first(data, *cands)
                if not wanted:
                    continue
                if isinstance(wanted, MutableMapping):
                    _wanted = dict(wanted)
                    if "name" in wanted:
                        common[key] = _wanted.pop("name")
                    if key in wanted:
                        common[key] = _wanted.pop(key)
                    if _wanted != wanted:
                        common.update(_wanted)
                else:
                    common[key] = wanted
            return common
        #
        # Common lookups
        rosetta = {
            # shallow
            "body": ("text", "sMessage"),
            # deep
            "network": ("network", "Network"),
            "channel": ("channel", "Channel", "sChannel", "Chan", "sChan"),
            "nick": ("nick", "Nick"),
        }
        narrowed = narrow(rosetta)
        narrowed["context"] = narrowed.get("channel") or narrowed["nick"]
        return narrowed

    def screen_onner(self, name, args_dict):
        """ Dedupe and filter out unwanted hooks

        Always ignore PING/PONG-related traffic (don't even issue
        deprecation warnings)
        """
        #
        if any(s in name for s in ("Raw", "SendTo", "BufferPlay")):
            if self.log_raw is False:
                return False
            #
            if "msg" in args_dict:
                from . import cmess_helpers
                cmt = getattr(cmess_helpers, "types", None)
                if self.debug:
                    assert self.znc_version >= (1, 7, 0)
                cmtype = cmt(args_dict["msg"].GetType())
                if cmtype in (cmt.Ping, cmt.Pong):
                    return False
            elif "sLine" in args_dict:
                if self.debug and self.znc_version >= (1, 7, 0):
                    assert name in self.deprecated_hooks
                # XXX false positives: should probably leverage ":" to narrow
                line = str(args_dict["sLine"])
                if "BufferPlay" not in name:
                    if any(s in line for s in ("PING", "PONG")):
                        return False
                elif self.debug:
                    assert not any(s in line for s in ("PING", "PONG"))
            else:
                self.logger.info(f"Unexpected hook {name!r}: {args_dict!r}")
        #
        if (self.log_old_hooks is False
                and self.deprecated_hooks  # 1.7+
                and name in self.deprecated_hooks):
            raise PendingDeprecationWarning
        return True

    def normalize_onner(self, name, args_dict):
        """Preprocess hook arguments

        Ignore hooks describing client-server business. Extract relevant
        info from others, and save them in a normalized fashion for
        later use.
        """
        from . import cmess_helpers as cm_util
        from collections.abc import Sized  # has __len__
        out_dict = dict(args_dict)
        #
        # FIXME name should be 'unempty'
        def upnempty(**kwargs):  # noqa: E306
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
                return upnempty(name=str(v.GetName()) or None,
                                away=v.IsIRCAway(),
                                client_count=len(v.GetClients()))
            elif isinstance(v, znc.CChan):
                return upnempty(name=str(v.GetName()) or None,
                                detached=v.IsDetached())
            elif isinstance(v, znc.CNick):
                # TODO see src to find out how nickmask differs from hostmask
                return upnempty(nick=v.GetNick(),
                                ident=v.GetIdent(),
                                host=v.GetHost(),
                                perms=v.GetPermStr(),
                                nickmask=v.GetNickMask(),
                                hostmask=v.GetHostMask())
            # Covers CPartMessage, CTextMessage
            elif hasattr(znc, "CMessage") and isinstance(v, znc.CMessage):
                return upnempty(type=cm_util.types(v.GetType()).name,
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
                self.logger.debug(f"Unhandled arg: {k!r}: {v!r}")
        #
        for k, v in args_dict.items():
            try:
                out_dict[k] = extract(v)
            except Exception:
                self.print_traceback()
        #
        # Needed for common lookups (reckoning and expanding msg fmt vars)
        if ((self.debug or name in self.active_hooks)
                and not self.get_first(out_dict, "network", "Network")):
            net = self.GetNetwork()
            if net:
                out_dict["network"] = {"name": net.GetName(),
                                       "away": net.IsIRCAway(),
                                       "client_count": len(net.GetClients())}
        #
        # Needed for config conditions involving client activity/actions. See
        # also: note re CMessage.GetTime() above.
        from datetime import datetime
        justnow = datetime.now(self.tz)
        out_dict["time"] = justnow.isoformat()
        time_hooks = {"OnUserMsg", "OnUserTextMessage",  # rhs are 1.7+
                      "OnUserAction", "OnUserActionMessage"}
        if name in time_hooks:
            target = self.get_first(out_dict, "target", "sTarget")
            if target:
                if not hasattr(self, "_user_targets"):
                    self._user_targets = {}
                self._user_targets[target] = dict(last_active=justnow,
                                                  last_reply=justnow)
        idle_hooks = {"OnUserJoin", "OnUserJoinMessage",  # rhs are 1.7+
                      "OnUserPart", "OnUserPartMessage",
                      "OnUserTopic", "OnUserTopicMessage",
                      "OnUserTopicRequest"}
        if name in time_hooks | idle_hooks:
            self._idle = justnow
        #
        return out_dict

    def _wrap_onner(self, onner):
        """A surrogate for CModule 'On' hooks"""
        #
        def handle_onner(*args, **kwargs):
            from inspect import signature
            sig = signature(onner)
            bound = sig.bind(*args, **kwargs)
            name = onner.__name__
            relevant = None
            try:
                relevant = self.screen_onner(name, bound.arguments)
            except PendingDeprecationWarning:
                if self.debug and self.log_raw is True:
                    self.logger.debug("Skipping deprecated hook {!r}"
                                      .format(name))
            except Exception:
                self.print_traceback()
            if not relevant:
                return znc.CONTINUE
            #
            self._hook_data[name] = normalized = None
            try:
                normalized = self.normalize_onner(name, bound.arguments)
            except Exception:
                self.print_traceback()
                return znc.CONTINUE
            if self.debug:
                from .ootil import OrderedPrettyPrinter as OrdPP
                pretty = OrdPP().pformat(normalized)
                self.logger.debug(f"{name}{sig}\n{pretty}")
            self._hook_data[name] = normalized
            rv = znc.CONTINUE
            try:
                if name in self.active_hooks:
                    self.route_verdict(name, normalized)  # void
                else:
                    rv = onner(*args, **kwargs)
            except Exception:  # most likely debug assertions
                self.print_traceback()
            finally:
                if not self.debug:
                    del self._hook_data[name]
                return rv
        #
        # NOTE both ``__dict__``s are empty, and the various introspection
        # attrs aren't used (even by the log formatter). And seems the magic
        # swig stuff only applies to passed-in objects.
        from functools import update_wrapper
        return update_wrapper(handle_onner, onner)  # <- useless, for now

    def parse_command_args(self, command, args):
        """Parse args for ZNC commands *not* DBus calls

        Raises ``KeyError`` if ``self.approx`` doesn't contain
        ``command``
        """
        from io import StringIO
        from contextlib import redirect_stderr, redirect_stdout
        with StringIO() as floe, StringIO() as floo:
            with redirect_stderr(floe), redirect_stdout(floo):
                try:
                    namespace = self.approx[command].parse_args(args)
                except SystemExit as e:
                    # Exit status 0 means --help|-h was passed, else error
                    self.put_pretty(floo.getvalue())
                    if e.code:
                        self.logger.info("Problem parsing commandline")
                        self.put_pretty(floe.getvalue())
                    namespace = None
                except Exception:
                    self.print_traceback()
                    raise
        return namespace

    def refresh_help_defaults(self):
        if not self.config or not self.approx:
            return
        # cmd_connect
        conns = self.approx._wrights.connect.kwargs
        setts = self.config.settings.bake(peel=True)
        kwargs = {}
        for option in ("host", "port"):
            value = setts.get(option)
            if value and conns.get(option) != value:
                kwargs[option] = value
        if kwargs:
            self.approx._wrights.connect(**kwargs)

    def OnClientDisconnect(self):
        """Stop tracking the current client

        This means ``put_pretty()`` will no longer target it.

        Note: this is defined as an 'explicit' hook because it's not
        messaging-service related or directly module related. Also, it's
        used by ``test_hooks_mro()`` to prove a point.
        """
        lmc = self.last_mod_cmd
        client_name = str(self.GetClient().GetFullName())
        if self.debug:
            # These include the trailing /<network> portion
            all_clients = self.get_clients(True)
            self.logger.debug(f"attached clients: {all_clients}")
            assert client_name not in all_clients
        network_name = str(self.GetNetwork().GetName())
        if (lmc["network"] == network_name and
                lmc["client"].startswith(client_name)):
            if self.debug:
                # Trailing "/<network>" portion is dropped from GetClient()
                assert "/".join((client_name, network_name)) == lmc["client"]
            self.last_mod_cmd = None
        return znc.CONTINUE

    def _OnLoad(self, argstr, message):
        # Treat module args like environment variables
        import os
        # TODO use znc.VersionMajor or CZNC.GetVersion() instead
        version_string = znc.CZNC_GetVersion().partition("-")[0]
        self.znc_version = tuple(map(int, version_string.split(".")))
        #
        if not self.GetUser().IsAdmin():
            message.s = "You must be an admin to use this module"
            return False
        #
        self.networks = self.GetUser().GetNetworks()
        #
        self.env = dict(os.environ)
        # Claim environment-variable namespace -> "SIGNALMOD_"
        for env_key, env_val in os.environ.items():
            if env_key.lower().startswith("signalmod_"):
                trunc_key = env_key.upper().replace("SIGNALMOD_", "")
                self.env[trunc_key] = env_val  # clobber collisions
        if str(argstr):
            import shlex
            self.env.update((a.split("=") for a in shlex.split(str(argstr))))
        # Leading underscore means undocumented/temporary dev/debug args
        from configparser import RawConfigParser
        bools = RawConfigParser.BOOLEAN_STATES
        self.debug = bools.get(self.env.get("DEBUG", "0").lower(), False)
        self.log_raw = bools.get(self.env.get("_RAW", "0").lower(), False)
        self.log_old_hooks = bools.get(self.env.get("_OLD_HOOKS",
                                                    "0").lower(), False)
        #
        self.data_dir = self.env.get("DATADIR") or self.GetSavePath()
        #
        msg = []
        msg.append(f"Args: {self.args_help_text}")
        #
        if self.debug:
            assert os.path.exists(self.data_dir)
            msg[-1] += "; or pass as env vars prefixed with SIGNALMOD_"
            # TODO update jeepney's ``get_logger`` (tcp_fork:debug branch) with
            # LOGFILE, if provided.
            logfile = self.env.get("LOGFILE")
            if not logfile:
                logfile = os.path.join(self.data_dir, "signal.log")
                msg.append("\x02Warning: DEBUG mode is useless without LOGFILE"
                           "; setting to %r, but will not rotate/truncate; "
                           "Consider a pty instead\x02" % logfile)
                self.env["LOGFILE"] = logfile
            try:
                get_logger.LOGFILE = open(logfile, "w")
            except PermissionError:
                # Perhaps better to simply die here instead.
                msg.append(f"\x02Warning: unable to write to {logfile}\x02")
                if not znc.CDebug_Debug():
                    msg.append("\x02Run ZNC in debug mode for more info\x02")
                self.print_traceback(where=os.sys.stderr)
                get_logger.LOGFILE = None  # effectively neuters
                if "LOGFILE" in self.env:
                    del self.env["LOGFILE"]
            else:
                # TODO find way to tell if isatty without/before opening
                try:
                    if not get_logger.LOGFILE.isatty():
                        if os.sys.platform.startswith("linux"):
                            from fcntl import fcntl, F_GETFL, F_SETFL
                            # Some may be ignored: e.g., O_LARGEFILE
                            status_flags = fcntl(get_logger.LOGFILE, F_GETFL)
                            fcntl(get_logger.LOGFILE, F_SETFL,
                                  status_flags | os.O_APPEND)
                            get_logger.LOGFILE.mode = "a"
                        # Seems to worsen missing-records issue (see below)
                        else:
                            get_logger.LOGFILE.close()
                            get_logger.LOGFILE = open(logfile, "a")
                except Exception:
                    self.print_traceback(where=os.sys.stderr)
                    raise
                import atexit
                atexit.register(lambda flo: flo.close(), get_logger.LOGFILE)
        self.logger = get_logger(self.__class__.__name__)
        # The first few writes to LOGFILE are blackholed when reloading (unless
        # modpython is also reloaded). This seems to force its hand (at least
        # on Linux w. ZNC 1.6.6). Problem only affects writes to "disk files"
        # (also tmpfs), which already suffer fits and starts.
        # TODO See if API offers delegating all file io through some central
        # selector/manager. A cursory glance at source files suggests no.
        if os.sys.platform.startswith("linux"):
            poll = None
            fds = []
            for handler in self.logger.handlers:
                try:
                    handler.flush()
                except (ValueError, OSError):
                    # Stale handlers may linger if ZNC recently crashed
                    self.print_traceback(where=os.sys.stderr)
                    self.logger.removeHandler(handler)
                else:
                    if hasattr(handler, "stream"):
                        if poll is None:
                            import select
                            poll = select.poll()
                        fd = handler.stream.fileno()
                        fds.append(fd)
                        poll.register(fd)
            if poll is not None and fds:
                while fds:
                    for tup in poll.poll(0):
                        fd, event = tup
                        if select.POLLOUT & event:
                            fds.remove(fd)
        self.logger.setLevel("DEBUG" if self.debug else "WARNING")
        # This and the logger call in OnShutdown are the only unguarded ones
        self.logger.debug("loaded, logging with: %r" % self.logger)
        #
        # Enable debugging on config objects
        if self.debug:
            from .dictchainy import BaseConfigDict
            BaseConfigDict.debug = True
        #
        from .cmdopts import initialize_all, AllParsed
        initialize_all(self.debug, update=dict(data_dir=self.data_dir))
        self.approx = AllParsed(debug=self.debug)
        #
        self.mod_commands = {c: getattr(self, c) for c in self.approx(True)}
        msg.append("Available commands: {}".format(", ".join(self.approx)))
        msg.append("Type '<command> -h' or 'help --usage' for more info")
        #
        if self.znc_version >= (1, 7, 0):
            on_hooks = {a for a in dir(znc.Module) if a.startswith("On")}
            depcands = {o.replace("TextMessage", "Msg")
                        .replace("PlayMessage", "PlayLine")
                        .replace("Message", "") for
                        o in on_hooks if o.endswith("Message")}
            self.deprecated_hooks = on_hooks & depcands
        #
        # TODO warn if locale is not en_US/UTF-8 or platform not Linux
        from .ootil import get_tz
        self.tz = get_tz()
        #
        self._hook_data = {}
        if self.debug:
            msg.extend(["Config auto-loading is disabled in debug mode",
                        "Type 'select' to load manually"])
        else:
            try:
                self.manage_config("load")
            except Exception as exc:
                msg.append(f"\x02Warning\x02: problem loading config; {exc!r}")
            else:
                self.refresh_help_defaults()
                # TODO make this work
                if self.config.settings["auto_connect"] is True:
                    msg.append("\x02Warning\x02: '/settings/auto_connect' "
                               "has not been implemented")
        #
        message.s = ". ".join(msg)
        return True  # apparently an outlier; others return EModRet

    def _OnShutdown(self):
        try:
            if self.config:
                import os
                version = self.config.settings["config_version"]
                path = os.path.join(self.data_dir, f"config.{version}.ini.bak")
                self.manage_config("export", force=True, path=path)
            else:
                self.manage_config("export", force=True, as_json=True)
        except Exception:
            if self.debug:
                self.print_traceback()
        try:
            self.logger.debug("%r shutting down" % self.GetModName())
        except AttributeError:
            return znc.CONTINUE
        import logging
        logging.shutdown()
        for handler in self.logger.handlers:
            self.logger.removeHandler(handler)
        import atexit
        try:
            atexit._run_exitfuncs()
        except Exception:
            pass
        if hasattr(get_logger, "LOGFILE"):
            del get_logger.LOGFILE
        return znc.CONTINUE

    def _OnModCommand(self, commandline):
        """Call arg parser and delegate to appropriate method

        ``cmd_`` namespace convention lifted from
        <https://github.com/MuffinMedic/znc-aka>
        """
        import shlex
        argv = shlex.split(str(commandline))
        from .cmdopts import RAWSEP
        if RAWSEP in argv:
            argv, *rest = str(commandline).partition(RAWSEP)
            argv = shlex.split(argv)
            argv.append("".join(rest))
        #
        command, *args = argv
        command = self.approx.decmd(command.lower())  # these alone don't check
        mod_name = self.approx.encmd(command)         # membership; see tests
        if mod_name not in self.mod_commands:
            msg = "Invalid command"
            if command.startswith("debug_") and not self.debug:
                msg += "; for debug-related commands, pass DEBUG=1"
            self.put_pretty(msg)
            return znc.CONTINUE
        #
        if (command == "debug_args" and
                args and args[0] not in ("--help", "-h")):
            args = ["--"] + args
        namespace = self.parse_command_args(mod_name, args)
        if namespace is None:
            return znc.CONTINUE
        #
        # When not hooking, ``GetClient().GetFullName()`` should throw, which
        # is OK. TODO ensure incoming instructions call cmd_* methods directly
        #
        self.last_mod_cmd = {"command": command,
                             "network": self.expand_string("%network%"),
                             "client": self.GetClient().GetFullName()}
        # TODO once convinced, delete this and similar
        if self.debug:
            assert self.last_mod_cmd["network"] not in ("", "%network%")
        #
        try:
            self.mod_commands[mod_name](**vars(namespace))  # void
        except Exception:
            self.print_traceback()
            # Raising here makes znc print something about the command not
            # being registered
        return znc.CONTINUE

    def handle_incoming(self, incoming: "incoming_NT"):
        """Interpret and respond to incoming instructions

        Right now, this is mainly just a placeholder. Everything is
        experimental/volatile.
        """
        # TODO find out what CClient::UserCommand does
        #
        # XXX should freeze this func till it has tests; already too unruly
        msg = {}
        if (self.config and incoming.source not in
                self.config.settings["authorized"]):
            msg["warning"] = ("{} not listed in /settings/authorized"
                              .format(incoming.source))
            try:
                raise UserWarning(msg["warning"])
            except Exception:
                self.print_traceback()
            if not self.debug:
                return
        if self.debug:
            assert self.config
            from datetime import datetime
            dto = datetime.fromtimestamp(incoming.timestamp/1000, self.tz)
            msg["incoming"] = dict(
                incoming._asdict(),
                timestamp=dto.isoformat(timespec="milliseconds")
            )
            from .ootil import OrderedPrettyPrinter as OrdPP
            self.logger.debug("\n{}".format(OrdPP(width=60).pformat(msg)))
            if "warning" in msg:
                return
        #
        retort = []
        if not hasattr(self, "_session"):
            self._session = {"network": None,
                             "focus": None}
        session = self._session
        request = incoming.message
        raw_out = None
        #
        connected = {n.GetName(): n for n in self.networks if
                     n.IsIRCConnected()}
        net_advise = False
        if not connected:
            retort.append("Not connected to any networks")
        elif request.startswith("/net"):
            cand = request.replace("/net", "", 1).strip()
            if cand in connected:
                session["network"] = connected[cand]
                retort.append(f"Network set to: {cand!r}")
            else:
                net_advise = True
        elif session["network"] is None:
            net_advise = True
        if net_advise:
            if len(connected) == 1:
                __, session["network"] = connected.popitem()
            else:
                joined_nets = ", ".join(connected)
                retort.extend(["Multiple IRC networks available:",
                               f" {joined_nets}",
                               "Select one with: /net <network>"])
            if session["network"]:
                netname = session['network'].GetName()
                retort.append(f"Current network is {netname!r}")
        #
        if request.startswith("/focus"):
            focus = request.replace("/focus", "", 1).strip()
            if not focus:
                if session["focus"] is not None:
                    retort.append(f"Current focus is {session['focus']!r}")
                else:
                    retort.append("Focus not set")
            else:
                if (focus.startswith("#") and session["network"]
                        and focus not in [c.GetName() for c in
                                          session["network"].GetChans()]):
                    chwarn = "Warning: channel {!r} not joined in network {!r}"
                    retort.append(chwarn.format(focus,
                                                session["network"].GetName()))
                session["focus"] = focus
                retort.append(f"Focus set to {session['focus']!r}")
        elif request.startswith("/msg"):
            raw_out = request.replace("/msg", "", 1).strip()
            try:
                target, body = raw_out.split(None, 1)
            except ValueError:
                retort.append("Unable to determine /msg <target>")
                raw_out = None
            else:
                raw_out = "PRIVMSG {} :{}".format(target, body)
        elif request.startswith("/help"):
            retort += ["Available commands:",
                       " /net, /focus, /msg"]
        elif not request.startswith("/") and session["focus"] is not None:
            raw_out = "PRIVMSG {} :{}".format(session["focus"], request)
        elif not retort:
            if request.split()[0] in ("/tail", "/snooze"):
                retort.append("Sorry, coming soon")
            else:
                retort.append(f"Unable to interpret {request!r}")
        #
        if retort:
            cb = self.make_generic_callback(lambda r: None)
            payload = ("\n".join(retort), [], incoming.source)
            self.do_send("Signal", "sendMessage", cb, payload)
            return
        if raw_out is not None:
            source = self.expand_string("%nick%")
            # TODO add lines to ZNC buffers for context, if possible
            self.put_pretty(f":{source} {raw_out}", where="PutClient")
            session["network"].PutIRC(raw_out)
        elif self.debug:
            self.logger.debug("Fell through; request: "
                              f"{request}, session: {session}")

    def make_generic_callback(self, real_callback, *args, **kwargs):
        "Make a callback for normal D-Bus methods (not signals)"
        def generic_callback(fut):
            try:
                result = fut.result()
                if result != ():
                    result = result[0]
                real_callback(result, *args, **kwargs)
            except Exception:
                self.print_traceback()  # <- ``fut.exception``, if set

        return generic_callback

    def do_subscribe(self, action=None):
        """Not for general ("lowercase" signal) DBus subscriptions;
        this is hard-coded for ``Signal.*.MessageReceived`` only.

        Unsure whether it's necessary to call ``RemoveMatch`` before
        dropping the main connection. Seems subs only persist after
        an abnormal termination, according to ``GetAllMatchRules``.
        ::
              dict entry(
                 string ":1.0"
                 array [        # <- normally a couple empty arrays
                 ]
              )

        # Signature as returned by Introspectable

        <signal name="MessageReceived">
            <arg type="x"  direction="out" /> <!-- integer      -->
            <arg type="s"  direction="out" /> <!-- string       -->
            <arg type="ay" direction="out" /> <!-- bytes array  -->
            <arg type="s"  direction="out" /> <!-- string       -->
            <arg type="as" direction="out" /> <!-- string array -->
        </signal>

        `Source code`__
        .. __: https://github.com/AsamK/signal-cli
           /blob/925d8db468ce39c0e2b164cc1ab464ea2edf4e86
           /src/main/java/org/asamk/Signal.java#L32
        """
        try:
            assert self._connection.unique_name is not None, "Not connected"
        except AttributeError as exc:
            raise AssertionError from exc
        # Caller must ensure connection is actually up (this doesn't check)
        from jeepney.integrate.asyncio import Proxy
        from jeepney.bus_messages import MatchRule
        from .jeepers import SignalMG, incoming_NT
        proxy = Proxy(SignalMG(), self._connection)
        match_rule = MatchRule(type="signal",
                               sender=proxy._msggen.bus_name,
                               interface=proxy._msggen.interface,
                               member="MessageReceived",
                               path=proxy._msggen.object_path)
        #
        def subscription_callback(msg_body):  # noqa E306
            assert isinstance(msg_body, tuple)
            try:
                self.handle_incoming(incoming_NT(*msg_body))
            except Exception:
                self.print_traceback()
        #
        def request_callback(result):  # noqa E306
            if result != ():
                msg = ("Problem with subscription request; "
                       f"action: {action!r}, result: {result!r}")
                try:
                    raise RuntimeError(msg)
                except RuntimeError:
                    self.print_traceback()
                return None
            if (hasattr(self, "_connection")
                    and not self._connection.IsClosed()):
                self._connection._subscribed = action is None
            self.put_pretty("Subscription successfully cancelled" if action
                            else "Subscription request successful")
            if action == "disconnect":
                return self.cmd_disconnect()
        #
        daemon_cb = self.make_generic_callback(request_callback)
        self._connection.router.subscribe_signal(
            callback=subscription_callback,
            path=proxy._msggen.object_path,
            interface=proxy._msggen.interface,
            member="MessageReceived"
        )
        if action in ("remove", "disconnect"):  # <- likely useless
            method = "RemoveMatch"
        else:
            method = "AddMatch"
        return self.do_send("DBus", method, daemon_cb, args=[match_rule])

    def do_send(self, node, method, callback, args=None):
        r"""An extremely limited dbus-send_(1) analog

        <node>     a key from the address book below: str
        <method>   leaf member (no interface components): str
        <callback> callable(fut: asyncio.Future) -> void
        [<args>]   iterable

        In practice, the address book is really only needed by
        ``Introspectable``. Unless the primary DBus system config grants
        all permissions and anon auth to TCP supplicants, calls to
        ``Monitoring`` and ``Stats`` nodes will likely be denied,
        generating: ``org.freedesktop.DBus.Error.AccessDenied``.
        Unfortunately, this means messing with it by hand from the host
        machine::

            ># docker exec signal.ops.example.com \
                    dbus-send --system --print-reply \
                    --type=method_call \
                    --dest=org.freedesktop.DBus \
                    /org/freedesktop/DBus \
                    org.freedesktop.DBus.Debug.Stats.GetAllMatchRules

        .. _dbus-send: https://dbus.freedesktop.org/doc/dbus-send.1.html
        """
        from jeepney.integrate.asyncio import Proxy
        # TODO make this a namedtuple in jeepers mod so other funcs can use
        addresses = {
            "Signal": ("org.asamk.Signal", "/org/asamk/Signal"),
            "DBus": ('org.freedesktop.DBus', '/org/freedesktop/DBus'),
            "Monitoring": ('org.freedesktop.DBus', '/org/freedesktop/DBus'),
            "Stats": ('org.freedesktop.DBus', '/org/freedesktop/DBus'),
        }
        args = args or ()
        # Stands apart because called on other nodes
        if method == "Introspect":
            from jeepney.wrappers import Introspectable as IntrospectableMG
            dest, path = addresses[node]
            proxy = Proxy(IntrospectableMG(object_path=path, bus_name=dest),
                          self._connection)
        elif node in addresses:
            if node != "Signal":
                import jeepney.bus_messages as bm
                MG = getattr(bm, node)
                proxy = Proxy(MG(), self._connection)
            else:
                from .jeepers import SignalMG
                proxy = Proxy(SignalMG(), self._connection)
        else:
            raise ValueError("Unable to determine destination")
        try:
            getattr(proxy, method)(*args).add_done_callback(callback)
        except AttributeError:
            raise ValueError("Method %r not found" % method)

    def manage_config(self, action=None, peel=False, force=False,
                      as_json=False, path=None):
        """ Save, load, import, export, or return a user config

            peel
                Return config diffed against default (vs. merged with default)

            actions
            ~~~~~~~
            save
                Cache config to ``Module.nv`` i.e. "non-volatile" .registry
                file on disk
            export
                Distinct from save because it writes to a standard format and
                is easily accessible from a known location controlled by this
                module
            reload
                Previously known as 'import' (for symantic symmetry) but
                changed to align with cmd_update option

            Note: 'save'
        """
        if action is None:
            return
        elif action == "view":
            if self.config is None:
                raise ValueError("No config loaded")
            flattened = {}
            for cat, bcd in self.config._asdict().items():
                flattened[cat] = bcd.peel(peel=peel)
            return flattened
        #
        nvid = self.expand_string("%user%")
        if not hasattr(self, "_nv_undo_stack"):
            from collections import deque
            self._nv_undo_stack = deque()
        #
        import os
        from .configgers import default_config
        defver = default_config.settings["config_version"]
        #
        def get_path(path):  # noqa: E306
            ext = "json" if as_json else "ini"
            if path and not force:
                path = os.path.expandvars(os.path.expanduser(path))
                path = os.path.abspath(path)
                # All dirs must exist; "export" creates files if absent
                if os.path.isdir(path):
                    path = os.path.join(path, f"config.{ext}")
                elif not os.path.exists(path):
                    parpath = os.path.dirname(path)
                    if not os.path.isdir(parpath):
                        path = None
                    elif not any(path.endswith(e) for e in (".json", ".ini")):
                        path = os.path.join(parpath, f"config.{ext}")
            if not path:
                path = os.path.join(self.data_dir, f"config.{ext}")
            return path
        #
        # save/export
        def ensure_defver(peeled):  # noqa: E306
            ps = peeled.setdefault("settings", {})
            ps.setdefault("config_version", defver)
        #
        # load/reload
        def handle_outdated(curver):  # noqa: E306
            dirname = os.path.dirname(path or get_path(path))
            basename = "config.{}.new".format("json" if as_json else "ini")
            dest = os.path.join(dirname, basename)
            orig, self.config = self.config, construct_config({})
            # OnHooks will be skipped during this call
            self.manage_config("export", force=True, as_json=as_json,
                               path=dest)
            self.config = orig
            msg = " ".join("""
                Your config appears to be outdated. Please update it
                using the latest defaults, which can be found here: {}.
                Make sure to include the new version number. Or, use
                --force to bypass this warning.
            """.split()).format(dest)
            raise UserWarning(msg)
        #
        if action == "load":
            from .configgers import load_config, construct_config
            stringified = self.nv.get(nvid)
            peeled = load_config(stringified) if stringified else {}
            # Could just view/peel, but this should be the only redundant item
            curver = peeled.get("settings", {}).get("config_version")
            if peeled:
                if not curver:
                    raise KeyError("Required item /settings/config_version "
                                   f"missing from nv[{nvid}]")
                elif curver == defver:
                    del peeled["settings"]["config_version"]
                elif not force:
                    handle_outdated(curver)
            self.config = construct_config(peeled)
            return
        elif action == "save":
            if not self.config.settings["host"] and not force:
                msg = ("Warning: not caching config because "
                       "'/settings/host' is empty; use --force to override")
                raise UserWarning(msg)
            peeled = self.manage_config(action="view", peel=True)
            # Must track version because module may be updated in the interim
            ensure_defver(peeled)
            from .ootil import restring
            if nvid in self.nv:
                MAX_UNDOS = 5
                if len(self._nv_undo_stack) == MAX_UNDOS:
                    del self.nv[self._nv_undo_stack.pop()]
                from datetime import datetime
                bakkey = f"{nvid}.{datetime.now().timestamp()}"
                self.nv[bakkey] = self.nv[nvid]
                self._nv_undo_stack.appendleft(bakkey)
            self.nv[nvid] = restring(peeled)
            return
        elif action == "undo":
            # TODO write tests for this, add to cmd_update
            raise RuntimeError("TODO: need tests for this")
            try:
                lastkey = self._nv_undo_stack.popleft()
            except IndexError:
                raise UserWarning("Nothing to undo")
            self.nv[nvid] = self.nv[lastkey]  # TODO see if nv supports pop
            del self.nv[lastkey]
            return self.manage_config("load")
        elif action not in ("reload", "export"):
            raise ValueError("Unrecognized action")
        #
        path = get_path(path)
        #
        def validate(peeled, skip_dropped=False):  # noqa: E306
            from .configgers import validate_config
            warn, info = validate_config(peeled)
            msg = []
            if skip_dropped:
                info = [l for l in info if "dropped" not in l]
            if info:
                msg += [f"\x02FYI:\x02\n"] + info
            if warn:
                msg += [f"\x02Potential problems:\x02\n"] + warn
            if msg:
                self.put_pretty("\n".join(msg))
            return False if warn else True
        #
        if action == "reload":
            if not os.path.exists(path):
                raise FileNotFoundError(f"No config found at {path}")
            from .configgers import load_config, construct_config
            loaded = load_config(path)
            if not force:
                curver = loaded.get("settings", {}).get("config_version")
                if curver:
                    if curver == defver:
                        del loaded["settings"]["config_version"]
                    elif not force:
                        handle_outdated(curver)
                elif as_json:
                    msg = ("Warning: 'config_version' absent from config; "
                           "use --force to try loading anyway")
                    raise UserWarning(msg)
                if not validate(loaded, as_json):
                    return
            self.config = construct_config(loaded)
            return self.manage_config("save")
        elif action == "export":
            try:
                peeled = self.manage_config("view", peel=True)
            except Exception:
                if not force:
                    raise
                else:
                    # "Emergency" backup called by OnShutdown(); must peel,
                    # unfortunately, since construct_config likely just failed
                    as_json = peel = True
                    strung = self.nv[nvid]
                    import json
                    peeled = json.loads(strung)
                    version = peeled["settings"]["config_version"]
                    path = os.path.dirname(path)
                    path = os.path.join(path, f"config.{version}.json.bak")
            if not force:
                if not peeled:
                    msg = ("Warning: cached config is empty; "
                           "use --force to export default config")
                    raise UserWarning(msg)
                if not validate(peeled):
                    return
            with open(path, "w") as flow:
                if as_json:
                    # No need to support "complete" (redundant) version
                    if not peel:
                        spread = self.config.conditions.spread
                        payload = self.manage_config("view", peel=spread)
                    else:
                        payload = peeled
                    ensure_defver(payload)
                    import json
                    json.dump(payload, flow, indent=2)
                else:
                    from Signal.iniquitous import gen_ini
                    formatted = gen_ini(self.config)
                    flow.write(formatted)

    def cmd_select(self, path=None, depth=2):
        if self.config is None:
            self.manage_config("load")
            self.refresh_help_defaults()
        config = self.manage_config("view")
        from .configgers import reaccess
        self.last_config_selector, selector, out, __ = reaccess(
            self.last_config_selector, path, config
        )
        if len(selector.parts) <= 2:
            cat = selector.parts[-1]
            if cat == "/" or hasattr(getattr(self.config, cat), "spread"):
                spread = self.config.conditions.spread
                out = self.manage_config("view", peel=spread)
                out = out.get(cat, out)
        depth = depth or None
        if path is None:
            depth = 1 if depth == 2 else depth
        from .ootil import OrderedPrettyPrinter as OrdPP
        formatted = OrdPP(width=60, depth=depth).pformat(out)
        if path is None:
            if len(str(selector).split()) > 1:
                reminder = f"{str(selector)!r} =>"
            else:
                reminder = f"{selector} =>"
            if len(reminder) > 30 and (formatted.count("\n") or
                                       len(formatted) > 30):
                formatted = "\n  ".join((reminder, *formatted.splitlines()))
            else:
                indent = " " * (len(reminder) + 1)
                first, *lines = formatted.splitlines()
                formatted = "\n".join((f"{reminder} {first}",
                                       *(f"{indent}{l}" for l in lines)))
        self.put_pretty(formatted)

    def cmd_update(self, path=None, value=None, remove=False, as_json=False,
                   reload=False, rename=False, force=False, export=False,
                   replacement=None, arrange=False):
        if reload:
            self.manage_config("reload", force=force, path=path)
            self.refresh_help_defaults()
            return self.cmd_select("/", depth=0)
        if export:
            self.manage_config("save", force=force)
            return self.manage_config("export", force=force, path=path)
        if self.config is None:
            self.manage_config("load")
        if remove is True:
            if not replacement and value is not None:
                if path is None:
                    path = value
                else:
                    from pathlib import PurePosixPath
                    path = PurePosixPath(path, value)
            value = None
        elif value is None:
            value, path = path, None
        from .configgers import reaccess, update_config_dict
        # NOTE ``pardir`` is misleading; only apt when ``wants_key=True``
        pardir, selector, obj, key = reaccess(
            self.last_config_selector, path, self.config._asdict(),
            wants_key=(not rename)
        )
        msg = None
        if arrange:
            if path is None:
                rename = True
            else:
                if not selector.match("/conditions/*"):
                    msg = "Only /conditions members are moveable"
                elif self.debug:
                    assert isinstance(obj, type(self.config.conditions))
                    assert not (replacement and value)
                old_selector = None
                if not replacement:
                    value = selector.__class__(value).name
                else:
                    old_selector = replacement[0]
                    if value is None:
                        value = key  # no orig 'value', path was numeric
                        key = old_selector.name
                if value.lstrip("-").isdecimal():
                    value = int(value)
                msg_src = None
                if selector.name == "default":
                    msg_src = old_selector or selector
                elif value == "default":
                    msg_src = selector
                elif old_selector and old_selector.name == "default":
                    msg_src = old_selector
                if msg is None and msg_src:
                    if isinstance(value, int):
                        msg = f"Problem shifting {selector} by {value:+}:"
                    else:
                        msg = f"Problem swapping {msg_src} and {value!r}:"
                replacement = None
                remove = False
        #
        if rename:
            # Call again as if deleting node we're actually assigning to
            if path is None:
                self.last_config_selector = selector.parent
            return self.cmd_update(path=value, value=None, rename=False,
                                   remove=True, replacement=(selector, obj),
                                   arrange=arrange)
        elif replacement is not None:
            old_key, new_value = replacement
            try:
                # ``obj`` is parent container of caller's selector target
                obj[key] = new_value
            except Exception as exc:
                msg = f"Problem moving item to {selector}:"
                replacement = exc
            else:
                key = old_key.name
                rename = True
                replacement = None
        if pardir.name == "":
            self.parse_command_args("cmd_update", ("--help",))
            return None
        if not arrange and value is None:
            msg = msg or f"Problem deleting {selector}:"
        elif not msg:
            msg = f"Problem setting {selector} to {value!r}:"
        try:
            if replacement:
                raise replacement
            if arrange:
                result = obj.move_modifiable(key, value, True)
            else:
                result = update_config_dict(obj, key, value, as_json)
        except Exception as exc:
            if isinstance(obj, BaseException):
                if (self.debug and "does not support item assignment" not
                        in exc.args[0]):
                    self.print_traceback()
                exc.args = ("{}: {}"
                            .format(obj.__class__.__name__,
                                    ", ".join(repr(o) for o in obj.args)),)
            msg = "\n  ".join((msg, *exc.args))
        else:
            assert result is True
            if remove is True:
                # XXX might want to say 'user-modified item deleted' to clear
                # up confusion regarding any (formerly) shadowed default
                # counterparts suddenly being displayed on success
                msg = "Item deleted."
                try:
                    obj[key]
                except (KeyError, TypeError) as exc:
                    from collections import MutableSequence
                    if (isinstance(exc, TypeError) and
                            not isinstance(obj, MutableSequence)):
                        raise
                    # XXX possibly undesired if wanting to assign new value
                    self.last_config_selector = pardir  # Go up 1 level
                    msg = "Item deleted; current selection has changed"
                if rename:
                    msg = msg.replace("deleted", "moved")
            else:
                msg = None
            # XXX it might make more sense to "load" immediately after saving
            # (optionally adding --force to "save"). That way, the ordering of
            # /conditions would remain consistent between self.nv and
            # self.config following additions/deletions.
            self.manage_config(action="save")
            self.refresh_help_defaults()
        if msg:
            self.put_pretty(msg)
            if "current selection has changed" in msg:
                return self.cmd_select()
        elif arrange:
            self.last_config_selector = pardir
        else:
            self.last_config_selector = selector
        self.last_config_selector, __, obj, __ = reaccess(
            self.last_config_selector, None, self.manage_config("view")
        )
        cwdstr = f"Selected: {self.last_config_selector} =>%s"
        from .ootil import OrderedRepr
        aRepr = OrderedRepr()
        aRepr.maxdict = aRepr.maxlist = 2
        aRepr.maxlevel = 1
        orep = aRepr.repr(obj)
        sep = "\n  " if len(orep) + len(cwdstr) > 60 else " "
        self.put_pretty(cwdstr % f"{sep}{orep}")

    def cmd_connect(self, address=None, host=None, port=None, bindhost=None):
        # TODO remove bindhost option; we're not listening for requests
        from jeepney import bus
        # Enable TCP transport and ANONYMOUS authentication
        bus.SUPPORTED_TRANSPORTS = ("unix", "tcp")
        #
        if address is None:
            if host is None:  # Port defaults to 47000
                msg = ("{metavar} must be specified, either here or in your "
                       "config under /settings/{dest}; {help}")
                raise self.approx._construct_error("connect", "host", msg)
            address = "tcp:host={host},port={port}".format(host=host,
                                                           port=port)
        bus_addr = bus.get_bus(address)
        if self.debug:
            self.logger.debug("Bus address: {}".format(bus_addr))
        if not isinstance(bus_addr, tuple):
            # Only triggered in debug mode if address is invalid
            return self.cmd_help("connect")
        elif (hasattr(self, "_connection") and
                not self._connection.IsClosed() and
                self._connection.bus_addr == bus_addr):
            self.put_pretty("Already connected to %r" % bus_addr)
            return
        from .degustibus import DBusConnection
        self._connection = self.CreateSocket(DBusConnection, bus_addr=bus_addr)
        host, port = bus_addr
        kwargs = dict(host=host, port=port)
        if bindhost is not None:
            kwargs["bindhost"] = bindhost
        self._connection.Connect(**kwargs)

    def cmd_disconnect(self):
        if not hasattr(self, "_connection"):
            self.put_pretty("No existing connection")
            return
        elif self._connection.IsClosed():
            del self._connection
            return
        if getattr(self._connection, "_subscribed", False):
            return self.do_subscribe("disconnect")
        try:
            self._connection.Close()
        except Exception:
            self.print_traceback()
            return
        else:
            if not self._connection.IsClosed():
                raise ConnectionError("Could not close %r" % self._connection)
            del self._connection

    def cmd_debug_send(self, node, method, raw_string=None, as_json=False):
        """This is for DBUS calls (not IRC commands)

        Note: <raw_string> is always evaluated, if present, so single strings
        must have nested quotes.
        """
        # TODO find out why this occasionally disconnects after certain
        # method-call/object combinations
        try:
            assert self._connection.unique_name is not None
        except (AttributeError, AssertionError):
            return self.cmd_help(("send",))
        #
        put_mod_cb = self.make_generic_callback(self.put_pretty)
        args = []
        if raw_string is not None:
            try:
                args += raw_string(as_json, True)
            except Exception:
                debug_args = ["--as_json"] if as_json else []
                debug_args += [node, method, raw_string]
                return self.cmd_debug_args("debug_send", debug_args)
        self.do_send(node, method, put_mod_cb, args)

    def cmd_debug_args(self, command, args):
        """Test arg parsing used by commands

        Note: default values provided by the parser are defined in
        ``initialize_commands``. Non-bool kwargs should all be set to
        None.

        TODO: this should only appear in menu when debug mode is active
        """
        command = self.approx.encmd(command)
        if command not in self.mod_commands:
            return self.cmd_help(commands=(command,))
        namespace = self.parse_command_args(command, args)
        if namespace is None:
            return
        kwargs = vars(namespace)
        outdict = dict(passed=args, parsed=kwargs)
        from .cmdopts import SerialSuspect
        to_eval = [(k, v) for k, v in kwargs.items() if
                   isinstance(v, SerialSuspect)]
        if to_eval:
            opt, val = to_eval.pop()
            outdict["parsed"].update({opt: str(val)})
            try:
                evaled = val(kwargs.get("as_json", False), True)
            except Exception as exc:
                self.put_pretty(exc.args[0])
                evaled = [repr(exc)]
            outdict["evaled"] = evaled
        import json
        # Dump JSON instead of pprint-ing so tests can capture and eval output.
        self.put_pretty(json.dumps(outdict, indent=2))

    def cmd_debug_fail(self, exc, msg):
        exception = __builtins__.get(exc)
        # Could just let these fail naturally, but msg might not be clear
        if exception is None:
            exception = NameError
            msg = "No exception named %r" % exc
        elif (not isinstance(exception, type) or
              not issubclass(exception, BaseException)):
            exception = TypeError
            msg = "%r is not raisable" % exc
        else:
            msg = " ".join(msg)
        raise exception(msg)

    def cmd_debug_expr(self, text, expression, as_json=False):
        from .lexpresser import ppexp
        # Named expressions (references) must exist in config
        from .cmdopts import SerialSuspect, RAWSEP
        # Check for literal expressions first
        if isinstance(expression, SerialSuspect):
            expr = expression(as_json)
        elif self.config is None:
            raise ValueError("No config detected. Use 'select' to load.")
        else:
            try:
                expr = self.config.expressions[expression]
            except KeyError:
                msg = ("No expression named {!r} found in config, and the "
                       "{} form wasn't used".format(expression, RAWSEP))
                raise KeyError(msg)
        if self.config is not None:
            from .lexpresser import expand_subs
            expr = expand_subs(expr, self.config.expressions)
        from io import StringIO
        with StringIO() as flo:
            ppexp(expr, text, file=flo)
            self.put_pretty(flo.getvalue())

    def cmd_debug_cons(self, stop=False, bindhost=None, port=None):
        # Not sure if it's advisable to call RemSocket here; the telnet module
        # keeps its own inventory and never registers anything with any manager
        msg = "Already stopped" if stop else None
        for sock_attr in ("_console_client", "_console_listener"):
            oldsock = getattr(self, sock_attr, None)
            if oldsock is None:
                continue
            if stop:
                msg = "Stopping"
                try:
                    oldsock.Close()
                except Exception:
                    self.print_traceback()
                finally:
                    # Otherwise znc crashes when trying to access stale object
                    delattr(self, sock_attr)
            else:
                if not oldsock.IsClosed():
                    oldsock_name = oldsock.GetSockName()
                    msg = (f"{oldsock_name!r} is still up; "
                           "use --stop to disconnect")
                    break
        if msg:
            self.put_pretty(msg)
            return
        kwargs = dict(bindhost=bindhost)
        if port is not None:
            kwargs["port"] = int(port)
        from .consola import Console
        sock = self.CreateSocket(get_listener(Console, **kwargs))
        self._console_listener = sock
        port = sock.Listen(**kwargs)
        if not port:
            raise ConnectionError
        sock.SetSockName("Console listener for %s" % self.GetModName())
        self.ListSockets()
        self.put_pretty("Listening over port {} on host {!r}"
                        .format(port, bindhost))
        # Ensure help(module.cmd_*) prints something
        for mod_cmd in self.mod_commands:
            base_func = getattr(Signal, mod_cmd)
            if getattr(base_func, "__doc__") is None:
                base_func.__doc__ = self.approx[mod_cmd].description

    def cmd_help(self, commands=None, usage=False):
        """List commands with either usage or summary field

        See note in debug_args re default params
        """
        if commands:
            usage = True
            commands = {self.approx.decmd(c.lower()) for c in commands}
            rejects = commands - self.approx.keys()
            for reject in rejects:
                self.put_pretty("No command named %r" % reject)
                continue
            commands -= rejects
            if self.debug:
                assert not any(self.approx.encmd(r) in self.mod_commands for
                               r in rejects)
                assert all(self.approx.encmd(c) in self.mod_commands for
                           c in commands)
            if not commands:
                return
            requested = zip(commands, (self.approx[c] for c in commands))
        else:
            requested = self.approx.items()
        help = znc.CTable()
        help.AddColumn("Command")
        help.AddColumn("Usage" if usage else "Description")
        from itertools import zip_longest
        #
        for command, parser in requested:
            if usage:
                upre = "usage: %s" % command
                rest = (parser.format_usage()
                        .replace(upre, "", 1)
                        .replace("[-h] ", "", 1))
                if self.znc_version < (1, 7, 0):
                    desc = [" ".join(rest.split())]
                else:
                    desc = [l.strip() for l in rest.split("\n") if l.strip()]
            else:
                desc = [parser.description]
            for line, comm in zip_longest(desc, (command,), fillvalue=""):
                help.AddRow()
                help.SetCell("Command", comm)
                help.SetCell("Usage" if usage else "Description", line)
        #
        s_line = znc.String()
        strung = []
        while help.GetLine(len(strung), s_line):
            strung.append(s_line.s)
        also = "  (<command> [-h] for details)"
        strung[1] = strung[1].replace(len(also) * " ", also, 1)
        self.put_pretty("\n".join(strung))


def get_listener(cls, *cls_args, **cls_kwargs):
    """The listener example from the modpython wiki_ article

    Note: originally tried making this a member func of the main module,
    but that resulted in crashes related to resource ownership

    .. _wiki: https://wiki.znc.in/Modpython#Sockets
    """
    def OnAccepted(inst, host, port):
        cls_kwargs.setdefault("host", host)
        cls_kwargs.setdefault("port", port)
        from enum import Enum
        # 0 is not unique, so the ``.name`` attr and repr are only valid for
        # the first key initialized to 0.
        econs = Enum("Csock::ECONState", ((k, v) for k, v in
                                          vars(znc.Csock).items() if
                                          k.startswith("CST_")))
        cls_kwargs.setdefault("econs", econs)
        return inst.GetModule().CreateSocket(cls, *cls_args, **cls_kwargs)

    def OnShutdown(inst):
        name = inst.__class__.__name__
        if inst.IsClosed():
            inst.GetModule().put_pretty("%r is shutting down" % name)
        else:
            # Triggered when an attempt is made to open a new listener
            # immediately after closing one with identical settings
            # TODO see if setting SO_REUSEADDR makes sense
            try:
                inst.GetModule().put_pretty("Error: socket is not closed")
            except AttributeError as exc:
                if not all(s in repr(exc.args) for s in ("NoneType",
                                                         "GetNewPyObj")):
                    raise

    return type(f"{cls.__name__}Listener", (znc.Socket,),
                dict(OnAccepted=OnAccepted, OnShutdown=OnShutdown))
