# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import pytest
import dummy_conf as dummy
from Signal.dictchainy import BaseConfigDict as _BCD__debug
_BCD__debug.debug = True


def test_basic_python_dict_comparisons():
    """
    From docs_:

        Mappings (instances of dict) compare equal if and only if they
        have equal (key, value) pairs. Equality comparison of the keys
        and values enforces reflexivity.

    .. _docs: https://docs.python.org/3.6/reference
        /expressions.html#value-comparisons
    """
    # Reprove basic dict __eq__ facts as reference for below
    from collections import OrderedDict
    d1 = dict(one=1, two=2)
    d2 = dict(two=2, one=1)
    #
    assert d1 == d2
    assert OrderedDict(d1) == OrderedDict(dict(one=1, two=2))
    assert OrderedDict(d1) != OrderedDict(d2)
    assert OrderedDict(d1) == d2  # unordered wins
    assert d1 == OrderedDict(d2)
    assert OrderedDict() == {}
    #
    # Only membership is tested with KeysView instances
    assert OrderedDict(d1).keys() == OrderedDict(d2).keys() == \
        d1.keys() == d2.keys() == {"one", "two"}
    #
    assert list(d1) != list(d2)
    assert list(d1) == list(dict(one=1, two=2))
    #
    # NOTE dont' bother with proving insertion-order behavior for normal dicts
    # because docs say it's implementation dependent
    #
    from types import MappingProxyType
    assert {} == MappingProxyType({})
    assert {"one": 1} == MappingProxyType({"one": 1})
    #
    from collections import UserDict
    assert UserDict({}) == UserDict(None) == UserDict()
    #
    assert dict(range(0)) == dict() == dict([]) == dict("") == {}


def test_inner_maps():
    from Signal.dictchainy import ChainoBase, MappingProxyType
    with pytest.raises(ValueError):
        ChainoBase()
    assert repr(ChainoBase({})) == "ChainoBase(mappingproxy({}))"
    assert len(ChainoBase({}).maps) == 1
    assert isinstance(ChainoBase({}).maps.pop(), MappingProxyType)
    # Last backing dict is kept as is when passed in
    assert repr(ChainoBase({}, {})) == \
        'ChainoBase(OrderedDict(), mappingproxy({}))'
    assert isinstance(ChainoBase({}, {}).maps.pop(), MappingProxyType)
    assert repr(ChainoBase({"one": 1})) == \
        "ChainoBase(mappingproxy({'one': 1}))"
    # All protected inner maps are also mapping proxies
    assert isinstance(ChainoBase({"one": {"two": ...}}).maps[-1]["one"],
                      MappingProxyType)
    # TODO add ChainoFixe tests


def test_base_config_dict():
    from Signal.dictchainy import BaseConfigDict
    from conftest import same_same, map_eq
    #
    assert map_eq(repr,
                  BaseConfigDict(),
                  BaseConfigDict({}),
                  BaseConfigDict({}, **{}),
                  BaseConfigDict({}, user_map={}),
                  BaseConfigDict({}, user_map={}, **{}),
                  BaseConfigDict(backing_map={}, user_map={}, **{}),
                  ref_obj="{}")
    assert BaseConfigDict().backing == {}
    # .backing attr is a shallow copy of last arg
    d = {"one": 1}
    assert BaseConfigDict(d).backing == d
    assert BaseConfigDict(d).backing is not d
    # Kwargs only update the user dict
    assert BaseConfigDict(**d).backing != d
    # .user attr is a shallow copy of first of two args:
    u = {"two": 2}
    assert BaseConfigDict(d, user_map={"two": 2}).user == u
    assert BaseConfigDict(d, user_map=u).user == u
    assert BaseConfigDict(d, user_map=u).user is not u
    assert BaseConfigDict(d, two=2).user == u
    assert BaseConfigDict(d, user_map=u).backing == d
    # shallow means nested dicts are just references
    du = dict(d=dict(d), u=dict(u))
    bcd_d = BaseConfigDict(du)
    bcd_u = BaseConfigDict(**du)
    du["d"]["THREE"] = "3!"
    du["u"]["two"] = ...
    assert "THREE" in bcd_d.backing["d"]
    assert bcd_d.backing["u"]["two"] is ...
    assert "THREE" in bcd_u.user["d"]
    assert bcd_u.user["u"]["two"] is ...
    #
    # Doesn't wrap .backing in anything special
    assert same_same(dict, *map(type, (BaseConfigDict().backing,
                                       BaseConfigDict(d).backing)))
    # Confusing 'wrong number of args' message
    with pytest.raises(TypeError) as exc_info:
        BaseConfigDict(d, u)
    assert ("__init__() takes from 1 to 2 positional arguments "
            "but 3 were given") == exc_info.value.args[0]
    #
    # Equality comparisons rely on ``dict(inst.data)``
    from types import MappingProxyType
    non = {"mpt": d}
    mpt = {"mpt": MappingProxyType(d)}
    assert BaseConfigDict(non) == BaseConfigDict(mpt) == non == mpt
    # "inst.user" maps are ignored completely because they're only really used
    # by subclasses to build inst.data ChainMaps
    assert BaseConfigDict(non, user_map={"a": 1}) == \
        BaseConfigDict(mpt, user_map={"b": 2})


