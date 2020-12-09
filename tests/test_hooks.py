# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import pytest
from copy import deepcopy
from collections import namedtuple
from conftest import signal_stub, signal_stub_debug, all_in
signal_stub = signal_stub  # quiet linter
signal_stub_debug = signal_stub_debug


@pytest.fixture
def env_stub(signal_stub):
    import os
    os.environ["SIGNALMOD_FAKE"] = "fake_val"
    os.environ["SIGNALMOD_FOO"] = "foo_val"
    argstring = f"DATADIR={os.devnull} FOO=someval UNKNOWN=ignored"
    signal_stub.__class__.foo = None
    signal_stub.__class__.fake = None
    env_stub = signal_stub.__class__(argstring)
    yield env_stub
    del signal_stub.__class__.foo
    del signal_stub.__class__.fake
    del os.environ["SIGNALMOD_FAKE"]
    del os.environ["SIGNALMOD_FOO"]
    if env_stub._buffer is not None:
        env_stub._buffer.close()


def test_OnLoad(env_stub):
    import os
    # Process environment is not modified
    assert all_in(os.environ, "SIGNALMOD_FAKE", "SIGNALMOD_FOO")
    assert env_stub.fake == os.environ["SIGNALMOD_FAKE"] == "fake_val"
    assert os.environ["SIGNALMOD_FOO"] == "foo_val"
    # OnLoad args override environment variables
    assert env_stub.foo == "someval"
    # Unknown attributes are ignored
    assert not hasattr(env_stub, "unknown")
    assert hasattr(env_stub, "datadir") and env_stub.datadir == os.devnull
    # TODO use pseudo terminal to test debug logger (likely requires Linux)


# NOTE: order doesn't (currently) matter for flattened/narrowed hook data
base_rel = {'body': 'Welcome dummy!',
            'network': 'testnet',
            'away': False,
            'client_count': 1,
            'nick': 'tbo',
            'ident': 'testbot',
            'host': 'znc.in',
            'hostmask': 'tbo!testbot@znc.in',
            # Real thing uses datetime object
            'time': '2018-04-21T01:20:13.751970+00:00'}

rels = namedtuple("Rels",
                  "OnChanTextMessage OnPrivTextMessage")(
    dict(base_rel,
         channel='#test_chan',
         detached=False,
         context='#test_chan'),
    dict(base_rel,
         body="Oi",
         context="dummy")
)

# NOTE OnPrivActionMessage(msg) and OnChanActionMessage(msg) are exactly the
# same as their "Text" counterparts above, once narrowed. Normalized inspector
# output will show: 'type': 'Action', 'params': ('dummy', '\x01ACTION Oi\x01')
# as the only real differences.


