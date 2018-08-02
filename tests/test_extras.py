from extras.inspect_hooks import InspectHooks, znc


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
