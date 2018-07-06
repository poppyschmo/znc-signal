# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import znc
from code import InteractiveConsole
from . import get_logger


class Console(znc.Socket, InteractiveConsole):
    """A Python console for remote telnet connections (not IRC clients)

    See also: <https://github.com/vxgmichel/aioconsole>
    """

    def Init(self, *args, **kwargs):
        self.module = self.GetModule()
        self.debug = self.module.debug
        self.logger = get_logger(self.__class__.__name__)
        self.__dict__.update(kwargs)
        from collections import deque
        self.run_next = deque()
        from pprint import pprint
        # Some SWIG-related objects not found in dir() listings crop up in
        # instance ``__dict__``s, but none seems useful (hence dir-only):
        self.locals.update(
            dict(pp=pprint,
                 pd=lambda o: pprint(dir(o)),
                 pf=lambda o, s: pprint([a for a in dir(o) if s in a.lower()]),
                 pm=self.post_mortem,
                 cznc=znc.CZNC.Get(),
                 console=self,
                 module=self.module)
        )
        _globals = ((k, v) for k, v in dict(globals()).items() if
                    not k.startswith("_"))
        self.locals.update(dict(_globals))
        self.console = self.interact()
        next(self.console)

    def runcode(self, code):
        from io import StringIO
        from contextlib import redirect_stderr, redirect_stdout
        try:
            with StringIO() as flo:
                with redirect_stderr(flo), redirect_stdout(flo):
                    exec(code, self.locals)
                    captured_output = flo.getvalue()
        except SystemExit:
            raise
        except Exception:
            self.showtraceback()
        else:
            self.write(captured_output)

    def post_mortem(self):
        """Provides pdb.post_mortem only (no pdb runtime facilities)

        Using IOBase.readline() to wait for input, as the superclass
        does, won't work here because it blocks OnReadData(). It also
        requires messing with the file offset at every turn.
        """
        from io import IOBase
        from pdb import Pdb

        class PeeDeeBee(Pdb):
            undoc_header = "Unsupported commands:"
            supported_commands = """
                a args bt d down exit h help l list ll longlist p pp q
                quit retval rv u up w whatis where
            """

            def __init__(_self):
                super().__init__(stdin=FakeIob(), stdout=FakeIob())
                _self._cmdloop = _self.cmdloop
                _self.supported_commands = _self.supported_commands.split()
                for cmd in (a for a in dir(_self) if a.startswith("do_")):
                    if (cmd.replace("do_", "", 1) not in
                            _self.supported_commands):
                        exec("_self.%s = _self.unsupported" % cmd)

            def unsupported(_self, *args, **kwargs):
                "Command not supported"
                _self.message("Command not supported")

            def bp_commands(_self, frame):
                # Hopefully, shadowing the do_* methods means this never runs
                # (it calls _cmdloop() but isn't awaited).
                raise RuntimeError

            def interaction(_self, frame, traceback):
                # BEGIN SRC /lib/python3.6/pdb.py
                if Pdb._previous_sigint_handler:
                    import signal
                    signal.signal(signal.SIGINT, Pdb._previous_sigint_handler)
                    Pdb._previous_sigint_handler = None
                if _self.setup(frame, traceback):
                    _self.forget()
                    return
                _self.print_stack_entry(_self.stack[_self.curindex])
                # END SRC /lib/python3.6/pdb.py
                yield from _self._cmdloop()
                _self.forget()

            def cmdloop(_self, intro=None):
                _self.preloop()
                stop = None
                while not stop:
                    if _self.cmdqueue:
                        line = _self.cmdqueue.pop(0)
                    else:
                        _self.stdout.write(_self.prompt)
                        line = yield
                        line = line.rstrip('\r\n')
                        if not len(line):
                            line = 'EOF'
                    line = _self.precmd(line)
                    stop = _self.onecmd(line)
                    stop = _self.postcmd(stop, line)
                _self.postloop()

        class FakeIob(IOBase):
            def __init__(_self):
                _self.readline = None

            def flush(_self):
                pass

            def write(_self, string):
                self.write(string)
                return len(string)

        def pm():
            p = PeeDeeBee()
            p.reset()
            import sys
            if self.module.last_traceback is not None:
                if self.debug:
                    self.logger.debug("Using module traceback: %r" %
                                      self.module.last_traceback)
                sys.last_traceback = self.module.last_traceback
            try:
                sys.last_traceback
            except AttributeError:
                sys.last_traceback = sys.exc_info()[-1]  # ouroboros
            yield from p.interaction(None, sys.last_traceback)

        self.run_next.appendleft(pm)

    def interact(self, banner=None, exitmsg=None) -> "<generator>":
        import sys
        cp = 'Type "help", "copyright", "credits" or "license" for more info.'
        self.write("Python %s on %s %s\n(%s)\n" %
                   (sys.version, sys.platform, cp, self.__class__.__name__))
        more = 0
        while True:
            try:
                while len(self.run_next):
                    call_this = self.run_next.pop()
                    if self.debug:
                        self.logger.debug("Launching %r" % call_this.__name__)
                    try:
                        yield from call_this()  # void
                    except EOFError:
                        self.write("Hint: use quit/exit instead of ^D(EOT)\n")
                        raise
                    except Exception:
                        self.showtraceback()
                        raise
                else:
                    self.write("... " if more else ">>> ")
                    line = yield
            except EOFError as e:
                self.write("EOF detected: %r\n" % e)
                break
            else:
                more = self.push(line)
        if exitmsg is None:
            self.write('Exiting %s...\n' % self.__class__.__name__)
        elif exitmsg != '':
            self.write('%s\n' % exitmsg)

    def put_issuer(self, msg):
        """Emit messages to issuing client only, if still connected

        Otherwise, target all clients, regardless of network
        """
        client = self.module.get_client(self.issuing_client)
        self.module.put_pretty(msg, putters=(client,) if client else None)

    def write(self, msg):
        if self.IsClosed():
            self.put_issuer(msg)
        else:
            self.Write(msg)

    def OnReadData(self, data):
        self.console.send(data.decode())

    def throw_gen(self, error, msg):
        """
        Send error if still possible, otherwise just print to query buf
        """
        try:
            self.console.throw(error, msg)
        except StopIteration:
            self.write(msg)

    # TODO use more precise errors for these
    def OnConnected(self):
        self.put_issuer("Python console connected from {!r}"
                        .format(self.GetSockName()))
        self.module._console_client = self
        self.SetSockName("Console client for %s" % self.module.GetModName())
        self.SetTimeout(0)  # Type is ALL
        if self.debug:
            self.logger.debug(self.econs(self.GetConState()))

    def OnDisconnected(self):
        self.throw_gen(EOFError, "Disconnected")

    def OnTimeout(self):
        self.throw_gen(EOFError, "Timed Out")

    def OnSockError(self, *args):
        self.put_issuer("Got a SockError: %r" % (args))

    def OnShutdown(self):
        name = self.GetSockName()
        if self.debug:
            # Throws ValueError if pipe is already closed, which occasionally
            # happens when mod is unloaded while still connected
            self.logger.debug("%r shutting down" % name)
        for handler in self.logger.handlers:
            self.logger.removeHandler(handler)


