# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import configparser
from collections import OrderedDict
from .configgers import default_config


class expression_(dict): pass  # noqa E701


class IniParser(configparser.ConfigParser):
    """ConfigParser for SettingsDict and subclasses

    Cannot handle nested BaseConfigDict objects like ConditionsDict and
    TemplatesDict. Incapable of round-trips; needs massaging from
    helpers below.
    """
    from enum import Enum
    nested = None
    category = None
    write_items = Enum("WriteItems", "defaults section both")

    def _read_types(self, value):
        if isinstance(value, str):
            return value
        conv = getattr(self, f"set{type(value).__name__}", None)
        if conv:
            return conv(value)
        else:
            return str(value)

    def read_dict(self, dictionary, source='<dict>'):
        """See orig in standard library."""
        elements_added = set()
        for section, keys in dictionary.items():
            section = str(section)
            try:
                self.add_section(section)
            except (configparser.DuplicateSectionError, ValueError):
                if self._strict and section in elements_added:
                    raise
            elements_added.add(section)
            for key, value in keys.items():
                key = self.optionxform(str(key))
                if value is not None:
                    # MOD begin
                    value = self._read_types(value)
                    # MOD end
                if self._strict and (section, key) in elements_added:
                    raise configparser.DuplicateOptionError(section, key,
                                                            source)
                elements_added.add((section, key))
                self.set(section, key, value)

    def setlist(self, value):
        import shlex
        if not value:
            return "[]"
        return " ".join(shlex.quote(s) for s in value)

    setErsatzList = setlist

    def setexpression_(self, value):
        import json
        return json.dumps(value)

    def getlist(self, section, option, *, raw=False, vars=None,
                fallback=configparser._UNSET, **kwargs):
        #
        def _conv(value):
            r"""
            >>> def tc(s):
            ...     return tuple(_conv(s))
            >>> {tc("+18885551212, +12127365000"),
            ...  tc("+18885551212 +12127365000"),
            ...  tc("+18885551212,+12127365000"),
            ...  tc('["+18885551212","+12127365000"]'),
            ...  tc('[+18885551212, +12127365000]'),
            ...  tc('[+18885551212,+12127365000]'),
            ...  tc('[+18885551212 +12127365000]')} == \
            ...     {('+18885551212', '+12127365000')}
            True
            >>> _conv("'+1 888 555 1212', +1-212-736-5000")
            ['+1 888 555 1212', '+1-212-736-5000']
            >>> _conv("[]")
            []
            """
            if value.startswith("[") and value.endswith("]"):
                if value == "[]":
                    return []
                if '"' in value:
                    import json
                    try:
                        return json.loads(value)
                    except Exception:
                        pass
                value = value.strip("[]")
            if " " not in value and "," in value.strip(","):
                return value.strip(",").split(",")
            import shlex
            return [s.rstrip(",") for s in shlex.split(value)]
        #
        return self._get_conv(section, option, _conv, raw=raw,
                              vars=vars, fallback=fallback, **kwargs)

    def getexpression_(self, section, option, *, raw=False, vars=None,
                       fallback=configparser._UNSET, **kwargs):
        def _conv(value):
            from .configgers import eval_string
            try:
                return eval_string(value, as_json=True)
            # XXX probably shouldn't catch this because it violates round-trip
            # representation principle; or just clobber/replace user ini
            except ValueError as exc:
                rv = eval_string(value, as_json=False)
                from warnings import warn
                warn(" ".join(str(a) for a in exc.args))
                return rv
        #
        return self._get_conv(section, option, _conv, raw=raw,
                              vars=vars, fallback=fallback, **kwargs)

    def _iter_both(self, section_items):
        """Return dict with keys 'commented out' for identical items

        Notes
        ~~~~~
        1. This is basically the body of some overridden
           ``ChainMap.__iter__()`` (with values)
        2. Can't just yield from originating BaseConfigDict instance
           (values have changed)
        3. Like ``BaseConfigDict.bake``, place user items before defaults,
           defying the precedence prescribed by ``configparser``
        """
        #
        # Can't use a set union because ordering is lost
        items = OrderedDict((k, v) for k, v in section_items.items() if
                            k not in self._defaults)
        for key, value in self._defaults.items():
            if key in items:
                continue
            if key in section_items and value != section_items[key]:
                items[key] = section_items[key]
            else:
                items[f"#{key}"] = self._defaults[key]
        return items

    def write(self, fp, **kw):
        """See configparser.ConfigParser.write.__doc__"""
        if self._sections and not self._defaults:
            raise ValueError("Must have defaults")
        #
        iter_items = kw.get("iter_items", self.write_items["section"])
        delimiter = " {} ".format(self._delimiters[0])
        #
        for section in self._sections:
            section_items = self._sections[section]
            indent = kw.get("indent", 0) * " "
            fp.write("{}[{}]\n".format(indent, section))
            indent += "    "
            if iter_items is self.write_items.defaults:
                items = self._defaults
            elif iter_items is self.write_items.section:
                items = self[section]
            else:
                items = self._iter_both(section_items)
            for key, value in items.items():
                if iter_items is self.write_items.both:
                    pass
                elif key in section_items:
                    value = section_items[key]
                else:
                    if iter_items is not self.write_items.defaults:
                        continue
                    key = f"#{key}"
                key = f"{indent}{key}"
                if value is not None or not self._allow_no_value:
                    value = delimiter + str(value).replace('\n', f"\n{indent}")
                else:
                    value = ""
                fp.write("{}{}\n".format(key, value.rstrip()))
            if self.category is not None:
                fp.write("\n")

    def _write_section(self, *args, **kwargs):
        raise RuntimeError("Unused in this implementation")


