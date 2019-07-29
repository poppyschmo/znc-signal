# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import pytest


def test_ordered_pprint():
    # Ensure monkey patching doesn't harm global pprint module
    from Signal.ootil import ordered_pprint, OrderedPrettyPrinter
    import pprint
    assert ordered_pprint.__dict__ is not pprint.__dict__
    assert pprint._safe_repr is not ordered_pprint._safe_repr
    #
    opp = OrderedPrettyPrinter()
    pp = pprint.PrettyPrinter()
    # Shallow mapping behaves correctly
    d_ordered = dict(one=1, two=2, three=3, four=4)
    assert opp.pformat(d_ordered) != pp.pformat(d_ordered)
    d_sorted = dict(sorted(d_ordered.items()))
    assert opp.pformat(d_sorted) == pp.pformat(d_sorted)
    #
    # Same at depth
    d_ordered.update({"five": dict(d_ordered)})
    assert opp.pformat(d_ordered) != pp.pformat(d_ordered)
    d_ordered["five"] = dict(d_sorted)
    d_sorted = dict(sorted(d_ordered.items()))
    assert opp.pformat(d_sorted) == pp.pformat(d_sorted)



def test_unescape_unicode_char():
    from Signal.ootil import unescape_unicode_char
    #
    def analog(s):  # noqa: E306
        if s.startswith("U+"):
            s = "\\U{:08x}".format(int(s.replace("U+", ""), 16))
        from ast import literal_eval
        while len(s) > 1 and s.startswith("\\"):
            s = literal_eval("'{}'".format(s))
        return s
    #
    inputs = ["\U000020BF",
              "\\U000020BF",
              "\\u20BF",
              "\\u20bf",
              "\\U000020bf",
              "\\\\u20BF",
              "U+20BF"]
    uuc = unescape_unicode_char
    assert uuc("\u20BF") == "₿"
    assert all(analog(r) == uuc(r) == "₿" for r in inputs) is True
    with pytest.raises(ValueError):
        uuc("ab")
    with pytest.raises(ValueError):
        uuc("42")
    xinputs = ["\\\\x42", "\\x42"]
    assert all(analog(r) == uuc(r) == "B" for r in xinputs) is True
    Uinputs = ["\U0001F21A", "U+1F21A", "\\U0001F21A"]
    assert all(analog(r) == uuc(r) == "\U0001F21A" for r in Uinputs) is True
    # Valid singles
    assert analog("\\") == uuc("\\") == "\\"
    assert analog("u") == uuc("u") == "u"
    assert analog("U") == uuc("U") == "U"
    assert analog("x") == uuc("x") == "x"
    # Invalid escapes
    int_msg = "invalid literal for int() with base 16: ''"
    with pytest.raises(ValueError) as exc_info:
        uuc("\\u")
    assert exc_info.value.args[0] == int_msg
    with pytest.raises(ValueError) as exc_info:
        uuc("\\U")
    assert exc_info.value.args[0] == int_msg
    with pytest.raises(ValueError) as exc_info:
        uuc("\\x")
    assert exc_info.value.args[0] == int_msg
    with pytest.raises(ValueError) as exc_info:
        uuc("U+")
    assert exc_info.value.args[0] == int_msg


def test_version():
    from Signal.commonweal import get_version
    from math import inf
    assert get_version("1.7.0") == (1, 7, 0)
    assert get_version("1.7.0-rc1") == (1, 7, 0)
    assert get_version("1.7") == (1, 7)
    assert get_version("1.7.x") == (1, 7, inf)
    # Note: the SHA abbrev happens to be 7 xdigits, but that's likely not
    # guaranteed. The docker-image "vcs-ref" label holds the full SHA.
    extra = "+docker-git-1.7.x-znc-1.7.0-50-g2058aa0"
    #                          ^^^^^^^^^^^^^^^^^^^^^ git-describe
    #                    ^^^^^^ TRAVIS_BRANCH + sep
    #        ^^^^^^^^^^^^ VERSION_EXTRA
    assert get_version("1.7.x" + extra) == (1, 7, inf)
    assert get_version("1.7.x", extra) == (1, 7, inf)
