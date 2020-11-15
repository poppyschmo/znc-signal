``Signal.lexpresser.eval_boolish_json``

Setup
    >>> mes = (
    ...     "There should be one-- and preferably only one "
    ...     "--obvious way to do it. Although that way may "
    ...     "not be obvious at first unless you're Dutch."
    ... )
    >>> def feed(expression):
    ...     cksum = hash(repr(expression))
    ...     result = eval_boolish_json(expression, mes)
    ...     assert cksum == hash(repr(expression))
    ...     return result

HAS_ALL
    >>> has_all_true = {"has_all": mes.split()}
    >>> feed(has_all_true)
    True
    >>> has_all_false = {"has_all": mes.split() + ["fake"]}
    >>> feed(has_all_false)
    False
    >>> feed({"has_all": "fake"})
    Traceback (most recent call last):
    TypeError: 'has_all' needs a list

HAS_ANY
    >>> has_any_true = {"has_any": ["unless"]}
    >>> feed(has_any_true)
    True
    >>> has_any_false = {"has_any": ["fake"]}
    >>> feed(has_any_false)
    False
    >>> feed({"has_any": "fake"})
    Traceback (most recent call last):
    TypeError: 'has_any' needs a list

HAS
    >>> has_true = {"has": "Dutch."}
    >>> feed(has_true)
    True
    >>> has_false = {"has": "dutch"}
    >>> feed(has_false)
    False
    >>> feed({"has": []})
    Traceback (most recent call last):
    TypeError: 'has' only takes a single string

EQ
    >>> eq_true = {"eq": mes}
    >>> feed(eq_true)
    True
    >>> eq_false = {"eq": mes[1:]}
    >>> feed(eq_false)
    False
    >>> feed({"eq": []})
    Traceback (most recent call last):
    TypeError: 'eq' only takes a single string

WILD_ANY
    >>> wild_any_true = {"wild_any": ["* ?ay*", "*fake*"]}
    >>> feed(wild_any_true)
    True
    >>> wild_any_false = {"wild_any": ["* ?ay", "*fake*"]}
    >>> feed(wild_any_false)
    False
    >>> feed({"wild_any": "string"})
    Traceback (most recent call last):
    TypeError: 'wild_any' needs a list

WILD_ALL
    >>> wild_all_true = {"wild_all": ["* ?ay*", "*[wm]ay*"]}
    >>> feed(wild_all_true)
    True
    >>> wild_all_false = {"wild_all": ["* ?ay", "*[wm]ay*"]}
    >>> feed(wild_all_false)
    False

WILD
    >>> wild_true = {"wild": "*should be one*preferably only one*"}
    >>> feed(wild_true)
    True
    >>> wild_false = {"wild": "*should be one*preferably one*"}
    >>> feed(wild_false)
    False
    >>> feed({"wild": []})
    Traceback (most recent call last):
    TypeError: 'wild' only takes a single string

RE
    >>> re_part_true = {"re": "\\s-{,2}obvious\\b"}
    >>> feed(re_part_true)
    True
    >>> re_part_false = {"re": "\\n"}
    >>> feed(re_part_false)
    False
    >>> re_full_true = {"re": "^There\\s.*Dutch\\.$"}
    >>> feed(re_full_true)
    True
    >>> re_full_true = {"re": "^There\\s.*fake.*Dutch\\.$"}
    >>> feed(re_full_true)
    False

ALL
    >>> all_true = {"all": [has_all_true, has_any_true]}     # T && T
    >>> feed(all_true)
    True
    >>> all_false = {"all": [has_all_true, has_all_false]}   # T && F
    >>> feed(all_false)
    False
    >>> feed({"all": []})                                    # T
    True

ANY
    >>> any_true = {"any": [has_all_true, has_all_false]}    # T || F
    >>> feed(any_true)
    True
    >>> any_false = {"any": [has_all_false, has_any_false]}  # F || F
    >>> feed(any_false)
    False
    >>> feed({"any": []})                                    # F
    False

