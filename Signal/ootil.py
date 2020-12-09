# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import sys
import pprint
import logging
import reprlib
from importlib.util import module_from_spec

ordered_pprint = module_from_spec(pprint.__spec__)
pprint.__loader__.exec_module(ordered_pprint)
sys.modules["ordered_pprint"] = ordered_pprint

ordered_reprlib = module_from_spec(reprlib.__spec__)
reprlib.__loader__.exec_module(ordered_reprlib)
sys.modules["ordered_reprlib"] = ordered_reprlib


class cmp_falso:
    __slots__ = ['obj']

    def __init__(self, obj):
        self.obj = obj

    def __lt__(self, other):
        return False


def _safe_tuple(t):
    """Call cmp_falso instead of _safe_key.

    Not sure how stable this is, but the original ``_safe_key`` still
    gets called by ``_pprint_set``.
    """
    return cmp_falso(t[0]), cmp_falso(t[1])


def _possibly_sorted(x):
    """Bypass the sorted() call in reprlib._possibly_sorted

    This is mostly for ensuring reproducibility in tests.
    """
    return list(x)


ordered_pprint._safe_tuple = _safe_tuple
OrderedPrettyPrinter = ordered_pprint.PrettyPrinter

ordered_reprlib._possibly_sorted = _possibly_sorted
OrderedRepr = ordered_reprlib.Repr


_logger_fmt = (
    "{dark}[%(asctime)s]{norm} {dim}%(name)s.%(funcName)s:{norm} %(message)s"
)


# FIXME wtf is all this nonsense? honestly.
class GetLogger:
    """Attach a single, common handler to the default logger

    Note: not sure why, but the (built-in) asyncio logging facility is
    only reliably enabled when the asyncio module has already been
    imported into the calling namespace (before calling this func)
    """
    LEVEL = "DEBUG"
    LOGFILE = None
    handler_name_fmt = "{name} (DEBUG)"
    handler_name = None
    _escapes = {
        "dark": "\x1b[38;5;241m",
        "dim": "\x1b[38;5;247m",
        "norm": "\x1b[m",
    }

    def __init__(self, level=None, logfile=None, handler_name=None, loop=None):
        self.LOGFILE = logfile
        self.LEVEL = level or self.LEVEL
        self.handler_name = handler_name
        self._handler = None
        self._formatter = None

    def get_formatter(self):
        if self._formatter is not None:
            return self._formatter
        tty = self.LOGFILE and self.LOGFILE.isatty()
        escapes = self._escapes if tty else dict(dark="", dim="", norm="")
        self._formatter = logging.Formatter(_logger_fmt.format(**escapes))
        return self._formatter

    def get_handler(self):
        if self._handler is not None:
            self.block_till_ready()
            return self._handler
        if self.LOGFILE.isatty():
            self._handler = logging.StreamHandler(stream=self.LOGFILE)
        else:
            self.LOGFILE.close()
            self._handler = logging.FileHandler(self.LOGFILE.name)
            self.LOGFILE = self._handler.stream
        self._handler.set_name(self.handler_name)
        # self._handler.setLevel(self.LEVEL)
        self._handler.setFormatter(self.get_formatter())
        self.block_till_ready()
        return self._handler

    def configure(self, file, level=None):
        self.LOGFILE = file
        if level is not None:
            if isinstance(level, int):
                level = logging.getLevelName(level)
            assert hasattr(logging, level)
        else:
            level = self.LEVEL

        self.handler_name = self.handler_name_fmt.format(
            name=self.LOGFILE.name
        )

        logging.root.handlers.clear()
        logging.basicConfig(
            level=level,
            handlers=[self.get_handler()]
        )

    def __call__(self, name, level=None):
        """Return the default logger

        This should only be called if ``logging.getLogger`` isn't doing
        the right thing.
        """
        return logging.getLogger(name)

    # FIXME remove this at call sites
    def clear(self):
        """Sequence to close handler and remove local reference"""
        if not self.handler_name:
            return
        logging._acquireLock()
        try:
            logging.root.handlers.clear()
            if not self._handler:
                pass
            elif isinstance(self._handler, logging.FileHandler):
                self._handler.close()
            elif hasattr(self._handler, "stream"):
                if hasattr(self._handler.stream, "flush"):
                    self._handler.stream.flush()
                self._handler.stream.close()
            if not self.LOGFILE.closed:
                raise RuntimeError(f"Could not close {self.LOGFILE}")
            self.__init__()
        finally:
            logging._releaseLock()

    def block_till_ready(self):
        # TODO ensure this still applies; this was moved from the main init
        # hook, but may no longer make sense. Formerly observed behavior:
        #
        #   The first few writes to LOGFILE are blackholed when reloading
        #   (unless modpython is also reloaded). This seems to force its hand
        #   (at least on Linux w. ZNC 1.6.6).
        #
        import os
        from io import TextIOWrapper
        if (not os.sys.platform.startswith("linux") or not
                hasattr(self._handler, "stream") or not
                isinstance(self._handler.stream, TextIOWrapper)):
            return
        try:
            self._handler.flush()
        except ValueError:
            # Stale handlers may linger if ZNC recently crashed
            assert self._handler.stream.closed
            self._handler = None
            raise
        import select
        poll = select.poll()
        poll.register(self._handler.stream.fileno())
        maxtries = 10000
        while maxtries:
            for tup in poll.poll(0):
                fd, event = tup
                if select.POLLOUT & event:
                    return
            maxtries -= 1
        raise RuntimeError(f"Timed out waiting for I/O on {self.LOGFILE!r}")


