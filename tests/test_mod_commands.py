# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import pytest

from conftest import signal_stub
from Signal.ootil import restring


def wrap_mod_command(stub, cmd, strip=True, rv=None):
    if rv is None:
        import znc
        rv = znc.CONTINUE

    def wrapped(*args, **kwargs):
        assert rv == cmd(*args, **kwargs)
        output = stub._read()
        if strip:
            output = output.rstrip("\n")
        return output
    return wrapped


def test_OnModCommand(signal_stub, signal_stub_debug):
    """
    For now, see ``test_cmd_debug_args`` for command-line parsing stuff
    """
    # Note: ``parser`` is initialized in ``_OnLoad``
    sig = signal_stub
    # Commands w. "debug_" are only honored when the debug attr is True
    assert not signal_stub.debug
    assert all(s.startswith("cmd_debug_") for
               s in sig.approx(True).keys() ^ sig.mod_commands.keys())
    # Attempt to run debug command fails
    sig._OnModCommand("debug_args debug_fail ValueError 'some msg'")
    assert sig._read().startswith("Invalid command; for debug-related ")
    #
    sig = signal_stub_debug
    # Invalid command (different msg)
    sig._OnModCommand("fake_command 'fake arg'")
    assert sig._read() == "Invalid command\n"
    # All debug commands are recognized
    assert not sig.approx(True).keys() ^ sig.mod_commands.keys()
    # Exceptions during call to associated method are caught
    sig._OnModCommand("debug_fail ValueError 'some msg'")
    assert sig._read() == ""  # Nothing Put when debug is active
    with open(sig.env["LOGFILE"]) as flo:
        output = flo.read().strip()
    assert output.splitlines()[-1] == 'ValueError: some msg'
    assert (sig.last_traceback.tb_frame.f_locals["argv"] ==
            ['debug_fail', 'ValueError', 'some msg'])


def test_cmd_debug_args(signal_stub_debug):
    """
    This command is pretty tightly coupled to ``parse_command_args`` and
    ``OnModCommand``. For now, this test is a catch-all for these and
    possibly others.
    """
    import json
    sig = signal_stub_debug
    prefix = "debug_args debug_send %s"
    # Python
    line = "Signal sendMessage @@ 'hello', [], '+18885551212'"
    sig._OnModCommand(prefix % line)
    o_norm = json.loads(sig._read())
    assert o_norm == {
        'passed': ['Signal', 'sendMessage', "@@ 'hello', [], '+18885551212'"],
        'parsed': {'as_json': False, 'node': 'Signal', 'method': 'sendMessage',
                   'raw_string': "'hello', [], '+18885551212'"},
        'evaled': ['hello', [], '+18885551212']
    }
    # Invalid JSON  (single '')
    line = "--json Signal sendMessage @@ 'hello', [], '+18885551212'"
    sig._OnModCommand(prefix % line)
    err_output = sig._read()  # <- error message printed first
    o_invalid_json = json.loads(err_output.split("\n", 1)[-1])
    assert o_invalid_json["parsed"]["as_json"] is True
    assert o_invalid_json["evaled"][0].startswith("ValueError")
    #
    # Valid JSON
    line = '--json Signal sendMessage @@ "hello", [], "+18885551212"'
    sig._OnModCommand(prefix % line)
    o_valid_json = json.loads(sig._read())
    assert o_valid_json["parsed"]["as_json"] is True
    assert o_valid_json["evaled"] == o_norm["evaled"]
    #
    # The real update command does not enclose raw string in []
    prefix = "debug_args update %s"
    line = '/expressions/custom @@ {"! i has": "foo"}'
    sig._OnModCommand(prefix % line)
    o_valid_exp = json.loads(sig._read())
    assert o_valid_exp == {
        'passed': ['/expressions/custom', '@@ {"! i has": "foo"}'],
        'parsed': {'reload': False,
                   'remove': False,
                   'rename': False,
                   'arrange': False,
                   'as_json': False,
                   'force': False,
                   'export': False,
                   'path': '/expressions/custom',
                   'value': '{"! i has": "foo"}'},
        'evaled': [{'! i has': 'foo'}]
    }
    # The second of two sequential optional args (see cmd_update's help
    # [<path>] [<value>]) is still interpreted as an @@ strings if the first is
    # absent (meaning the second is actually absent)
    line = '@@ {"! i has": "foo"}'
    sig._OnModCommand(prefix % line)
    assert json.loads(sig._read()) == {
        'passed': ['@@ {"! i has": "foo"}'],
        'parsed': {'arrange': False,
                   'as_json': False,
                   'export': False,
                   'force': False,
                   'path': '{"! i has": "foo"}',
                   'reload': False,
                   'remove': False,
                   'rename': False,
                   'value': None},
        'evaled': [{'! i has': 'foo'}]
    }