def gen_ini(config=None) -> str:
    """Generate an ini-formatted string from a config_NT instance
    """
    if config is None:
        from .configgers import construct_config
        config = construct_config({})
    else:
        if not isinstance(config, default_config.__class__):
            raise TypeError("gen_ini only accepts {}, not plain 'peeled' dicts"
                            .format(default_config.__class__.__name__))
    from io import StringIO
    # NOTE the __init__ keyword arg ``defaults`` expects a dict with values
    # that have already been converted to strings. So, must manually set
    # default after contruction/init to ensure ``.read_dict()`` is called.
    #
    def especialize(d):  # noqa: E306
        return {k: expression_(v) for k, v in d.items()}
    #
    DS = configparser.DEFAULTSECT
    settings = IniParser()
    settings[DS] = config.settings.backing
    settings["settings"] = config.settings.bake(peel=True)
    settings.category = "settings"
    #
    expressions = IniParser()
    expressions[DS] = especialize(config.expressions.backing)
    expressions["expressions"] = especialize(config.expressions
                                             .bake(peel=True))
    expressions.category = "expressions"
    #
    nesters = []
    for cat_name in ("templates", "conditions"):
        config_obj = getattr(config, cat_name)
        parser = IniParser()
        parser.category = cat_name
        parser[DS] = config_obj.backing["default"]
        #
        parser.nested = IniParser()
        parser.nested[DS] = config_obj.bake(peel=True).get("default", {})
        for name, data in config_obj.items():
            if name == "default":
                continue
            parser.nested[name] = config_obj.bake(peel=True).get(name, {})
        parser["default"] = config_obj.bake(peel=True).get("default", {})
        nesters.append(parser)
    #
    deefs, sect, both = IniParser.write_items
    with StringIO() as flo:
        settings.write(flo, indent=0, iter_items=deefs)
        expressions.write(flo, indent=0, iter_items=both)
        for parser in nesters:
            print("[{}]".format(parser.category), file=flo)
            if parser.nested:
                parser.nested.write(flo, indent=4)
            parser.write(flo, indent=4, iter_items=deefs)
        out_raw = flo.getvalue()
    return "{}\n".format(out_raw.strip())


def get_subsections(raw_section, as_dict=False):
    """Return nested sections as a processed dict or raw list

    Currenly only used for testing and verification

    list
        elements are strings with all subsection headings and
        indentation left intact; the main section heading is prepended
        if present

    dict
        output mimics that of ``subdivide_ini()``; if a main section
        heading is present, output is nested a level; all common
        indentation is stripped
    """
    from textwrap import dedent, indent
    title = None
    if dedent(raw_section) == raw_section:
        title, raw_section = raw_section.split("\n", 1)
        title = title.strip().strip("[]")
    # Probably an error if prefix is a null string
    prefix = raw_section.split("[", 1)[0].split("\n")[-1]
    raw_section = dedent(raw_section)
    subsections = subdivide_ini(raw_section, True)
    out = {} if as_dict else []
    for name, body in subsections.items():
        if as_dict:
            out[name] = body
            continue
        out.append(indent(body, prefix))
    if title:
        return {title: out} if as_dict else [f"[{title}]\n"] + out
    return out


