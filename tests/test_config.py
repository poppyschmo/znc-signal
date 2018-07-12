# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import pytest
import dummy_conf as dummy
from conftest import signal_stub_debug
signal_stub_debug = signal_stub_debug


def inject_config_version(string):
    """Temporary kludge to provide alternate json dummy conf
    """
    # Input string be compacted (no spaces)
    from Signal.configgers import default_config
    latest = default_config.settings["config_version"]
    return string.replace(
        '},"expressions"', f',"config_version":{latest}}},"expressions"'
    )


def test_verify_dummy_conf():
    """ Housekeeping to ensure confs remain intact
    """
    # NOTE this does not check ``dummy.ini``
    import json
    loaded = json.loads(dummy.json_full)
    assert loaded == dummy.peeled
    assert json.dumps(loaded, indent=2) == dummy.json_full
    assert json.dumps(loaded["settings"], indent=2) == dummy.json_settings
    assert json.dumps(loaded["expressions"],
                      indent=2) == dummy.json_expressions
    assert json.dumps(loaded["templates"],
                      indent=2) == dummy.json_templates
    assert json.dumps(loaded["conditions"],
                      indent=2) == dummy.json_conditions
    # Ensure version number absent from peeled (not ini)
    assert "config_version" not in dummy.peeled["settings"]


def test_access_by_pathname():
    """
    # f(selector, tree, leafless=False) -> selector (path), obj, leaf (name)
    """
    from textwrap import dedent
    from Signal.configgers import access_by_pathname
    import reprlib
    #
    config = dict(one="1", two=2, three=dict(four=[], five={}))
    selectors = ("", "/", ".",
                 "/one", "../two",  # <- rhs: tops out, no "prefix" to prepend
                 "/two/fake", "./three/four",
                 "./fake", "three/four/..",
                 "three/five/fake", "/three/four/0")
    resolved, objects, __ = zip(*(access_by_pathname(sel, config) for
                                  sel in selectors))
    from os import PathLike
    assert all(isinstance(p, PathLike) for p in resolved)
    reprlib.aRepr.maxdict = 2
    sel2obj = "\n".join("{!r:19}=> {}".format(sel, reprlib.repr(val)) for
                        sel, val in zip(selectors, objects))
    # Old doctest output from access_by_pathname.<locals>.pluck()
    assert sel2obj == dedent("""
    ''                 => {'one': '1', 'three': {'five': {}, 'four': []}, ...}
    '/'                => {'one': '1', 'three': {'five': {}, 'four': []}, ...}
    '.'                => {'one': '1', 'three': {'five': {}, 'four': []}, ...}
    '/one'             => '1'
    '../two'           => KeyError('..',)
    '/two/fake'        => KeyError('fake',)
    './three/four'     => []
    './fake'           => KeyError('fake',)
    'three/four/..'    => {'five': {}, 'four': []}
    'three/five/fake'  => KeyError('fake',)
    '/three/four/0'    => IndexError(0,)
    """).strip()
    #
    # NOTE all of the following behavior is courtesy of os.path.normpath; the
    # output is merely listed here for reference.
    from posixpath import normpath
    assert tuple(normpath(p) for p in selectors) == tuple(map(str, resolved))
    # 1. Leading slashes aren't added/removed, even for root
    # 2. Empty string "" becomes "."
    # 3. ../ is only resolved if it's a depth 1+ component
    # 4. Leading ./ is always stripped, as are intervening */./*
    # 5. Resolved path includes non-existing components
    #
    sel2sel = "\n".join("{!r:19} => {!r}".format(sel, str(res)) for
                        sel, res in zip(selectors, resolved))
    assert sel2sel == dedent("""\
    ''                  => '.'
    '/'                 => '/'
    '.'                 => '.'
    '/one'              => '/one'
    '../two'            => '../two'
    '/two/fake'         => '/two/fake'
    './three/four'      => 'three/four'
    './fake'            => 'fake'
    'three/four/..'     => 'three'
    'three/five/fake'   => 'three/five/fake'
    '/three/four/0'     => '/three/four/0'
    """).strip()
    #
    # Splitting dirname/basename (for assignment prep)
    from collections import MutableSequence, MutableMapping
    #
    # Bogus dirname component
    resolved, values, leaves = zip(*(access_by_pathname(sel, config, True) for
                                     sel in selectors))
    reprlib.aRepr.maxdict = 1
    sel2objkey = "\n".join("{!r:19}=> {:30}{}"
                           .format(sel, reprlib.repr(val), "[%r]" % leaf) for
                           sel, val, leaf in zip(selectors, values, leaves))
    assert sel2objkey == dedent("""
    ''                 => {'one': '1', ...}             ['']
    '/'                => {'one': '1', ...}             ['']
    '.'                => {'one': '1', ...}             ['']
    '/one'             => {'one': '1', ...}             ['one']
    '../two'           => KeyError('..',)               ['two']
    '/two/fake'        => TypeError("Li...; got 'int'",)['fake']
    './three/four'     => {'five': {}, ...}             ['four']
    './fake'           => {'one': '1', ...}             ['fake']
    'three/four/..'    => {'one': '1', ...}             ['three']
    'three/five/fake'  => {}                            ['fake']
    '/three/four/0'    => []                            ['0']
    """).strip()
    assert all(isinstance(o, (MutableMapping, MutableSequence, BaseException))
               for o in values)
    assert all(isinstance(s, str) for s in leaves)
    #
    # Leaves aren't checked for validity before they're returned.
    sel, obj, key = access_by_pathname("./fake", config, leafless=True)
    with pytest.raises(KeyError):
        config["fake"]
    #
    sel, obj, key = access_by_pathname("three/four", config, leafless=True)
    assert obj[key] == config["three"]["four"] == []
    #
    obj[key].append("someval")
    sel, obj, key = access_by_pathname("three/four/0", config, leafless=True)
    #
    assert key == "0" and obj == ["someval"]
    with pytest.raises(TypeError):
        obj[key]
    # However, we can still access/select "someval" when not stopping short
    sel, obj, key = access_by_pathname("three/four/0", config, leafless=False)
    assert str(sel) == "three/four/0" and obj == "someval" and key is None
    # Possible to access string members, here "someval"[0] -> "s"?
    arg = "three/four/0/0"
    sel, obj, key = access_by_pathname(arg, config, leafless=False)
    # Compare this to last param iteration of old doctest output above
    assert str(sel) == arg and repr(obj) == "KeyError('0',)"
    #
    # Encountering an ErsatzList (with intent to set list item)
    # Note: corresponds to relevant section in "configgers.reaccess()"
    from Signal.dictchainy import ErsatzList, SettingsDict
    from Signal.configgers import default_config, access_by_pathname
    import json
    D = default_config.settings
    U = SettingsDict(D, **json.loads(dummy.json_settings))
    selector, obj, key = access_by_pathname("/authorized/0", U, True)
    assert isinstance(obj, ErsatzList)
    assert str(selector) == "/authorized"  # PurePosixPath
    __, _obj, _key = access_by_pathname(selector, U, True)
    assert _key not in getattr(_obj, "maps", [{}])[0]
    assert _obj[_key] is obj


