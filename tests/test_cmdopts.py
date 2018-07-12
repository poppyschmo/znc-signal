# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from conftest import signal_stub
signal_stub = signal_stub

# TODO add tests for HelpFormatterMod


def test_initialize_all():
    from Signal.cmdopts import apwrights, initialize_all
    #
    # All .p attrs initialized to None
    assert all(hasattr(a, "p") for a in apwrights)
    assert not any(getattr(a, "p", None) for a in apwrights)
    #
    initialize_all(update=dict(datadir="/tmp/baz"))
    assert all(a.p for a in apwrights)
    assert "/tmp/baz" in apwrights.update.p.format_help()
    #
    # Toggle 'debug' attr on non-debug makers
    norms = [f for f in apwrights._fields if not f.startswith("debug_")]
    assert norms
    assert not any(getattr(apwrights, f).debug for f in norms)
    initialize_all(True)
    assert all(getattr(apwrights, f).debug for f in norms)


def test_suspect_serial_data_string():
    # See test_config.test_update_config_dict for other SerialSuspect stuff
    from Signal.cmdopts import SerialSuspect, strip_suspect, RAWSEP
    assert isinstance(SerialSuspect("some string"), str)
    some_string = strip_suspect(f'{RAWSEP} "some string"')  # strips @@
    assert some_string == strip_suspect(f'{RAWSEP}"some string"')
    assert some_string != SerialSuspect("some string")
    assert some_string == SerialSuspect('"some string"')
    assert some_string == '"some string"'
    assert some_string(True) == "some string"
    assert some_string(True, True) == ["some string"]


def test_apwrights():
    """
    Caching argparse objects couldn't hurt, but usage is only requested
    infrequently

    >>> from timeit import timeit
    >>> setup = "existing = apwrights.debug_cons()"
    >>> a = timeit("existing.format_help()", setup=setup,
    ...            number=100000, globals=locals())
    >>> b = timeit("apwrights.debug_cons().format_help()",
    ...            number=100000, globals=locals())
    >>> assert b / a < 2.2
    """
    # XXX coverage limited to a few import-time tasks; could definitely be
    # improved
    from Signal.cmdopts import apwrights, patch_epilog
    # Named tuple membership and @wraps attr surgery
    assert [f.__name__ for f in apwrights] == """
        cmd_help        cmd_connect
        cmd_disconnect  cmd_select
        cmd_update      cmd_debug_args
        cmd_debug_cons  cmd_debug_expr
        cmd_debug_fail  cmd_debug_send
    """.split()  # apwrights is populated at import time
    #
    # Calling with kwargs updates partialized bindings
    apwrights.update(datadir="/tmp/foo")
    assert "/tmp/foo" in apwrights.update.p.format_help()
    apwrights.update()
    assert "/tmp/foo" in apwrights.update.p.format_help()
    assert apwrights.update.p.format_help().count("/tmp/foo") == 1
    apwrights.update(datadir="/tmp/bar")
    assert "/tmp/foo" not in apwrights.update.p.format_help()
    assert "/tmp/bar" in apwrights.update.p.format_help()
    assert apwrights.update.kwargs["datadir"] == "/tmp/bar"
    apwrights.update.p = None
    #
    # Epilog patch is idempotent
    apwrights.debug_cons()  # applied once on ``.p`` init
    epilog = apwrights.debug_cons.p.epilog
    patch_epilog(apwrights.debug_cons.p, apwrights.debug_cons.aliases)
    assert epilog == apwrights.debug_cons.p.epilog
    assert "Aliases: 'cons', 'console'" in epilog
    apwrights.debug_cons.p = None


def test_refresh_help_defaults(signal_stub):
    sig = signal_stub
    sig.cmd_select()
    assert "Traceback" not in sig._read()
    defaults = ("localhost", "47000")
    curhelp = sig.approx.connect.format_help()
    assert all(s in curhelp for s in defaults)
    sig.cmd_update("/settings/host", "signal.example.com")
    sig.cmd_update("/settings/port", "8888")
    from conftest import any_in
    assert not any_in(sig._read().lower(), "traceback", "problem", "error")
    sig.refresh_help_defaults()
    newhelp = sig.approx.connect.format_help()
    assert "default: 8888" in newhelp
    assert "signal.example.com" in newhelp


def test_parser_proxy():
    from Signal.cmdopts import initialize_all, apwrights, AllParsed
    initialize_all()
    apos = [apw.p for apw in apwrights]
    parsers = AllParsed(debug=True)
    assert list(parsers._all) == apos
    from conftest import same_same
    assert parsers.cons in apos
    # access
    for p in (parsers(False, False), parsers(False, True),
              parsers(True, False), parsers(True, True)):
        assert same_same(apwrights.debug_cons.p,
                         p.debug_cons, parsers["debug_cons"],
                         p.cmd_debug_cons, parsers["cmd_debug_cons"],
                         p.cmd_console, parsers["cmd_console"],
                         p.cons, parsers["cons"],
                         p.console, parsers["console"])
        assert (a in p for a in ("debug_cons", "cmd_debug_cons",
                                 "cmd_console", "cons", "console"))
    unprefixed = list(apwrights._fields)
    assert list(parsers(False)) == unprefixed
    prefixed = list(f"cmd_{n}" for n in apwrights._fields)
    assert list(parsers(True)) == prefixed
    from Signal.cmdopts import debug_aliases
    from conftest import all_in, map_eq
    assert all_in(parsers, *debug_aliases)
    assert unprefixed == list(parsers(False)) == [p.prog for p in apos]
    assert parsers(True).items() == dict(zip(prefixed, apos)).items()
    assert parsers(False).items() == dict(zip(unprefixed, apos)).items()
    #
    # TODO change ref_obj kwarg name to "expect"
    assert map_eq(parsers.encmd,
                  "cmd_cons",
                  "cmd_console",
                  "cons",
                  "console",
                  "debug_cons",
                  ref_obj="cmd_debug_cons")
    # No validation is performed
    assert parsers.encmd("fake") == "cmd_fake"
    assert parsers.encmd("debug_fake") == "cmd_debug_fake"
    assert parsers.decmd("fake") == 'fake'
    assert parsers.decmd("cmd_fake") == 'fake'
    assert parsers.decmd("debug_fake") == 'debug_fake'
    assert parsers.decmd("cmd_debug_fake") == 'debug_fake'
    # debug toggle
    prod = parsers(False, debug=False).keys()
    assert prod and not any(k.startswith("debug_") for k in prod)
    assert prod == {f for f in apwrights._fields if not f.startswith("debug_")}
    buggers = set(unprefixed) - prod
    assert buggers and buggers == {f for f in apwrights._fields if
                                   f.startswith("debug_")}
    # eq
    assert parsers == parsers(False, True)
    assert parsers != parsers(False, debug=False)
    assert parsers != parsers(prefixed=True)
    assert parsers != parsers(True, True)
