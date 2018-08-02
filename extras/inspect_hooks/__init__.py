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
    normalize_onner = None
else:
    get_logger = ootil.GetLogger()
    znc_version = commonweal.znc_version
    from .helpers import (deprecated_hooks, normalize_onner,
                          get_first, get_cmess_types)


class InspectHooks(znc.Module):
    module_types = [znc.CModInfo.UserModule]
    args_help_text = "LOGFILE=<path> LOG_RAW=<bool> LOG_OLD_HOOKS=<bool>"
    has_args = True
    logfile = None
    log_raw = False
    log_old_hooks = False
    normalize_onner = normalize_onner

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
        if normalize_onner is None:
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
        self.cmess_types = get_cmess_types()
        #
        return True

    def _OnShutdown(self):
        if not normalize_onner:
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
                assert znc_version >= (1, 7, 0)
                cmtype = self.cmess_types(args_dict["msg"].GetType())
                if cmtype in (self.cmess_types.Ping, self.cmess_types.Pong):
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
        """Additional info not included by normalize_onner"""
        # Trailing "/<network>" portion missing when called during
        # OnClientDisconnect but present during OnClientLogin
        if not get_first(args_dict, "client", "Client"):
            try:
                client_name = self.GetClient().GetFullName()
            except AttributeError:
                pass
            else:
                args_dict["client"] = client_name
        #
        # Add declaration type info from native CModule (znc_core)
        args_dict["native_types"] = getattr(znc.CModule, name).__annotations__
        return args_dict

    def _wrap_onner(self, onner):
        """A surrogate for CModule 'On' hooks"""
        #
        def dump(*args, **kwargs):
            from inspect import signature
            sig = signature(onner)
            bound = sig.bind(*args, **kwargs)
            name = onner.__name__
            rv = None
            # NOTE sig.return_annotation reflects the bound method from self,
            # which doesn't have the SWIG annotations from znc_core's CModule
            ret_anno = getattr(znc.CModule, name).__annotations__.get("return")
            if ret_anno == "CModule::EModRet":
                rv = znc.CONTINUE
            elif ret_anno == "bool":
                if name in ("OnBoot",):  # OnLoad is overridden
                    rv = True  # otherwise None for web/cap stuff
                else:
                    assert any(s in name.lower() for s in ("web", "cap"))
            else:
                try:
                    assert ret_anno == "void"
                except AssertionError:
                    self.print_traceback(f"Unexpected return type: {ret_anno}")
            #
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
                return rv
            #
            self._hook_data[name] = normalized = None
            try:
                normalized = self.normalize_onner(name, bound.arguments,
                                                  ensure_net=True)
                normalized = self.post_normalize(name, normalized)
            except Exception:
                self.print_traceback()
                return rv
            OrdPP = ootil.OrderedPrettyPrinter
            pretty = OrdPP().pformat(normalized)
            self.logger.debug(f"{name}{sig}\n{pretty}")
            self._hook_data[name] = normalized
            #
            # NOTE consider only doing this when the instance has been patched;
            # otherwise, its only use is for detecting upstream changes.
            _rv = onner(*args, **kwargs)  # call real hook
            if _rv == rv:
                return rv
            try:
                assert _rv is None
                assert name not in InspectHooks.__dict__
                assert name in znc.Module.__dict__  # obvious
            except (AssertionError):
                self.print_traceback(f"Expected {rv!r} but {name} returned "
                                     f"{_rv!r} of type {type(_rv)}")
            finally:
                return rv
        #
        # NOTE The attrs assigned by wraps aren't used by the log formatter;
        # see tests for changes to freestanding funcs bound to instances.
        from functools import update_wrapper
        return update_wrapper(dump, onner)


inspect_hooks = InspectHooks