def get_tz():
    """Ask Python for tzinfo from system or env

    Change timezone for some datetime object::
        mydt.astimezone(tz=get_tz())
    """
    import time
    import datetime
    lt = time.localtime()  # <- apparently calls tzset()
    try:
        # Docs say to use localtime() for system/env tz facts instead of
        # something like ``time.tzname[time.daylight]``
        return datetime.timezone(datetime.timedelta(seconds=lt.tm_gmtoff),
                                 name=lt.tm_zone)
    except Exception:
        return None


def timestr2dt(in_string):
    """Given some tz-suffixed ISO-8601/RFC-3339-like string, try to
    return a datetime object. Unsuitable for production.

    >>> dt = timestr2dt("2014-05-01T12:00:00.123456+0000")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=....utc)
    >>> print(dt)
    2014-05-01 12:00:00.123456+00:00
    >>> dt.isoformat()
    '2014-05-01T12:00:00.123456+00:00'
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01 12:00:00.123Z")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123000, tzinfo=....utc)
    >>> print(dt)
    2014-05-01 12:00:00.123000+00:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01 12:00:00.123456+0000")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=....utc)
    >>> print(dt)
    2014-05-01 12:00:00.123456+00:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01T12:00:00.123456+01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=...3600)))
    >>> print(dt)
    2014-05-01 12:00:00.123456+01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01T12:00:00.123456-01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=...82800)))
    >>> print(dt)
    2014-05-01 12:00:00.123456-01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01 12:00:00.123456789-01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123457, tzinfo=...82800)))
    >>> print(dt)
    2014-05-01 12:00:00.123457-01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01 12:00:00,123456789-01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123457, tzinfo=...82800)))
    >>> print(dt)
    2014-05-01 12:00:00.123457-01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    TODO add exceptions, different locale, etc.
    """
    from datetime import datetime
    if in_string.endswith("Z"):
        in_string = "{}+00:00".format(in_string[:-1])
    rest = in_string
    parts = []
    try:
        for delims in ("T ", ",.", "+-"):
            found = [c for c in delims if c in rest]
            if len(found) != 1:
                raise ValueError
            *save, rest = rest.partition(found.pop())
            parts.extend(save)
    except Exception:
        return
    else:
        parts.append(rest)
    date_str, sep, time_str, punct, frac, sign, off = parts
    #
    if ":" in off:  # < 3.7 compat
        off = off.replace(":", "")
    #
    # Truncate ns to µs
    if len(frac) > 6:
        frac = str(round(float(frac)/10**len(frac), 6))[2:]
    reconst = "".join((date_str, sep, time_str, punct, frac, sign, off))
    fmtstr = f"%Y-%m-%d{sep}%H:%M:%S{punct}%f%z"
    try:
        return datetime.strptime(reconst, fmtstr)
    except Exception:
        return None


def restring(rec):
    """(Re-)serialize str or JSON-like obj in compact (minified) form"""
    import json
    if isinstance(rec, str):
        rec = json.loads(rec)
    return json.dumps(rec, separators=(",", ":"))