def test_reaccess():
    # The difference between this and ``access_by_pathname`` is that the prefix
    # becomes the new root (if walk exists).
    import reprlib
    from textwrap import dedent
    from Signal.configgers import reaccess
    from pathlib import PurePosixPath
    config = dict(one="1", two=2, three=dict(four=["someval"], five={}))
    sargs = (               # "curdir"
        "",
        "/",
        "..",                # already at root
        "/one",              # cd to /one
        "../two",            # back to root, cd to "/two"
        "/two/fake",         # error, so still at root
        "/three",            # at /two, cd to /three (abs path)
        "./four",            # cd to /three/four
        "..",                # cd to /three
        "four",              # cd to /three/four
        "/three/four/fake",  # error, so still at /three/four
        "./0"                # cd to /three/four/0
    )
    #
    last_path = None
    #
    def caller(path):  # noqa E306
        nonlocal last_path
        last_path, sel, obj, __ = reaccess(last_path, path, config, False)
        assert __ is None
        assert all(isinstance(s, PurePosixPath) for s in (last_path, sel))
        assert last_path == sel or isinstance(obj, BaseException)
        return last_path, sel, obj
    #
    reprlib.aRepr.maxdict = 1
    count4 = "\n".join("{!r:19} {!r:15} {!r:19} {}"
                       .format(a, str(p), str(s), reprlib.repr(o)) for
                       a, p, s, o in zip(sargs, *zip(*map(caller, sargs))))
    # orig arg          # new prefix   # new selector      # obj
    assert count4 == dedent("""
    ''                  '/'             '/'                 {'one': '1', ...}
    '/'                 '/'             '/'                 {'one': '1', ...}
    '..'                '/'             '/'                 {'one': '1', ...}
    '/one'              '/one'          '/one'              '1'
    '../two'            '/two'          '/two'              2
    '/two/fake'         '/two'          '/two/fake'         KeyError('fake',)
    '/three'            '/three'        '/three'            {'five': {}, ...}
    './four'            '/three/four'   '/three/four'       ['someval']
    '..'                '/three'        '/three'            {'five': {}, ...}
    'four'              '/three/four'   '/three/four'       ['someval']
    '/three/four/fake'  '/three/four'   '/three/four/fake'  KeyError('fake',)
    './0'               '/three/four/0' '/three/four/0'     'someval'
    """).strip()
    #
    import json
    from functools import partial
    reaccess = partial(reaccess, wants_strings=True)
    from Signal.dictchainy import ExpressionsDict
    from Signal.configgers import default_config
    D = default_config.expressions
    U = ExpressionsDict(D, **json.loads(dummy.json_expressions))
    #
    assert repr(reaccess("/dummy/all/-1", "fake", U, True)) == """
    ('/dummy/all/-1', '/dummy/all/-1/fake', {'! i has': 'bar'}, 'fake')
    """.strip()  # prefix, selector, object (in all[-1]), key
    #
    assert repr(reaccess("/dummy/all/-1", "fake", U, False)) == """
    ('/dummy/all/-1', '/dummy/all/-1/fake', KeyError('fake',), None)
    """.strip()  # reverted, tried, result
    #
    # Empty selector is replaced with prefix
    assert repr(reaccess("/dummy/all/-1", "", U, False)) == \
        repr(reaccess("/dummy/all/-1", None, U, False)) == """
    ('/dummy/all/-1', '/dummy/all/-1', {'! i has': 'bar'}, None)
    """.strip()
    assert repr(reaccess("/dummy/all/0/wild", "", U, True)) == \
        repr(reaccess("/dummy/all/0/wild", None, U, True)) == """
    ('/dummy/all/0', '/dummy/all/0/wild', {'wild': '#foo*'}, 'wild')
    """.strip()
    #
    # Encountering an ``ErsatzList`` (when wanting list/key to assign to)
    # Note: see corresponding section in ``test_access_by_pathname()``
    from Signal.dictchainy import (SettingsDict, ErsatzList,
                                   ProtectedItemError)
    D = default_config.settings
    U = SettingsDict(D, **json.loads(dummy.json_settings))
    assert isinstance(U["authorized"], ErsatzList)
    with pytest.raises(ProtectedItemError):
        U["authorized"].append("failure")
    prefix, selector, obj, key = reaccess("/authorized", "0",
                                          U, wants_key=True)
    assert obj is U["authorized"] and not isinstance(U["authorized"],
                                                     ErsatzList)
    obj.append("success")


