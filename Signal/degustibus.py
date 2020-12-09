# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from . import znc
from . import get_logger
from .jeepers import Incoming, get_msggen

from collections import deque

from jeepney.auth import (  # type: ignore[import]
    Authenticator, ClientState, make_auth_anonymous,
)
from jeepney.bus import parse_addresses  # type: ignore[import]
from jeepney.low_level import Parser  # type: ignore[import]
from jeepney.routing import Router  # type: ignore[import]
from jeepney.io.blocking import Proxy, _Future  # type: ignore[import]
from jeepney.io.common import (  # type: ignore[import]
    MessageFilters, FilterHandle,
)
from jeepney.bus_messages import MatchRule  # type: ignore[import]

from typing import Tuple, Optional, Callable, Iterable, Any


def send_dbus_message(
    connection: znc.Socket,
    node: str,
    method: str,
    callback: Callable,
    args: Optional[Iterable[str]] = None,
) -> None:
    """Send a DBus message."""
    service = get_msggen(node)
    args = args or ()
    # Stands apart because called on other objects
    if method == "Introspect":
        from jeepney.wrappers import Introspectable  # type: ignore[import]
        service = Introspectable(
            object_path=service.object_path,
            bus_name=service.bus_name,
        )
    proxy = OldProxy(service, connection)
    try:
        getattr(proxy, method)(*args).add_done_callback(callback)
    except AttributeError:
        raise ValueError("Method %r not found" % method)


default_subs = (("DBus", "NameOwnerChanged"), ("Signal", "MessageReceived"))


