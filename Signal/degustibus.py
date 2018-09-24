# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from . import znc
from . import get_logger
from .jeepers import incoming_NT, get_msggen

from asyncio.events import AbstractEventLoop
from asyncio.futures import Future as AsyncFuture

from jeepney.auth import (SASLParser, BEGIN,
                          make_auth_anonymous, make_auth_external)
from jeepney.bus import parse_addresses
from jeepney.low_level import Parser
from jeepney.routing import Router
from jeepney.integrate.asyncio import Proxy


class DBusConnection(znc.Socket):
    """Connection to the Signal host's message bus

    Currently, only TCP is supported.
    """
    from .commonweal import put_issuer

    def Init(self, *args, **kwargs):
        self.module = self.GetModule()
        self.debug = self.module.debug
        self.logger = get_logger(self.__class__.__name__)
        # Well-known name (org.asamk.Signal) registered with message bus
        self.has_service = False
        #
        self.__dict__.update(kwargs)
        self.unique_name = None
        #
        self.auth_parser = SASLParserAnonAuth()
        self.parser = Parser()
        #
        FakeFuture.fake_loop = FakeLoop(self.module)
        self.router = Router(FakeFuture)
        #
        if self.debug:
            from jeepney.low_level import HeaderFields

            def on_unhandled(msg):
                member = msg.header.fields[HeaderFields.member]
                if member == "NameAcquired":
                    # This fires before the "Hello" reply callback
                    log_msg = f"Received routine opening signal: {member!r}; "
                else:
                    log_msg = "See 'data_received' entry above for contents"
                self.logger.debug(log_msg)

            self.router.on_unhandled = on_unhandled
        self.authentication = FakeFuture()
        # FIXME explain why this appears twice (see above)
        self.unique_name = None

    def check_subscription(self, service_name=None, member=None):
        """Check if a 'signal-received' callback has been registered

        Without ``member``, return True if any subscriptions exist for
        object described by ``service_name``.
        """
        if service_name is None:
            return bool(self.router.signal_callbacks)
        service = get_msggen(service_name)
        if member:
            key = (service.object_path, service.interface, member)
            return key in self.router.signal_callbacks
        else:
            key = (service.object_path, service.interface)
            return any(k[:-1] == key for k in self.router.signal_callbacks)

    def remove_subscription(self, service_name=None, member=None):
        """Remove a 'signal-received' callback

        Without ``member``, remove all subscriptions registered to
        object described by ``service_name``.
        """
        if service_name is None:
            self.router.signal_callbacks.clear()
            return
        service = get_msggen(service_name)
        if member:
            key = (service.object_path, service.interface, member)
            if key in self.router.signal_callbacks:
                del self.router.signal_callbacks[key]
        else:
            key = (service.object_path, service.interface)
            for k in tuple(self.router.signal_callbacks):
                if k[:-1] == key:
                    del self.router.signal_callbacks[k]

    def add_subscription(self, service_name, member, callback):
        """Add a 'signal-received' callback"""
        service = get_msggen(service_name)
        self.router.subscribe_signal(callback=callback,
                                     path=service.object_path,
                                     interface=service.interface,
                                     member=member)

    def subscribe_incoming(self):
        """Register handler for incoming Signal messages"""
        self.put_issuer("Signal service found")
        self.has_service = True
        #
        if not self.module.config or not self.module.config.settings["obey"]:
            return
        #
        def watch_message_received_cb(msg_body):  # noqa: E306
            if self.debug:
                assert isinstance(msg_body, tuple)
            try:
                self.module.handle_incoming(incoming_NT(*msg_body))
            except Exception:
                self.module.print_traceback()
        #
        def add_message_received_cb():  # noqa: E306
            self.put_issuer("Subscribed to incoming Signal messages")
            if self.debug:
                self.logger.debug("Registering signal callback for "
                                  "'MessageReceived' on 'Signal'")
            self.add_subscription("Signal", "MessageReceived",
                                  watch_message_received_cb)
        #
        if self.debug:
            self.logger.debug("Adding match rule for 'MessageReceived'")
        try:
            self.module.do_subscribe("Signal", "MessageReceived",
                                     add_message_received_cb)
        except Exception:
            self.module.print_traceback()

    def ensure_service(self):
        """Query message bus for Signal service, act accordingly

        For now, this just waits for an announcement of `name
        acquisition`__, then resumes the normal subscription sequence.

        .. __: https://dbus.freedesktop.org/doc/dbus-specification.html
           #bus-messages-name-owner-changed
        """
        service_name = get_msggen("Signal").bus_name
        member = "NameOwnerChanged"
        #
        def watch_name_acquired_cb(msg_body):  # noqa: E306
            if self.debug:
                assert type(msg_body) is tuple
                assert len(msg_body) == 3
                assert all(type(s) is str for s in msg_body)
            if msg_body[0] == service_name:
                self.remove_subscription("DBus", member)
                self.module.do_subscribe("DBus", member,
                                         remove_name_owner_changed_cb,
                                         remove=True)
        #
        def remove_name_owner_changed_cb():  # noqa: E306
            if self.debug:
                self.logger.debug("Cancelled subscription for "
                                  f"{member} on 'DBus'")
            self.subscribe_incoming()
        #
        def add_name_owner_changed_cb():  # noqa: E306
            if self.debug:
                self.logger.debug("Registering signal callback for "
                                  f"{member} on 'DBus'")
            self.add_subscription("DBus", member, watch_name_acquired_cb)
        #
        def name_has_owner_cb(result):  # noqa: E306
            if self.debug:
                assert type(result) is int
            if result:
                self.subscribe_incoming()
            else:
                self.put_issuer("Waiting for Signal service...")
                self.module.do_subscribe("DBus", member,
                                         add_name_owner_changed_cb)
        #
        wrapped = self.module.make_generic_callback(name_has_owner_cb)
        self.module.do_send("DBus", "NameHasOwner", wrapped,
                            args=(service_name,))

    def _open_session(self):
        bus = Proxy(get_msggen("DBus"), self)
        hello_reply = bus.Hello()

        def hello_cb(fut):
            if self.debug:
                self.logger.debug("Got hello reply: %r" % fut)
            self.unique_name = fut.result()[0]
            self.put_issuer("Registered with message bus; session id is: %r" %
                            self.unique_name)
            self.ensure_service()

        if self.debug:
            self.logger.debug("Waiting for hello reply: %r" % hello_reply)
        #
        hello_reply.add_done_callback(hello_cb)

    def _authenticated(self):
        self.WriteBytes(BEGIN)
        self.authentication.set_result(True)
        self.data_received = self.data_received_post_auth
        self.data_received(self.auth_parser.buffer)
        if self.debug:
            self.logger.debug("D-Bus connection authenticated")
        self._open_session()

    def data_received(self, data):
        self.auth_parser.feed(data)
        if self.auth_parser.authenticated:
            self._authenticated()
        elif self.auth_parser.error:
            self.authentication.set_exception(
                ValueError(self.auth_parser.error)
            )
        elif self.auth_parser.rejected is not None:
            if b"ANONYMOUS" in self.auth_parser.rejected:
                self.WriteBytes(make_auth_anonymous())
                self.auth_parser.rejected = None
            else:
                self.auth_parser.error = self.auth_parser.rejected

    def format_debug_msg(self, msg):
        from .ootil import OrderedPrettyPrinter as OrdPP
        from jeepney.low_level import Message
        if not hasattr(self, "_opp"):
            self._opp = OrdPP(width=72)
        if not isinstance(msg, Message):
            return self._opp.pformat(msg)
        header = msg.header
        data = {"header": (header.endianness, header.message_type,
                           dict(flags=header.flags,
                                version=header.protocol_version,
                                length=header.body_length,
                                serial=header.serial,),
                           {"fields": {k.name: v for
                                       k, v in header.fields.items()}}),
                "body": msg.body}
        return self._opp.pformat(data)

    def data_received_post_auth(self, data):
        if self.debug:
            num_futs = len(self.router.awaiting_reply)
            log_msg = [f"Futures awaiting reply: {num_futs}"]
        for msg in self.parser.feed(data):
            self.router.incoming(msg)
            if self.debug:
                log_msg.append(self.format_debug_msg(msg))
        if self.debug:
            self.logger.debug("\n".join(log_msg))

    def send_message(self, message):
        if not self.authentication.done():
            # TODO remove if unable to trigger this
            raise RuntimeError("Wait for authentication before sending "
                               "messages")
        future = self.router.outgoing(message)
        data = message.serialise()
        # Logging must happen here, after:
        #   1. Router increments serial cookie
        #   2. Message.serialize() updates the header w. correct body length
        if self.debug:
            num_futs = len(self.router.awaiting_reply)
            log_msg = self.format_debug_msg(message)
            self.logger.debug(f"Futures awaiting reply: {num_futs}\n{log_msg}")
        self.WriteBytes(data)
        return future

    def OnConnected(self):
        self.WriteBytes(b'\0' + make_auth_external())
        self.put_issuer("Connected to: %s:%s" % self.bus_addr)
        self.SetSockName("DBus proxy to signal server")
        self.SetTimeout(0)

    def OnReadData(self, data):
        self.data_received(data)

    def OnDisconnected(self):
        self.put_issuer("Disconnected from %s:%s for session %r" %
                        (*self.bus_addr, self.unique_name))

    def OnShutdown(self):
        name = self.GetSockName()
        if self.debug:
            try:
                self.logger.debug("%r shutting down" % name)
            except ValueError as exc:
                # Only occurs when disconnect teardown is interrupted
                if "operation on closed file" not in repr(exc):
                    raise