def test_update_config_dict():
    # Can't really decouple this method from ConfigDict types because
    # it needs them to throw the appropriate errors
    #
    import json
    from Signal.dictchainy import SettingsDict, ExpressionsDict
    from Signal.configgers import default_config, reaccess, update_config_dict
    from functools import partial
    reaccess = partial(reaccess, wants_strings=True)
    # Leaf container based on SettingsDict (ChainoFixe)
    D = default_config.settings
    U = SettingsDict(D, **json.loads(dummy.json_settings))
    pre = ""
    # Note: this step is just for clarity but will be skipped from now on
    pre, __, obj, key = reaccess(pre, "/host", U, wants_key=True)
    assert pre == "/"  # <- new prefix leaf matches key
    assert obj == U
    assert key == "host"
    # no conv
    assert update_config_dict(obj, key, "fake", as_json=False) is True
    assert obj[key] == "fake"
    #
    # strtoi
    assert update_config_dict(U, "port", "123", as_json=False) is True
    assert U["port"] == 123
    #
    key = "obey"
    # Python bool
    assert update_config_dict(obj, key, "True", as_json=False) is True
    assert U[key] is True
    #
    # invalid Python bool
    with pytest.raises(ValueError) as exc_info:
        update_config_dict(obj, key, "no", as_json=False)
    assert "invalid Python" in "".join(exc_info.value.args)
    # invalid JSON bool
    with pytest.raises(ValueError) as exc_info:
        update_config_dict(obj, key, "yes", as_json=True)
    assert "invalid JSON" in "".join(exc_info.value.args)
    # good JSON bool
    assert update_config_dict(obj, key, "false", as_json=True) is True
    assert obj[key] is False
    # corrected Python bool
    assert update_config_dict(obj, key, "false", as_json=False) is True
    assert obj[key] is False
    # corrected JSON bool
    assert update_config_dict(obj, key, "False", as_json=True) is True
    assert obj[key] is False
    #
    # Bad call (3rd param not str). Unlikely, but possible from other funcs.
    with pytest.raises(TypeError) as exc_info:
        update_config_dict({}, "", 1, as_json=False)
    assert "update_config_dict" in exc_info.value.args[0]
    #
    # Nested container - ExpressionsDict (ChainoBase)
    # Values must be SerialSuspect instances
    from Signal.cmdopts import SerialSuspect as S
    D = default_config.expressions
    U = ExpressionsDict(D, **json.loads(dummy.json_expressions))
    obj = U
    # New key in root
    key = "another_exp"
    val = S('{"has": "foo"}')
    assert update_config_dict(U, key, val, as_json=False) is True
    #
    val = S("{'has': 'foo'}")  # swap quotes
    with pytest.raises(ValueError) as exc_info:
        update_config_dict(U, key, val, as_json=True)
    assert "invalid JSON" in exc_info.value.args[0]
    assert U[key] == {"has": "foo"}
    #
    pre, __, obj, key = reaccess("", "/dummy/all/1", U, wants_key=True)
    assert pre == "/dummy/all"
    from collections import MutableSequence
    assert isinstance(obj, MutableSequence)  # <- [{'wild': '#foo*'}, {...}]
    assert update_config_dict(obj, key, val, as_json=False) is True
    assert obj[int(key)] == {"has": "foo"}
    #
    # Append to list if key is out of range
    assert len(obj) == 2
    key = "2"  # <- out of range
    val = S('{"has": "bar"}')
    assert update_config_dict(obj, key, val, as_json=False) is True
    assert obj[-1] == {"has": "bar"} and len(obj) == 3
    #
    # Delete by index
    with pytest.raises(TypeError):
        update_config_dict(obj, 2, None, False)
    assert update_config_dict(obj, "2", None, False) is True
    assert obj[-1] != {"has": "bar"} and len(obj) == 2
    val = S('{"! has any": ["baz", "spam"]}')
    assert update_config_dict(obj, "2", val, as_json=False) is True
    assert len(obj) == 3
    #
    # Delete by value
    __, __, l_obj, __ = reaccess("", "/dummy/all/-1/! has any", U,
                                 wants_key=False)
    assert l_obj == ["baz", "spam"]
    with pytest.raises(ValueError):
        update_config_dict(l_obj, "fake", None, as_json=False)
    assert l_obj == ["baz", "spam"]
    assert update_config_dict(l_obj, "baz", None, as_json=False) is True
    assert l_obj == ["spam"]
    val = S('{"has": "bar"}')
    assert update_config_dict(obj, "2", val, as_json=False) is True
    assert obj[-1] == {"has": "bar"} and len(obj) == 3
    #
    key = "4294967295"  # <- out of range
    val = S('{"has": "baz"}')
    assert update_config_dict(obj, key, val, as_json=False) is True
    assert obj[-1] == {"has": "baz"}
    #
    key = "-1"
    val = S("None")
    assert update_config_dict(obj, key, val, as_json=False) is True
    assert obj[-1] == {"has": "bar"} and len(obj) == 3
    #
    pre, __, obj, key = reaccess("/dummy/all", "-1/has", U, wants_key=True)
    #
    assert key == "has"
    val = S("baz")  # <- invalid arg ~~> @@ baz
    with pytest.raises(ValueError) as exc_info:
        update_config_dict(obj, key, val, False)
    assert "invalid Python" in exc_info.value.args[0]
    #
    val = S("'baz'")
    assert update_config_dict(obj, key, val, False) is True
    assert obj == {"has": "baz"}
    #
    val = "baz"
    assert S("baz") == val
    assert update_config_dict(obj, key, val, False) is True
    assert obj == {"has": "baz"}


