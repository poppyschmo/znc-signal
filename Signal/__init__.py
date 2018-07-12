# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.
r"""
A smoother debugging experience can be had by logging to a tty rather than a
disk file.  Do this by passing ``LOGFILE=<path>`` as a module arg or exporting
it as an env var with: ``SIGNALMOD_LOGFILE``.  If ZNC's not running as root,
you might have mess with file permissions::

    # docker exec -t my_znc_container /bin/sh -c \
    >     'c=$(tty); test -c $c && chmod -v o+w $c && exec cat $c'

    mode of '/dev/pts/2' changed to 0622 (rw--w--w-)
                      ^

    [*status] LoadMod Signal DEBUG=1 LOGFILE=/dev/pts/2

"""

import sys
import znc


def _zip_inject(pack_name, glob_pat=None):
    """Find and load a wheel package from the ususal ZNC module dirs

    Doesn't seem like ZNC likes dynamically loading zip archives
    inserted into ``sys.path``. Might be ``imp``-related.
    """
    import os
    from glob import iglob
    from itertools import chain
    from zipimport import zipimporter
    from importlib import invalidate_caches
    #
    if glob_pat is None:
        glob_pat = "**/%s*.whl" % pack_name
    #
    dirs = chain.from_iterable(znc.CModules.GetModDirs())
    candidates = chain.from_iterable(
        iglob(os.path.join(p, glob_pat), recursive=True) for p in dirs
    )
    #
    candidate = next(candidates)
    invalidate_caches()
    try:
        loader = zipimporter(candidate)
        m = loader.load_module(pack_name)
        assert sys.modules[pack_name] is m
    except Exception as exc:
        candidates = set(candidates) - {candidate}
        if not candidates:
            raise
        msg = ("Problem loading package archive %r. Possibly related to "
               "trying %r instead of %r. Also see previous exception.")
        msg = msg % (pack_name, candidate, candidates)
        raise RuntimeError(msg) from exc


# Load the DBus library
_zip_inject("jeepney")

if sys.version_info < (3, 6):
    raise RuntimeError("This module requires Python 3.6+")


cmess_helpers = None
if hasattr(znc, "CMessage"):  # helpers for CMessage in 1.7.0-rc1

    def _get_params(instance):
        """Kludge for CMessage.GetParams()"""
        params = instance.GetParams()
        vout = []
        for i, p in enumerate(params):
            p.disown()  # <- relevant line
            vout.append(instance.GetParam(i))
        return tuple(vout)

    from collections import namedtuple
    cmess_helpers_NT = namedtuple("CMessageHelpers", "types get_params")
    cmess_helpers_NT.__doc__ += r"""
    >>> mymsg = znc.CMessage(":irc.znc.in PONG irc.znc.in test_server")
    >>> mymsg.GetParams()  # doctest: +ELLIPSIS +SKIP
    (<Swig Object of type 'unknown' at 0x...>, <Swig Object ...>)
    >>> cmess_helpers.get_params(mymsg)
    ('irc.znc.in', 'test_server')
    >>> cmess_helpers.types(mymsg.GetType())
    <CMessage::Type.Pong: 16>
    >>> cmess_helpers.types(16) == cmess_helpers.types.Pong == \
    ...     cmess_helpers.types["Pong"] == _
    True

    Note: running the above without the ``+SKIP`` directive produces
    this friendly log message::

        swig/python detected a memory leak of type 'unknown', ...
            no destructor found.

    Actually, the lack of log formatting suggests it's just dumped
    straight to the out stream.
    """
    from enum import Enum
    cmess_helpers = cmess_helpers_NT(
        Enum("CMessage::Type",
             ((k.split("_", 1)[-1], v) for
              k, v in vars(znc.CMessage).items() if
              k.startswith("Type_"))),
        _get_params
    )


from .ootil import GetLogger  # noqa E402
get_logger = GetLogger()
from .textsecure import Signal  # noqa E402