def test_reckon(signal_stub_debug):
    # Simulate converted dict passed to Signal.reckon()
    from Signal.reckognize import reckon
    from collections import defaultdict
    defnul = defaultdict(type(None), rels.OnPrivTextMessage)
    assert defnul["channel"] is None
    assert defnul["detached"] is None
    #
    # Load default config
    sig = signal_stub_debug
    sig.manage_config("load")  # same as '[*Signal] select'
    # Quiet "no host" warning
    sig.OnModCommand('update /settings/host localhost')
    # Simulate a single, simple hook case
    rel = rels.OnChanTextMessage
    #
    data_bak = deepcopy(rel)
    conds = sig.config.conditions
    from collections import defaultdict
    data = defaultdict(type(None), rel)
    #
    sig._read()  # clear read buffer
    # Step through default config to ensure test module stays current with
    # future changes to options
    current_defaults = iter(sig.config.conditions["default"])
    #
    assert reckon(sig.config, data, sig.debug) is False
    data_reck = data["reckoning"]
    assert data_reck == ["<default", "!body>"]
    #
    assert next(current_defaults) == "enabled"
    sig.cmd_update("/conditions/default/enabled", "False")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<default", "enabled>"]
    sig.cmd_update("/conditions/default/enabled", remove=True)
    #
    assert next(current_defaults) == "away_only"
    sig.cmd_update("/conditions/default/away_only", "True")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<default", "away_only>"]
    sig.cmd_update("/conditions/default/away_only", remove=True)
    #
    assert next(current_defaults) == "scope"
    assert not conds["default"].maps[0]  # updated list is auto initialized
    sig.cmd_update("/conditions/default/scope/attached", remove=True)
    assert conds["default"]["scope"] == ["query", "detached"]
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<default", "scope>"]
    sig.cmd_update("/conditions/default/scope", remove=True)
    #
    # TODO replied_only
    assert next(current_defaults) == "replied_only"
    #
    assert next(current_defaults) == "max_clients"
    data["client_count"] = 2
    sig.cmd_update("/conditions/default/max_clients", "1")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<default", "max_clients>"]
    sig.cmd_update("/conditions/default/max_clients", remove=True)
    data["client_count"] = 1
    _data = dict(data)
    _data.pop("reckoning")
    # _data.pop("template")
    assert data_bak == _data
    #
    assert sig._read().splitlines() == [
        "Selected: /conditions/default/enabled => False", "Item deleted.",
        "Selected: /conditions/default/enabled => True",
        #
        "Selected: /conditions/default/away_only => True", "Item deleted.",
        "Selected: /conditions/default/away_only => False",
        #
        "Item deleted; current selection has changed",
        "/conditions/default/scope => ['query', 'detached']",
        "Item deleted.",
        "Selected: /conditions/default/scope =>",
        "  ['query', 'detached', ...]",
        #
        "Selected: /conditions/default/max_clients => 1", "Item deleted.",
        "Selected: /conditions/default/max_clients => 0"
    ]
    #
    # TODO mock datetime.now() for time-based conditions
    assert next(current_defaults) == "timeout_post"
    assert next(current_defaults) == "timeout_push"
    assert next(current_defaults) == "timeout_idle"
    #
    # NOTE the rest aren't tested in order, just popped as encountered
    current_defaults = list(current_defaults)
    #
    sig.OnModCommand('update /expressions/custom @@ {"has": "dummy"}')
    sig.OnModCommand('update /templates/standard @@ '
                     '{"recipients": ["+12127365000"]}')
    # Create non-default condition
    current_defaults.remove("template")
    sig.OnModCommand('update /conditions/custom @@ {"template": "custom"}')
    # The "default" condition always runs last
    assert list(sig.manage_config("view")["conditions"]) == ["custom",
                                                             "default"]
    #
    # Network
    current_defaults.remove("network")
    sig.cmd_update("/conditions/custom/network", "$custom")
    assert data["network"] == "testnet"
    assert sig.config.expressions["custom"] == {"has": "dummy"}
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!network>", "<default", "!body>"]
    sig.cmd_update("/conditions/custom/network", "$pass")
    #
    # Channel
    current_defaults.remove("channel")
    sig.OnModCommand('update /conditions/custom/channel $custom')
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!channel>", "<default", "!body>"]
    sig.cmd_update("/expressions/custom/has", "test_chan")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!body>", "<default", "!body>"]
    sig.cmd_update("/expressions/custom/has", "dummy")
    sig.cmd_update("/conditions/custom/channel", "$pass")
    #
    # Source
    current_defaults.remove("source")
    sig.OnModCommand('update /conditions/custom/source $custom')
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!source>", "<default", "!body>"]
    sig.OnModCommand('update /expressions/custom @@ {"wild": "*testbot*"}')
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!body>", "<default", "!body>"]
    current_defaults.remove("x_source")
    assert conds["custom"]["x_source"] == "hostmask"
    sig.cmd_update("/conditions/custom/x_source", "nick")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!source>", "<default", "!body>"]
    sig.OnModCommand('update /expressions/custom @@ {"eq": "tbo"}')
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!body>", "<default", "!body>"]
    sig.cmd_update("/conditions/custom/x_source", remove=True)
    sig.cmd_update("/conditions/custom/source", "$pass")
    #
    # Body
    current_defaults.remove("body")
    sig.cmd_update("/conditions/custom/body", "$custom")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!body>", "<default", "!body>"]
    sig.OnModCommand('update /expressions/custom @@ {"has": "dummy"}')
    assert reckon(sig.config, data, sig.debug) is True
    #
    # Body empty
    data["body"] = ""
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!body>", "<default", "!body>"]
    sig.cmd_update("/conditions/custom/body", "$drop")
    data["body"] = "Welcome dummy!"
    #
    # Inline expression
    sig.OnModCommand(
        'update /conditions/custom/body @@ {"any": []}'
    )  # same as !has ""
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "!body>", "<default", "!body>"]
    sig.OnModCommand(
        'update /conditions/custom/body @@ {"i has": "welcome"}'
    )
    assert reckon(sig.config, data, sig.debug) is True
    assert data_reck == ["<custom", "&>"]
    sig.cmd_update("/conditions/custom/body", "$drop")
    #
    # Make pass the same as drop
    sig.OnModCommand('update /expressions/pass @@ {"!has": ""}')
    assert conds["custom"]["body"] == "$drop"
    sig.cmd_update("/conditions/custom/body", "$pass")
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", '!network>', "<default", '!network>']
    #
    # Use literal expression in condition
    assert conds["custom"]["body"] == "$pass"
    sig.cmd_update("/expressions/pass", remove=True)
    assert sig.config.expressions["pass"] == {"has": ""}
    sig.OnModCommand('update /conditions/custom/body @@ {"!has": ""}')
    assert conds["custom"]["body"] == {"!has": ""}
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", '!body>', "<default", '!body>']
    sig.cmd_update("/conditions/custom/body", remove=True)
    sig.OnModCommand('update /expressions/pass @@ {"any": []}')
    #
    # Change per-condition, collective expressions bias
    current_defaults.remove("x_policy")  # only governs expressions portion
    assert conds["custom"]["x_policy"] == "filter"
    sig.OnModCommand('update /conditions/default/x_policy first')
    assert reckon(sig.config, data, sig.debug) is False
    assert data_reck == ["<custom", "|>", "<default", "|>"]  # Falls through
    #
    assert not current_defaults
    #
    # "FIRST" (short circuit) hit
    sig.OnModCommand('update /conditions/custom/body $custom')
    assert reckon(sig.config, data, sig.debug) is True
    assert data_reck == ["<custom", "body!>"]
    #
    sig.OnModCommand('update /conditions/onetime @@ {}')
    from textwrap import dedent
    sig.cmd_select("../")
    # Clear module buffer (lots of '/foo =>' output so far)
    assert "Error" not in sig._read()
    #
    # Add another condition that runs ahead of 'custom'
    sig.OnModCommand('select')
    assert sig._read().strip() == dedent("""
        /conditions => {'custom': {...}, 'onetime': {}, 'default': {...}}
    """).strip()
    sig.cmd_update("/conditions/onetime", "custom", arrange=True)
    assert sig._read().strip() == dedent("""
        Selected: /conditions =>
          {'onetime': {...}, 'custom': {...}, ...}
    """).strip()
    assert reckon(sig.config, data, sig.debug) is True
    assert data_reck == ["<onetime", "|>", "<custom", "body!>"]


