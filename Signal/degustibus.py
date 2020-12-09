# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from . import znc
from . import get_logger
from .jeepers import (
    Incoming, get_msggen, get_handle, make_sub_rule, remove_subscription,
)

from collections import deque
from itertools import count

from jeepney.wrappers import Introspectable, unwrap_msg  # type: ignore[import]
from jeepney.auth import (  # type: ignore[import]
    Authenticator, ClientState, make_auth_anonymous,
)
from jeepney.bus import parse_addresses  # type: ignore[import]
from jeepney.low_level import Message, Parser  # type: ignore[import]
from jeepney.io.blocking import (  # type: ignore[import]
    Proxy as _Proxy, _Future
)
from jeepney.io.common import (  # type: ignore[import]
    MessageFilters, FilterHandle, ReplyMatcher, check_replyable,
)
from jeepney.bus_messages import MatchRule  # type: ignore[import]

from typing import Tuple, Optional, Callable, Iterable, Any, Generator, List


# FIXME remove add_done_callback after adapting to new Jeepney 0.5 interface
class Future(_Future):
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


MsG = Generator[Future, None, Message]


def send_dbus_message(
    connection: znc.Socket,
    node: str,
    method: str,
    callback: Optional[Callable[[Future], None]],
    args: Optional[Iterable[str]] = None,
) -> MsG:
    """Send a DBus message.

    Callback Future argument will resolve to a jeepney.low_level.Message
    object.

    """
    service = get_msggen(node)
    args = args or ()
    # Stands apart because called on other objects
    if method == "Introspect":
        service = Introspectable(
            object_path=service.object_path, bus_name=service.bus_name
        )
    proxy = Proxy(service, connection)
    try:
        g = getattr(proxy, method)(*args)
        fut = next(g)
        assert isinstance(fut, Future)
        assert not fut.done()
        if callback:
            fut.add_done_callback(callback)
        return g
    except AttributeError:
        raise ValueError("Method %r not found" % method)


default_subs = (("DBus", "NameOwnerChanged"), ("Signal", "MessageReceived"))


def unsolo_result(message: Message):
    result = unwrap_msg(message)
    if isinstance(result, tuple) and len(result) == 1:
        result, = result
    return result


