# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import configparser
from pathlib import PurePosixPath
from collections.abc import MutableMapping, MutableSequence
from collections import namedtuple

config_NT = namedtuple("Config", "settings expressions templates conditions")

# TODO store all config comments as Python strings in a separate file, so they
# can be sprinkled in "programmatically" via the ini generator. OR just dump
# them in a readme/wiki
#
# In ini files, list-style options look like this when left as default:
#
#     #recipients = []
#
# These can be specified in a manner resembling shell-command arguments:
#
#     recipients = +18885551212 "1 (212) 736-5000"
#
# Values expressed as JSON that span multiple lines of an ini file must be
# properly indented. See the tail end of tests/dummy_conf.py for an example.
#
# The focus indicator can be:
#   1. a literal character
#   2. a code-point string, like "U+1F517"
#   3. a "string representation" of a valid Unicode escape, like "\\U0001F517"
#      for JSON or \U0001F517 in .ini files
#
# Of these, the first form is preferred for ascii chars and second for unicode
# glyphs (it's less distracting when converting to/from JSON because it won't
# get double-backslash-surrogate-paired on the way out and rendered into some
# full-color icon on the way in; also less prone to backslash hell and
# letter-case-related errors).
#
# TODO add aliases for incoming commands; this should be based on SettingsDict;
# perhaps also allow arbitrary raw IRC commands and module commands like
# 'select' and 'update'
#
#     "aliases": {
#         "prefix": "/",   # must be [^[:alnum:][:space:]_"'`]
#         "help": "h",     # respond with summary of available commands
#         "msg": "m",      # same as typical client
#         "net": "n",      # choose network
#         "focus": "f",    # '/f [<ctx>]' route subsequent non-prefixed msgs
#                          # to <ctx>, or show current (default)
#         "tail": "t",     # '/t <ctx> [n]' last msg (or n msgs) from <ctx>
#         "snooze", "z",   # '/z [n]' do not disturb for n mins (w/o n, reset)
#     }
#
default_config = config_NT(**{
    "settings": {
        "host": "",                 # often hostname of Signal docker container
        "port": 47000,
        "obey": True,               # listen for and run incoming instructions
        "authorized": [],           # numbers authorized to issue instructions
        "auto_connect": False,
        "config_version": 0.3
    },
    "expressions": {
        "pass": {"has": ""},      # i.e., always True, use !has "" for False
        "drop": {"! has": ""}
    },
    # NOTE until upstream adds reverse lookup for contacts and groups, it makes
    # little sense to include these as options for /templates/*/recipients.
    # TODO add mod-type User option to only show {network} if not currently
    # selected
    # TODO consider a substitution table, through which some nick "foo" always
    # gets swapped out for "bar" when {nick} is resolved/expanded; values
    # could allow variables, and keys wildcards, e.g., "nick": {"*":
    # "|{nick}|"}, etc.
    "templates": {
        "default": {
            "recipients": [],         # at least 1 required for pushing
            # Also honored: 'hostmask', 'network'; 'context' is a proper name,
            # like '#foo', not a scope type (like 'query'); focus indicator
            # only appears when applicable, otherwise collapses to ""
            "format": "{focus}{context}: [{nick}] {body}",
            "focus_char": "U+1F517",  # symbolizes locked Sig → ZNC context
            "length": 0               # max length of push msg body
        }
    },
    # Conditions are OR'd together, order is preserved, default runs last
    # TODO if replied_only or a timeout_* constraint is triggered (and the
    # condition otherwise would have rendered a SEND verdict), the message body
    # and metadata are pushed back to a context buffer, which can be viewed
    # remotely with the /tail command
    "conditions": {
        "default": {
            "enabled": True,
            "away_only": False,      # disable this condition while away
            "scope": ["query",       # applicable contexts
                      "detached",
                      "attached"],
            "replied_only": False,   # require past engagement (during session)
            "max_clients": 0,        # disable condition if value met/exceeded
            # must exceed secs elapsed since...
            "timeout_post": 180,     # last client → ZNC → IRC message
            "timeout_push": 300,     # last Sig ← ZNC notification
            "timeout_idle": 0,       # last client → ZNC activity
            # named templates
            "template": "default",   # "default" -> /templates/default
            # expressions options
            "x_policy": "filter",    # filter|first (i.e., and|or, all|any)
            "x_source": "hostmask",  # nick|hostmask (nick!ident@host)
            # named expressions
            "network": "pass",       # "pass" -> /expressions/pass
            "channel": "pass",       # skipped if context is N/A
            "source": "pass",        # see x_source, above
            "body": "drop"
        }
    },
})