def test_settings_dict():
    from Signal.configgers import default_config
    from Signal.dictchainy import (SettingsDict, OrderedDict, ChainoFixe,
                                   MappingProxyType)
    SettingsDict.debug = True
    #
    # Initializing with empty dict or no args
    from conftest import map_eq
    assert map_eq(
        repr,
        SettingsDict().data,
        SettingsDict({}).data,
        SettingsDict(OrderedDict()).data,
        ChainoFixe({}, MappingProxyType(OrderedDict())),
        ChainoFixe(OrderedDict(), MappingProxyType(OrderedDict())),
        ref_obj="ChainoFixe(OrderedDict(), mappingproxy(OrderedDict()))"
    )
    # Non-empty still gets converted to OrderedDict
    assert map_eq(
        repr,
        SettingsDict({"one": 1}).data,
        SettingsDict(OrderedDict({"one": 1})).data,
        ChainoFixe(OrderedDict(), MappingProxyType(OrderedDict({"one": 1}))),
        ref_obj="ChainoFixe(OrderedDict(), "
                "mappingproxy(OrderedDict([('one', 1)])))"
    )
    sd = SettingsDict()
    assert sd.maps is sd.data.maps
    assert isinstance(sd.maps[-1], MappingProxyType)
    assert isinstance(sd.maps[-1].copy(), OrderedDict)
    #
    # No dicts allowed as members (when debug is active)
    with pytest.raises(AssertionError):
        SettingsDict({"one": {"two": ...}})
    #
    # Normal behavior: dicts compare equal regardless of key ordering
    D = default_config.settings
    D_snapshot = repr(D)
    U = SettingsDict(D)
    U_v1 = SettingsDict(D, user_map={})
    #
    # Basic properties: has .data attr from UserDict and .maps from ChainMap
    assert U.data == U == U_v1.data == U_v1
    assert U.data.maps == U.maps == U_v1.data.maps == U_v1.maps
    #
    # Basic operations
    with pytest.raises(KeyError):  # can't set unknown key
        U["fake key"] = "fake value"
    with pytest.raises(KeyError):  # can't delete a default item
        del U["host"]
    U["host"] = "example.com"
    del U["host"]
    with pytest.raises(TypeError):  # must set correct type
        U["host"] = 1
    #
    # Simulate loading from ZNC's built-in store
    import json
    user_in = json.loads(dummy.json_settings)
    U1 = SettingsDict(D, **user_in)
    assert U1.user is not U1.maps[0]  # LHS is just a backup of orig input
    assert U1.user == user_in and U1.user is not user_in
    #
    # Baking
    # Returns sorted root dict unless it's an OrderedDict
    assert list(sorted(D)) != list(D)
    assert repr(U.bake()) == repr(U_v1.bake()) == repr(dict(D))
    # Peeled bakes do *not* call ``__getitem__`` on all PRO items
    assert U1.peel() == user_in == U1.user
    # But full baking *does*
    assert "authorized" in U1.bake() and U1.bake() != user_in
    assert U1.bake() == dict(**user_in, authorized=[], config_version=0.2)
    # "authorized" gets inserted at the end, so reprs won't match
    assert repr(U1.bake()) != repr(dict(**user_in, authorized=[]))
    with pytest.raises(KeyError) as exc_info:
        del U1["authorized"]
    assert "Cannot delete default item" in exc_info.value.args
    # Ensure proper baked key order for newly created MOD item
    # Note: ``dict_keys`` uses set-like ``__eq__``, hence ``list()``
    U1["authorized"] = []
    assert repr(U1.bake()) == repr(dict(U1))
    U1["authorized"] = ["+11111111111"]
    assert list(U1.bake().keys()) == list(U1.maps[-1].keys())
    # Back to one
    del U1["authorized"]
    assert json.dumps(U1.peel(), indent=2) == dummy.json_settings
    # Only save what's been modified (version is dealt with in manage_config())
    assert U1.peel() == user_in  # no empty fields
    del U1["host"]
    assert U1.peel() != user_in
    assert U1["host"] == D["host"]
    #
    # The MutableMapping methods overridden in __init__ only affect .maps[0]
    U2 = eval(U1._construction_repr())
    assert U1 == U2 and repr(U1) == repr(U2)
    U1.clear()  # works as expected
    assert U1 == U
    del U2.popitem
    U2.clear()  # fails, items remain
    assert U2 != U1 and U2.peel() != {}
    from conftest import all_in
    assert all_in(list(U2.peel()), "port", "obey")
    assert next(iter(U2)) == "host"
    assert "host" not in U2.maps[0]
    with pytest.raises(KeyError) as exc_info:  # simulate bound methods
        del U2[next(iter(U2))]
    assert exc_info.value.args[0] == 'Cannot delete default item'
    U2.popitem = U2.data.popitem  # may be implementation specific
    U2.clear()
    assert U2 == U1
    #
    # User items matching default ones are peeled away during storage prep
    U1["host"] = ""
    assert U1.maps[0]["host"] == U1.maps[-1]["host"] == ""
    assert U1.maps[0] == OrderedDict([('host', '')])
    assert U1.peel() == {}
    #
    assert repr(D) == D_snapshot


