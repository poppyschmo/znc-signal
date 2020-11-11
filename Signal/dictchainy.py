# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

"""
Simplified diagram of expected behavior for templates and conditions dicts.
(The settings and expressions variants are simpler.)::

    D  default config
    U  user config
    *  special dict
    ⁿ  same object
    →  resolves to if missing

    U                      D
    └── category*      →   └── category
        ├── default*   →       └── default
        │   └── item¹  →           └── item
        └── custom*
            └── item   →   item¹
"""
from types import MappingProxyType
from collections.abc import MutableMapping, MutableSequence
from collections import ChainMap, OrderedDict, UserDict
from enum import IntEnum

PRO = -1  # default (bottommost/read-only ChainMap item)
MOD = 0   # user    (topmost/editable)

# TODO extend this to other variants and use them. Current approach (checking
# for phrases in exc instance arg messages) is inconvenient/high maintenance
class ConfigError(RuntimeError): pass  # noqa E701


class ProtectedItemError(ConfigError):
    """Marker raised when an attempt is made to mutate an ErsatzList

    Should trigger special handling, like copying the list to a user-
    map node at the same path, and then retrying the original operation.
    """


class ErsatzList(list):
    """Effectively a tuple masquerading as a list

    Its purpose is to impersonate a list in instance tests but otherwise
    raise ``ProtectedItemError`` on ``MutableSequence`` methods.
    """
    __quashed = ("append", "insert", "extend", "pop",
                 "remove", "clear", "sort", "reverse")

    def __getattribute__(self, name):
        if name in super().__getattribute__("_ErsatzList__quashed"):
            return self._balk(name=name)
        else:
            return super().__getattribute__(name)

    def _balk(self, *args, name=None):
        if name:
            msg = f"Cannot call {name}{args} on protected item"
        else:
            msg = "Cannot modify protected item"
        raise ProtectedItemError(msg)

    def __setitem__(self, *args):
        return self._balk(*args, name="__setitem__")

    def __delitem__(self, *args):
        return self._balk(*args, name="__delitem__")

    def __iadd__(self, *args):
        return self._balk(*args, name="__iadd__")

    def __imul__(self, *args):
        return self._balk(*args, name="__imul__")


class ChainoBase(ChainMap):
    """A ChainMap with an ordered modifiable dict

    This is the inner 'data' dict for all ``BaseConfigDict``-derived
    classes. The maps list is limited to two members, modifiable and
    protected, and the modifiable map may include keys not present in
    the backing map.

    The backing map is not ordered, but it may be converted to a
    ``MappingProxyType`` with ``proxify_last``
    """
    bias = MOD

    def __init__(self, *args, bias=None, proxify_last=True):
        if len(args) > 2:
            raise ValueError("Only one modifiable map is allowed")
        self.bias = bias if bias is not None else self.bias
        *args, last = args  # lhs get assigned right-to-left
        if not isinstance(last, (MutableMapping, MappingProxyType)):
            # ChainMap does not type-check args
            raise TypeError("Last arg must be a dict")
        if proxify_last:
            last = self.proxify(last)
        super().__init__(*args, last)  # <- superclass wants *vargs
        self.maps = [OrderedDict(m) for m in self.maps[:PRO]] + [last]

    def __delitem__(self, key):
        if self.bias == PRO:
            if key not in self.maps[PRO]:
                try:
                    del self.maps[MOD][key]
                except KeyError:
                    pass
                else:
                    return
        else:
            try:
                del self.maps[MOD][key]
            except KeyError:
                pass
            else:
                return
        if key in self.maps[PRO]:
            # XXX MappingProxyType raises TypeError for a similar case; should
            # probably do so also but would need tests to support
            msg = "Cannot delete default item"
        else:
            msg = "Key not found: %r" % key
        raise KeyError(msg)

    def proxify(self, d):
        for k, v in d.items():
            if isinstance(v, MutableSequence):
                d[k] = ErsatzList(v)
            if isinstance(v, MutableMapping):
                d[k] = MappingProxyType(self.proxify(v))
        return MappingProxyType(d)