def test_load_config(tmpdir):
    import os
    import json
    from Signal.configgers import load_config
    #
    assert load_config(json.dumps(dummy.peeled)) == dummy.peeled
    assert load_config(dummy.ini) == dummy.peeled
    #
    path = os.path.join(tmpdir, "myconf.json")
    with open(path, "w") as flow:
        json.dump(dummy.peeled, flow)
    assert load_config(path) == dummy.peeled
    #
    path = os.path.join(tmpdir, "myconf.ini")
    with open(path, "w") as flow:
        flow.write(dummy.ini)
    assert load_config(path) == dummy.peeled


def test_subdivide_ini():
    from Signal.iniquitous import subdivide_ini
    sections = subdivide_ini(dummy.ini)
    assert list(sections) == ['settings', 'expressions',
                              'templates', 'conditions']
    assert {type(v).__name__ for v in sections.values()} == {'str'}
    assert "\n".join(sections.values()) == dummy.ini
    #
    replacement = dummy.ini_stub_expanded_expressions
    replaced = dummy.ini.replace(sections["expressions"], replacement)
    sections = subdivide_ini(replaced)
    assert sections["expressions"] == replacement
    assert "\n".join(sections.values()) == replaced


def test_get_subsections():
    from textwrap import dedent, indent
    from Signal.iniquitous import get_subsections
    # dict
    conf = dummy.ini_stub_custom_template
    section = get_subsections(conf, as_dict=True)
    assert list(section) == ["templates"]
    templates = section["templates"]
    assert list(templates) == ["custom", "default"]
    expected = dedent("""
        [custom]
            focus_char = \\u2713
        [default]
            recipients = +12127365000
            #format = {focus}{context}: [{nick}] {body}
            #focus_char = U+1F517
            length = 80
    """).strip()
    expected = f"{expected}\n"
    assert "".join(templates.values()) == expected
    # list
    raw_title, *subsections = get_subsections(conf)
    assert [indent(s, "    ") for s in templates.values()] == subsections
    assert dedent("".join(subsections)) == expected


def test_parse_ini():
    from Signal.iniquitous import parse_ini, subdivide_ini, get_subsections
    # Dummy conf matches
    sections = subdivide_ini(dummy.ini)
    assert parse_ini(sections) == dummy.peeled
    # Custom template before default
    temp = dummy.ini_stub_custom_template
    temped = dict(sections)
    temped.update(templates=temp)
    expected = {"custom": {"focus_char": "\\u2713"},
                "default": {"length": 80,
                            "recipients": ["+12127365000"]}}
    from collections import OrderedDict
    assert OrderedDict(parse_ini(temped)["templates"]) == OrderedDict(expected)
    # Custom template after default is not promoted
    raw_title, *subs = get_subsections(temp)
    temp = "".join((raw_title, *reversed(subs)))
    temped = dict(sections)
    temped.update(templates=temp)
    expected = {"default": {"length": 80,
                            "recipients": ["+12127365000"]},
                "custom": {"focus_char": "\\u2713"}}
    assert OrderedDict(parse_ini(temped)["templates"]) == OrderedDict(expected)
    #
    sections = subdivide_ini(
        dummy.ini.replace(sections["expressions"],
                          dummy.ini_stub_expanded_expressions)
    )
    assert parse_ini(sections) == dummy.peeled
    # Commented-out version present in settings section but peeled away from
    # parsed dict (because it matches latest version)
    assert "#config_version = 0.2" in sections["settings"]
    assert "config_version" not in dummy.peeled["settings"]
    #
    # An obsolete version number is retained even when commented out
    sections["settings"] = sections["settings"].replace(
        "#config_version = 0.2", "#config_version = 0.1"
    )
    parsed = parse_ini(sections)
    verdiff = parsed["settings"].pop("config_version")
    assert parsed == dummy.peeled
    assert verdiff == 0.1


