import ast
import os
import pytest
from extras.inspect_hooks import znc, InspectHooks
from extras.inspect_hooks.helpers import get_deprecated_hooks

znc_url = "https://znc.in/releases/archive/znc-{rel}.tar.gz"
pinned_releases = ("1.7.0", "1.7.1", "1.7.3", "1.7.4")


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


def test_normalize_hook_args(base_dir, cpymodule_hook_args):
    from conftest import any_in
    release, hook_args = cpymodule_hook_args
    # TODO see if any of this is still needed after ditching 1.6.x
    from glob import glob
    message_related = glob(f"{base_dir}/znc-{release}/**/Message.[hc]*",
                           recursive=True)
    #
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
    #
    # Note: this no longer *directly* affects the main Signal class because
    # it no longer imports "deprecated_hooks". However, the inspector
    # helper still relies on it, and that's used to keep things current.
    deprecated_hooks = get_deprecated_hooks(hook_args.keys())
    assert deprecated_hooks == outliers | deprecados
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
    assert not all_sliners - deprecated_hooks


class C:
    def OnOne(self):
        print(C.OnOne.__qualname__)

    def OnTwo(self):
        print(C.OnTwo.__qualname__)

    def OnThree(self):
        print(C.OnThree.__qualname__)

    def OnFour(self):
        print(C.OnFour.__qualname__)


class D(C):

    def __getattribute__(self, name):
        candidate = super().__getattribute__(name)
        if name.startswith("On"):
            try:
                candidate = super().__getattribute__(f"_{name}")
            except AttributeError:
                return self.do_wrap(candidate)
        return candidate

    def OnOne(self):
        print(D.OnOne.__qualname__)

    def _OnTwo(self):
        print(D._OnTwo.__qualname__)

    def do_wrap(self, f):
        def wrapped(*args, **kwargs):
            print(f"Wrapped: ", end="")
            f(*args, **kwargs)
        from functools import update_wrapper
        return update_wrapper(wrapped, f)


def on_four(inst):
    "Func for patching D"
    print(inst.OnFour.__qualname__)


def test_inspect_hooks_simplified(capsys):
    d = D()
    d.OnOne()
    d.OnTwo()
    d.OnThree()
    # Patched method retains original __qualname__
    d.__dict__["OnFour"] = on_four.__get__(d)
    d.OnFour()
    out, __ = capsys.readouterr()
    from textwrap import dedent
    assert out.rstrip() == dedent("""
        Wrapped: D.OnOne
        D._OnTwo
        Wrapped: C.OnThree
        Wrapped: on_four
    """).strip()


def test_inspect_hooks(capsys):

    def fake_on_load(self, *args):
        """Overridden with underscore (ignore, don't wrap)"""

    def fake_on_user_raw(self, *args):
        """Non-overriden (wrap)"""

    def fake_on_client_login_znc(self, *args):
        """Overridden normal (wrap)"""

    def fake_on_client_login_mod(self, *args):
        """Overridden normal (wrap)"""

    # Patch superclass (our fake "test" znc.Module in tests/znc.py)
    manifest_znc = dir(znc.Module)
    manifest_mod = dir(InspectHooks)
    znc.Module.OnLoad = fake_on_load
    znc.Module.OnUserRaw = fake_on_user_raw
    znc.Module.OnClientLogin = fake_on_client_login_znc
    InspectHooks.OnClientLogin = fake_on_client_login_mod

    # __wrapped__ is from functools.update_wrapper
    mod = InspectHooks()
    assert mod.OnLoad.__func__ is InspectHooks._OnLoad
    assert mod.OnUserRaw.__wrapped__.__func__ is znc.Module.OnUserRaw
    assert (mod.OnClientLogin.__wrapped__.__func__ is
            InspectHooks.OnClientLogin)

    # Restore
    del znc.Module.OnLoad
    del znc.Module.OnUserRaw
    del znc.Module.OnClientLogin
    del InspectHooks.OnClientLogin
    assert manifest_znc == dir(znc.Module)
    assert manifest_mod == dir(InspectHooks)