def test_cmd_select(signal_stub):
    # Argparse-related tests for this method may be split off to another
    # func. This stuff concerns the pprint output.
    from textwrap import dedent
    from dummy_conf import json_full
    from test_config import inject_config_version
    sig = signal_stub
    UN = sig.expand_string("%user%/%network%")  # <- "testdummy/dummynet"
    #
    sig.nv[UN] = inject_config_version(restring(json_full))
    out_one_dot = dedent("""\
    {'settings': {'host': 'example.com',
                  'port': 1024,
                  'obey': False,
                  'authorized': [],
                  'auto_connect': True,
                  'config_version': 0.2},
     'expressions': {'custom': {...},
                     'dummy': {...},
                     'default': {...}},
     'templates': {'default': {...}},
     'conditions': {'custom': {...}, 'default': {...}}}""")
    #
    cmd_select = wrap_mod_command(sig, sig.cmd_select, True)
    #
    from Signal.configgers import default_config
    assert sig.config is not None and not sig.debug
    sig.config = None
    assert out_one_dot == cmd_select("/")
    assert isinstance(sig.config, default_config.__class__)
    out_repeat_root = dedent("""\
    / => {'settings': {...},
          'expressions': {...},
          'templates': {...},
          'conditions': {...}}""")
    assert cmd_select() == out_repeat_root
    settings_stashed = cmd_select("settings")
    out_repeat_settings = dedent("""\
    /settings => {'host': 'example.com',
                  'port': 1024,
                  'obey': False,
                  'authorized': [],
                  'auto_connect': True,
                  'config_version': 0.2}""")
    assert cmd_select() == out_repeat_settings
    assert cmd_select(".") == settings_stashed  # no "=>" reminder
    assert cmd_select() == out_repeat_settings
    out_expr = dedent("""\
    {'custom': {'has': 'fixed string'},
     'dummy': {'all': [...]},
     'default': {'has': ''}}""")
    assert (cmd_select("/expressions") == cmd_select("../expressions")
            == cmd_select("has/../") == out_expr)
    assert cmd_select("/expressions/custom/has") == "'fixed string'"
    assert cmd_select("/expressions/dummy") == "{'all': [{...}, {...}]}"
    assert cmd_select("all/0") == "{'wild': '#foo*'}"
    cmd_select("../1/! i has")
    # Quoted LHS contains whitespace
    assert cmd_select() == "'/expressions/dummy/all/1/! i has' => 'bar'"
    # Repeat query w. long path adds newline and indents subsequent lines
    sig.config.templates["excessively long name"] = {}
    cmd_select("/templates/excessively long name")
    assert cmd_select() == dedent("""
        '/templates/excessively long name' =>
          {'recipients': [...],
           'format': '{focus}{context}: [{nick}] {body}',
           'focus_char': 'U+1F517',
           'length': 80}
    """).strip()


