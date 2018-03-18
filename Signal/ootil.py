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


def get_logger(name, level=None, logfile=None, loop=None):
    """Attach a common handler to a default logger

    Optional function attributes
        LOGFILE : file-like-object (io.IOBase)
        handler_name : str

    Note: not sure why, but the (built-in) asyncio logging facility is
    only reliably enabled when the asyncio module has already been
    imported into the calling namespace (before calling this func)
    ::
        >>> import asyncio
        >>> import io
        >>> cap = io.StringIO()
        >>> get_logger("asyncio", "DEBUG", cap)
        <Logger asyncio (DEBUG)>
        >>> async def bar():
        ...     pass
        >>> async def foo():
        ...     bar()
        >>> asyncio.get_event_loop().run_until_complete(foo())

        # Check formatter
        >>> 'asyncio.__del__: <CoroWrapper bar()' in cap.getvalue()
        True

        # Check exc
        >>> 'never yielded from' in cap.getvalue()
        True
        >>> cap.close()
    """
    # TODO: Add exit handler or context manager (for main() or exe).
    #
    # NOTE re func attrs: ugly for sure, but would otherwise have to nest
    # LOGFILE in another global to spare caller from having to import this
    # module's namespace just to update LOGFILE. Could also change this func
    # to a class or use env vars.
    LOGFILE = getattr(get_logger, "LOGFILE", None)
    #
    if logfile is None:
        if LOGFILE is None:
            return logging.getLogger(name)
        else:
            logfile = LOGFILE
    #
    if level is not None:
        if isinstance(level, int):
            level = logging.getLevelName(level)
        assert hasattr(logging, level)
    else:
        level = "DEBUG"
    #
    logger = logging.getLogger(name)
    if name == "asyncio":
        if loop is None:
            from asyncio import get_event_loop
            loop = get_event_loop()
        loop.set_debug(1)
        logging.captureWarnings(True)
    #
    handler_name = getattr(get_logger, "handler_name",
                           "get_logger.LOGFILE (DEBUG)")
    if any(h.get_name() == handler_name for h in logger.handlers):
        return logger
    #
    escapes = dict(dark="", dim="", norm="")
    if logfile.isatty():
        # Assume 256-color term w. dark bg (v-console shouldn't explode)
        escapes.update(dark="\x1b[38;5;241m",
                       dim="\x1b[38;5;247m",
                       norm="\x1b[m")
    fmt = ("{dark}[%(asctime)s]{norm} {dim}%(name)s"
           ".%(funcName)s:{norm} %(message)s")
    formatter = logging.Formatter(fmt.format(**escapes))
    handler = logging.StreamHandler(stream=logfile)
    handler.set_name(handler_name)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)  # str or int
    return logger


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

    >>> dt = timestr2dt("2014-05-01 12:00:00.123456+0000")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=....utc)
    >>> print(dt)
    2014-05-01 12:00:00.123456+00:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01T12:00:00.123456+01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=...(0, 3600)))
    >>> print(dt)
    2014-05-01 12:00:00.123456+01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01T12:00:00.123456-01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123456, tzinfo=...(-1, 82800)))
    >>> print(dt)
    2014-05-01 12:00:00.123456-01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01 12:00:00.123456789-01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123457, tzinfo=...(-1, 82800)))
    >>> print(dt)
    2014-05-01 12:00:00.123457-01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    >>> dt = timestr2dt("2014-05-01 12:00:00,123456789-01:00")
    >>> dt  # doctest: +ELLIPSIS
    datetime.datetime(2014, 5, 1, 12, 0, 0, 123457, tzinfo=...(-1, 82800)))
    >>> print(dt)
    2014-05-01 12:00:00.123457-01:00
    >>> timestr2dt(dt.isoformat()) == timestr2dt(str(dt)) == dt
    True

    TODO add exceptions, different locale, etc.
    """
    from datetime import datetime
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