def subdivide_ini(raw_conf, allow_unknown=False):
    """Segement raw string into config sections

    This crudely emulates the initial section-parsing behavior of
    ``ConfigParser._read``, except it allows for nested sections and
    optional validation checks.
    """
    import re
    from itertools import chain, islice, tee
    # Get the stuff between all [section] markers
    section_pat_RE = re.compile(r'(?P<indent>\s*)(\[(?P<name>\w+)\])\n',
                                re.MULTILINE)
    em1, em2 = tee(section_pat_RE.finditer(raw_conf))
    sec_info = (m.groupdict() for m in em1)
    dexes = chain.from_iterable((*(m.span() for m in em2), (len(raw_conf),)))
    next(dexes)  # advance to end of 1st section header; add end pos ^^^^^^
    even, odd = tee(dexes)
    regrouped = zip(islice(even, 0, None, 2), islice(odd, 1, None, 2))
    sliced = (slice(*span) for span in regrouped)
    # NOTE any errors thus far likely won't throw till this loop runs. If too
    # common and/or debugging gets impractical, save unrolled iterators
    seen = OrderedDict()
    sections = OrderedDict()
    tabsize = None
    for info, bounds in zip(sec_info, sliced):
        # For non-headings, this would be inadequate (expands all tabs)
        indent = info["indent"].expandtabs(4).split("\n")[-1]
        level = len(indent)
        if not tabsize:
            tabsize = level
        if tabsize:
            level, bad = divmod(level, tabsize)
            if bad:
                raise IndentationError("Section headers improperly indented")
            if level > 1:
                from warnings import warn
                warn("Inconsistent indentation: "
                     f"expected {tabsize}, got {level * tabsize}")
        name = info["name"]
        if not level:
            if name in seen:
                raise configparser.DuplicateSectionError(section=name)
            elif not allow_unknown and name not in default_config._fields:
                raise KeyError("Unrecognized Section: %r" % name)
            seen[name] = set()
            section = name
        else:
            section, current = next(reversed(seen.items()))
            if name in current:
                raise configparser.DuplicateSectionError(section=name)
            current.add(name)
        lines = [l.replace(max((level - 1) * 4, 0) * " ", "", 1) for
                 l in raw_conf[bounds].splitlines() if l.strip()]
        lines.append("")
        if section in sections:
            joined = "\n".join([f"{indent}[{name}]"] + lines)
            sections[section] += joined
        else:
            joined = "\n".join([f"[{section}]"] + lines)
            sections[section] = joined
    return sections


def parse_ini(sections):
    """Convert preprocessed hunks into peeled sections
    """
    def conv(parser, category, section=None):
        """Convert strings to default types

        categroy: settings/expressions/conditions/templates
        section:  only used for nested dicts, e.g.
                  IniParser["templates"]["custom"]

        Note on "default" expressions
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        Its ``default_config`` category (table) is mocked below because
        the real thing, "/expressions", doesn't contain any standard
        (required) items other than an expression named "default", so
        all other lookups would fail.

        Compare this to (the only other actual) category structure,
        ``SettingsDict``, whose members are all required.
        """
        p = parser
        s = section or category
        d = dict(p[s])  # "nested" or top-level dict; children are ini options
        #
        if category == "expressions":
            proto_d = {k: expression_() for k in d}
        else:
            proto_d = getattr(default_config, category)
            if category in ("conditions", "templates"):
                proto_d = proto_d["default"]
        #
        for k, v in dict(d).items():
            canon_t = type(proto_d[k])
            if type(v) is not canon_t:
                if canon_t is bool:
                    d[k] = p.getboolean(s, k)
                else:
                    d[k] = getattr(p, f"get{canon_t.__name__}")(s, k)
        return d

    # Retain config_version if outdated and commented out
    setts = sections["settings"]
    vbeg = setts.find("#config_version")
    if (vbeg != -1 and "config_version" not in
            setts.replace("#config_version", "")):
        vend = setts.find("\n", vbeg)
        if vend == -1 or "=" not in setts[vbeg:vend]:
            raise ValueError("Malformed ini section: 'settings'")
        existing_ver = float(setts[vbeg:vend].split()[-1])
        if existing_ver < default_config.settings["config_version"]:
            sections["settings"] = setts.replace("#config_version",
                                                 "config_version", 1)
    #
    out_dict = {}
    for cat, hunk in sections.items():
        parser = IniParser()
        if cat in ("conditions", "templates"):
            heading, hunk = hunk.strip().split("\n", 1)
            assert cat == heading[1:-1]
            parser.read_string(hunk)
            value = {s: conv(parser, cat, s) for
                     s in parser.sections() if dict(parser[s])}
        else:
            parser.read_string(hunk.strip())
            value = conv(parser, cat)
        if value:
            out_dict[cat] = value
    return out_dict