class FakeFuture(_Future):

    def __init__(self):
        super().__init__()
        self._callbacks = []

    def set_result(self, result):
        self._result = (True, result)
        for callback, _ in self._callbacks:
            callback(self)
        self._callbacks.clear()

    def add_done_callback(self, fn, *, context=None):
        self._callbacks.append((fn, context))


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
        self.auth_parser = AnonAuthenticator(self.debug)
        self.parser = Parser()
        #
        self._filters = MessageFilters()
        self.router = Router(
            handle_factory=FakeFuture,
            on_unhandled=self.on_unhandled if self.debug else None,
        )

        self.authentication = FakeFuture()
        # FIXME explain why this appears twice (see above)
        self.unique_name = None

    def on_unhandled(self, msg):
        from jeepney.low_level import HeaderFields
        member = msg.header.fields[HeaderFields.member]
        if member == "NameAcquired":
            # This fires before the "Hello" reply callback
            log_msg = f"Received routine opening signal: {member!r}; "
        else:
            log_msg = "See 'data_received' entry above for contents"
        self.logger.debug(log_msg)

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

    def remove_subscription(
        self,
        service_name: Optional[str] = None,
        member: Optional[str] = None
    ):
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
            for k in tuple(self.router.signal_callbacks):
                if k[:-1] == (service.object_path, service.interface):
                    del self.router.signal_callbacks[k]

    def add_subscription(self, service_name, member, callback):
        """Add a 'signal-received' callback"""
        service = get_msggen(service_name)
        self.router.subscribe_signal(callback=callback,
                                     path=service.object_path,
                                     interface=service.interface,
                                     member=member)

    _send = send_dbus_message

    def _ensure_subscription_result(self, result: Any, **kwargs: Any) -> None:
        msg = []
        if result != ():
            msg.append("Problem with subscription request")
        elif self.IsClosed():
            msg.append("Connection unexpectedly closed")
        if msg:
            msg.extend((f"{k}: {v}" for k, v in kwargs.items()))
            try:
                raise RuntimeError("; ".join(msg))
            except RuntimeError:
                self.module.print_traceback()
        return None

    def _subscribe(
        self,
        node: str,
        member: str,
        callback: Optional[Callable[[], None]] = None,
        remove: bool = False
    ) -> None:
        """Register or remove a match rule."""
        try:
            # Caller must ensure connection is actually up; this doesn't check
            assert self.unique_name is not None, "Not connected"
        except AttributeError as exc:
            raise AssertionError from exc
        service = get_msggen(node)
        match_rule = MatchRule(
            type="signal",
            sender=service.bus_name,
            interface=service.interface,
            member=member,
            path=service.object_path
        )

        def request_cb(fut):  # noqa E306
            self._ensure_subscription_result(fut.result())
            if callback:
                return callback()

        method = "AddMatch" if remove is False else "RemoveMatch"
        self._send("DBus", method, request_cb, args=[match_rule])

    def _cancel_subscriptions(
        self, callback: Callable[[], None], pairs=default_subs
    ) -> None:
        # It seems like the system bus normally removes match rules when their
        # owner disconnects, so this is likely superfluous.

        def b(service, member):  # bind lexically by shadowing
            def _inner():
                self.remove_subscription(service, member)
                msg = f"Cancelled D-Bus subscription for {member!r}"
                self.module.put_issuer(msg)
                callback()
            return _inner

        for service, member in pairs:
            if not self.check_subscription(service, member):
                continue
            self._subscribe(service, member, b(service, member), remove=True)

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
                incoming = Incoming(*msg_body)
                if not incoming.message:
                    if self.debug:
                        self.logger.debug("msg_body: %r", incoming)
                    return
                self.module.handle_incoming(incoming)
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
            self._subscribe(
                "Signal", "MessageReceived", add_message_received_cb
            )
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
                self._subscribe(
                    "DBus", member, remove_name_owner_changed_cb, remove=True
                )
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
                msg = "name_has_owner_cb: {!s}({!r})"
                self.logger.debug(msg.format(type(result), result))
            if result:
                self.subscribe_incoming()
            else:
                self.put_issuer("Waiting for Signal service...")
                self._subscribe("DBus", member, add_name_owner_changed_cb)
        #
        wrapped = self.module.make_generic_callback(name_has_owner_cb)
        self._send("DBus", "NameHasOwner", wrapped, args=(service_name,))

    def _open_session(self):
        bus = OldProxy(get_msggen("DBus"), self)
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
        assert self.auth_parser.data_to_send() is None
        # Off by one, it seems (data_to_send() already inhbited by done flag)
        self.WriteBytes(self.auth_parser._to_send)
        self.authentication.set_result(True)
        self.data_received = self.data_received_post_auth
        self.data_received(self.auth_parser.buffer)
        if self.debug:
            self.logger.debug("D-Bus connection authenticated")
        self._open_session()

    def data_received(self, data):
        if self.debug:
            self.logger.debug("Feeding auth: {!r}".format(data))
        self.auth_parser.feed(data)
        if self.auth_parser.authenticated:
            self._authenticated()
        elif self.auth_parser.error:
            self.authentication.set_exception(
                ValueError(self.auth_parser.error)
            )
        else:
            out = self.auth_parser.data_to_send()
            if self.debug:
                self.logger.debug("Sending auth: {!r}".format(out))
            self.WriteBytes(out)

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
            log_msg = []
        for msg in self.parser.feed(data):
            self.router.incoming(msg)
            # for filter in self._filters.matches(msg):
            #     filter.queue.append(msg)
            if self.debug:
                log_msg.append(self.format_debug_msg(msg))
        if self.debug:
            num_futs = len(self.router.awaiting_reply)
            log_msg = [f"Futures awaiting reply: {num_futs}"] + log_msg
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

    def send_and_get_reply(self, message, *, timeout=None, unwrap=None):
        return self.send_message(message)

    def filter(self, rule, *, queue: Optional[deque] = None, bufsize=1):
        """See io.blocking.DBusConnection.filter"""
        if queue is None:
            queue = deque(maxlen=bufsize)
        return FilterHandle(self._filters, rule, queue)

    def OnConnected(self):
        self.WriteBytes(self.auth_parser.data_to_send())
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


class AnonAuthenticator(Authenticator):
    state: ClientState

    def __init__(self, debug: bool, enable_fds=False):
        super().__init__(enable_fds)
        self.debug = debug
        self.logger = get_logger(self.__class__.__name__)

    def process_line(self, line: bytes) -> Tuple[bytes, ClientState]:
        if self.debug:
            self.logger.debug("line: {!r}".format(line))
        if self.state is ClientState.WaitingForReject:
            self.state = ClientState.WaitingForOk
        elif line.startswith(b"REJECTED"):
            if b"ANONYMOUS" in line:
                return make_auth_anonymous(), ClientState.WaitingForReject
            self.error = line
        return super().process_line(line)


class OldProxy(Proxy):
    _connection: DBusConnection


def get_tcp_address(addr):
    """Return a single host/port tuple"""
    transport, kv = next(parse_addresses(addr))
    # Unix domain sockets are not yet supported by ZNC
    # FIXME add issue/PR id above
    assert transport == "tcp"
    assert kv.get("bind") is None
    assert kv.get("family", "ipv4") == "ipv4"
    return kv["host"], int(kv["port"])