def access_by_pathname(selector, tree, leafless=False):
    """Retrieve an item (or its parent) from a nested container.

    Takes a "selector" resembling a directory path instead of the usual
    chain of member-access operators like ``[]`` or ``.``. For simple
    stuff, avoids the complexity of proxy objects or libraries like
    jmespath. ``leafless`` means selector's dirname is processed in its
    stead, and basename is also returned.
    """
    from posixpath import normpath

    def pluck(level, keys):
        key = ""
        try:
            while key in ("", ".", "/"):
                key = next(keys)
        except StopIteration:
            return level
        if not isinstance(level, MutableMapping):
            if (isinstance(level, MutableSequence) and
                    key.lstrip("-").isdecimal()):
                key = int(key)
            else:
                return KeyError(key)
        try:
            level = level[key]
        except KeyError:
            return KeyError(key)
        except IndexError:
            return IndexError(key)
        return pluck(level, keys)

    selector = PurePosixPath(normpath(selector))  # logically resolve ../
    leaf = None
    if leafless:
        selector, leaf = selector.parent, selector.name  # (.name -> str)
    obj = pluck(tree, iter(selector.parts))
    # The whole point of ``leafless`` is to provide a mutable container
    # accessible by the a key (here, leaf).
    if leafless and not isinstance(obj, (MutableMapping, MutableSequence,
                                         BaseException)):
        obj = TypeError("List or dict expected; got %r" % type(obj).__name__)
    return selector, obj, leaf


def reaccess(prefix, new_path, config, wants_key=False, wants_strings=False):
    """Prepends prefix to selector before calling ``access_by_pathname``
    but doesn't keep state. Returns "resolved/canonicalized" selector as
    new prefix upon success (along with everything else).
    """
    PPath = PurePosixPath
    prefix = PPath(prefix or "/")
    selector = PPath(prefix, new_path or "")
    #
    selector, obj, key = access_by_pathname(selector, config, wants_key)
    from .dictchainy import ErsatzList
    if wants_key and isinstance(obj, ErsatzList):
        __, _obj, _key = access_by_pathname(selector, config, wants_key)
        obj = _obj[_key] = list(obj)
    if not isinstance(obj, BaseException):
        prefix /= selector
    if wants_key:
        selector /= PPath(key)
    if wants_strings:
        return str(prefix), str(selector), obj, key
    return prefix, selector, obj, key


def eval_string(value, as_json):
    try:
        if as_json:
            import json
            value = json.loads(value)
        else:
            from ast import literal_eval
            value = literal_eval(value)
    except Exception as exc:
        msg = ()
        if as_json:
            if isinstance(exc, json.JSONDecodeError):
                msg = exc.args
        else:
            if isinstance(exc, ValueError) and "malformed" in repr(exc):
                msg = ("Try adding/removing quotes.",)
        raise ValueError("Couldn't evaluate input; invalid %s." %
                         ("JSON" if as_json else "Python"), *msg)
    return value


def update_config_dict(obj, key, value, as_json):
    from .cmdopts import SerialSuspect
    if not isinstance(key, str):
        raise TypeError("update_config_dict: keys must be strings")
    if value is not None and not isinstance(value, str):  # incl. SerialSuspect
        raise TypeError("update_config_dict: values must be string-like")
    #
    generic = "Problem setting %r to %r" % (key, value)
    msg = caste = None
    if isinstance(obj, MutableSequence):
        try:
            key = int(key)
        except ValueError:
            # Only supported type is list of strings, but same error regardless
            key = obj.index(key)
    if isinstance(value, SerialSuspect):
        value = value(as_json)
    if value is None:
        del obj[key]
        return True
    try:
        obj[key] = value
    except TypeError as exc:
        try:
            *msg, caste = exc.args
        except ValueError:  # Not enough values to unpack
            raise exc if exc.args else ValueError(generic)
        # Continues below...
    except IndexError as exc:
        # For now, this can only mean object is some list in an
        # ``ExpressionsDict`` instance, and value should thus be appended.
        # XXX is this still true after adding lists to SettingsDict and
        # ConditionsDict? If not, fix comment.
        if "out of range" in repr(exc):
            obj.append(value)
            return True
        else:
            raise
    else:
        return True
    #
    if caste:
        from .dictchainy import BaseConfigDict
        if BaseConfigDict.debug:
            assert isinstance(obj, (BaseConfigDict, BaseException))
            assert caste is not type(value)
            assert caste not in (type(None), str)
        if caste is bool:
            if not as_json and value in ("false", "true"):
                value = value.capitalize()
            if as_json and value in ("False", "True"):
                value = value.lower()
        # Expressions|SomeDict must be of type...
        if caste.__class__ is not type:
            msg = msg + (caste,)
            caste = None
    if not caste or "must be" not in str(msg):
        raise ValueError(generic)
    try:
        value = eval_string(value, as_json)
    except ValueError as exc:
        if msg is not None:
            raise ValueError(*exc.args, *msg)
        else:
            raise
    if msg is not None and not isinstance(value, caste):
        raise ValueError(*msg)
    obj[key] = value
    return True


