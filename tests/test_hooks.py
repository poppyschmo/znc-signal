# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import pytest
from copy import deepcopy
from conftest import signal_stub, signal_stub_debug, all_in
signal_stub = signal_stub  # quiet linter
signal_stub_debug = signal_stub_debug


@pytest.fixture
def env_stub(signal_stub):
    import os
    os.environ["SIGNALMOD_FAKE"] = "fake_val"
    os.environ["SIGNALMOD_FOO"] = "foo_val"
    signal_stub.__class__._argstring = \
        f"DATADIR={os.devnull} FOO=someval UNKNOWN=ignored"
    signal_stub.__class__.foo = None
    signal_stub.__class__.fake = None
    env_stub = signal_stub.__class__()
    signal_stub.__class__._argstring = ""
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


# TODO move these data records to a separate file and use script to generate
# (requires irc3 package and a running instance of ZNC)
get_rel_params = []
# OnChanMsg(Nick, Channel, sMessage)
ocm = {'Nick': {'nick': 'tbo',
                'ident': 'testbot',
                'host': 'znc.in',
                'hostmask': 'tbo!testbot@znc.in'},
       'Channel': {'name': '#test_chan',
                   'detached': False},
       'sMessage': 'Welcome dummy!',
       'network': {'name': 'testnet',
                   'away': False,
                   'client_count': 1},
       'time': '2018-04-21T01:20:13.751970+00:00'}
get_rel_params.append(("OnChanMsg", ocm))

# OnChanTextMessage(msg):
octm = {'msg': {'type': 'Text',
                'nick': {'nick': 'tbo',
                         'ident': 'testbot',
                         'host': 'znc.in',
                         'hostmask': 'tbo!testbot@znc.in'},
                'channel': {'name': '#test_chan',
                            'detached': False},
                'command': 'PRIVMSG',
                'params': ('#test_chan', 'Welcome dummy!'),
                'network': {'name': 'testnet',
                            'away': False,
                            'client_count': 1},
                'target': '#test_chan',
                'text': 'Welcome dummy!'},
        'time': '2018-04-21T01:20:13.751970+00:00'}
get_rel_params.append(("OnChanTextMessage", octm))

# OnPrivMsg(Nick, sMessage)
opm = deepcopy(ocm)
del opm["Channel"]
opm["sMessage"] = "Oi"
get_rel_params.append(("OnPrivMsg", opm))

# OnPrivTextMessage(msg)
optm = deepcopy(octm)
del optm["msg"]["channel"]
optm["msg"].update({'params': ('dummy', 'Oi'),  # "command" is still "PRIVMSG"
                    'target': 'dummy',
                    'text': 'Oi'})
get_rel_params.append(("OnPrivTextMessage", optm))

# TODO add sub-1.7 analogs, then add to test params
#
# OnPrivActionMessage(msg)
opam = deepcopy(optm)
opam["msg"].update({'type': 'Action',
                    'params': ('dummy', '\x01ACTION Oi\x01')})

# OnPrivCTCPMessage(msg)
opctcpm = deepcopy(opam)
opctcpm["msg"]["text"] = "ACTION Oi"


def get_relevant_legacy(data):
    """Narrow/flatten normalized data to zone of interest

    At this point, all data/data.msg values should (mostly) be
    primitives (strings and ints).
    """
    from Signal.commonweal import get_first
    #
    def narrow(lookups):  # noqa: E306
        common = {}
        from collections import MutableMapping
        for key, cands in lookups.items():
            wanted = get_first(data, *cands)
            if not wanted:
                continue
            if isinstance(wanted, MutableMapping):
                _wanted = dict(wanted)
                if "name" in wanted:
                    common[key] = _wanted.pop("name")
                if key in wanted:
                    common[key] = _wanted.pop(key)
                if _wanted != wanted:
                    common.update(_wanted)
            else:
                common[key] = wanted
        return common
    #
    # Common lookups
    rosetta = {
        # shallow
        "body": ("text", "sMessage"),
        # deep
        "network": ("network", "Network"),
        "channel": ("channel", "Channel", "sChannel", "Chan", "sChan"),
        "nick": ("nick", "Nick"),
    }
    narrowed = narrow(rosetta)
    narrowed["context"] = narrowed.get("channel") or narrowed["nick"]
    return narrowed


@pytest.mark.parametrize("hook_name,hook_data", get_rel_params)
def test_get_relevant(hook_name, hook_data):
    rel = get_relevant_legacy(hook_data)
    # NOTE: order doesn't matter for flattened/narrowed hook data
    base = {"away": False,
            "client_count": 1,
            "host": "znc.in",
            "hostmask": "tbo!testbot@znc.in",
            "ident": "testbot",
            "network": "testnet",
            "nick": "tbo"}
    if hook_name.startswith("OnChan"):
        chan_flat = dict(base)
        chan_flat.update({"channel": "#test_chan",
                          "body": "Welcome dummy!",
                          "detached": False,
                          "context": "#test_chan"})
        assert rel == chan_flat
    else:
        priv_flat = dict(base)
        priv_flat.update(body="Oi", context="tbo")
        assert rel == priv_flat
    #
    # Simulate converted dict passed to Signal.reckon()
    if hook_name in ("OnChanTextMessage", "OnPrivTextMessage"):
        network = hook_data["msg"]["network"]
        if hook_name == "OnChanTextMessage":
            channel = hook_data["msg"]["channel"]
            context = channel["name"]
        else:
            context = hook_data["msg"]["nick"]["nick"]
        src_info = hook_data["msg"]["nick"]
    elif hook_name in ("OnChanMsg", "OnPrivMsg"):
        network = hook_data["network"]
        if hook_name == "OnChanMsg":
            channel = hook_data["Channel"]
            context = hook_data["Channel"]["name"]
        else:
            context = hook_data["Nick"]["nick"]
        src_info = hook_data["Nick"]
    from collections import defaultdict
    defnul = defaultdict(type(None), rel)
    assert defnul["network"] == network["name"]
    assert defnul["away"] == network["away"]
    assert defnul["client_count"] == network["client_count"]
    if hook_name.startswith("OnChan"):
        assert defnul["channel"] == channel["name"]
        assert defnul["detached"] == channel["detached"]
    assert defnul["context"] == context
    assert defnul["nick"] == src_info["nick"]
    assert defnul["hostmask"] == src_info["hostmask"]