# The new Jeepney 0.5 API inverts the router/connection relationship for
# asyncio code. There is also a hybrid scheme in the blocking variant. Since we
# don't have a means of blocking while waiting for IO, this uses generators to
# mimic the latter.
class DBusConnection(znc.Socket):
    """Connection to the Signal host's message bus

    Currently, only TCP is supported.
    """
    _gennies: List[Generator]
    bus_addr: Tuple[str, int]
    issuing_client: str
    _service_unique_name: Optional[str] = None
    # Our (Jeepney client's) unique name (like :1.2)
    unique_name: Optional[str] = None

    from .commonweal import put_issuer

    def Init(self, *args, **kwargs):
        self.module = self.GetModule()
        self.debug = self.module.debug
        self.logger = get_logger(self.__class__.__name__)

        self.__dict__.update(kwargs)

        self.auth_parser = AnonAuthenticator(self.debug)
        self.parser = Parser()

        self._outgoing_serial = count(start=1)
        self._filters = MessageFilters()
        self._replies = ReplyMatcher()
        self._gennies = []

    def _run(self, generator: Generator) -> Any:
        self._gennies.append(generator)
        return next(generator)

    def troll_for_sub(
        self, match_rule: MatchRule,
    ) -> Generator[None, None, Message]:
        with self.filter(match_rule) as queue:
            while True:
                if len(queue) == 0:
                    yield None
                return queue.popleft()

    def troll_for_sub_forever(
        self,
        match_rule: MatchRule,
        callback: Optional[Callable[[Message], None]] = None
    ) -> Generator[Optional[Message], None, None]:
        with self.filter(match_rule) as queue:
            while True:
                if len(queue) == 0:
                    yield None
                    continue
                # TODO maybe guard this against exceptions so it never dies
                msg = queue.popleft()
                if callback:
                    callback(msg)
                yield msg

    _send = send_dbus_message

    def send_external(self, node, method, callback, args) -> None:
        self._run(self._send(node, method, callback, args))

    def _dump_latest(self):
        assert self.debug
        import os
        file = os.path.join(self.module.datadir, "latest.bindgen.py")

        def do_generate():
            msg = yield from generate(self, file)
            self.logger.debug(msg)
            print(msg)

        self._run(do_generate())

    def _ensure_subscription_result(
        self, message: Message, **kwargs: Any
    ) -> None:
        result = unsolo_result(message)
        msg = []
        if result != ():
            msg.append(f"Problem with subscription request: {result!r}")
        elif self.IsClosed():
            msg.append("Connection unexpectedly closed")
        if not msg:
            return None
        msg.extend((f"{k}: {v}" for k, v in kwargs.items()))
        try:
            raise RuntimeError("; ".join(msg))
        except RuntimeError:
            self.module.print_traceback()
        return None

    def add_and_await_sub(
        self, node: str, member: str,
    ) -> Generator[Optional[Future], None, Message]:
        """Subscribe to a signal and wait until match.

        See ``.recv_until_filtered()`` methods in jeepney.io.

        """
        match_rule = make_sub_rule(node, member)
        message = self._send("DBus", "AddMatch", None, args=[match_rule])
        yield from message
        return (yield from self.troll_for_sub(match_rule))

    def _subscribe(
        self,
        node: str,
        member: str,
        callback: Optional[Callable[[], None]] = None,
        remove: bool = False
    ) -> MsG:
        """Register or remove a match rule."""
        try:
            # Caller must ensure connection is actually up; this doesn't check
            assert self.unique_name is not None, "Not connected"
        except AttributeError as exc:
            raise AssertionError from exc
        match_rule = make_sub_rule(node, member)

        def request_cb(fut):
            res = fut.result()
            assert isinstance(res, Message)
            self._ensure_subscription_result(res)
            if callback:
                return callback()

        method = "AddMatch" if remove is False else "RemoveMatch"
        return self._send("DBus", method, request_cb, args=[match_rule])

    def _unsubscribe(self, node: str, member: str, callback: Callable) -> MsG:
        return self._subscribe(node, member, callback, remove=True)

    # By deleting filter, whatever handler (genny) was processing this should
    # exhaust immediately on the next iteration and be removed by recv
    # wrangler. Instead of this we'd ideally just throw an error into the genny
    # and let the context manager take care of closing it, but we don't
    # currently track any associations for rule:genny. One reason for this is
    # that rules are often created by the gennys themselves during the normal
    # course of execution (although that's easily remedied).
    def _cancel_subscriptions(
        self, callback: Callable[[], None], pairs=default_subs
    ) -> None:
        # It seems like the system bus normally removes match rules when their
        # owner disconnects, so this is likely superfluous.

        def b(service, member):  # bind lexically by shadowing
            def _inner():
                remove_subscription(self._filters, service, member)
                msg = f"Cancelled D-Bus subscription for {member!r}"
                self.module.put_issuer(msg)
                callback()
            return _inner

        for service, member in pairs:
            if not get_handle(self._filters, get_msggen(service), member):
                continue
            self._unsubscribe(service, member, b(service, member))

    def handle_incoming(self, msg: Message) -> None:
        if self.debug:
            assert isinstance(msg.body, tuple)
        try:
            incoming = Incoming(*msg.body)
            if not incoming.message:
                if self.debug:
                    self.logger.debug("msg_body: %r", incoming)
                return
            self.module.handle_incoming(incoming)
        except Exception:
            self.module.print_traceback()

    @property
    def has_service(self):
        return bool(self._service_unique_name)

    def _subscribe_incoming(self) -> Generator[Optional[Message], None, None]:
        """Register handler for incoming Signal messages"""
        assert self.has_service
        self.put_issuer("Signal service found")

        if not self.module.config or not self.module.config.settings["obey"]:
            return

        if self.debug:
            self.logger.debug("Adding match rule for 'MessageReceived'")
        yield from self._subscribe("Signal", "MessageReceived")
        self.put_issuer("Subscribed to incoming Signal messages")
        if self.debug:
            m = "Registering signal callback for 'MessageReceived' on 'Signal'"
            self.logger.debug(m)
        match_rule = make_sub_rule("Signal", "MessageReceived")
        message = self._send("DBus", "AddMatch", None, args=[match_rule])
        yield from message
        yield from self.troll_for_sub_forever(match_rule, self.handle_incoming)

    # TODO This probably never runs unless there's a problem. Signal used to
    # have a connection bug where it would take upwards of 30 min to connect.
    def _await_service(
        self, service_name: str
    ) -> Generator[Optional[Future], None, None]:
        self.put_issuer("Waiting for Signal service...")
        yield from self._subscribe("DBus", "NameOwnerChanged")

        if self.debug:
            m = "Subscribing to NameOwnerChanged singal on iface DBus"
            self.logger.debug(m)
        message = yield from self.add_and_await_sub(
            "DBus", "NameOwnerChanged",
        )
        if self.debug:
            assert type(message.body) is tuple
            assert len(message.body) == 3
            assert all(type(s) is str for s in message.body)
        assert message.body[0] == service_name
        assert not get_handle(
            self._filters, get_msggen("DBus"), "NameOwnerChanged"
        )
        yield from self._unsubscribe("DBus", "NameOwnerChanged")
        if self.debug:
            m = "Cancelled subscription for NameOwnerChanged on iface DBus"
            self.logger.debug(m)

    def _ensure_service(self) -> Generator[Optional[Future], None, None]:
        """Query message bus for Signal service, act accordingly

        For now, this just waits for an announcement of `name
        acquisition`__, then resumes the normal subscription sequence.

        .. __: https://dbus.freedesktop.org/doc/dbus-specification.html
           #bus-messages-name-owner-changed
        """
        service = get_msggen("Signal")
        service_name = service.bus_name

        reply = yield from self._send(
            "DBus", "NameHasOwner", None, args=(service_name,)
        )
        has_name = unsolo_result(reply)
        assert isinstance(has_name, bool)
        if self.debug:
            self.logger.debug("NameHasOwner (we own our name): %r", has_name)
        if not has_name:
            yield from self._await_service(service_name)
        # Now save the name
        reply = yield from self._send(
            "DBus", "GetNameOwner", None, args=(service_name,)
        )
        service_unique_name = unsolo_result(reply)
        assert isinstance(service_unique_name, str)
        Proxy(service, self)._set_unique_name(service_unique_name)
        self._service_unique_name = service_unique_name

    def _open_session(self) -> MsG:
        bus = Proxy(get_msggen("DBus"), self)

        if self.debug:
            self.logger.debug("Waiting for hello reply")

        hello_reply = yield from bus.Hello()

        if self.debug:
            self.logger.debug("Got hello reply: %r" % hello_reply)
        self.unique_name = unsolo_result(hello_reply)
        self.put_issuer(
            "Registered with message bus; session id is: %r" % self.unique_name
        )
        yield from self._ensure_service()
        out = yield from self._subscribe_incoming()
        # This never runs because ^ doesn't return
        return out

    def data_received(self, data):
        if self.debug:
            self.logger.debug("Feeding auth: {!r}".format(data))
        self.auth_parser.feed(data)

        if not self.auth_parser.authenticated:
            assert self.auth_parser.error is None
            output = self.auth_parser.data_to_send()
            if self.debug:
                self.logger.debug("Sending auth: {!r}".format(output))
            self.WriteBytes(output)
            return

        assert self.auth_parser.data_to_send() is None
        # Off by one, seems (data_to_send() already inhbited by done flag)
        # At this point, data startswith OK and to_send is BEGIN ...
        self.WriteBytes(self.auth_parser._to_send)
        assert not self.auth_parser.buffer
        if self.debug:
            self.logger.debug("D-Bus connection authenticated")
        self._run(self._open_session())

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

    def _continue(self):
        for g in list(self._gennies):
            try:
                next(g)
            except StopIteration:
                if self.debug:
                    self.logger.debug("Removing exhausted task: %r", g)
                self._gennies.remove(g)
            except Exception:
                self.module.print_traceback()

    def _tally_activity(self) -> str:
        """Return summary of outstanding activity """
        num_futs = len(self._replies._futures)
        num_sigs = len(self._filters.filters)
        num_gens = len(self._gennies)
        return f"Replies: {num_futs}, SigSubs: {num_sigs}, Gennys: {num_gens}"

    def data_received_post_auth(self, data):
        if self.debug:
            log_msg = []
        for msg in self.parser.feed(data):
            msg: Message
            if not self._replies.dispatch(msg):
                # Not a method reply, so must be a DBus-signal subscription
                matches = list(self._filters.matches(msg))
                for filter in matches:
                    filter.queue.append(msg)
                if self.debug and not matches:
                    self.logger.debug(get_unhandled_message(msg))
            if self.debug:
                log_msg.append(self.format_debug_msg(msg))
        if self.debug:
            log_msg = [self._tally_activity()] + log_msg
            self.logger.debug("\n".join(log_msg))
        self._continue()

    def send_message(self, message) -> MsG:
        if not self.auth_parser.authenticated:
            raise RuntimeError("Not authenticated")
        check_replyable(message)
        serial = next(self._outgoing_serial)
        out = message.serialise(serial)

        if self.debug:
            log_msg = [self._tally_activity(), self.format_debug_msg(message)]
            self.logger.debug("\n".join(log_msg))

        self.WriteBytes(out)
        with self._replies.catch(serial, Future()) as reply_fut:
            while not reply_fut.done():
                yield reply_fut
            return reply_fut.result()

    def send_and_get_reply(self, message, *, timeout=None, unwrap=None) -> MsG:
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
        if self.auth_parser.authenticated:
            return self.data_received_post_auth(data)
        self.data_received(data)

    def OnDisconnected(self):
        self._replies.drop_all()
        self._gennies.clear()
        self._service_unique_name = None
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