def scope_conditional_stub(data, scope):
    cond = dict(scope=scope)
    # This is was copied verbatim from Signal.reckon, but code creep is
    # inevitable
    #
    channel = data["channel"]
    detached = data["detached"]
    if ((channel and (("detached" not in cond["scope"] and detached) or
                      ("attached" not in cond["scope"] and not detached))
         or (not channel and "query" not in cond["scope"]))):
        return True
    return False


# XXX this used to be justified when the option was "ignored_scopes" (more
# flags, not so trivial); should just merge with test_reckon or delete
def test_reject_scope():
    f = scope_conditional_stub
    c = "channel"
    a = "attached"
    d = "detached"
    q = "query"
    #
    data = {c: True, d: False}
    assert all((f(data, []),
                f(data, [q]),
                f(data, [d]),
                f(data, [d, q]))) is True
    assert not any((f(data, [a]),
                    f(data, [q, a]),
                    f(data, [q, a, d]))) is True
    #
    data = {c: True, d: True}
    assert all((f(data, []),
                f(data, [q]),
                f(data, [a]),
                f(data, [a, q]))) is True
    assert not any((f(data, [d]),
                    f(data, [d, a]),
                    f(data, [d, q, a]))) is True
    #
    data = {c: None, d: None}
    assert f(data, [q]) is False  # pass (not rejected)
    assert all((f(data, []),
                f(data, [d]),
                f(data, [a]),
                f(data, [d, a]))) is True