def test_reckon(signal_stub_debug):
    # Load default config
    sig = signal_stub_debug
    sig.manage_config("load")  # same as '[*Signal] select'
    # Quiet "no host" warning
    sig.OnModCommand('update /settings/host localhost')
    # Simulate a single, simple hook case
    rel = {'away': False,
           'channel': '#test_chan',
           "detached": False,
           'client_count': 1,
           'body': 'Welcome dummy!',
           'host': 'znc.in',
           'hostmask': 'tbo!testbot@znc.in',
           'ident': 'testbot',
           'network': 'testnet',
           'nick': 'tbo',
           'context': '#test_chan'}
    assert get_relevant_legacy(octm) == rel
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
    assert sig.reckon(data) is True
    data_reck = data["reckoning"]
    assert data_reck == ["<default", "&>"]
    #
    assert next(current_defaults) == "enabled"
    sig.cmd_update("/conditions/default/enabled", "False")
    assert sig.reckon(data) is False
    assert data_reck == ["<default", "enabled>"]
    sig.cmd_update("/conditions/default/enabled", remove=True)
    #
    assert next(current_defaults) == "away_only"
    sig.cmd_update("/conditions/default/away_only", "True")
    assert sig.reckon(data) is False
    assert data_reck == ["<default", "away_only>"]
    sig.cmd_update("/conditions/default/away_only", remove=True)
    #
    assert next(current_defaults) == "scope"
    assert not conds["default"].maps[0]  # updated list is auto initialized
    sig.cmd_update("/conditions/default/scope/attached", remove=True)
    assert conds["default"]["scope"] == ["query", "detached"]
    assert sig.reckon(data) is False
    assert data_reck == ["<default", "scope>"]
    sig.cmd_update("/conditions/default/scope", remove=True)
    #
    # TODO replied_only
    assert next(current_defaults) == "replied_only"
    #
    assert next(current_defaults) == "max_clients"
    data["client_count"] = 2
    sig.cmd_update("/conditions/default/max_clients", "1")
    assert sig.reckon(data) is False
    assert data_reck == ["<default", "max_clients>"]
    sig.cmd_update("/conditions/default/max_clients", remove=True)
    data["client_count"] = 1
    _data = dict(data)
    _data.pop("reckoning")
    _data.pop("template")
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
    sig.cmd_update("/conditions/custom/network", "custom")
    assert data["network"] == "testnet"
    assert sig.config.expressions["custom"] == {"has": "dummy"}
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!network>", "<default", "&>"]
    sig.cmd_update("/conditions/custom/network", "default")
    #
    # Channel
    current_defaults.remove("channel")
    sig.OnModCommand('update /conditions/custom/channel custom')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!channel>", "<default", "&>"]
    sig.cmd_update("/expressions/custom/has", "test_chan")
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "&>"]
    sig.cmd_update("/expressions/custom/has", "dummy")
    sig.cmd_update("/conditions/custom/channel", "default")
    #
    # Source
    current_defaults.remove("source")
    sig.OnModCommand('update /conditions/custom/source custom')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!source>", "<default", "&>"]
    sig.OnModCommand('update /expressions/custom @@ {"wild": "*testbot*"}')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "&>"]
    current_defaults.remove("x_source")
    assert conds["custom"]["x_source"] == "hostmask"
    sig.cmd_update("/conditions/custom/x_source", "nick")
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!source>", "<default", "&>"]
    sig.OnModCommand('update /expressions/custom @@ {"eq": "tbo"}')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "&>"]
    sig.cmd_update("/conditions/custom/x_source", remove=True)
    sig.cmd_update("/conditions/custom/source", "default")
    #
    # Body
    current_defaults.remove("body")
    sig.cmd_update("/conditions/custom/body", "custom")
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!body>", "<default", "&>"]
    sig.OnModCommand('update /expressions/custom @@ {"has": "dummy"}')
    sig.cmd_update("/conditions/custom/body", "default")
    #
    # Change default condition to always fail
    sig.OnModCommand('update /expressions/default @@ {"!has": ""}')
    assert conds["custom"]["body"] == "default"
    assert sig.reckon(data) is False
    assert data_reck == ["<custom", '!network>', "<default", '!network>']
    #
    # Change per-condition, collective expressions bias
    current_defaults.remove("x_policy")  # only governs expressions portion
    assert conds["custom"]["x_policy"] == "filter"
    sig.OnModCommand('update /conditions/default/x_policy first')
    assert sig.reckon(data) is False
    assert data_reck == ["<custom", "|>", "<default", "|>"]  # Falls through
    #
    assert not current_defaults
    #
    # "FIRST" (short circuit) hit
    sig.OnModCommand('update /conditions/custom/body custom')
    assert sig.reckon(data) is True
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
    assert sig.reckon(data) is True
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