def test_expressions_dict():
    from Signal.configgers import default_config
    from Signal.dictchainy import ExpressionsDict
    assert ExpressionsDict.debug is True
    #
    D = default_config.expressions
    D_snapshot = repr(D)
    #
    U = ExpressionsDict(D)
    U_v1 = ExpressionsDict(U)  # misleading (deep objects are not duplicated)
    U_v2 = ExpressionsDict(D, user_map={})
    assert U == U_v1 == U_v2
    assert repr(U) == repr(U_v1)  # also potentially misleading (must use bake)
    assert repr(U.bake()) == repr(U_v1.bake()) == D_snapshot
    assert U_v1.peel() == U.peel() == {}
    #
    # Can't delete default
    with pytest.raises(KeyError):
        del U["default"]
    # Calling clear() doesn't delete backing dict
    assert not U.maps[0]
    U["not_default"] = {"has": "foo"}
    assert U.maps[0]
    U.clear()
    assert not U.maps[0]
    assert len(U.maps) == 2 and U.maps[-1]
    # Expression ops are not checked here
    U["default"] = {"fake key": "fake value"}
    assert U["default"] == {"fake key": "fake value"}
    # Expressions values are not checked for type
    U["default"] = {"fake key": ...}
    # Flattening creates new objects
    assert U.bake()["default"]["fake key"] == U["default"]["fake key"]
    assert U.bake()["default"] is not U["default"]
    # Can delete user-shadowed item
    del U["default"]
    #
    assert U["default"] != {}  # -> mappingproxy({'has': ''})
    assert U["default"] == U_v1["default"]
    #
    # If user item compares equal to protected counterpart, it's peeled away
    U["default"] = dict(U["default"])
    assert U.peel() == {}
    del U["default"]
    # Note: see settings/conditions variants for nested chain maps
    D_v1 = {"default": {"all": [{"has": "foo"}, {"!has": "bar"}]}}
    U_v2 = ExpressionsDict(D_v1, user_map={})
    # Mapping proxies compare equal to normal dicts
    assert repr(U_v2["default"]).startswith("mappingproxy(mappingproxy(")
    assert U_v2["default"] == {'all': [{'has': 'foo'}, {'!has': 'bar'}]}
    # Changing value of nested rhs item causes comparison to fail
    assert U_v2["default"] != {'all': [{'has': 'foo'}, {'!has': 'baz'}]}
    U_v2["default"] = {'all': [{'has': 'foo'}, {'!has': 'bar'}]}
    # Follows for nested protected entry
    assert U_v2.peel() == {}
    U_v2["default"]["all"][-1]["!has"] = "baz"
    assert U_v2.peel() == \
        {"default": {'all': [{'has': 'foo'}, {'!has': 'baz'}]}}
    #
    # Accessing items
    exp_name, exp_val = list(D["default"].items()).pop()  # -> ("has", "")
    assert isinstance(U["default"][exp_name], type(exp_val))
    with pytest.raises(TypeError):
        del U["default"][exp_name]
    with pytest.raises(TypeError):
        U["default"][exp_name] = "some value"
    #
    U["custom"] = {"fake key": "fake value"}
    assert len(U.bake()) == 2
    assert len(U.peel()) == 1
    with pytest.raises(TypeError):
        U["invalid"] = ...
    #
    # Modifiable dict is sorted on init and with every insertion
    import json
    user_in = json.loads(dummy.json_expressions)
    U1 = ExpressionsDict(D, **user_in)
    assert json.dumps(U1.peel(), indent=2) == dummy.json_expressions
    snapshot = repr(U1)
    custom = U1.pop("custom")
    U1["custom"] = custom  # insert at end (after "dummy")
    assert repr(U1) == snapshot
    assert json.dumps(U1.peel(), indent=2) == dummy.json_expressions
    #
    assert repr(D) == D_snapshot
    #
    # Ordering (everything's constantly sorted)
    assert list(U) == ['custom', 'default']
    for key in "zebra":
        U[key] = {}
    assert list(U) == ['a', 'b', 'custom', 'e', 'r', 'z', 'default']
    assert U.peel() == {'a': {}, 'b': {}, 'custom': {'fake key': 'fake value'},
                        'e': {}, 'r': {}, 'z': {}}
    # Modifying an existing item occurs in place (nothing reinserted)
    U["b"] = {"! has": "foo"}
    assert list(U) == ['a', 'b', 'custom', 'e', 'r', 'z', 'default']
    assert list(U.peel()) == ['a', 'b', 'custom', 'e', 'r', 'z']
    assert U.peel()["b"] == {"! has": "foo"}