class Listener(znc.Socket):
    """The listener example from the modpython wiki_ article

    .. _wiki: https://wiki.znc.in/Modpython#Sockets
    """
    con_class = None
    con_args = ()
    con_kwargs = {}

    def OnAccepted(self, host, port):
        self.con_kwargs.setdefault("host", host)
        self.con_kwargs.setdefault("port", port)
        from enum import Enum
        # 0 is not unique, so the ``.name`` attr and repr are only valid for
        # the first key initialized to 0.
        econs = Enum("Csock::ECONState",
                     ((k, v) for k, v in vars(znc.Csock).items() if
                      k.startswith("CST_")))
        self.con_kwargs.setdefault("econs", econs)
        return self.GetModule().CreateSocket(self.con_class, *self.con_args,
                                             **self.con_kwargs)

    def OnShutdown(self):
        if self.IsClosed():
            mod = self.GetModule()
            client = mod.get_client(self.con_kwargs["issuing_client"])
            name = "%s.%s" % (self.__module__, self.__class__.__name__)
            mod.put_pretty("%r is shutting down" % name,
                           putters=(client,) if client else None)
        # GetModule() always works when sock is closed, but sometimes fails
        # when still open (seemingly after attempt is made to open a new
        # listener immediately after closing one with identical settings)
        # TODO see if setting SO_REUSEADDR makes sense
        else:
            try:
                # Emit to all clients, regardless of network
                self.GetModule().put_pretty("\x02Error\x02: console listener "
                                            "is not closed")
            except AttributeError as exc:
                if not all(s in repr(exc.args) for s in ("NoneType",
                                                         "GetNewPyObj")):
                    raise