class SASLParserAnonAuth(SASLParser):
    def __init__(self):
        super().__init__()
        self.rejected = None

    def process_line(self, line):
        self.rejected = None
        if line.startswith(b"REJECTED"):
            self.rejected = line
        else:
            super().process_line(line)

    def feed(self, data):
        self.buffer += data
        while ((b'\r\n' in self.buffer)
               and not self.authenticated
               and self.rejected is None):
            line, self.buffer = self.buffer.split(b'\r\n', 1)
            self.process_line(line)


class FakeLoop(AbstractEventLoop):
    """Kludge for DBusConnection's incoming data dispatcher (router)

    Obviously, this is pure mockery and not a real shim.
    """
    def __init__(self, module):
        self.module = module

    def call_later(self, delay, callback, *args):
        """This is actually ``call_soon``"""
        assert delay == 0
        callback(*args)

    def get_debug(self):
        return False


class FakeFuture(AsyncFuture):
    fake_loop = None

    def __init__(self):
        assert self.fake_loop is not None
        super().__init__(loop=self.fake_loop)


def get_tcp_address(addr):
    """Return a single host/port tuple"""
    transport, kv = next(parse_addresses(addr))
    # Unix domain sockets are not yet supported by ZNC
    # FIXME add issue/PR id above
    assert transport == "tcp"
    assert kv.get("bind") is None
    assert kv.get("family", "ipv4") == "ipv4"
    return kv["host"], int(kv["port"])