def test_conditions_dict():
    from Signal.configgers import default_config
    from Signal.dictchainy import (ConditionsDict, Condition, ChainoBase,
                                   OrderedDict)
    # Set debug attr for internal data members (i.e., "Condition" dicts)
    assert ConditionsDict.debug is True
    assert Condition.debug is True
    #
    # Basic constructor invariants
    with pytest.raises(KeyError):
        ConditionsDict()
    with pytest.raises(KeyError):
        ConditionsDict({})
    with pytest.raises(TypeError):
        ConditionsDict({"one": 1})
    # .data attr is normal ChainoBase plus this:  vv
    assert isinstance(ConditionsDict({"default": {}}).data, ChainoBase)
    # Protected map is converted to OrderedDict  ^^ (and proxified)
    assert isinstance(
        ConditionsDict({"default": {}}).maps[-1]["default"].copy(),
        OrderedDict
    )  # Note: calling .copy() clones original from proxy
    assert repr(ConditionsDict({"default": {}}).maps[-1]) == \
        "mappingproxy({'default': mappingproxy(mappingproxy(OrderedDict()))})"
    #
    D = default_config.conditions
    D_snapshot = repr(D)
    U = ConditionsDict(D)
    #
    with pytest.raises(KeyError):
        del U["default"]
    with pytest.raises(KeyError):  # Value type doesn't matter if protected
        U["default"] = ...
    with pytest.raises(KeyError):
        U["default"] = {}
    #
    from collections import UserDict
    for item in [UserDict, [], 0, 0.0, ""]:  # New items must be dicts
        with pytest.raises(TypeError):
            U["custom"] = item
    #
    # Changing a default value
    assert isinstance(D["default"]["away_only"], bool)
    U["default"]["away_only"] = not D["default"]["away_only"]
    assert U["default"]["away_only"] == (not D["default"]["away_only"])
    assert U.bake()["default"]["away_only"] == (not D["default"]["away_only"])
    assert len(U.peel()["default"]) == 1
    assert "away_only" in U.peel()["default"]
    # Assigning same value as default
    U["default"]["away_only"] = D["default"]["away_only"]
    assert "away_only" in U["default"].maps[0]
    assert U.peel() == {}  # peeled away
    del U["default"]["away_only"]
    # Attempt to assign wrong type
    with pytest.raises(TypeError) as exc:
        U["default"]["away_only"] = "foo"
    assert exc.value.args == (
        "Condition/away_only must be of type 'bool', not 'str'", bool
    )
    #
    import json
    dummy_saved = json.loads(dummy.json_conditions)
    dummy_saved_snap = (repr(dummy_saved), id(dummy_saved))
    U1 = ConditionsDict(backing_map=D, user_map=dummy_saved)
    # Loading preserves input dict
    assert dummy_saved_snap == (repr(dummy_saved), id(dummy_saved))
    assert json.loads(json.dumps(U1.peel())) == dummy_saved
    #
    # Lookups devolving to user modified defaults
    drop_one = (dummy_saved["default"].keys() - dummy_saved["custom"].keys())
    # Lookups devolving back to D
    drop_all = (D["default"].keys() -
                dummy_saved["default"].keys() - dummy_saved["custom"].keys())
    for key in drop_one:
        assert U1["custom"][key] == U1["default"][key]
    for key in drop_all:
        assert U1["custom"][key] == D["default"][key]
    #
    # Ordering - both "custom" and "default" dummy conditions have their
    # expressions out-of-order (compared to backing default dict)
    ds_cus = [list(D["default"]).index(k) for k in dummy_saved["custom"]]
    assert list(sorted(ds_cus)) != ds_cus  # [1, 5, 7, 11, 15, 14] for v0.2
    assert list(dummy_saved["custom"])[-2:] == ['body', 'source']
    ds_def = [list(D["default"]).index(k) for k in dummy_saved["default"]]
    assert list(sorted(ds_def)) != ds_def  # [3, 6, 14, 12]
    assert list(dummy_saved["default"])[-2:] == ['source', 'network']
    # Peeling applies default ordering to output:
    #   1. network, 2. target, 3. source, 4. body
    reordiff = [(new.strip(), orig.strip()) for new, orig in
                zip(json.dumps(U1.peel(), indent=2).splitlines(),
                dummy.json_conditions.splitlines()) if new != orig]
    #                                   new     orig
    assert reordiff == [('"source": "custom",', '"body": "custom",'),
                        ('"body": "custom"', '"source": "custom"'),
                        # ^^^^^^^^^^^^ [custom / default] vvvvvvvvvvv
                        ('"network": "dummy",', '"source": "dummy",'),
                        ('"source": "dummy"', '"network": "dummy"')]
    #
    # The "protected" map of non-default dicts is just a link to the main
    # default, itself a chain map
    assert U1["custom"].maps[-1] is U1["default"]
    # Read-only maps (proxies for default_config)
    assert U1.maps[-1]["default"] is U1["custom"].maps[-1].maps[-1]
    assert U1.maps[-1]["default"] is U1["default"].maps[-1]
    #
    assert U1["custom"]["replied_only"] is True
    assert [(o, i, U1[o].maps[i].get("replied_only"))
            for o in ("custom", "default")
            for i in (0, -1)] == [('custom', 0, None),
                                  ('custom', -1, True),  # <- just a pointer to
                                  ('default', 0, True),  # <- this
                                  ('default', -1, False)]
    del U1["default"]["replied_only"]
    assert [(o, i, U1[o].maps[i].get("replied_only"))
            for o in ("custom", "default")
            for i in (0, -1)] == [('custom', 0, None),
                                  ('custom', -1, False),   # <- now points to
                                  ('default', 0, None),
                                  ('default', -1, False)]  # <- this
    assert U1["custom"]["replied_only"] is False
    U1["default"]["replied_only"] = True  # restore for stuff below
    #
    # Removing custom items and modified defaults restores newly minted state
    assert len(U1) == 2
    del U1["custom"]
    with pytest.raises(KeyError):
        U1["custom"]
    assert len(U1) == 1
    # Attempt to delete default dict fails
    with pytest.raises(KeyError) as exc:
        del U1["default"]
    assert exc.value.args[0] == "Cannot delete default item"
    # Calling clear() preserves both modifiable default and backing dict
    assert len(U.maps[0]) == 1 and "default" in U.maps[0]
    U["custom"] = {"away_only": True}
    assert list(U.maps[0]) == ['default', 'custom']
    U.clear()
    assert list(U.maps[0]) == ['default']  # User default intact
    assert len(U.maps) == 2 and U.maps[-1]  # primary backing intact (obvious)
    # Modifiable default dict still equals dummy.json_conditions (same 4 items)
    assert len(U1["default"].maps) == 2
    assert len(U1["default"].maps[0]) == 4
    U1["default"].clear()
    assert len(U1["default"].maps) == 2
    assert len(U1["default"].maps[0]) == 0
    assert repr(U1.bake()) == repr(U.bake())
    #
    assert repr(D) == D_snapshot
    #
    # Basic characteristics of Condition (and Template) dicts. Obvious from
    # definition but nice to have reference when messing w. ConfigDict.bake()
    from Signal.dictchainy import Condition, ChainoFixe, OrderedDict
    # All ConditionsDict members are Condition dicts
    assert isinstance(U["default"], Condition)
    # 1. have a ChainoFixe for their .data attr
    assert isinstance(U["default"].data, ChainoFixe)
    # 2. have a .bake attr and .maps attr
    assert hasattr(U["default"], "bake") and hasattr(U["default"], "maps")
    # 3. have an OrderedDict for .maps[0]
    assert isinstance(U["default"].maps[0], OrderedDict)
    #
    # Ordering
    assert list(U) == ["default"]
    for key in "zebra":
        U[key] = {}
    assert list(U) == ["z", "e", "b", "r", "a", "default"]
    assert U.peel() == {'z': {}, 'e': {}, 'b': {}, 'r': {}, 'a': {}}
    from conftest import all_eq
    assert all_eq(U.bake().items())
    # Modifying an existing item occurs in place (nothing's reinserted)
    U["z"]["x_source"] = "nick"
    assert list(U) == ["z", "e", "b", "r", "a", "default"]
    assert list(U.peel()) == ["z", "e", "b", "r", "a"]
    assert U.peel()["z"] == {"x_source": "nick"}
    #
    # Moving
    snapshot = U._construction_repr()
    # NOTE can't use normal repr for comparing ordered contents because
    # modified defaults may be out of place. The ._construction_repr() method
    # works as expected in this regard.
    with pytest.raises(KeyError):
        U.move_modifiable("b", "default")
    with pytest.raises(KeyError):
        U.move_modifiable("default", "b")
    with pytest.raises(KeyError):
        U.move_modifiable("default", 0)
    orig = ["z", "e", "b", "r", "a", "default"]
    # Can't swap adjacent going from left to right
    for src, dest in ("ze", "eb", "br", "ra"):
        U.move_modifiable(src, dest)
        assert list(U) == orig
    #
    # TODO use pytest's built-in combo tools automate these
    U.move_modifiable("e", "z")
    assert list(U) == ["e", "z", "b", "r", "a", "default"]
    U.move_modifiable("z", "e")
    assert list(U) == orig
    U.move_modifiable("a", "r")
    assert list(U) == ["z", "e", "b", "a", "r", "default"]
    U.move_modifiable("r", "a")
    assert list(U) == orig
    U.move_modifiable("e", "r")
    assert list(U) == ["z", "b", "e", "r", "a", "default"]
    U.move_modifiable("e", "b")
    assert list(U) == orig
    #
    # Switcharoo
    from itertools import (combinations, combinations_with_replacement,
                           permutations)
    combs = combinations
    rcomb = combinations_with_replacement
    perms = permutations
    for pair in combs("zebra", 2):
        for out, back in set(perms(perms(pair))) | set(rcomb(perms(pair), 2)):
            left, right = out
            effect = list("zebra".replace(left, "!").replace(right, left)
                          .replace("!", right)) + ["default"]
            # {(('L', 'R'), ('L', 'R')),    <-- inner
            #  (('L', 'R'), ('R', 'L')),    <-- loop
            #  (('R', 'L'), ('L', 'R')),    <-- makes
            #  (('R', 'L'), ('R', 'L'))}    <-- these
            U.move_modifiable(*out, True)
            assert list(U) == effect
            U.move_modifiable(*back, True)
            assert list(U) == orig
    #
    # Numeric shift
    U.move_modifiable("z", 1, True)
    assert list(U) == ["e", "z", "b", "r", "a", "default"]
    U.move_modifiable("z", -1, True)
    assert list(U) == orig
    U.move_modifiable("z", 2, True)
    assert list(U) == ["e", "b", "z", "r", "a", "default"]
    U.move_modifiable("z", -2, True)
    assert list(U) == orig
    U.move_modifiable("r", 1, True)
    assert list(U) == ["z", "e", "b", "a", "r", "default"]
    U.move_modifiable("r", -1, True)
    assert list(U) == orig
    U.move_modifiable("a", -4, True)
    assert list(U) == ["a", "z", "e", "b", "r", "default"]
    U.move_modifiable("a", 4, True)
    assert list(U) == orig
    #
    # Explicit index
    for dest, src in enumerate("zebra"):  # dest is src index
        U.move_modifiable(src, dest)
        assert list(U) == orig
    U.move_modifiable("z", 1)
    assert list(U) == ["e", "z", "b", "r", "a", "default"]
    U.move_modifiable("z", 0)
    assert list(U) == orig
    U.move_modifiable("z", 2)
    assert list(U) == ["e", "b", "z", "r", "a", "default"]
    U.move_modifiable("z", 0)
    assert list(U) == orig
    U.move_modifiable("z", 3)
    assert list(U) == ["e", "b", "r", "z", "a", "default"]
    U.move_modifiable("z", 0)
    assert list(U) == orig
    U.move_modifiable("e", 2)
    assert list(U) == ["z", "b", "e", "r", "a", "default"]
    U.move_modifiable("e", 1)
    assert list(U) == orig
    U.move_modifiable("e", 0)
    assert list(U) == ["e", "z", "b", "r", "a", "default"]
    U.move_modifiable("e", 1)
    assert list(U) == orig
    U.move_modifiable("a", 3)
    assert list(U) == ["z", "e", "b", "a", "r", "default"]
    U.move_modifiable("a", 4)
    assert list(U) == orig
    U.move_modifiable("b", -1)
    assert list(U) == ["z", "e", "r", "a", "b", "default"]
    U.move_modifiable("b", 2)
    assert list(U) == orig
    U.move_modifiable("a", -4)
    assert list(U) == ["z", "a", "e", "b", "r", "default"]
    U.move_modifiable("a", -1)
    assert list(U) == orig
    assert snapshot == U._construction_repr()
    #
    # Spread
    assert U1.peel() == {}
    assert D == default_config.conditions
    assert D["default"] == dict(U1.maps[-1]["default"])
    # When no modified default exists, the backing default dict is inserted
    # last, which happens to be the desired position for this class
    U1.maps[0]["default"].maps[0] == OrderedDict()
    U1["custom"] = {"away_only": True,
                    "template": "custom",
                    "x_source": "nick"}
    spread = U1.peel(U1.spread)
    assert "default" not in U1.peel()
    assert spread["custom"] == U1["custom"].peel()
    assert list(spread["custom"]) == list(U1["custom"].peel())
    assert spread["default"] == D["default"]
    assert list(spread["default"]) == list(D["default"])
    assert list(spread["default"].values()) == list(D["default"].values())
    # Modified default items are retained in their preferred position, but
    # changes bubble upward to affect now matching items in custom conditions
    U1["default"].update({"timeout_idle": 100, "template": "custom"})
    assert U1.maps[0]["default"].maps[0] == \
        OrderedDict({"timeout_idle": 100, "template": "custom"})
    spread = U1.peel(peel=U1.spread)
    assert spread["custom"] == U1["custom"].peel()
    assert "template" not in spread["custom"]  # dropped
    assert spread["default"] != D["default"]
    assert list(spread["default"]) == list(D["default"])  # ordering retained