def test_cmd_update(signal_stub):
    """
    Note on ``namedtuple._asdict()``:

    If the selector is ``/{named_field}``, calling ``__delitem__`` or
    ``__setitem__`` does nothing since the ``OrderedDict`` returned is
    ephemeral.  The old behavior relied on this as a cheat to protect
    ``self.config``. Now, we bail out early and issue a warning.
    """
    from textwrap import dedent
    from dummy_conf import json_full
    from test_config import inject_config_version
    sig = signal_stub
    cmd_update = wrap_mod_command(sig, sig.cmd_update, True)
    UN = sig.expand_string("%user%/%network%")  # <- "testdummy/dummynet"
    sig.nv[UN] = inject_config_version(restring(json_full))
    # Config is auto-loaded when not in debug mode
    assert sig.config is not None and not sig.debug
    sig.config = None
    # Ignore this (irrelevant, just need to initialize parser)
    sig._OnModCommand("fake_command")
    assert sig._read().startswith("Invalid")
    # Attempts to modify root shows help
    assert cmd_update().startswith("usage: update [-h]")
    assert sig.last_config_selector is None
    #
    assert sig.config is not None  # <- load sig.config
    assert cmd_update("/settings").startswith("usage: update [-h]")
    assert cmd_update("/fake").startswith("usage: update [-h]")
    #
    cmd_select = wrap_mod_command(sig, sig.cmd_select, True)
    assert cmd_select("/settings/host") == "'example.com'"  # <- prints repr
    assert cmd_update("foo") == "Selected: /settings/host => 'foo'"
    assert sig.config.settings["host"] == "foo"
    assert str(sig.last_config_selector) == "/settings/host"
    # ChainoFixe modifiable item exists
    assert sig.config.settings.maps[0]["host"] == "foo"
    #
    # Removing
    cmd_update("/settings/port", "42")
    assert cmd_update(remove=True) == dedent("""
        Item deleted.
        Selected: /settings/port => 47000
    """).strip()
    #
    assert cmd_update("42") == "Selected: /settings/port => 42"
    assert cmd_update("/settings/port", remove=True) == dedent("""
        Item deleted.
        Selected: /settings/port => 47000
    """).strip()
    assert cmd_update("42") == "Selected: /settings/port => 42"
    # CWD doesn't change
    assert str(sig.last_config_selector) == "/settings/port"
    cmd_select("..")
    assert cmd_update("port", remove=True) == dedent("""
        Item deleted.
        Selected: /settings => {'host': 'foo', 'port': 47000, ...}
    """).strip()
    assert str(sig.last_config_selector) == "/settings"
    assert cmd_update("port", "42") == "Selected: /settings/port => 42"
    cmd_select("..")
    assert cmd_update("/settings", "port", remove=True) == dedent("""
        Item deleted.
        Selected: /settings => {'host': 'foo', 'port': 47000, ...}
    """).strip()
    assert str(sig.last_config_selector) == "/settings"
    # ChainoFixe modifiable item absent
    with pytest.raises(KeyError):
        sig.config.settings.maps[0]["port"]
    # Attempt to delete protected item fails
    cmd_select("port")
    assert cmd_update(remove=True) == dedent("""
        Problem deleting /settings/port:
          Cannot delete default item
        Selected: /settings/port => 47000
    """).strip()
    #
    assert str(sig.last_config_selector) == "/settings/port"
    # Sets correct type for SettingsDict members
    assert cmd_select("../port") == "47000"
    assert cmd_update("1099") == "Selected: /settings/port => 1099"
    assert cmd_select() == "/settings/port => 1099"
    assert sig.config.settings["port"] == 1099  # int
    #
    # ConditionsDict ----------------------------------------------------------
    assert sig.config.conditions["custom"].maps[0]["away_only"] is True
    assert sig.config.conditions["custom"].maps[-1]["away_only"] is False
    #
    assert cmd_update("/conditions/custom/away_only", "false") == \
        "Selected: /conditions/custom/away_only => False"
    # XXX this may be changed (to KeyError) if manage_config > save is made to
    # call load immediately after saving (redundant items will be peeled away).
    assert sig.config.conditions["custom"].maps[0]["away_only"] is False
    assert cmd_update("foo") == dedent("""
        Problem setting /conditions/custom/away_only to 'foo':
          Couldn't evaluate input; invalid Python.
          Try adding/removing quotes.
          Condition/away_only must be of type 'bool', not 'str'
        Selected: /conditions/custom/away_only => False
    """).strip()
    assert cmd_select() == "/conditions/custom/away_only => False"
    # Lookup devolves to default after deletion
    assert cmd_update(remove=True) == dedent("""
        Item deleted.
        Selected: /conditions/custom/away_only => False
    """).strip()
    with pytest.raises(KeyError):
        sig.config.conditions["custom"].maps[0]["away_only"]
    assert cmd_select() == "/conditions/custom/away_only => False"
    # Setting nonexistent item
    assert cmd_update("true") == \
        "Selected: /conditions/custom/away_only => True"
    # Setting unknown key
    assert cmd_update("/conditions/custom/fake", "foo") == dedent("""
        Problem setting /conditions/custom/fake to 'foo':
          Unrecognized condition: 'fake'
        Selected: /conditions/custom/away_only => True
    """).strip()
    # Delete entire custom condition
    from Signal.cmdopts import SerialSuspect
    # Must call bake() here because "away_only" is modified (reinserted) above
    stashed = sig.config.conditions["custom"].peel()
    assert cmd_update("/conditions/custom", remove=True) == dedent("""
        Item deleted; current selection has changed
        /conditions => {'default': {...}}
    """).strip()
    raw_string = SerialSuspect(
        '{"away_only":true,"timeout_post":360,"timeout_idle":120,'
        '"x_source":"nick","body":"custom","source":"custom"}'
    )
    assert cmd_update("custom", raw_string, as_json=True) == dedent("""
        Selected: /conditions/custom =>
          {'enabled': True, 'away_only': True, ...}
    """).strip()
    assert dict(sig.config.conditions["custom"].maps[0]) == stashed
    #
    # Expressionsdict ---------------------------------------------------------
    # Attempt to create new expression w. valid string
    assert cmd_update("/expressions/new", '{"foo": "bar"}') == \
        "Selected: /expressions/new => {'foo': 'bar'}"
    # Attempt to create new expression w. invalid string
    assert cmd_update("/expressions/fake", "some string") == dedent("""
        Problem setting /expressions/fake to 'some string':
          Couldn't evaluate input; invalid Python.
          Expressions must be JSON objects or Python dicts, not 'str'.
          See '/expressions/*' for reference.
        Selected: /expressions/new => {'foo': 'bar'}
    """).strip()
    assert cmd_update(remove=True) == dedent("""
        Item deleted; current selection has changed
        /expressions => {'custom': {...}, 'dummy': {...}, 'default': {...}}
    """).strip()
    new_exp = SerialSuspect('{"not": {"has": "foo"}}')
    assert cmd_update("new", new_exp, as_json=True) == \
        "Selected: /expressions/new => {'not': {...}}"
    # See "sequential optional args" case in test_cmd_debug_args above
    assert cmd_update(new_exp) == \
        "Selected: /expressions/new => {'not': {...}}"
    assert cmd_update("not/has", "bar") == \
        "Selected: /expressions/new/not/has => 'bar'"
    assert cmd_update("../../../default", '{"has any": ["one", "two"]}') == \
        "Selected: /expressions/default => {'has any': [...]}"
    #
    # TemplatesDict -----------------------------------------------------------
    assert cmd_update("/templates/custom", "'not a dict'") == dedent("""
        Problem setting /templates/custom to "'not a dict'":
          Templates must be JSON objects or Python dicts, not 'str'.
          See '/templates/*' for reference.
        Selected: /expressions/default => {'has any': [...]}
    """).strip()
    # Create new record with @@ form
    # Note: adjusting the "format" string can produce what looks like buggy
    # output from reprlib, but that's just an illusion. For example:
    # "[{...}]" instead of "[{nick}]"
    assert cmd_update("/templates/custom/", SerialSuspect("{}")) == dedent("""
        Selected: /templates/custom =>
          {'recipients': [...], 'format': '{focus}{cont...nick}] {body}', ...}
    """).strip()
    cmd_update(remove=True)
    # Accept normal strings when type is matches
    assert cmd_update("/templates/custom/", "{}") == dedent("""
        Selected: /templates/custom =>
          {'recipients': [...], 'format': '{focus}{cont...nick}] {body}', ...}
    """).strip()
    # Assign to non-existent index to create new entry
    assert cmd_update("recipients/0", "some number") == \
        "Selected: /templates/custom/recipients/0 => 'some number'"
    #
    # Renaming ----------------------------------------------------------------
    cmd_select("/expressions")
    stashed = sig.config.expressions["new"]
    assert cmd_update("new", "old", rename=True) == dedent("""
        Item moved; current selection has changed
        /expressions => {'custom': {...},
                         'dummy': {...},
                         'old': {...},
                         'default': {...}}
    """).strip()
    assert "new" not in sig.config.expressions
    assert stashed == sig.config.expressions["old"]
    #
    cmd_select("old")
    assert cmd_update("new", rename=True) == dedent("""
        Item moved; current selection has changed
        /expressions => {'custom': {...},
                         'dummy': {...},
                         'new': {...},
                         'default': {...}}
    """).strip()
    assert stashed == sig.config.expressions["new"]
    #
    assert cmd_update("new", "old/fake", rename=True) == dedent("""
        Problem moving item to /expressions/old/fake:
          KeyError: 'old'
        Selected: /expressions =>
          {'custom': {...}, 'dummy': {...}, ...}
    """).strip()
    assert "new" in sig.config.expressions
    assert not any(k in sig.config.expressions for k in ("old", "fake",
                                                         "old/fake"))
    assert stashed == sig.config.expressions["new"]
    #
    # Moving ------------------------------------------------------------------
    sig.debug = True
    cmd_select("/conditions")
    C = sig.config.conditions
    assert list(C) == ["custom", "default"]
    assert cmd_update("foo", SerialSuspect("{}")) == dedent("""
        Selected: /conditions/foo =>
          {'enabled': True, 'away_only': False, ...}
    """).strip()
    cmd_update("/conditions/bar", SerialSuspect("{}"))
    cmd_update("/conditions/baz", SerialSuspect("{}"))
    cmd_update("/conditions/spam", SerialSuspect("{}"))
    assert list(C) == ['custom', 'foo', 'bar', 'baz', 'spam', 'default']
    cmd_update("/conditions/custom", "foo", arrange=True)
    assert list(C) == ['foo', 'custom', 'bar', 'baz', 'spam', 'default']
    # After moving, selection defaults to parent
    assert cmd_select() == dedent("""
        /conditions => {'foo': {},
                        'custom': {...},
                        'bar': {},
                        'baz': {},
                        'spam': {},
                        'default': {...}}
    """).strip()
    cmd_update("/conditions/custom", "1", arrange=True)
    assert list(C) == ['foo', 'bar', 'custom', 'baz', 'spam', 'default']
    cmd_select("/conditions/custom")
    assert cmd_update("-1", arrange=True) == dedent("""
        Selected: /conditions =>
          {'foo': {...}, 'custom': {...}, ...}
    """).strip()
    cmd_update("custom", "spam", arrange=True)
    assert list(C) == ['foo', 'spam', 'bar', 'baz', 'custom', 'default']
    cmd_select("/conditions/custom")
    assert cmd_update("spam", arrange=True) == dedent("""
        Selected: /conditions =>
          {'foo': {...}, 'custom': {...}, ...}
    """).strip()
    # Attempt to move non-conditions
    only_msg = "Only /conditions members are moveable"
    for args in [("/settings/away_only", "reply_only"),
                 ("/templates/custom", "default"),
                 ("/expressions/dummy", "custom")]:
        assert only_msg in cmd_update(*args, arrange=True)
        assert str(sig.last_config_selector) == "/conditions"
    # Attempt to move default
    assert cmd_update("custom", "default", arrange=True) == dedent("""
        Problem swapping /conditions/custom and 'default':
          Cannot move default item
        Selected: /conditions =>
          {'foo': {...}, 'custom': {...}, ...}
    """).strip()
    assert cmd_update("default", "1", arrange=True) == dedent("""
        Problem shifting /conditions/default by +1:
          Cannot move default item
        Selected: /conditions =>
          {'foo': {...}, 'custom': {...}, ...}
    """).strip()
    cmd_select("default")
    assert cmd_update("custom", arrange=True) == dedent("""
        Problem swapping /conditions/default and 'custom':
          Cannot move default item
        Selected: /conditions =>
          {'foo': {...}, 'custom': {...}, ...}
    """).strip()
    cmd_select("custom")
    assert cmd_update("default", arrange=True) == dedent("""
        Problem swapping /conditions/custom and 'default':
          Cannot move default item
        Selected: /conditions =>
          {'foo': {...}, 'custom': {...}, ...}
    """).strip()


if __name__ == "__main__":
    from conftest import runner
    # name, func, fixtures, gen_fixtures
    tests = [
        (test_OnModCommand, (), (signal_stub,)),
        (test_cmd_debug_args, (), (signal_stub,)),
        (test_cmd_select, (), (signal_stub,)),
        (test_cmd_update, (), (signal_stub,)),
    ]
    runner(tests, locals())
