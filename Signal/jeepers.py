# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

"""
Miscellaneous objects for the DBus connection
"""
# XXX shocking/sad didn't grok static typing at all back whenever this file was
# last touched. Too scared to look. Too lazy to fix.

from jeepney.io.common import MessageFilters, FilterHandle  # type: ignore[import]  # noqa: E501
from jeepney.bus_messages import MatchRule  # type: ignore[import]
from jeepney.wrappers import MessageGenerator, new_method_call  # type: ignore[import]  # noqa: E501
from typing import List, Union, Optional
from collections import namedtuple

from ._generated import Signal as SignalMGRaw

Incoming = namedtuple("Incoming",
                      "timestamp source groupID message attachments")

EMPTY = object()


class SignalMG(SignalMGRaw):
    """Codegen with overloaded methods overridden

    """
    _unique_name: Optional[str]

    def isRegistered(self, arg0=EMPTY):
        if arg0 is EMPTY:
            return new_method_call(self, 'isRegistered')
        return new_method_call(self, 'isRegistered', 's', (arg0,))

    def sendMessage(
        self,
        message: str,
        attachments: List[str],
        recip: Union[str, List[str]]
    ):
        signature = "sass" if isinstance(recip, str) else "sasas"
        return new_method_call(
            self, 'sendMessage', signature, (message, attachments, recip)
        )

    def sendRemoteDeleteMessage(
        self,
        arg0,
        arg1: Union[str, List[str]]
    ):
        sig = "xs" if isinstance(arg1, str) else "xas"
        return new_method_call(
            self, 'sendRemoteDeleteMessage', sig, (arg0, arg1)
        )

    def sendMessageReaction(
        self,
        arg0,
        arg1,
        arg2,
        arg3,
        arg4: Union[str, List[str]]
    ):
        sig = "sbsxs" if isinstance(arg4, str) else "sbsxas"
        return new_method_call(
            self,
            'sendMessageReaction',
            sig,
            (arg0, arg1, arg2, arg3, arg4)
        )


signal_service = SignalMG()


def get_msggen(name):
    """Return a MessageGenerator instance for D-Bus object <name>"""
    if name == "Signal":
        mg = signal_service
    elif name == "DBus":
        from jeepney.bus_messages import message_bus  # type: ignore[import]
        mg = message_bus
    elif name in ("Stats", "Monitoring"):
        import jeepney.bus_messages as bm  # type: ignore[import]
        mg = getattr(bm, name)()
    else:
        raise ValueError("Unable to determine target object")
    return mg


def get_handle(
    filters: MessageFilters,
    service: MessageGenerator,
    member: Optional[str]
) -> Optional[FilterHandle]:
    for handle in filters.filters.values():
        fields = handle.rule.header_fields
        if fields["sender"] != service.bus_name:
            continue
        if fields["interface"] != service.interface:
            continue
        if member and fields["member"] != member:
            continue
        if fields["path"] != service.object_path:
            continue
        return handle
    return None


def make_sub_rule(node: str, member: str) -> MatchRule:
    service = get_msggen(node)
    return MatchRule(
        type="signal",
        sender=getattr(service, "_unique_name", service.bus_name),
        interface=service.interface,
        member=member,
        path=service.object_path
    )


def remove_subscription(
    filters: MessageFilters,
    service_name: Optional[str] = None,
    member: Optional[str] = None
) -> None:
    """Remove a DBus signal subscription

    Without ``member``, remove all subscriptions registered to
    object described by ``service_name``.

    """
    if service_name is None:
        filters.clear()
        return
    service = get_msggen(service_name)
    handle = get_handle(filters, service, member)
    if handle:
        handle.close()
