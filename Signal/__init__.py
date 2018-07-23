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

import os
import sys
import znc  # noqa: F401

if sys.version_info < (3, 6):
    raise RuntimeError("This module requires Python 3.6+")

jeepney_lib_path = os.path.join(os.path.dirname(__file__), "lib/jeepney")
if os.path.isdir(jeepney_lib_path) and sys.path[0] != jeepney_lib_path:
    while jeepney_lib_path in sys.path[:]:
        sys.path.remove(jeepney_lib_path)
    sys.path.insert(0, jeepney_lib_path)

try:
    from jeepney.auth import make_auth_anonymous  # noqa: F401
except ImportError as exc:
    if "make_auth_anonymous" in repr(exc.args):
        errmsg = ("This module requires a patched version of jeepney; "
                  "see .gitmodules for the URL")
        raise ImportError(errmsg) from exc
    else:
        raise
else:
    del make_auth_anonymous

from .ootil import GetLogger  # noqa E402
get_logger = GetLogger()
from .textsecure import Signal  # noqa E402