def load_config(raw):
    """Read in string data; return a "peeled" config

    A peeled config structure contains only JSON-like objects (dicts) or
    primitives, as shown in ``default_config``. Objects returned are
    "assumed peeled" but may be far from it.

    raw
        data in string form or path to a file

    JSON dedupes automatically by updating existing items. The IniParser
    should buck with some native exception.
    """
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        import json
        return json.loads(stripped)
    elif "\n" in stripped:
        from .iniquitous import subdivide_ini, parse_ini
        sections = subdivide_ini(raw)
        return parse_ini(sections)
    else:
        path = PurePosixPath(raw)
        # Raises FileNotFoundError if missing
        with open(path) as flo:
            if path.suffix == ".json":
                import json
                return json.load(flo)
            else:
                raw = flo.read()
                if "\n" not in raw.strip():
                    raise configparser.Error("Unrecognized config format")
                return load_config(raw)


def construct_config(loaded):
    """Convert a peeled config into a full, multi-dict object

    "Peeled" means a correctly structured config containing only items
    that differ from those in ``default_config``. "Multi-dict object"
    means a ``config_NT`` instance containing a ``BaseConfigDict``-based
    object for each category. Except for "/expressions", the latter
    contain items "backed" by (chained to) some corresponding default.
    """
    from .dictchainy import (SettingsDict, ExpressionsDict,
                             TemplatesDict, ConditionsDict)
    config = config_NT(
        SettingsDict(
            default_config.settings,
            user_map=loaded.get("settings", {})
        ),
        ExpressionsDict(
            default_config.expressions,
            user_map=loaded.get("expressions", {})
        ),
        TemplatesDict(
            default_config.templates,
            user_map=loaded.get("templates", {})
        ),
        ConditionsDict(
            default_config.conditions,
            user_map=loaded.get("conditions", {})
        )
    )
    return config