def backwrap(itb, sep=None, width=None):
    r"""Combine strings from a sequence, capping width at that of first

    Returns a generator producing the combined strings. Otherwise acts
    like textwrap.wrap but ingests a sequence of strings and preserves
    their whitespace.

    >>> import sys
    >>> if sys.modules.get("this"):
    ...     raw = getattr(sys.modules["this"], "rots", None)
    ...     if raw is None:
    ...         import codecs
    ...         raw = codecs.encode(sys.modules["this"].s, "rot_13")
    ...         setattr(sys.modules["this"], "rots", raw)
    ... else:
    ...     from contextlib import redirect_stdout
    ...     from io import StringIO
    ...     with StringIO() as buf:
    ...         with redirect_stdout(buf):
    ...             import this
    ...             raw = buf.getvalue()
    ...     setattr(sys.modules["this"], "rots", raw)

    >>> first, *rest = [l for l in raw.split("\n") if l]
    >>> left, rest = [l.split(None, l.count(" ")*2//3) for
    ...               l in rest[:9]], rest[9:]
    >>> right, rest = [l.rsplit(None, l.count(" ")*2//3) for
    ...                l in rest[:9]], rest[9:]
    >>> lines = sum((*left, *right, *(l.split() for l in rest)), [first])

    >>> lines  # doctest: +ELLIPSIS
    ['The Zen of Python, by Tim Peters', 'Beautiful', 'is', ... 'those!']
    >>> list(backwrap([]))
    []
    >>> list(backwrap(["foo"]))
    ['foo']
    >>> lines[5:11] == ['is',
    ...                 'better than implicit.',
    ...                 'Simple',
    ...                 'is',
    ...                 'better than complex.',
    ...                 'Complex']
    True
    >>> list(backwrap(lines))[:4][-1]
    'better than implicit. Simple is'
    >>> list(backwrap(lines))[:5][-1]
    'better than complex. Complex is'

    Use textwrap to render expected output
    >>> def checker(lines):
    ...     used = set.union(*(set(p) for p in lines))
    ...     whites = " \t\n\v\f\r"
    ...     holders = []
    ...     for i in range(1, 0x10ffff):
    ...         c = chr(i)
    ...         if not c.isprintable() or c.isspace():
    ...             continue
    ...         if c not in used:
    ...             holders.append(c)
    ...         if len(holders) == len(whites):
    ...             break
    ...     #
    ...     def replace_all(lines, pats, subs):
    ...         def sub_all(line):
    ...             for pat, sub in zip(pats, subs):
    ...                 line = line.replace(pat, sub)
    ...             return line
    ...         return [sub_all(l) for l in lines]
    ...     #
    ...     replaced = replace_all(lines, whites, holders)
    ...     from textwrap import wrap
    ...     wrapped = wrap(" ".join(replaced),
    ...                    width=len(lines[0]),
    ...                    expand_tabs=False,
    ...                    replace_whitespace=False,
    ...                    break_long_words=False,
    ...                    break_on_hyphens=False)
    ...     return replace_all(wrapped, holders, whites)

    >>> list(backwrap(lines)) == checker(lines)
    True
    >>> all(list(backwrap(lines[:i])) == checker(lines[:i])
    ...     for i in range(1, len(lines)))
    True
    >>> [lines[0]] + list(backwrap(lines[1:],
    ...                            width=32)) == checker(lines)
    True
    >>> list(backwrap(lines, width=32)) == checker(lines)
    True

    Lines exceeding a provided width are left alone
    >>> " ".join(lines) == " ".join(backwrap(lines, width=20))
    True
    >>> ([l for l in lines if len(l) > 20] ==
    ...  [l for l in backwrap(lines, width=20) if len(l) > 20])
    True
    """
    sep = " " if sep is None else sep
    it = iter(itb)
    if width:
        first = None
    else:
        first = next(it, None)
        width = len(first) if first is not None else -1
    #
    def inner(it):  # noqa: E306
        if first is not None:
            yield first
        r = []
        for c in it:
            if len(sep.join(r + [c])) <= width:
                r.append(c)
            else:
                if r:
                    yield sep.join(r)
                r = [c]
        if r:
            yield sep.join(r)
    return inner(it)


def cacheprop(f):
    """Wrapper for caching/shadowing dynamic attrs when first retrieved

    Requires an instance ``__dict__``
    """
    # Not sure if there's a conventional idiom for this (or some ready-made
    # analog in the standard library)
    class Cached:
        """A "self-effacing," cache-on-call descriptor

        Use ``del instance.f`` to reset
        """
        def __get__(self, instance, inst_cls):
            if not instance:
                return self
            rv = f(instance)
            instance.__dict__[f.__name__] = rv
            return rv
    return Cached()


def unescape_unicode_char(raw):
    """Literalize a single Unicode-escape-like sequence or code-point
    """
    out = raw
    low = raw.lower()
    unslashed = low.lstrip("\\")
    if (low.startswith("u+") or (unslashed != low and unslashed and
                                 unslashed[0] in "ux")):
        out = raw.lstrip("\\Uux+")
    if out == raw and len(out) > 1:
        # Otherwise "ab" -> '«', and "42" -> 'B'
        raise ValueError("Arg <raw> must be a single character")
    return len(out) == 1 and out or chr(int(out, 16))