def test_gen_ini():
    import json
    from Signal.configgers import construct_config, load_config
    from Signal.iniquitous import gen_ini, subdivide_ini
    #
    loaded = load_config(json.dumps(dummy.peeled))
    with pytest.raises(TypeError):
        gen_ini(loaded)
    converted = construct_config(loaded)
    generated = gen_ini(converted)
    assert generated == dummy.ini
    #
    # Modified defaults appear after custom items
    from copy import deepcopy
    from textwrap import dedent
    modded = deepcopy(loaded)
    modded["expressions"].update({"default": {"! has": ""}})
    converted = construct_config(modded)
    generated = gen_ini(converted)
    assert subdivide_ini(generated)["expressions"].rstrip() == dedent("""
    [expressions]
        custom = {"has": "fixed string"}
        dummy = {"all": [{"wild": "#foo*"}, {"! i has": "bar"}]}
        default = {"! has": ""}
    """).strip()
    #
    modded = deepcopy(loaded)
    modded["templates"].update({"custom": {"focus_char": "\\u2713"}})
    assert list(modded["templates"]) == ["default", "custom"]  # inserted last
    converted = construct_config(modded)
    assert list(converted.templates) == ["custom", "default"]
    #
    # Assume input config objects exhibit correct ordering
    del converted.templates["custom"]
    converted.templates["custom"] = modded["templates"]["custom"]
    assert list(converted.templates.maps[0]) == ["custom", "default"]
    assert list(converted.templates) == ["custom", "default"]
    generated = gen_ini(converted)
    #
    assert subdivide_ini(generated)["templates"] == \
        dummy.ini_stub_custom_template


def test_construct_config():
    from Signal.configgers import construct_config, default_config
    null_cats = {}
    real_cats = {"settings": {}, "expressions": {},
                 "templates": {}, "conditions": {}}
    some_cats = {"settings": {}, "conditions": {}}
    fake_cats = {"fake1": {}, "fake2": {}, "fake3": {}}
    #
    structed = tuple(construct_config(s) for s in
                     (null_cats, real_cats, some_cats, fake_cats))
    #
    from conftest import all_eq, map_eq
    assert all_eq(*structed)
    assert map_eq(repr, *structed)
    #
    from collections import OrderedDict as OD
    cats = structed[0]  # all same
    #
    assert [len(d) for d in cats] == [6, 1, 1, 1]
    #
    assert OD({k: OD(v.bake()) for k, v in cats._asdict().items()}) == \
        OD({c: OD(d) for c, d in default_config._asdict().items()})
    #
    assert OD({k: OD(v.peel()) for
               k, v in cats._asdict().items()}) == \
        OD({"settings": {}, "expressions": {},
            "templates": {}, "conditions": {}})
    #
    # Invalid keys for children of SettingsDict raise exception
    loaded = {"settings": {"fake": None}}  # unknown key
    with pytest.raises(KeyError) as exc_info:
        construct_config(loaded)
    assert "Unrecognized settings" in repr(exc_info.value)
    loaded = {"settings": {"port": "some string"}}  # wrong value type
    with pytest.raises(TypeError) as exc_info:
        construct_config(loaded)
    assert "Settings/port must be of type 'int'" in repr(exc_info.value)
    #
    # Expressions values must be dicts
    loaded = {"expressions": {"fake": None}}
    with pytest.raises(TypeError) as exc_info:
        construct_config(loaded)
    assert "Expressions must be" in repr(exc_info.value)
    # Default caught earlier, but same exception type thrown
    loaded = {"expressions": {"default": None}}
    with pytest.raises(TypeError) as def_exc_info:
        construct_config(loaded)
    assert "Expressions/default must be" in repr(def_exc_info.value)
    assert def_exc_info.traceback[-1].name == exc_info.traceback[-1].name
    assert def_exc_info.traceback[-1].lineno != exc_info.traceback[-1].lineno
    #
    # Templates/Conditions
    #
    # The point of this is to emphasize that construct_config passes category
    # values as the user_map arg to all ConfigDicts
    for cat in ("conditions", "templates"):
        singular = cat[:-1]
        # Any <arg> for which ``dict(UserDict(<arg>)) == {}`` is ignored
        construct_config({cat: {"default": None}})
        construct_config({cat: {"default": []}})
        #
        # Non(empty)-iterables won't quack, but msg is not super helpful
        with pytest.raises(TypeError) as exc_info:
            construct_config({cat: {"default": ...}})
        assert "'ellipsis' object is not iterable" == exc_info.value.args[0]
        assert exc_info.traceback[-1].name == "_init_user_map"
        #
        with pytest.raises(KeyError) as exc_info:
            construct_config({cat: {"default": ["a1"]}})  # Bad key
        assert f"Unrecognized {singular}: 'a'" in exc_info.value.args[0]
        assert exc_info.traceback[-1].name == "validate_prospect"
        #
        with pytest.raises(KeyError) as exc_info:
            construct_config({cat: {"custom": {"fake": None}}})
        assert f"Unrecognized {singular}: 'fake'" in exc_info.value.args[0]
        assert exc_info.traceback[-1].name == "validate_prospect"
    # Wrong type
    loaded = {"conditions": {"custom": {"replied_only": 1}}}
    with pytest.raises(TypeError) as exc_info:
        construct_config(loaded)
    assert ("Condition/replied_only must be of type 'bool'" in
            repr(exc_info.value))
    loaded = {"templates": {"custom": {"format": 1}}}
    with pytest.raises(TypeError) as exc_info:
        construct_config(loaded)
    assert "Template/format must be of type 'str'" in repr(exc_info.value)
    #
    # Redundant items (matching backing dict) aren't rejected; must call
    # bake/peel for that. See also: individual BaseConfigDict tests
    loaded = {"settings": {"config_version":
                           default_config.settings["config_version"]}}
    assert construct_config(loaded).settings.maps[0]["config_version"] == \
        default_config.settings["config_version"]


