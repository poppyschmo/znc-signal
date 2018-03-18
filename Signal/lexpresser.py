# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

from types import MappingProxyType
from collections.abc import MutableMapping, MutableSequence


def eval_boolish_json(expression, message):
    """
    Compare strings by evaluating boolean expressions shoehorned into
    JSON containers.

    TODO: use testing framework combo tools to generate more variants

    { Key (string)       : Value (below) }  <==>  Expression
    --------------------   ---------------
    NOT                  : exp
         I               : exp              // ignore case
    (!) (i)      ANY     : list of exps     // "or"
    (!) (i)          ALL : list of exps     // "and"

    (!) (i) has          : str              // "contains"
    (!) (i) has  any|all : list of strs
    (!) (i) wild         : str              // wildcards
    (!) (i) wild any|all : list of strs
    (!) (i) re           : str              // regex
    (!)     eq           : str              // verbatim match

    Notes on keys:
    1. letter case doesn't matter
    2. whitespace and underscores are ignored
    3. () modifiers should not include parentheses
    4. NOT doesn't undo I (you need separate branches)

    Notes on values:
    1. WILD uses Unix shell-style filename matching, see:
       <https://docs.python.org/3.6/library/fnmatch.html>
       Gnu-extension features likely don't work; see fnmatch(3)
    2. Regex matching uses Python's re.search, which resembles
       PCRE. Clients may handle "\t\b", etc., differently. The
       debug_exp command may reveal this: e.g., "\b" -> "\x08".
    """

    def do_feed(expression, icase=False):
        # Massage and validate ------------------------------------------------
        if len(expression) != 1 or not isinstance(expression, MutableMapping):
            raise ValueError("Expected single-item JSON object "
                             'of the form {"name": <exp>}')
        _op, value = next(iter(expression.items()))  # <- dict(exp).popitem()
        op = _op.lower().replace(" ", "").replace("_", "")
        if "all" in op or "any" in op:
            if not isinstance(value, MutableSequence):
                raise TypeError(f"{_op!r} needs a list")
        elif op in ("not", "!", "i", "!i"):
            if not isinstance(value, MutableMapping):
                raise TypeError("'not' only negates other expressions")
        elif op.lstrip("!i") in ("has", "re", "wild", "eq"):
            if not isinstance(value, str):
                raise TypeError(f"{_op!r} only takes a single string")
        else:
            raise ValueError(f"Unrecognized key: {_op!r}")
        #
        if len(op) > 1:
            if op.startswith("!"):
                value = {op[1:]: value}
                op = "not"
            elif op.startswith("i"):
                op = op[1:]
                icase = True
        msg = message.lower() if icase else message
        # Eval ----------------------------------------------------------------
        def ic(s):  # noqa E306
            return s.lower() if icase else s
        #
        if op == "i":
            return do_feed(value, True)
        if op in ("not", "!"):
            return not do_feed(value, icase)
        elif op == "all":
            return all(do_feed(c, icase) for c in value)
        elif op == "any":
            return any(do_feed(c, icase) for c in value)
        elif op.startswith("has"):
            if op.endswith("all"):
                return all(ic(s) in msg for s in value)
            elif op.endswith("any"):
                return any(ic(s) in msg for s in value)
            else:
                return ic(value) in msg
        elif op.startswith("wild"):
            from fnmatch import fnmatch
            if op.endswith("all"):
                return all(fnmatch(msg, ic(s)) for s in value)
            elif op.endswith("any"):
                return any(fnmatch(msg, ic(s)) for s in value)
            else:
                return fnmatch(msg, ic(value))
        elif op == "re":
            from re import search
            return search(ic(value), msg) is not None
        elif op == "eq":
            return value == message  # disallow (i)
        else:
            raise ValueError(f"Unrecognized operation: {op}")

    return do_feed(expression)


def expand_subs(node, table, _count=None):
    """Preprocess an expression, expanding references to others

    Note: this thing is entirely dependent on ``eval_boolish_json()``;
    any changes will have to be rippled.
    """
    if _count is None:
        _count = ([], 0)
    seen, level = _count  # level only used in debug mode, but meh
    if getattr(expand_subs, "debug", False):
        from pprint import pformat
        nstr = pformat(node, depth=1)
        colw = getattr(expand_subs, "colw", 40)
        print("{}{lseen:<4}{nstr}{:{w}}{seen}"
              .format(".   " * level, "", lseen=level, nstr=nstr,
                      w=colw - len(nstr) - level * 4, seen=seen))
    if isinstance(node, str) and node in table:
        if node in seen:
            raise RecursionError("An expression can't contain itself")
        seen.append(node)
        return expand_subs(table[node], table, (seen, level))
    elif (isinstance(node, (MutableMapping, MappingProxyType)) and
          len(node) == 1):
        level += 1
        key, value = dict(node).popitem()
        if (isinstance(value, MutableSequence) and
                not any(s in key.lower() for s in ("has", "wild"))):
            value = [expand_subs(v, table, (seen, level)) for v in value]
        elif (isinstance(value, str) and
              key.lower() in ("not", "i") or
              isinstance(value, MutableMapping)):
            value = expand_subs(value, table, (seen, level))
        if len(seen):
            seen.pop()
        return {key: value}
    raise ValueError(f"Unknown reference: {node!r}")


def ppexp(exp, mes, file=None, indent=0):
    """Eval JSON-like expression, printing results along the way

    ``file`` is passed to ``print``
    ``indent`` is for internal state msg passing
    ``pformat``'s width is hard-wired to 50
    """
    from pprint import pformat
    if isinstance(exp, MutableMapping):
        result = eval_boolish_json(exp, mes)
        space = ".   " * indent
        r = f"{space}{str(result)[:1]}   "
        __, e = dict(exp).popitem()
        depth = 2 if not any(isinstance(i, MutableMapping) for i in e) else 1
        out = space.join(pformat(exp, depth=depth, width=50).splitlines(True))
        print(f"{r}{out}", file=file)
        return ppexp(e, mes, file, indent+1)
    elif isinstance(exp, MutableSequence):
        for e in exp:
            ppexp(e, mes, file, indent)
