# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from . import znc
from . import get_logger


class DBusConnection(znc.Socket):
    """Create a stream connection to the Signal host's message bus

    Currently, only TCP is supported.
    """
    def Init(self, *args, **kwargs):
        self.module = self.GetModule()
        self.debug = self.module.debug
        self.logger = get_logger(self.__class__.__name__)
        #
        self.__dict__.update(kwargs)
        self.unique_name = None
        #
        from jeepney.auth import SASLParser, make_auth_anonymous
        make_auth_anonymous.ALLOW = True
        self.auth_parser = SASLParser()
        #
        from jeepney.low_level import Parser
        self.parser = Parser()
        #
        from .jeepers import FakeFuture, FakeLoop
        FakeFuture.fake_loop = FakeLoop(self.module)
        #
        from jeepney.routing import Router
        self.router = Router(FakeFuture)
        #
        if self.debug:
            def on_unhandled(msg):
                self.logger.debug("Unhandled msg: {}".format(msg))

            self.router.on_unhandled = on_unhandled
        self.authentication = FakeFuture()
        self.unique_name = None

    def _open_session(self):
        from jeepney.integrate.asyncio import Proxy
        from .jeepers import get_msggen
        #
        bus = Proxy(get_msggen("DBus"), self)
        hello_reply = bus.Hello()

        def sub_cb(msg_body):
            if self.debug:
                assert isinstance(msg_body, tuple)
            from .jeepers import incoming_NT
            try:
                self.module.handle_incoming(incoming_NT(*msg_body))
            except Exception:
                self.module.print_traceback()

        def hello_cb(fut):
            if self.debug:
                self.logger.debug("Got hello reply: %r" % fut)
            self.unique_name = fut.result()[0]
            self.put_issuer("Session id is: %r. Ready." % self.unique_name)
            if self.module.config and self.module.config.settings["obey"]:
                service = get_msggen("Signal")
                try:
                    self.router.subscribe_signal(callback=sub_cb,
                                                 path=service.object_path,
                                                 interface=service.interface,
                                                 member="MessageReceived")
                    self.module.do_subscribe("Signal", "MessageReceived")
                except Exception:
                    self.module.print_traceback()

        if self.debug:
            self.logger.debug("Waiting for hello reply: %r" % hello_reply)
        #
        hello_reply.add_done_callback(hello_cb)

    def _authenticated(self):
        from jeepney.auth import BEGIN
        self.WriteBytes(BEGIN)
        self.authentication.set_result(True)
        self.data_received = self.data_received_post_auth
        self.data_received(self.auth_parser.buffer)
        self.put_issuer("D-Bus connection authenticated")
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
                from jeepney.auth import make_auth_anonymous
                self.WriteBytes(make_auth_anonymous())
                self.auth_parser.rejected = None
            else:
                self.auth_parser.error = self.auth_parser.rejected

    def data_received_post_auth(self, data):
        if self.debug:
            self.logger.debug("self.router.awaiting_reply: {}"
                              .format(self.router.awaiting_reply))
        for msg in self.parser.feed(data):
            if self.debug:
                self.logger.debug("data_received() - msg: {}"
                                  .format(msg))
            self.router.incoming(msg)

    def send_message(self, message):
        if not self.authentication.done():
            raise RuntimeError(
                "Wait for authentication before sending messages"
            )
        future = self.router.outgoing(message)
        if self.debug:
            self.logger.debug("self.router.awaiting_reply: {}"
                              .format(self.router.awaiting_reply))
            self.logger.debug("send_message: {}".format(message))
        data = message.serialise()
        self.WriteBytes(data)
        return future

    def put_issuer(self, msg):
        """Emit messages to invoking client only, if still connected

        Otherwise, target all clients, regardless of network
        """
        client = self.module.get_client(self.issuing_client)
        self.module.put_pretty(msg, putters=(client,) if client else None)

    def OnConnected(self):
        from jeepney.auth import make_auth_external
        self.WriteBytes(b'\0' + make_auth_external())
        self.put_issuer("Connected to: %s:%s" % self.bus_addr)
        self.SetSockName("DBus proxy to signal server")
        self.SetTimeout(0)

    def OnReadData(self, data):
        self.data_received(data)

    def OnDisconnected(self):
        self.put_issuer("Disconnected from %s:%s" % self.bus_addr)
        try:
            del self.module._connection
        except AttributeError:
            pass

    def OnTimeout(self):
        self.put_issuer("Connection to %s:%s timed out" % self.bus_addr)

    def OnShutdown(self):
        name = self.GetSockName()
        if self.debug:
            try:
                self.logger.debug("%r shutting down" % name)
            except ValueError as exc:
                # Only occurs when disconnect teardown is interrupted
                if "operation on closed file" not in repr(exc):
                    raise
        for handler in self.logger.handlers:
            self.logger.removeHandler(handler)
        self.module.ListSockets()

    def ConnectUnix(self, path):
        raise RuntimeError("Unix domain sockets are not yet supported")
