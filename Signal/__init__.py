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
import znc  # noqa: F401

from pathlib import Path

if sys.version_info < (3, 6):
    raise RuntimeError("This module requires Python 3.6+")

jeepney_lib_path = (Path(__file__).parent / "lib/jeepney").resolve(True)
sys.path = [str(jeepney_lib_path)] + [p for p in sys.path if
                                      Path(p).resolve() != jeepney_lib_path]


from .ootil import GetLogger  # noqa E402
get_logger = GetLogger()
from .textsecure import Signal  # noqa E402