class ChainoFixe(ChainoBase):
    """An ordered ChainMap supporting only known modifiable keys

    In other words, this assumes unknown keys won't be added to the
    modifiable map. Enforcement is left to the "host" ``BaseConfigDict``
    to handle.
    """
    def __init__(self, *args, skip_last=True, **kwargs):
        """
        ``skip_last`` defaults to True because it's assumed protected
        maps should normally be left alone (i.e., they're passed in
        ready to go). The other option would be to pass all vkwargs to
        super init (instead of using an explicit keyword-only arg), but
        that's arguably more confusing.
        """
        super().__init__(*args, proxify_last=not skip_last, **kwargs)
        if skip_last is False:
            self.maps[PRO] = self.proxify(OrderedDict(self.maps[PRO]))

    def __iter__(self):
        return iter(self.maps[PRO])


class BaseConfigDict(UserDict):
    """A ``UserDict`` supporting a ``ChainMap``-like data attribute
    """
    debug = False
    init_user_visitors = None
    init_backing_visitors = None
    data_factory = None
    data_fact_kwargs = None

    def __init__(self, backing_map=None, *, user_map=None, **kwargs):
        if user_map is not None:
            self.user = self._init_user_map(user_map)
        else:
            self.user = {}
        self.user.update(kwargs)
        # UserDict() creates self.data as a shallow copy of backing_map
        super().__init__(backing_map)  # None is treated like *()
        self.backing = self._init_backing_map(backing_map)
        if self.init_user_visitors is None:
            self.init_user_visitors = [self.validate_prospect]
        self._init_visit_items(self.user, *self.init_user_visitors)
        if self.init_backing_visitors is not None:
            self._init_visit_items(self.backing,
                                   *self.init_backing_visitors)
        if self.data_factory and self.data_fact_kwargs is not None:  # clobbers
            self.data = self.data_factory(self.user, self.backing,
                                          **self.data_fact_kwargs)
            if isinstance(self.data, ChainMap):
                self.maps = self.data.maps

    def _init_user_map(self, user_map):
        """Initialize user map"""
        return dict(user_map)

    def _init_backing_map(self, backing_map):
        """Initialize backing map"""
        return dict(self.data)

    def _init_visit_items(self, d, *funcs):
        if not d or not funcs:
            return
        for key, val in dict(d).items():
            for func in funcs:
                func(key, val)

    def validate_prospect(self, key, item):
        if key not in self.backing:
            return
        base_type = type(self.bake(self.backing)[key])
        # Can't use isinstance() here because bool subclasses int, etc.
        if not type(item) is base_type:
            name = self.__class__.__name__.replace("Dict", "")
            raise TypeError("{}/{} must be of type {!r}, not {!r}"
                            .format(name, key, base_type.__name__,
                                    type(item).__name__), base_type)

    def _setitem(self, key, item):
        """The *actual* __setitem__"""
        self.data[key] = item

    def __setitem__(self, key, item):
        if not hasattr(self, "backing"):
            self.data[key] = item
        else:
            self.validate_prospect(key, item)
            self._setitem(key, item)

    def sort_by_surrogate(self, mapping, reference, append=False):
        """Return a new dict sorted by another's ordering
        >>> r = dict(one=1, two=2, three=3)
        >>> m = dict(sorted((("four", 4), *r.items(), ("fake", 100))))
        >>> m
        {'fake': 100, 'four': 4, 'one': 1, 'three': 3, 'two': 2}
        >>> bee = BaseConfigDict()

        "fake" is encountered before "four", and both are unknown to r
        >>> bee.sort_by_surrogate(m, r, True)
        {'one': 1, 'two': 2, 'three': 3, 'fake': 100, 'four': 4}
        >>> bee.sort_by_surrogate(m, r)
        {'fake': 100, 'four': 4, 'one': 1, 'two': 2, 'three': 3}

        """
        # Normally, probably desirable for keys unknown to <reference> to be
        # relegated to the end, but config dicts want known defaults last.
        r = reference
        m = mapping
        if append:
            undex = len(m)
        else:
            undex = -1
        #
        def key(i):  # noqa: E306
            k, __ = i
            return list(r).index(k) if k in r else undex
        #
        if isinstance(mapping, OrderedDict):
            return OrderedDict(sorted(m.items(), key=key))
        return dict(sorted(m.items(), key=key))

    def bake(self, mapping=None, peel=False):
        """Convert all non-dict/OrderedDict mappings to normal dicts.

        peel
            Replace ChainMaps with their topmost layer stripped of
            non-unique items (user items minus backing items).

        mapping
            If absent, a sorted copy of self.data is returned.

        Additional checks for ExpressionsDict instances are enabled in
        debug mode.

        ``OrderedDict`` instances are allowed because they're compatible
        with the json load/dump methods.
        """

        def inner(din):
            if peel and isinstance(din, BaseConfigDict):
                _d = self.sort_by_surrogate(din.maps[MOD], din.maps[PRO])
            else:
                _d = din
            # NOTE copying/deleting might be slightly faster than adding to an
            # empty dict. But this seems clearer/more explicit. Both preserve
            # insertion order.
            d = {}
            for k, v in _d.items():
                # NOTE Condition and Template are subclasses of BaseConfigDict
                if peel and isinstance(din, BaseConfigDict):
                    if k in din.maps[PRO] and v == din.maps[PRO][k]:
                        continue
                    elif (isinstance(v, (Condition, Template)) and
                          v == v.maps[PRO]):
                        d[k] = {}
                        continue
                    elif (not isinstance(v, MutableMapping) and
                          k not in din.maps[PRO]):
                        # FIXME wrong place to enforce this. Happens to be
                        # compatible with the default config, but that could
                        # change. Use getters/setters instead.
                        # TODO write test *not* using default config that
                        # triggers this to ensure it even runs.
                        raise KeyError(f"Unrecognized key: {k}")
                    elif k in din.maps[PRO] and isinstance(din.maps[PRO][k],
                                                           ErsatzList):
                        if (din.diff_list_order is False
                                and set(v) == set(din.maps[PRO][k])):
                            continue
                    else:
                        # Must be a unique and valid MOD value
                        pass
                elif peel and self.debug:
                    assert not hasattr(din, "maps")
                #
                if isinstance(v, (MutableMapping, MappingProxyType)):
                    if self.debug:
                        if isinstance(v, BaseConfigDict):
                            # Never SettingsDict/ExpressionsDict/ConditionsDict
                            assert isinstance(v, (Condition, Template))
                        else:
                            # MappingProxyType or regular dict
                            assert isinstance(self, ExpressionsDict)
                    d[k] = inner(v)
                elif isinstance(v, ErsatzList):
                    d[k] = list(v)
                else:
                    d[k] = v
            if self.debug and peel and isinstance(din, BaseConfigDict):
                assert list(self.sort_by_surrogate(d,
                                                   din.maps[PRO])) == list(d)
            return d

        if self.debug:
            if mapping is None:  # Normal case
                assert isinstance(self.maps[MOD], OrderedDict)
            else:
                # Only called internally by validate_prospect (self.backing)
                assert isinstance(self, BaseConfigDict)
        cand = mapping or self
        outdict = inner(cand)
        return outdict

    def peel(self, peel=True):
        """A wrapper calling bake to peel the data dict

        Derived dicts with a "defkey" attr manipulate output based on
        the value of the ``peel`` arg. If this is not desired, call
        ``.bake(peel=True)`` directly.
        """
        return self.bake(None, bool(peel))

    def _construction_repr(self):
        if hasattr(self, "defkey"):
            backing = {self.defkey: dict(self.backing[self.defkey])}
        else:
            backing = dict(self.backing)
        return "{}({!r}, user_map={!r})".format(self.__class__.__name__,
                                                backing, self.bake(peel=True))

    def _compare_strict(self, other):
        """Alternate __eq__ for testing purposes"""
        if not isinstance(other, BaseConfigDict):
            raise TypeError("For comparing BaseConfigDict instances only")
        return (self.user == other.user and
                self.backing == other.backing)


