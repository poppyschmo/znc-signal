# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import os
import ast
import pytest
from copy import deepcopy
from conftest import signal_stub, signal_stub_debug, any_in, all_in
signal_stub = signal_stub  # quiet linter
signal_stub_debug = signal_stub_debug

# TODO checkout pre-1.7.0 commit and get total run count for all releases (like
# --collect-only, but must manually count). If > 5, diff against latest
# changes. Reason: in haste to accommodate 1.7.0 final, replaced some
# loop-based tests with parametrized fixtures, but might have dropped coverage
# the process.

znc_url = "https://znc.in/releases/archive/znc-{rel}.tar.gz"
pinned_releases = ("1.6.6", "1.7.0-rc1", "1.7.0")


class CullNonHooks(ast.NodeTransformer):
    def visit_Assign(self, node):
        return None

    def visit_FunctionDef(self, node):
        if node.name.startswith("On"):
            return node


def get_class_node(tree, cls_name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            return node


def get_hook_args(node):
    """Look for Module in modpython script, return On*Method args node
    """
    assert node.name == "Module"
    return dict(
        (n.name, dict(vars(n.args), args=tuple(a.arg for a in n.args.args)))
        for n in ast.iter_child_nodes(node) if
        isinstance(n, ast.FunctionDef) and n.name.startswith("On")
    )


def retrieve_sources(release, base_dir):
    # TODO look into using shutil instead of tarfile
    from urllib.request import urlopen
    import tarfile
    with urlopen(znc_url.format(rel=release)) as flor:
        with tarfile.open(mode="r:gz", fileobj=flor) as tfo:
            tfo.extractall(base_dir)


def read_source(base_dir, rel_path, release):
    """Return file at <rel_path> from every release"""
    # TODO re-obtain file if older than so many days; fairly limited without
    # local git repo or github api key.
    path = f"{base_dir}/znc-{release}/{rel_path.lstrip('/')}"
    if not os.path.exists(path) or not os.stat(path).st_size:
        retrieve_sources(release, base_dir)
    if not os.path.exists(path):
        source = None
    else:
        with open(path) as flo:
            source = flo.read()
    return source


@pytest.fixture
def base_dir(pytestconfig):
    return pytestconfig.cache.makedir("releases")


@pytest.fixture(params=pinned_releases)
def cpymodule_node(base_dir, request):
    release = request.param
    source = read_source(base_dir, "modules/modpython/znc.py", release)
    mod_tree = get_class_node(ast.parse(source), "Module")
    return release, mod_tree


@pytest.fixture
def cpymodule_hook_args(cpymodule_node):
    release, mod_tree = cpymodule_node
    data = get_hook_args(mod_tree)
    #
    for hook_name, sig_data in dict(data).items():
        assert sig_data["vararg"] is None
        assert sig_data["kwonlyargs"] == []
        assert sig_data["kw_defaults"] == []
        assert sig_data["kwarg"] is None
        if hook_name == "OnPart":
            assert len(sig_data["defaults"]) == 1
            assert sig_data["defaults"][0].value is None
        else:
            assert sig_data["defaults"] == []
        # Overwrite sig_data with args; dict -> tuple(*signature - "self")
        data[hook_name] = sig_data["args"][1:]
    assert all(a.startswith("On") for a in data)
    return release, data


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


@pytest.fixture
def mro_stub(cpymodule_node, signal_stub):
    """Patch the znc.Module stub with modpython methods"""
    #
    import os
    pruned = CullNonHooks().visit(cpymodule_node[-1])
    wrapper = ast.Module(body=[pruned])
    cap_dict = {}
    exec(compile(wrapper, "<string>", "exec"), cap_dict)
    from Signal import textsecure
    textsecure.znc.Module
    for attr in dir(cap_dict["Module"]):
        if attr.startswith("On"):
            setattr(textsecure.znc.Module, attr,
                    getattr(cap_dict["Module"], attr))

    class MroStub(signal_stub.__class__):
        _argstring = f"DATADIR={os.devnull}"
        __new__ = textsecure.Signal.__new__

    stub = MroStub()
    yield stub
    if stub._buffer is not None:
        stub._buffer.close()


def test_normalize_hook_args(base_dir, cpymodule_hook_args):
    release, hook_args = cpymodule_hook_args
    # Ensure 1.6.6 didn't suddenly add CMessage. Sad substitute for ensuring
    # ``hasattr(znc, "CMessage")`` is False
    from glob import glob
    message_related = glob(f"{base_dir}/znc-{release}/**/Message.[hc]*",
                           recursive=True)
    #
    # 1.6 stuff
    if release.startswith("1.6"):
        assert not message_related
        one6_args = set.union(*(set(v) for v in hook_args.values()))
        # Msg doesn't appear in any sub-1.7 sigs
        assert "msg" not in one6_args
    #
    # 1.7+ stuff ("+" for now, we'll see)
    else:
        assert any_in([os.path.split(p)[-1] for p in message_related],
                      "Message.h", "Message.cpp")
        # Deal with outliers like Msg -> TextMessage and any future
        # non-null/Message-analog pairing. Need an automated solution for
        # flagging these in the future
        outliers = {o.replace("TextMessage", "Msg") for o in
                    hook_args if
                    o.endswith("TextMessage") and
                    o.replace("TextMessage", "Msg") in hook_args}
        outliers |= {o.replace("PlayMessage", "PlayLine") for o in
                     hook_args if
                     o.endswith("PlayMessage") and
                     o.replace("PlayMessage", "PlayLine") in hook_args}
        deprecados = {o.replace("Message", "") for
                      o in hook_args if
                      o.endswith("Message") and
                      o.replace("Message", "") in hook_args}
        assert not deprecados & outliers  # obvious (delete me)
        # Hard-code these to literal expect values for now
        assert outliers == {'OnChanMsg', 'OnPrivMsg', 'OnUserMsg',
                            'OnPrivBufferPlayLine', 'OnChanBufferPlayLine'}
        # Dev crutch (used verbatim in OnLoad as "depcands"):
        crutch = {o.replace("TextMessage", "Msg")
                  .replace("PlayMessage", "PlayLine")
                  .replace("Message", "") for
                  o in hook_args if
                  o.endswith("Message")} & hook_args.keys()
        assert crutch == outliers | deprecados
        #
        # "Noisy" hooks (those containing "Raw" or "SendTo") don't contain
        # "sLine" in 1.7+ unless deprecated
        raw_sliners = {k for k, v in hook_args.items() if
                       any_in(k, "Raw", "SendTo") and "sLine" in v}
        assert not raw_sliners - deprecados
        # TODO double check and replace previous with following, which holds
        # and is stronger (meaning prev is obsolete because ``deprecados`` is
        # meaningless without ``outliers`` and ``all_sliners`` includes
        # ``raw_sliners``
        all_sliners = {k for k, v in hook_args.items() if "sLine" in v}
        assert not all_sliners - crutch


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


# XXX These seem wholly irrelevant now (?) since all ``OnHooks`` mix-in methods
# were merged back in to the main module class.
#
# TODO justify relevance or remove (also remove fixture stub)
def test_hooks_mro(mro_stub):
    # The first two are bogus (describe test stub)
    assert repr(mro_stub.__class__.__mro__) == " ".join("""
        (<class 'test_hooks.mro_stub.<locals>.MroStub'>,
         <class 'conftest.SignalStub'>,
         <class 'Signal.textsecure.Signal'>,
         <class 'znc.Module'>,
         <class 'object'>)
        """.split())
    mrod = {f"{c.__module__}.{c.__name__}": c for
            c in mro_stub.__class__.__mro__}
    assert mro_stub.OnLoad.__func__.__name__ == "_OnLoad"
    assert mro_stub.OnModCommand.__func__.__name__ == "_OnModCommand"
    # Overridden
    assert mro_stub.OnClientDisconnect.__qualname__ == \
        'Signal.OnClientDisconnect'
    assert (mro_stub.OnClientDisconnect.__wrapped__.__func__ in
            mrod["Signal.textsecure.Signal"].__dict__.values())
    # Not overridden
    assert mro_stub.OnAddUser.__qualname__ == "Module.OnAddUser"
    assert (mro_stub.OnAddUser.__wrapped__.__func__ not in
            mrod["Signal.textsecure.Signal"].__dict__.values())
    assert (mro_stub.OnAddUser.__wrapped__.__func__ in
            mrod["znc.Module"].__dict__.values())


# TODO move these data records to a separate file and use script to generate
# (requires irc3 package and a running instance of ZNC)
get_rel_params = []
# OnChanMsg(Nick, Channel, sMessage)
ocm = {'Nick': {'nick': 'tbo',
                'ident': 'testbot',
                'host': 'znc.in',
                'nickmask': 'tbo!testbot@znc.in',
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
                         'nickmask': 'tbo!testbot@znc.in',
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


@pytest.mark.parametrize("hook_name,hook_data", get_rel_params)
def test_get_relevant(hook_name, hook_data, signal_stub_debug):
    sig = signal_stub_debug
    rel = sig.get_relevant(hook_data)
    # NOTE: order doesn't matter for flattened/narrowed hook data
    base = {"away": False,
            "client_count": 1,
            "host": "znc.in",
            "hostmask": "tbo!testbot@znc.in",
            "ident": "testbot",
            "network": "testnet",
            "nick": "tbo",
            "nickmask": "tbo!testbot@znc.in"}
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
    sig._OnModCommand('update /settings/host localhost')
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
           'nickmask': 'tbo!testbot@znc.in',
           'context': '#test_chan'}
    assert sig.get_relevant(octm) == rel
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
    sig._OnModCommand('update /expressions/custom @@ {"has": "dummy"}')
    sig._OnModCommand('update /templates/standard @@ '
                      '{"recipients": ["+12127365000"]}')
    # Create non-default condition
    current_defaults.remove("template")
    sig._OnModCommand('update /conditions/custom @@ {"template": "custom"}')
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
    sig._OnModCommand('update /conditions/custom/channel custom')
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
    sig._OnModCommand('update /conditions/custom/source custom')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!source>", "<default", "&>"]
    sig._OnModCommand('update /expressions/custom @@ {"wild": "*testbot*"}')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "&>"]
    current_defaults.remove("x_source")
    assert conds["custom"]["x_source"] == "hostmask"
    sig.cmd_update("/conditions/custom/x_source", "nick")
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "!source>", "<default", "&>"]
    sig._OnModCommand('update /expressions/custom @@ {"eq": "tbo"}')
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
    sig._OnModCommand('update /expressions/custom @@ {"has": "dummy"}')
    sig.cmd_update("/conditions/custom/body", "default")
    #
    # Change default condition to always fail
    sig._OnModCommand('update /expressions/default @@ {"!has": ""}')
    assert conds["custom"]["body"] == "default"
    assert sig.reckon(data) is False
    assert data_reck == ["<custom", '!network>', "<default", '!network>']
    #
    # Change per-condition, collective expressions bias
    current_defaults.remove("x_policy")  # only governs expressions portion
    assert conds["custom"]["x_policy"] == "filter"
    sig._OnModCommand('update /conditions/default/x_policy first')
    assert sig.reckon(data) is False
    assert data_reck == ["<custom", "|>", "<default", "|>"]  # Falls through
    #
    assert not current_defaults
    #
    # "FIRST" (short circuit) hit
    sig._OnModCommand('update /conditions/custom/body custom')
    assert sig.reckon(data) is True
    assert data_reck == ["<custom", "body!>"]
    #
    sig._OnModCommand('update /conditions/onetime @@ {}')
    from textwrap import dedent
    sig.cmd_select("../")
    # Clear module buffer (lots of '/foo =>' output so far)
    assert "Error" not in sig._read()
    #
    # Add another condition that runs ahead of 'custom'
    sig._OnModCommand('select')
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