def test_validate_config():
    from Signal.configgers import validate_config, default_config
    from textwrap import dedent
    #
    # Empty input
    warn, info = validate_config({})
    assert not info
    assert "\n".join(warn) == dedent("""
        /settings/host is required but missing
        /templates/*/recipients is required for ZNC -> Signal forwarding
    """).strip()
    #
    loaded = {"settings": {"host": "fake",
                           "authorized": ["one", "two"]},
              "conditions": {"default": {"x_source": "foo"},
                             "custom": {"scope": ["foo", "bar"],
                                        "x_source": "bar"}}}
    warn, info = validate_config(loaded)
    assert not info
    assert "\n".join(warn) == dedent("""
        /templates/*/recipients is required for ZNC -> Signal forwarding
        /conditions/custom/scope can only contain:
          ('attached', 'detached', 'query'); not 'bar' or 'foo'
        /conditions/custom/x_source 'bar' not in ('hostmask', 'nick')
        /conditions/default/x_source 'foo' not in ('hostmask', 'nick')
        /settings/authorized changed while attempting to load config:
          ['one', 'two'] -> [ValueError('one',), ValueError('two',)]
    """).strip()
    #
    loaded = dummy.peeled
    assert validate_config(loaded) == ([], [])
    # Ensure values in custom entry that happens to match ones in
    # outermost protected mapping are retained when (inner) default
    # entry shadows outer (confuso)
    assert default_config.conditions["default"]["source"] == "default"
    assert loaded["conditions"]["default"]["source"] == "dummy"
    assert loaded["conditions"]["custom"]["source"] == "custom"
    loaded["conditions"]["custom"]["source"] = "default"  # ↓
    assert loaded["conditions"]["custom"]["source"] == "default"
    assert validate_config(loaded) == ([], [])
    #
    # Skip /settings/host and /templates/*/recipients warnings:
    stem = {"settings": {"host": "fake"},
            "templates": {"default": {"recipients": ["+122233344445555"]}}}
    from copy import deepcopy
    loaded = deepcopy(stem)
    loaded["settings"].update({"port": 47000})
    warn, info = validate_config(loaded)
    assert "\n".join(info) == dedent("""
        /settings/port: 47000 was dropped; reason: default
    """).strip()
    assert not warn
    # Wrong type for config_version
    loaded = deepcopy(stem)
    loaded["settings"].update({"config_version": None})
    warn, info = validate_config(loaded)
    assert not info
    assert "\n".join(warn) == dedent("""
        Error converting user config to internal data
        Settings/config_version must be of type 'float', not 'NoneType'
        Unable to continue; please fix existing errors
    """).strip()
    # Config version tag is NOT exempt from "dropped" warning
    loaded = deepcopy(stem)
    curver = default_config.settings["config_version"]
    loaded["settings"].update({"config_version": curver})
    warn, info = validate_config(loaded)
    assert not warn
    assert info == [
        "/settings/config_version: 0.2 was dropped; reason: default"
    ]
    # Template format
    loaded = deepcopy(stem)
    loaded["templates"]["default"].setdefault("format", "{nick}: {body}")
    loaded["templates"]["custom"] = {"format": "{nick}: {fake}"}
    warn, info = validate_config(loaded)
    assert not info
    assert "\n".join(warn) == dedent("""
        /templates/custom/format changed while attempting to load config:
          '{nick}: {fake}' -> KeyError('fake',)
    """).strip()
    # Expression expansion
    loaded = deepcopy(stem)
    loaded.update({"expressions": {"custom": {"not": "fake"},
                                   "foo": {"not": "bar"},
                                   "bar": {"has": "some needle"}}})
    warn, info = validate_config(loaded)
    assert not info
    assert "\n".join(warn) == dedent("""
        /expressions/custom changed while attempting to load config:
          {'not': 'fake'} -> ValueError("Unknown reference: 'fake'",)
    """).strip()
    # Expression eval
    loaded = deepcopy(stem)
    loaded.update({"expressions": {"foo": {"all": ""}}})
    warn, info = validate_config(loaded)
    assert not info
    assert "\n".join(warn) == dedent("""
        /expressions/foo changed while attempting to load config:
          {'all': ''} -> TypeError("'all' needs a list",)
    """).strip()
    # Superfluous items
    loaded = deepcopy(stem)
    loaded.update({"conditions": {"default": {"x_source": "hostmask"},
                                  "custom": {"x_source": "hostmask"}}})
    warn, info = validate_config(loaded)
    assert not warn
    assert info == [
        "/conditions/default/x_source: 'hostmask' was dropped; "
        "reason: redundant",
        "/conditions/custom/x_source: 'hostmask' was dropped; "
        "reason: default"
    ]
    # Options/flags
    loaded = deepcopy(stem)
    loaded.update({"conditions": {"custom": {"x_policy": "both",
                                             "x_source": "ident"}}})
    warn, info = validate_config(loaded)
    assert not info
    assert warn == [
        "/conditions/custom/x_policy 'both' not in ('filter', 'first')",
        "/conditions/custom/x_source 'ident' not in ('hostmask', 'nick')"
    ]
    # Template reference
    loaded = deepcopy(stem)
    loaded.update({"conditions": {"custom": {"template": "default"},
                                  "default": {"template": "dummy"}}})
    warn, info = validate_config(loaded)
    assert not info
    assert warn == [
        "/conditions/default/template 'dummy' not found in /templates"
    ]
    # Named expressions
    loaded = deepcopy(stem)
    loaded.update({"expressions": {"dummy": {"has": "foo"}},
                   "conditions": {"custom": {"source": "default",
                                             "channel": "dummy",
                                             "body": "fake"}}})
    warn, info = validate_config(loaded)
    assert warn == [
        "/conditions/custom/body 'fake' not found in /expressions"
    ]
    assert info == [
        "/conditions/custom/source: 'default' was dropped; reason: default"
    ]
    # Scope members out-of-order
    loaded = deepcopy(stem)
    loaded.update({"conditions": {"custom": {"scope": ["detached",
                                                       "attached",
                                                       "query"]}}})
    warn, info = validate_config(loaded)
    assert warn == []
    assert info == [
        "/conditions/custom/scope: ['detached', 'attached', 'query']"
        " was dropped; reason: default"
    ]
    # Focus char
    loaded = deepcopy(stem)
    loaded.update({"templates": {"custom": {"recipients": ["+11111111111"],
                                            "focus_char": "ab"}}})
    warn, info = validate_config(loaded)
    assert info == []
    assert "\n".join(warn) == dedent("""
        /templates/custom/focus_char changed while attempting to load config:
          'ab' -> ValueError('Arg <raw> must be a single character',)
    """).strip()
    loaded["templates"]["custom"]["focus_char"] = "U+"
    warn, info = validate_config(loaded)
    assert "\n".join(warn) == dedent("""
        /templates/custom/focus_char changed while attempting to load config:
          'U+' -> ValueError("invalid literal for int() with base 16: ''",)
    """).strip()


