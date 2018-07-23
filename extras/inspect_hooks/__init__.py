# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import znc
try:
    from Signal import ootil, commonweal
except ImportError:
    try:
        from . import ootil, commonweal
    except ImportError:
        pass

try:
    ootil
except NameError:
    _normalize_onner = None
else:
    get_logger = ootil.GetLogger()
    znc_version = commonweal.znc_version
    deprecated_hooks = commonweal.deprecated_hooks
    _normalize_onner = commonweal.normalize_onner


class InspectHooks(znc.Module):
    module_types = [znc.CModInfo.UserModule]
    args_help_text = "LOGFILE=<path> LOG_RAW=<bool> LOG_OLD_HOOKS=<bool>"
    has_args = True
    logfile = None
    log_raw = False
    log_old_hooks = False
    normalize_onner = _normalize_onner

    def __getattribute__(self, name):
        """Intercept calls to On* methods for learning purposes

        Wrap all On* methods with args inspector except those that begin
        with a single leading underscore.

        See ``test_intercept_hooks`` in tests/test_extras.py
        """
        candidate = super().__getattribute__(name)
        if name.startswith("On"):
            try:
                candidate = super().__getattribute__(f"_{name}")
            except AttributeError:
                return self._wrap_onner(candidate)
        return candidate

    def print_traceback(self, msg=None):
        """Needed by normalize_onner"""
        self.logger.exception(msg or "")

    def _OnLoad(self, argstr, message):
        #
        if self.normalize_onner is None:
            message.s = ("Copy or link commonweal.py and ootil.py from Signal "
                         "into this package's dir. Or just load Signal.")
            return False
        #
        commonweal.update_module_attributes(self, argstr, "inspecthooks_")
        if znc_version < (1, 7):
            self.log_old_hooks = False
        #
        if self.logfile is None:
            message.s = ("LOGFILE is required. Pass as module arg or export "
                         "INSPECTHOOKS_LOGFILE to ZNC's environment.")
            return False
        get_logger.LOGFILE = open(self.logfile, "w")
        self.logger = get_logger(self.__class__.__name__)
        self.logger.setLevel("DEBUG")
        self.logger.debug("loaded, logging with: %r" % self.logger)
        #
        self._hook_data = {}
        #
        return True

    def _OnShutdown(self):
        if not _normalize_onner:
            return
        try:
            self.logger.debug("%r shutting down" % self.GetModName())
        except AttributeError:
            pass
        get_logger.clear()

    def _OnModCommand(self, commandline):
        try:
            raise Warning("This module doesn't provide any commands")
        except Warning:
            self.print_traceback("Except for this test of 'print_traceback'")
        return znc.CONTINUE

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
                cmt = getattr(commonweal.cmess_helpers, "types", None)
                assert znc_version >= (1, 7, 0)
                cmtype = cmt(args_dict["msg"].GetType())
                if cmtype in (cmt.Ping, cmt.Pong):
                    return False
            elif "sLine" in args_dict:
                if znc_version >= (1, 7, 0):
                    assert name in deprecated_hooks
                # XXX false positives: should probably leverage ":" to narrow
                line = str(args_dict["sLine"])
                if "BufferPlay" not in name:
                    if any(s in line for s in ("PING", "PONG")):
                        return False
                else:
                    assert not any(s in line for s in ("PING", "PONG"))
            else:
                self.logger.info(f"Unexpected hook {name!r}: {args_dict!r}")
        #
        if (self.log_old_hooks is False
                and deprecated_hooks  # 1.7+
                and name in deprecated_hooks):
            raise PendingDeprecationWarning
        return True

    def post_normalize(self, name, args_dict):
        """Additional info not included by commonweal.normalize_onner"""
        # Trailing "/<network>" portion missing when called during
        # OnClientDisconnect but present during OnClientLogin
        if not commonweal.get_first(args_dict, "client", "Client"):
            try:
                client_name = self.GetClient().GetFullName()
            except AttributeError:
                pass
            else:
                args_dict["client"] = client_name
        return args_dict

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
                if self.log_raw is True:
                    self.logger.debug("Skipping deprecated hook {!r}"
                                      .format(name))
            except Exception:
                self.print_traceback()
            if not relevant:
                return znc.CONTINUE
            #
            self._hook_data[name] = normalized = None
            try:
                normalized = self.normalize_onner(name, bound.arguments,
                                                  ensure_net=True)
                normalized = self.post_normalize(name, normalized)
            except Exception:
                self.print_traceback()
                return znc.CONTINUE
            OrdPP = ootil.OrderedPrettyPrinter
            pretty = OrdPP().pformat(normalized)
            self.logger.debug(f"{name}{sig}\n{pretty}")
            self._hook_data[name] = normalized
            rv = onner(*args, **kwargs)
            if not isinstance(rv, (type(None), type(znc.CONTINUE))):
                self.logger.debug(f"{name} returned {rv!r} of type {type(rv)}")
            return znc.CONTINUE
        #
        # NOTE both ``__dict__``s are empty, and the various introspection
        # attrs aren't used (even by the log formatter). And seems the magic
        # swig stuff only applies to passed-in objects.
        from functools import update_wrapper
        return update_wrapper(handle_onner, onner)  # <- useless, for now


inspect_hooks = InspectHooks