def test_templates_dict():
    # TODO some of these are leftovers describing obsolete behavior; they still
    # work but are superfluous and should be excised
    from Signal.configgers import default_config
    from Signal.dictchainy import TemplatesDict, Template, ProtectedItemError
    assert TemplatesDict.debug is True
    assert Template.debug is True
    #
    D = default_config.templates
    U = TemplatesDict(D)
    # See ConditionsDict tests above
    assert U["default"].maps[-1] is U.maps[-1]["default"]
    protected_rec_id = id(U.maps[-1]["default"]["recipients"])
    # Modifiable recipients list doesn't exist, and appending doesn't create
    assert len(U.maps[0]["default"].maps[0]) == 0
    with pytest.raises(ProtectedItemError):
        U["default"]["recipients"].append("+12345678900")
    assert len(U.maps[0]["default"].maps[0]) == 0
    U["default"]["recipients"] = ["+12345678900"]
    assert len(U.maps[0]["default"].maps[0]) == 1
    assert U["default"].peel() == {'recipients': ["+12345678900"]}
    # See ConditionsDict if this doesn't make sense
    assert U.maps[0]["default"]["recipients"] is U["default"]["recipients"]
    assert U["default"]["recipients"] == ['+12345678900']
    assert id(U["default"]["recipients"]) != protected_rec_id
    assert protected_rec_id == id(U.maps[-1]["default"]["recipients"])
    # Successful deletion of item from modifiable map
    del U["default"]["recipients"]
    assert len(U.maps[0]["default"].maps[0]) == 0
    # No automatic creation if accessing map directly (obvious)
    with pytest.raises(KeyError) as exc:
        U.maps[0]["default"].maps[0]["recipients"]
    assert exc.value.args[0] == "recipients"
    # Attempt to delete default version fails
    with pytest.raises(KeyError) as exc:
        del U["default"]["recipients"]
    assert exc.value.args[0] == "Cannot delete default item"
    # Plain lookup does not create empty modifiable
    assert U["default"]["recipients"] == []
    assert id(U["default"]["recipients"]) == protected_rec_id
    # New default
    U["default"]["recipients"] = []
    # Attempt to delete non-existing custom w. same message
    U["custom"] = {}
    assert U["custom"]["recipients"] is U["default"]["recipients"]
    with pytest.raises(KeyError) as exc:
        del U["custom"]["recipients"]
    assert exc.value.args[0] == "Cannot delete default item"
    del U["default"]["recipients"]  # throws no error
    assert "recipients" not in U["default"].maps[0]
    #
    # Assigning to custom/recipients works as expected
    U["custom"]["recipients"] = ["foo"]
    assert U["custom"]["recipients"] == ["foo"]
    # A phantom list is not created in defaults
    with pytest.raises(KeyError):
        U.maps[0]["default"].maps[0]["recipients"]
    del U["custom"]["recipients"]
    assert "recipients" in U["custom"]
    #
    r = "recipients"
    U["custom"][r] = ["+11111111111"]
    U["default"][r] = ["+99999999999"]
    assert U["custom"].maps[0][r] == ["+11111111111"]
    assert U["custom"].maps[-1].maps[0][r] == ["+99999999999"]
    #
    del U["custom"][r]
    assert U["custom"][r] == ["+99999999999"]
    assert U["custom"][r] is U["custom"].maps[-1].maps[0][r]
    assert U["custom"][r] is U["default"][r]
    #
    del U["default"][r]
    assert U["custom"][r] is U["custom"].maps[-1].maps[-1][r]
    from conftest import same_same
    assert same_same(U["custom"][r],
                     U["default"][r],
                     U["default"].maps[-1][r],
                     U.maps[-1]["default"][r],
                     ref_id=protected_rec_id)
    #
    # Ordering (auto-sorted exactly like ExpressionsDict)
    assert list(U) == ['custom', 'default']
    for key in "zebra":
        U[key] = {}
    assert list(U) == ['a', 'b', 'custom', 'e', 'r', 'z', 'default']
    assert U.peel() == {'a': {}, 'b': {}, 'custom': {},
                        'e': {}, 'r': {}, 'z': {}}
    from conftest import all_eq
    assert all_eq(U.bake().items())
    # Modifying an existing item occurs in place (nothing's reinserted)
    U["b"]["focus_char"] = "!"
    assert list(U) == ['a', 'b', 'custom', 'e', 'r', 'z', 'default']
    assert list(U.peel()) == ['a', 'b', 'custom', 'e', 'r', 'z']
    assert U.peel()["b"] == {'focus_char': '!'}