I, (i)
    >>> # All three words are capitalized in sample text above
    >>> i_true = {"i": {"has_all": ["dutch", "DUTCH", "Dutch"]}}
    >>> feed(i_true)
    True
    >>> feed({"!i": {"has": "dutch"}})  # persistent
    False
    >>> feed({"i": {"ihas": "dutch"}})  # idempotent
    True
    >>> feed({"!": {"ihas": "dutch"}})  # irreversible
    False
    >>> feed({"all": [{"i": {"has": "dutch"}},
    ...               {"!has": "dutch"}]})
    True

NOT
    >>> feed({"not": has_all_true})
    False
    >>> feed({"not": has_all_false})
    True
    >>> feed({"!": has_all_true})
    False
    >>> feed({"!": has_all_false})
    True

(!)
    >>> true_exps = [all_true, has_all_true, any_true, has_any_true,
    ...              has_true, eq_true, wild_all_true, wild_any_true,
    ...              wild_true, re_part_true, i_true]
    >>> false_exps = [all_false, has_all_false, any_false, has_any_false,
    ...               has_false, eq_false, wild_all_false, wild_any_false,
    ...               wild_false, re_part_false]
    >>> for exp in true_exps:
    ...     op, value = list(exp.items()).pop()
    ...     assert feed({"!" + op: value}) is False
    >>> for exp in false_exps:
    ...     op, value = list(exp.items()).pop()
    ...     assert feed({"!" + op: value}) is True


``.expand_subs``

>>> table = {"spam": {"!has": "Green"},
...          "foo": {"has": "red"},
...          "bar": {"any": ["$foo", "$spam",
...                          {"has any": ["blue", "bar"]}]},
...          "baz": {"not": {"all": ["$bar", "$spam"]}}
...         }

>>> test = {"any": ["$baz", "$foo"]}
>>> expect = {
...     'any': [
...         {'not': {'all': [{'any': [{'has': 'red'},
...                                   {'!has': 'Green'},
...                                   {'has any': ['blue', 'bar']}]},
...                          {'!has': 'Green'}]}},
...         {'has': 'red'}]
... }

>>> expand_subs({"any": [{"has": "fake"}]}, table) == expect
False

>>> expand_subs.debug = True
>>> expand_subs(test, table) == expect
0   {'any': [...]}                          []
.   1   '$baz'                              []
.   1   {'not': {...}}                      ['baz']
.   .   2   {'all': [...]}                  ['baz']
.   .   .   3   '$bar'                      ['baz']
.   .   .   3   {'any': [...]}              ['baz', 'bar']
.   .   .   .   4   '$foo'                  ['baz', 'bar']
.   .   .   .   4   {'has': 'red'}          ['baz', 'bar', 'foo']
.   .   .   .   4   '$spam'                 ['baz', 'bar']
.   .   .   .   4   {'!has': 'Green'}       ['baz', 'bar', 'spam']
.   .   .   .   4   {'has any': [...]}      ['baz', 'bar']
.   .   .   3   '$spam'                     []
.   .   .   3   {'!has': 'Green'}           ['spam']
.   1   '$foo'                              []
.   1   {'has': 'red'}                      ['foo']
True

>>> table["bar"]["any"][-1] = "$baz"
>>> expand_subs(test, table)
Traceback (most recent call last):
RecursionError: An expression can't contain itself

>>> del table["bar"]["any"][-1]
>>> table["foo"] = {"not": "$bar"}
>>> expand_subs(test, table)
Traceback (most recent call last):
RecursionError: An expression can't contain itself

>>> del expand_subs.debug

>>> expand_subs({"any": ["$fake"]}, table)
Traceback (most recent call last):
ValueError: Unknown reference: '$fake'

>>> expand_subs({"any": ["fake"]}, table)
Traceback (most recent call last):
ValueError: Invalid reference: 'fake'

``.ppexp``

>>> myexp =  {"any": [{"has": "ok"},
...                   {"not": {"has": "no"}},
...                   {"has all": ["y", "a", "n"]}]}
>>> notherexp = {"all": [myexp, {"! has": "fake"}]}
>>> ppexp(notherexp, "nokay")
T   {'all': [...]}
.   T   {'any': [...]}
.   .   T   {'has': 'ok'}
.   .   F   {'not': {'has': 'no'}}
.   .   .   T   {'has': 'no'}
.   .   T   {'has all': ['y', 'a', 'n']}
.   T   {'! has': 'fake'}