class Proxy(_Proxy):
    _connection: DBusConnection

    def _set_unique_name(self, name):
        self._msggen._unique_name = name


def get_tcp_address(addr):
    """Return a single host/port tuple"""
    transport, kv = next(parse_addresses(addr))
    # Unix domain sockets are not yet supported by ZNC
    # FIXME add issue/PR id above
    assert transport == "tcp"
    assert kv.get("bind") is None
    assert kv.get("family", "ipv4") == "ipv4"
    return kv["host"], int(kv["port"])


# Sometimes it's not worth having program logic wait for a signal but rather
# just throw away the handle and continue on.
def get_unhandled_message(message: Message):
    from jeepney.low_level import HeaderFields
    member = message.header.fields[HeaderFields.member]
    if member == "NameAcquired":
        # This fires before the "Hello" reply callback
        return f"Received routine opening signal: {member!r}; "
    return "See 'data_received' entry above for contents"


def generate(conn: znc.Socket, save_path: str) -> Generator[None, None, str]:
    """Dump latest Signal interface description to file.

    See ``jeepney.bindgen.generate``.

    """
    from jeepney.bindgen import code_from_xml  # type: ignore[import]
    message = yield from send_dbus_message(conn, "Signal", "Introspect", None)
    sigstub = get_msggen("Signal")
    path = sigstub.object_path
    name = sigstub.bus_name
    xml = unsolo_result(message)
    n_interfaces = code_from_xml(xml, path, name, save_path)
    return (
        "Written {} interface wrappers to {}".format(n_interfaces, save_path)
    )