class SorteM:
    """Ensure modifiable data map is always sorted

    Obviously requires that self.data be a ChainMap instance.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sort_modifiable()

    def sort_modifiable(self):
        self.maps[MOD] = self.maps[MOD].__class__(
            sorted(self.maps[MOD].items())
        )

    def _setitem(self, key, item):
        """The *actual* __setitem__"""
        super()._setitem(key, item)
        self.sort_modifiable()


class SettingsDict(BaseConfigDict):
    """Config category with fixed options and no subdirs

    I.e., contains no internal branches and its length and data
    membership are made permanent on creation

    XXX the above requirement is never checked/enforced. The problem
    lies in the lookup scheme, which muddles things by treating anything
    accepted by ``__getitem__`` as a valid path component.  But
    hashables like "" and (), which we don't want, also support
    ``__getitem__``. The current approach is to assume the "protected"
    dict is correct and to check all new assignments against it. This
    seems safer than screening on instantiation with something like::

        for all maps
            for all values
                reject any Container that's not a string

    """
    data_factory = ChainoFixe
    data_fact_kwargs = {"skip_last": False}
    diff_list_order = True  # peel unequal lists with equal membership

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.popitem = self.data.popitem  # covers clear()

    def _init_backing_map(self, backing_map):
        if self.debug and backing_map:
            assert not any(isinstance(v, MutableMapping) for
                           v in backing_map.values())
        return dict(self.data)

    def validate_prospect(self, key, item):
        super().validate_prospect(key, item)
        if key not in self.backing:
            name = self.__class__.__name__.replace("Dict", "")  # noqa: F841
            raise KeyError(f"Unrecognized {name.lower()}: {key!r}")


class ExpressionsDict(SorteM, BaseConfigDict):
    """A sorted, variable-length dict containing only normal dicts

    I.e, no non-dict members (and the protected dict always goes last).
    """
    data_factory = ChainoBase
    data_fact_kwargs = {}
    defkey = "default"  # has a default item and its name is ...

    def validate_prospect(self, key, item):
        super().validate_prospect(key, item)
        if isinstance(item, dict):
            return
        nested_msg = gen_nested_type_error_msg(self)
        raise TypeError(*(nested_msg % type(item).__name__).splitlines(), dict)

    def __iter__(self):
        """Preserve insertion order but with default items last
        """
        from itertools import chain
        return chain((k for k in self.maps[MOD] if k not in self.maps[PRO]),
                     self.backing)


class Condition(SettingsDict):
    """Inner modifiable map type for ConditionsDict

    Construction requirement
        The desired "backing dict" (what would normally be the last arg)
        must be nested in another dict as its lone item.  Otherwise,
        we'll only get a "peeled" copy stripped of inner maps, which is
        useless.
    """
    diff_list_order = False

    def __new__(cls, *args, **kwargs):
        inst = super(SettingsDict, cls).__new__(cls)  # BaseConfigDict
        inst.data_fact_kwargs = {}
        return inst

    def _init_backing_map(self, backing_map):
        if self.debug:
            assert self.data == backing_map and self.data is not backing_map
        __, protected = self.popitem()
        return protected


class ConditionsDict(BaseConfigDict):
    """Like ExpressionsDict, but unsorted

    And all members must be of type ``Condition``. Initialization tasks
    and individual item-setting are confusing. See module doc string for
    explanation.
    """
    init_user_visitors = []
    data_factory = ChainoBase
    data_fact_kwargs = {"bias": PRO}
    defkey = "default"
    mapper = Condition
    spread = IntEnum("Spread", (("spread", False),)).spread

    def __init__(self, *args, **kwargs):
        self.init_backing_visitors = [self._init_order_all_backing]
        super().__init__(*args, **kwargs)
        self.maps[MOD][self.defkey] = self.mapper(
            self.maps[PRO],  # <- {"default": {...}}
            user_map=self.maps[MOD].get(self.defkey, {})
        )
        for key in self.maps[MOD].keys() - {self.defkey}:
            existing = self.maps[MOD].pop(key)
            self[key] = existing

    def _init_order_all_backing(self, k, v):
        self.backing[k] = OrderedDict(v)

    def validate_prospect(self, key, item):
        if key in self.backing:
            raise KeyError("Cannot set protected key: %r" % key)
        if not isinstance(item, (dict, Condition)):  # deny ChainMaps, UserDicts
            nested_msg = gen_nested_type_error_msg(self)
            raise TypeError(*(nested_msg % type(item).__name__)
                            .splitlines(), dict)

    def _setitem(self, key, item):
        """Create a new mapper tethered to the default"""
        # Maybe just assign existing reference? This makes a copy
        if isinstance(item, Condition):
            item = item.peel()
        self.data[key] = self.mapper(dict(__=self.data[self.defkey]),
                                     user_map=item)

    def __iter__(self):
        """Preserve insertion order but with default items last
        """
        from itertools import chain
        return chain((k for k in self.maps[MOD] if k not in self.maps[PRO]),
                     self.backing)

    def move_modifiable(self, src, dest, relative=False):
        """Reposition, shift, or swap modifiable item(s)

        str
            Move <src> in front of <dest>, or, with <relative>,
            swap/transpose them.

        int
            Move <src> to (current) index <dest>; with <relative>,
            shift/translate <dest> positions.

        >>> keys = list("abc")
        >>> [(n, max(n, 0) and min(len(keys) - 1, n)) for n in range(-2, 4)]
        [(-2, 0), (-1, 0), (0, 0), (1, 1), (2, 2), (3, 2)]
        """
        if src in self.maps[PRO] or dest in self.maps[PRO]:
            raise KeyError("Cannot move default item")
        #
        def rekey():  # noqa: E306
            return [k for k in self if k not in self.maps[PRO]]
        #
        def get_updated():  # noqa: E306
            return [(k, v) for k, v in self.maps[MOD].items() if
                    k not in self.maps[PRO]]
        #
        keys = rekey()
        updated = tardex = None
        if isinstance(dest, int):
            if not relative and dest < 0:  # allow addressing from end
                dest = len(keys) + dest
            newdex = dest if not relative else keys.index(src) + dest
            newdex = max(newdex, 0) and min(len(keys) - 1, newdex)  # doc str
            if not relative:
                if keys.index(src) < dest:
                    tardex = newdex
                else:
                    dest = keys[newdex]
                    if dest == src:
                        return True
            else:
                tardex = newdex
        elif relative:  # swap
            srcdex, destdex = keys.index(src), keys.index(dest)
            updated = get_updated()
            temp = updated[destdex]
            updated[destdex] = updated[srcdex]
            updated[srcdex] = temp
        if updated is None:
            val = self.maps[MOD].pop(src)
            if tardex is None:
                keys = rekey()
                tardex = keys.index(dest)
            updated = get_updated()
            updated.insert(tardex, (src, val))
        updated += [(k, v) for k, v in self.maps[MOD].items() if
                    k in self.maps[PRO]]
        self.maps[MOD] = self.maps[MOD].__class__(updated)
        return True

    def peel(self, peel=True):
        """Optionally return a hybrid baked/peeled dict

        When ``peel`` is a non-bool, return a "fanned-out" manifold view
        with peeled user maps atop the flattened default. Comparable to
        an ini generated for export.
        """
        # Guard against "accidentally" passing peel=None to mean peel=False
        if peel is not self.spread:
            return super().peel(peel=peel)
        peeled = self.bake(None, True)
        peeled[self.defkey] = {}
        peeled[self.defkey].update(self[self.defkey])
        return peeled


class Template(Condition):
    diff_list_order = True


class TemplatesDict(SorteM, ConditionsDict):
    """Hybrid of ExpressionsDict and ConditionsDict

    Items are sorted, but all members are Template objects
    """
    mapper = Template

    def move_modifiable(self, src, dest):
        raise RuntimeError("Unsupported operation")


def gen_nested_type_error_msg(instance):
    """TypeError message for nested ConfigDicts

    User-map-destined args must be maps containing only maps
    """
    short_name = instance.__class__.__qualname__.replace("Dict", "")
    msg = ("{} must be JSON objects or Python dicts, not %r.\nSee '/{}/*' "
           "for reference.").format(short_name, short_name.lower())
    return msg