def test_manage_config(signal_stub_debug):
    from Signal.configgers import default_config as D
    sig = signal_stub_debug
    assert sig.config is None
    sig.manage_config("load")
    assert isinstance(sig.config, D.__class__)
    for cat in D.__class__._fields:
        assert getattr(sig.config, cat) == getattr(D, cat)
    snapshot = repr(sig.config)
    # Refuses to save when /settings/host is unset
    with pytest.raises(UserWarning) as exc_info:
        sig.manage_config("save")
    assert "'/settings/host' is empty" in repr(exc_info.value.args)
    assert len(sig.nv) == 0
    # Adding --force (via cmd_update) grants save request
    sig.manage_config("save", force=True)
    assert len(sig.nv) == 1
    sig.nv.clear()
    assert repr(sig.config) == snapshot
    sig.manage_config("load")
    assert repr(sig.config) == snapshot
    #
    from Signal.ootil import restring
    from copy import deepcopy
    mydummy = deepcopy(dummy.peeled)  # graft custom template on dummy
    mydummy["templates"]["custom"] = {"focus_char": "\\u2713"}
    some_backup = restring(mydummy)
    UN = sig.expand_string("%user%")  # <- "testdummy"
    #
    # Required item missing: /settings/config_version
    sig.nv[UN] = some_backup
    assert "config_version" not in sig.nv[UN]  # rhs is a string
    with pytest.raises(KeyError) as exc_info:
        sig.manage_config("load")
    assert ("Required item /settings/config_version missing" in
            exc_info.value.args[0])
    latest = D.settings["config_version"]
    assert sig.config.settings["config_version"] == latest
    assert "config_version" not in sig.config.settings.maps[0]
    assert "config_version" in sig.config.settings
    sig.nv[UN] = some_backup = inject_config_version(some_backup)
    # Cached version is reordered to match default (see test_conditions_dict >
    # ordering above). Basically, dummy.json_full is out of order.
    sig.manage_config("load")
    sig.manage_config("save")
    assert sig.nv[UN] != some_backup
    some_backup = sig.nv[UN]
    sig.manage_config("load")
    sig.manage_config("save")
    assert sig.nv[UN] == some_backup
    snapshot = repr(sig.config)
    #
    # Otherwise, only peeled objects (diffed maps) are saved
    assert sig.config.settings["port"] != D.settings["port"]
    user_port = sig.config.settings.pop("port")  # 1024
    assert sig.config.settings["port"] == D.settings["port"]  # 47000
    sig.manage_config("save")
    assert sig.nv[UN] == some_backup.replace(f'"port":{user_port},', "")
    # Restore
    sig.config.settings["port"] = user_port
    assert repr(sig.config) != snapshot  # insertion order changed
    sig.manage_config("save")
    assert sig.nv[UN] == some_backup
    sig.manage_config("load")
    assert repr(sig.config) == snapshot
    #
    # Check path twiddling
    import os
    # Try reloading nonexistent config
    with pytest.raises(FileNotFoundError) as exc_info:
        sig.manage_config("reload")
    assert exc_info.value.args[0] == \
        f"No config found at {sig.datadir}/config.ini"
    # Looks for .json if requested
    with pytest.raises(FileNotFoundError) as exc_info:
        sig.manage_config("reload", as_json=True)
    assert exc_info.value.args[0] == \
        f"No config found at {sig.datadir}/config.json"
    # Note: for simplicty, "reload" is used instead of "export"; exceptions are
    # always raised because files don't actually exist
    foo_path = os.path.join(sig.datadir, "foo")
    # Dir passed as path
    os.makedirs(foo_path)
    with pytest.raises(FileNotFoundError) as exc_info:
        sig.manage_config("reload", path=foo_path)
    assert exc_info.value.args[0] == \
        f"No config found at {foo_path}/config.ini"
    # Nonexistent, explicitly named leaf.ini/.json is ok if dirname exists
    with pytest.raises(FileNotFoundError) as exc_info:
        sig.manage_config("reload", path=f"{foo_path}/my_config.ini")
    assert exc_info.value.args[0] == \
        f"No config found at {foo_path}/my_config.ini"
    # Otherwise, reset to default
    with pytest.raises(FileNotFoundError) as exc_info:
        sig.manage_config("reload", path=f"{foo_path}/fake.txt")
    assert exc_info.value.args[0] == \
        f"No config found at {foo_path}/config.ini"
    #
    # Export non-empty config
    assert sig.config is not None
    assert sig.nv[UN] == some_backup
    assert not os.path.exists(os.path.join(sig.datadir, "config.ini"))
    sig.manage_config("export")
    assert not sig._read()  # no errors
    assert os.path.exists(os.path.join(sig.datadir, "config.ini"))
    sig.config = None
    del sig.nv[UN]
    sig.manage_config("reload")
    assert sig.config is not None
    assert sig.nv[UN] == some_backup
    #
    # Attempt to export empty config
    sig.config = None
    del sig.nv[UN]
    with pytest.raises(ValueError):
        sig.manage_config("export")
    #
    # Reload previously exported file from explicit, non-default path
    os.rename(os.path.join(sig.datadir, "config.ini"),
              os.path.join(foo_path, "config.ini"))
    sig.manage_config("reload", path=os.path.join(foo_path, "config.ini"))
    assert sig.nv[UN] == some_backup
    #
    # Export json version to default path
    assert "config_version" not in sig.config.settings.maps[0]
    sig.manage_config("export", as_json=True)
    assert os.path.exists(os.path.join(sig.datadir, "config.json"))
    import json
    # Version always saved, even though absent from user config
    with open(os.path.join(sig.datadir, "config.json")) as flo:
        json_exported = json.load(flo)
    assert "config_version" in json_exported["settings"]
    sig.config = None
    del sig.nv[UN]
    sig.manage_config("reload", as_json=True)
    assert not sig._read()  # no errors
    assert sig.nv[UN] == some_backup
    assert "config_version" not in sig.config.settings.maps[0]
    #
    # Defaults present, but no redundant items in conditions/templates
    # Also note that "dropped" errors were omitted during reload validation
    dkds = [n for n, d in sig.config._asdict().items() if hasattr(d, "defkey")]
    assert ["conditions", "expressions", "templates"] == sorted(dkds)
    # Although /expressions has "defkey", its items are single-item dicts, so
    # spread-peeling is the same as bake(). Hence, no "spread" attr.
    assert json_exported["expressions"]["default"] == \
        sig.config.expressions.peel(False)["default"]
    dkds.remove("expressions")
    assert not hasattr(sig.config.expressions, "spread")
    for cat in dkds:
        assert "default" in json_exported[cat]
        cat_dict = getattr(sig.config, cat)
        assert cat_dict.peel()["default"]  # mutated, not empty
        assert json_exported[cat]["default"] == cat_dict.peel(False)["default"]
        assert list(json_exported[cat]) == list(cat_dict.peel(False))
        assert list(json_exported[cat]["default"]) == \
            list(cat_dict.peel(False)["default"])
    # /settings is exported in full
    assert list(json_exported["settings"]) != list(sig.config.settings.peel())
    assert list(json_exported["settings"]) == list(sig.config.settings)
    #
    # Reload outdated config version
    with open(os.path.join(foo_path, "config.ini"), "r") as flor:
        old = flor.read()
    curver = sig.config.settings['config_version']
    new = old.replace(f"config_version = {curver}",
                      "config_version = 0.1")
    with open(os.path.join(foo_path, "config.ini"), "w") as flow:
        flow.write(new)
    with pytest.raises(UserWarning) as exc_info:
        sig.manage_config("reload", path=os.path.join(foo_path, "config.ini"))
    assert ("Your config appears to be outdated. Please update it" in
            exc_info.value.args[0])
    assert not sig._read()  # no other errors
    with open(os.path.join(foo_path, "config.ini.new")) as flo:
        assert f"config_version = {curver}" in flo.read()
    #
    # Reload outdated config version as json
    with open(os.path.join(sig.datadir, "config.json")) as flor:
        old = flor.read()
    new = old.replace(f'"config_version": {curver}',
                      '"config_version": 0.1')
    assert new != old
    with open(os.path.join(sig.datadir, "config.json"), "w") as flow:
        flow.write(new)
    with pytest.raises(UserWarning) as exc_info:
        sig.manage_config("reload", as_json=True,
                          path=os.path.join(sig.datadir, "config.json"))
    assert ("Your config appears to be outdated. Please update it" in
            exc_info.value.args[0])
    assert not sig._read()  # no other errors
    with open(os.path.join(sig.datadir, "config.json.new")) as flo:
        assert f'"config_version": {curver}' in flo.read()