def validate_config(loaded):
    """Perform crude heuristic checks on a prospective config

    loaded
        user-provided config, assumed peeled but may contain unmodified
        defaults

    Returns ([<warning msg>, ...], [<info msg>, ...])

    This should probably only run between ``load_config`` and
    ``construct_config``, which it actually calls, but only to report
    errors
    """
    #
    # Solely to catch typos so desired items don't get dropped
    for k in loaded:
        if k not in config_NT._fields:
            raise ValueError("Unknown top-level config category: %r" % k)
    #
    # Handled by constructors of ``BaseConfigDict`` types above:
    # 1. Unrecognized keys
    # 2. Invalid types
    warn = []
    info = []
    try:
        structed = construct_config(loaded)
    except Exception as exc:
        structed = None
        warn.append("Error converting user config to internal data")
        warn.extend(a for a in exc.args if isinstance(a, str))
    try:
        peeled = {k: v.bake(peel=True) for k, v in structed._asdict().items()}
    except Exception as exc:
        if not isinstance(exc, AttributeError):
            warn.append("Error turning ingested data back into usable config")
            warn.extend(a for a in exc.args if isinstance(a, str))
    if warn:
        warn.append("Unable to continue; please fix existing errors")
        return warn, info
    #
    # Ensure phone numbers adhere to +international format:
    def itutplusize(*nums):  # noqa: E306
        out = []
        for num in nums:
            _num = "".join(d for d in num if d.isdecimal())
            # XXX lower bound arbitrarily chosen; likely erroneous
            if not 7 <= len(_num) <= 15:
                _num = ValueError(f"{num}")
            else:
                _num = f"+{_num}"
            out.append(_num)
        return out
    #
    if "settings" in peeled:
        ps = peeled["settings"]
        if "host" not in ps or not ps["host"]:
            warn.append("/settings/host is required but missing")
        if "authorized" in ps:
            ps["authorized"] = itutplusize(*ps["authorized"])
    else:  # not in loaded
        warn.append("/settings is required but missing")
    #
    if "expressions" in peeled:
        etable = dict(peeled["expressions"])
        etable.setdefault("pass", default_config.expressions["pass"])
        etable.setdefault("drop", default_config.expressions["drop"])
        from .lexpresser import expand_subs, eval_boolish_json
        for name, expr in peeled["expressions"].items():
            try:
                _expr = expand_subs(expr, etable)
                _expr = eval_boolish_json(_expr, "")
            except Exception as exc:
                peeled["expressions"][name] = exc
    #
    has_recipients = False
    if "templates" in peeled:
        for name, template in peeled["templates"].items():
            if "format" in template and template["format"]:
                fkeys = "context|body|channel|nick|hostmask|network"
                fkeys = fkeys.split("|")
                fdict = dict(zip(fkeys, range(len(fkeys))))
                try:
                    template["format"].format(**fdict)
                except Exception as exc:
                    template["format"] = exc
            if "focus_char" in template:
                from .ootil import unescape_unicode_char
                try:
                    unescape_unicode_char(template["focus_char"])
                except ValueError as exc:
                    template["focus_char"] = exc
            if "length" in template and template["length"] < 0:
                warn.append(f"/templates/{name}/length must be non-negative")
            if "recipients" not in template:
                continue
            template["recipients"] = itutplusize(*template["recipients"])
            if template["recipients"]:
                has_recipients = True
    if not has_recipients:
        warn.append("/templates/*/recipients is required for "
                    "ZNC -> Signal forwarding")
    if "conditions" in peeled:
        for name, cond in peeled["conditions"].items():
            pfx = f"/conditions/{name}"
            # Check number semantics, .e.g. 0 rather than -1 to mean +infinity
            for numitem in ("max_clients",
                            "timeout_post", "timeout_push", "timeout_idle"):
                if numitem in cond and cond[numitem] < 0:
                    warn.append(f"{pfx}/{numitem} must be non-negative")
            if "scope" in cond:
                def_ttypes = {"query", "attached", "detached"}
                cur_ttypes = set(cond["scope"])
                if cur_ttypes - def_ttypes:
                    offending = " or ".join(repr(s) for s in
                                            sorted(cur_ttypes - def_ttypes))
                    def_ttypes = tuple(sorted(def_ttypes))
                    warn.append(f"{pfx}/scope can only contain:"
                                f"\n  {def_ttypes}; not {offending}")
            # Check option/flag-style items
            if "x_policy" in cond:
                emodes = ("filter", "first", "all", "any", "and", "or")
                if cond["x_policy"] not in emodes:
                    warn.append(f"{pfx}/x_policy {cond['x_policy']!r} not in "
                                f"{emodes[:2]}")
            if ("x_source" in cond and
                    cond["x_source"] not in ("hostmask", "nick")):
                warn.append(f"{pfx}/x_source {cond['x_source']!r} not in "
                            "('hostmask', 'nick')")
            # Ensure references to other sections resolve (interpolation)
            if ("template" in cond and cond["template"] not in
                    peeled.get("templates", {}).keys() | {"default"}):
                warn.append(f"{pfx}/template {cond['template']!r} not found "
                            "in /templates")
            for eref in ("channel", "network", "source", "body"):
                if (eref in cond and cond[eref] not in
                        peeled.get("expressions", {}).keys() | {"pass", "drop"}):
                    warn.append(f"{pfx}/{eref} {cond[eref]!r} not found in "
                                "/expressions")
    #
    # Superfluous items (uncommented or misplaced defaults) are dropped by the
    # ``structed`` to ``peeled`` conversion above
    def cmp(cat, items, pre):  # noqa: E306
        for key, value in items:
            if cat in ("conditions", "templates"):
                cmp(key, value.items(), cat)
                continue
            path = f"{pre}/{cat}" if pre else cat
            try:
                new = peeled[pre][cat][key] if pre else peeled[cat][key]
                if value != new:
                    warn.append(mdiff.format(path, key, value, new))
            except KeyError:
                reason = "redundant" if cat == "default" else "default"
                info.append(mdrop.format(path, key, value, reason))
    #
    if peeled and loaded != peeled:
        mdiff = ("/{}/{} changed while attempting to load config:\n"
                 "  {!r} -> {!r}")
        mdrop = "/{}/{}: {!r} was dropped; reason: {}"
        for cat_k, cat_v in loaded.items():
            if cat_v != peeled[cat_k]:
                cmp(cat_k, cat_v.items(), pre="")
    #
    return warn, info
