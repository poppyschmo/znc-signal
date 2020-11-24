import pytest
from Signal.lexpresser import eval_boolish_json, get_has_regex


def test_regexp_cache():
    abc = get_has_regex("abc")
    abc_ = get_has_regex("abc")
    assert abc_ is abc
    assert abc.search("123.abc.456")
    assert abc.search("123 abc 456")
    assert not abc.search("123abc.456")
    xyz = get_has_regex(c for c in ("x", "y", "z"))
    xyz_ = get_has_regex(c for c in ("x", "y", "z"))
    assert xyz is xyz_
    assert xyz.search("01.y.23345456")
    assert xyz.search("01 y 23345456")
    assert not xyz.search("01y.23345456")

    ghi = get_has_regex("ghi.")
    ghi_ = get_has_regex("ghi.")
    assert ghi_ is ghi
    assert ghi.search("123.ghi.456")
    assert ghi.search("123 ghi. 456")


mes = (
    "There should be one-- and preferably only one "
    "--obvious way to do it. Although that way may "
    "not be obvious at first unless you're Dutch."
)

has_true = {"has": "Dutch."}
has_false = {"has": "dutch"}
has_all_true = {"has_all": mes.split()}
has_all_false = {"has_all": mes.split() + ["fake"]}
has_any_true = {"has_any": ["unless"]}
has_any_false = {"has_any": ["fake"]}


def feed(expression, mes=mes):
    cksum = hash(repr(expression))
    result = eval_boolish_json(expression, mes)
    assert cksum == hash(repr(expression))
    return result


def test_has():
    assert feed({"has": "123!"}, "abc 123! 456")
    assert feed({"has": "123!"}, "abc 123!456")
    assert not feed({"has": "123!"}, "abc123!456")
    #
    assert feed(has_true) is True
    assert feed(has_false) is False
    with pytest.raises(TypeError) as exc_info:
        feed({"has": []})
    assert exc_info.match("only takes a single string")


def test_has_all():
    assert feed(has_all_true) is True
    assert feed(has_all_false) is False
    with pytest.raises(TypeError) as exc_info:
        feed({"has_all": "fake"})
    assert exc_info.match("list")


def test_has_any():
    assert feed(has_any_true) is True
    assert feed(has_any_false) is False
    with pytest.raises(TypeError) as exc_info:
        feed({"has_any": "fake"})
    assert exc_info.match("list")
