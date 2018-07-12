# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

"""
Notes
~~~~~

When REPLing outside of pytest/pdb, might have to drop the leading dot from
module names in import statements::

    try:
        from .spam import foo
    except ImportError:  # covers ModuleNotFoundError
        if __name__ != "__main__":
            raise
        from spam import foo

The normal way around this is to import the whole package, but we can't do that
without a live ZNC instance or a built-in (non-test) shim.


__init__.py
    If adding tests that require a real ZNC instance, run the the doctests for
    the ``CMessage`` helper, either via ``docker-exec`` or the telnet console
    using pexpect::

      >>> from Signal import cmess_helpers      # doctest: +SKIP
      >>> from doctest import \
      ...     run_docstring_examples as run     # doctest: +SKIP
      >>> run(cmess_helpers, globals())         # doctest: +SKIP
"""
import pytest


def _inject_paths():
    import os
    import sys
    from glob import glob
    #
    pat = "**/Signal/__init__.py"
    cand = glob(pat, recursive=True) or glob("../" + pat, recursive=True)
    if cand:
        pardir = os.path.dirname(os.path.dirname(cand.pop()))
        if pardir not in sys.path:
            sys.path.insert(0, pardir)


_inject_paths()


@pytest.fixture(autouse=True)
def add_configgers_namespace(doctest_namespace):
    from Signal.lexpresser import eval_boolish_json, expand_subs, ppexp
    doctest_namespace["eval_boolish_json"] = eval_boolish_json
    doctest_namespace["expand_subs"] = expand_subs
    doctest_namespace["ppexp"] = ppexp


def runner(tests, main_globals):
    """A dumb, emergency queuer for REPLing if PDB is broken

    Pretty useless, at present, because it doesn't work with fixtures.
    Better alternative would be some pytest plugin that allows
    breakpoints to be passed as pytest command-line options. This would
    spare user the hassle of injecting debug statements and cleaning
    them up afterward.
    """
    import os
    import sys

    def pwrap(local_dict, f, name):
        def pf(*args, **kwargs):
            __tracebackhide__ = True
            print(f(*args, **kwargs))
        local_dict[name] = pf

    main_globals["pwrap"] = pwrap
    sys.path.insert(0, os.path.dirname(sys.argv[0]))
    found = {v for k, v in main_globals.items() if
             k.startswith("test_") and callable(v)}
    provided = {f for f, _, __ in tests}
    for skipped in found - provided:
        print("Skipping %r" % skipped)
    for test in tests:
        func, fixtures, gen_fixtures = test
        args = []
        its = []
        # Must call all args before passing: @fixture is bunk in "__main__"
        for f in fixtures:
            args.append(f())
        for g in gen_fixtures:
            it = g()
            its.append(it)
            args.append(next(it))
        try:
            func(*args)
        finally:
            for it in its:
                try:
                    next(it)
                except StopIteration:
                    pass


def map_eq(func, *args, ref_obj=...):
    """Compare results from calling func on each arg
    >>> from types import MappingProxyType
    >>> str(MappingProxyType({}))
    '{}'
    >>> map_eq(str, MappingProxyType({}), {})
    True
    >>> repr(MappingProxyType({}))
    'mappingproxy({})'
    >>> map_eq(repr, MappingProxyType({}), {})
    False
    >>> map_eq(repr, "abc", "abc", "abc", ref_obj="'abc'")
    True
    """
    if ref_obj is not ...:
        return all_eq(ref_obj, *map(func, args))
    return all_eq(*map(func, args))


def all_eq(*args):
    """
    >>> all_eq("abc", "abc", "abc")
    True
    >>> all_eq(1, 1)
    True
    >>> all_eq(1, 0)
    False
    >>> all_eq(1)
    True
    >>> all_eq(0)
    True
    >>> all_eq()
    True
    """
    return all(a == args[0] for a in args[1:])


def same_same(*args, ref_id=None):
    cmpset = {ref_id} if ref_id else set()
    return len(set(map(id, args)) | cmpset) == 1


def any_in(haystack, *needles, pop_solo=True):
    """Return True if the first arg contains any of the rest

    pop_solo
        When ``needles`` contains a singleton, use that in its place
        (flatten).  Set to False in cases where len/type of ``needles``
        is uncertain.

    >>> def any_in_w(*args, **kw):
    ...     ids = [(id(a), a) for a in args]
    ...     result = any_in(*args, **kw)
    ...     assert ids == [(id(a), a) for a in args]
    ...     return result

    >>> hay = "abc123"
    >>> need = ["fake", "abc", "123"]
    >>> any_in_w(hay, *need)
    True
    >>> any_in_w(hay, need)
    True
    >>> hay, need = need, hay   # swap
    >>> any_in_w(hay, need)
    False
    >>> hay.append("a")
    >>> any_in_w(hay, need)
    True
    >>> need = (*need,)         # ('a', 'b', 'c', '1', '2', '3')
    >>> any_in_w(hay, need)
    True
    >>> any_in_w(hay, *need)
    True
    >>> hay = hay[:-1]          # back to one
    >>> any_in_w(hay, need)
    False
    >>> any_in_w(hay, *need)
    False

    >>> d = dict(zip("abc", "123"))
    >>> any_in_w("abc", d.keys())
    True
    >>> any_in_w("abc", *d.keys())
    True
    >>> d = {"a": "1"}
    >>> any_in_w("abc", d.keys())
    True
    >>> any_in_w("abc", *d.keys())
    True

    TODO find real version of this in standard lib
    """
    if len(needles) == 1 and pop_solo:
        needles = needles[0]
    return any(s in haystack for s in needles)


def all_in(haystack, *needles, pop_solo=True):
    """True if first arg contains all the rest

    Not the same as ``lambda H, n: set(H) >= set(n)``
    >>> H = "abc123"
    >>> n = ["abc", "123"]
    >>> all_in(H, n)
    True
    >>> n += ["fake"]
    >>> all_in(H, n)
    False
    >>> n = "123abc"
    >>> H += "4"
    >>> all_in(H, n)
    True
    >>> all_in(H, (n,))
    False
    >>> all_in(H, (*n,))
    True
    """
    if len(needles) == 1 and pop_solo:
        needles = needles[0]
    return all(s in haystack for s in needles)


from Signal.textsecure import Signal  # noqa: E402

# Ensure this isn't real ZNC
from Signal import znc as _znc  # noqa: F401
if not hasattr(_znc, "IS_MOCK"):
    raise RuntimeError("Running against real ZNC isn't yet supported")


class SignalStub(Signal):
    _using_debug = False
    _network = "dummynet"
    _user = "testdummy"
    _nick = "dummy"
    _client_ident = "dummyclient"
    _argstring = ""
    _buffer = None
    _buffer_pos = 0
    __new__ = object.__new__

    def __init__(self):
        if not self._using_debug:
            from functools import partialmethod
            self.print_traceback = partialmethod(Signal.print_traceback,
                                                 where="PutTest")
        from znc import String, ModuleNV
        self.nv = ModuleNV()
        self._OnLoad(self._argstring, String(""))

    def put_pretty(self, lines, where="PutTest"):
        # Can't partialize because calls from ``print_traceback`` would
        # pass double ``where`` kwargs
        return super().put_pretty(lines, where)

    def PutTest(self, line):
        if self._buffer is None:
            from io import StringIO
            self._buffer = StringIO()
        if line == " ":
            line = ""
        self._buffer_pos += self._buffer.write(line + "\n")

    def expand_string(self, string):
        # FIXME for now, involving this method causes problems. Bottom line:
        # more ZNC knowhow is required for simulating Module.ExpandString.
        # Version, mod-type, calling hook all affect the result, which may
        # include ignored or null substitutions.
        for pat, sub in (("%user%", self._user), ("%network%", self._network),
                         ("%nick%", self._nick)):
            string = string.replace(pat, sub)
        return string

    def _read(self):
        """Return contents of string buffer (not num bytes read)

        If no need to inspect buffer while debugging tests, can avoid
        keeping track of position and just do
        ::
            self._buffer.getvalue()
            self._buffer.seek(self._buffer.truncate(0))
        """
        if self._buffer is None:
            return ""
        self._buffer.seek(0)
        content = self._buffer.read(self._buffer_pos)
        self._buffer_pos = self._buffer.seek(0)
        return content


@pytest.fixture
def signal_stub():
    import os
    SignalStub._argstring = f"DATADIR={os.devnull}"
    stub = SignalStub()
    SignalStub._argstring = ""
    yield stub
    if stub._buffer is not None:
        stub._buffer.close()


@pytest.fixture
def signal_stub_debug(tmpdir, monkeypatch):
    import os
    #
    def gsp(self):  # noqa: E306
        return str(tmpdir)
    #
    monkeypatch.setattr(_znc.Module, "GetSavePath", gsp)
    SignalStub._using_debug = True
    os.environ["SIGNALMOD_DEBUG"] = "1"
    stub = SignalStub()
    SignalStub._using_debug = False
    del os.environ["SIGNALMOD_DEBUG"]
    yield stub
    stub._OnShutdown()
    del stub.env["LOGFILE"]
    if stub._buffer is not None:
        stub._buffer.close()


if __name__ == "__main__":
    import doctest
    doctest.testmod()
