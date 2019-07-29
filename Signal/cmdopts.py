# This file is part of ZNC-Signal <https://github.com/poppyschmo/znc-signal>,
# licensed under Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>.

import argparse
from textwrap import dedent
from collections import namedtuple
from .ootil import cacheprop

debug_aliases = {}  # accept "foo" in place of "debug_foo"
_apwrights = {}

PREFIX = "cmd_"
RAWSEP = "@@"  # stash rhs as raw data string

# TODO explore making this module "debug-aware" at import time; currently, all
# non-debug makers and every AllParsed instance keeps track independently.


def strip_suspect(string):
    if string.startswith(RAWSEP):  # assume possible data source
        value = string.replace(RAWSEP, "", 1).lstrip()
        return SerialSuspect(value)
    else:
        return string


class SerialSuspect(str):
    """String marked as candidate for deserialization
    """
    def __call__(self, as_json, enclose=False):
        from .configgers import eval_string
        if enclose:
            return eval_string("[%s]" % self, as_json)
        return eval_string(self, as_json)


class HelpFormatterMod(argparse.HelpFormatter):
    """
    Put optionals and positionals on the same line
    """
    def _format_usage(self, *args, **kwargs):
        output = super()._format_usage(*args, **kwargs)
        prefix = f"usage: {self._prog} "
        indent = " " * len(prefix)
        from .ootil import backwrap
        backed = backwrap((l.strip() for l in output.strip().splitlines()))
        indented = f"\n{indent}".join(backed)
        return f"{indented}\n\n"


class RawDescriptionHelpFormatterMod(HelpFormatterMod,
                                     argparse.RawDescriptionHelpFormatter):
    pass


class AllParsed:
    """A member-access proxy for apwrights

    To get unprefixed names, i.e., 'progs'::
        progs = (*ap(False),)

    Mod-command form::
        mod_command_names = (*ap(True),)

    """
    _wrights = None
    _iterpre = None
    _debug = None

    def __init__(self, prefixed=False, debug=False):
        self._debug = debug
        self._iterpre = prefixed
        self._wrights = apwrights
        if not apwrights._peed:
            raise ValueError("apwrights is missing parser objects")

    def __getattr__(self, name):
        name = decmd(name)
        name = debug_aliases.get(name, name)
        if hasattr(self._wrights, name):
            return getattr(self._wrights, name).p
        raise AttributeError

    def __eq__(self, other):
        if not isinstance(other, AllParsed):
            return self._wrights == other
        else:
            return self.items() == other.items()

    def _asdict(self):
        if "_AllParsed__data" not in self.__dict__:
            self.__dict__["_AllParsed__data"] = dict(zip(self, self._all))
        return self.__dict__["_AllParsed__data"]

    def items(self):
        return self._asdict().items()

    def keys(self):
        return self._asdict().keys()

    def values(self):
        return self._asdict().values()

    def __contains__(self, key):
        return (self.decmd(key) in self._fields or
                self.encmd(key) in self._fields)

    def __iter__(self):
        return iter(self._fields)

    def __getitem__(self, key):
        return getattr(self, key)

    def __dir__(self):
        """The usual, plus 'cmd_'-prefixed parser objects"""
        # Unprefixed variants like '.update' are collision prone
        return list(self(True).keys() | set(object.__dir__(self)))

    def __call__(self, prefixed=None, debug=None):
        if debug is None:
            debug = self._debug
        if prefixed is None:
            prefixed = self._iterpre
        return type(self)(prefixed=prefixed, debug=debug)

    def encmd(self, cmd_name):
        """Return unaliased (canonicalized) 'mod-command' form"""
        return encmd(self.decmd(cmd_name))

    def decmd(self, cmd_name):
        """Return canonicalized form without leading 'cmd_' prefix"""
        cmd_name = decmd(cmd_name)
        cmd_name = debug_aliases.get(cmd_name, cmd_name)
        return cmd_name

    @cacheprop
    def _all(self):
        # Returning generators instead of caching is quicker if .items(), etc.
        # are only invoked once per instance, which is common
        return tuple(getattr(self, a) for a in self)

    @cacheprop
    def _fields(self):
        # Would be nice to commit to prefixed/unprefixed names here, but
        # __contains__ should work regardless of mode
        if self._debug:
            fields = self._wrights._fields
        else:
            fields = (f for f in self._wrights._fields if
                      not f.startswith("debug_"))
        if self._iterpre is False:
            return tuple(fields)
        else:
            return tuple(encmd(a) for a in fields)

    def _get_action(self, cmd_name, option):
        actions = self[cmd_name]._actions
        return [a for a in actions if a.dest == option].pop()

    def _construct_error(self, cmd_name, option, msg):
        """Return ArgumentError instance with formatted msg"""
        action = self._get_action(cmd_name, option)
        msg = msg.format(**vars(action))
        return argparse.ArgumentError(action, msg)


def patch_apo_formatter(p):
    if p.formatter_class is argparse.HelpFormatter:
        p.formatter_class = HelpFormatterMod
    elif p.formatter_class is argparse.RawDescriptionHelpFormatter:
        p.formatter_class = RawDescriptionHelpFormatterMod


def patch_epilog(apo, aliases):
    """Append aliases to help epilogue"""
    strung = ", ".join(sorted(repr(a) for a in aliases))
    if len(aliases) > 1:
        fmtstr = f"Aliases: {strung}"
    else:
        fmtstr = f"Alias: {strung}"
    if apo.epilog is None:
        apo.epilog = fmtstr
        return
    elif fmtstr in apo.epilog:
        return
    orig = apo.epilog
    if (apo.formatter_class == argparse.HelpFormatter or
            orig.splitlines()[-1].strip()):
        orig = orig.rstrip(". \t\r\n")
        addendum = f". {fmtstr}."
    else:
        addendum = f"\n{fmtstr}"
    apo.epilog = f"{orig}{addendum}"


def initialize_all(debug=False, **kwargs):
    if set(apwrights._fields) & {a for a in dir(AllParsed) if
                                 not a.startswith("_")}:
        raise ValueError("Attribute name collision detected")
    for field, func in apwrights._asdict().items():
        if hasattr(func, "debug"):
            func.debug = debug
        func(**kwargs.get(field, {}))
    apwrights._peed = True


def decmd(cmd_name):
    return cmd_name.replace(PREFIX, "", 1)


def encmd(cmd_name):
    if cmd_name.startswith(PREFIX):
        return cmd_name
    return f"{PREFIX}{cmd_name}"


def mando(f, *aliases):
    #
    def wrap(**kw):  # noqa: E306
        wrap.kwargs.update(kw)
        p = f(**wrap.kwargs)
        patch_apo_formatter(p)
        if wrap.aliases:
            patch_epilog(p, wrap.aliases)
        wrap.p = p
        return p
    #
    def maker(g):  # noqa: E306
        nonlocal f
        f = g  # covers non-callable case below
        from functools import update_wrapper
        attrized = update_wrapper(wrap, g)
        tail = decmd(g.__name__)
        _apwrights[tail] = attrized
        wrap.aliases = set()
        if tail.startswith("debug_"):
            abbreved = tail.replace("debug_", "")
            debug_aliases.update({abbreved: tail})
            wrap.aliases.add(abbreved)
        else:
            wrap.debug = None
        if aliases:
            debug_aliases.update({a: tail for a in aliases})
            wrap.aliases.update(aliases)
        wrap.aliases = tuple(wrap.aliases)
        wrap.kwargs = {}
        wrap.p = None
        return wrap
    #
    if not callable(f):
        aliases = (f, *aliases)
        return maker
    else:
        return maker(f)


@mando
def cmd_help():
    p = argparse.ArgumentParser(
        prog="help",
        description="List args or short description for commands"
    )
    p.add_argument(
        "--usage",
        action="store_true",
        help="""
            show usage (options/args) instead of descriptions. Implied when
            <command> present
        """
    )
    p.add_argument(
        "commands", metavar="<command>",
        nargs="*",
        help="default: all commands"
    )
    return p


@mando
def cmd_connect(host=None, port=None):
    debug = cmd_connect.debug
    p = argparse.ArgumentParser(
        prog="connect",
        description="""Connect to a local Signal service""",
        epilog="""
            Note: the --address option is a placeholder for UNIX domain
            socket addresses, which aren't yet supported. This means well
            known default aliases like SESSION and SYSTEM, i,e.,
            '/var/run/dbus/*' and '/var/run/user/$UID/*', won't work.
        """ if debug else None
    )
    #
    p.add_argument(
        "--address", metavar="<address>",
        help="""
            full DBus address of a local Signal service daemon; example:
            tcp:host=signal.service,port=1234
        """ if debug else argparse.SUPPRESS
    )
    #
    connect_sep = p.add_argument_group("without address") if debug else p
    #
    host_kwargs = {"metavar": "<host>",
                   "help": "example: localhost"}
    # Don't set the ``required`` kwarg, let module cmd_* func handle if missing
    if host:
        host_kwargs["default"] = host
        host_kwargs["help"] = "default: %(default)s"
    connect_sep.add_argument("--host", **host_kwargs)
    #
    connect_sep.add_argument(
        "--port", metavar="<port>",
        type=int, default=port or 47000,
        help="default: %(default)s"
    )
    return p


@mando
def cmd_disconnect():
    p = argparse.ArgumentParser(
        prog="disconnect",
        description="Disconnect from a local Signal service"
    )
    return p


@mando
def cmd_select():
    p = argparse.ArgumentParser(
        prog="select",
        description="Retrieve a config entry"
    )
    p.add_argument(
        "path", metavar="<path>",
        nargs="?",
        help="""
            path to some item; on success, either becomes new "selection"
            (i.e., "working dir") or, if relative, modifies it; when absent,
            shows current selection; example: ../foo/-1 selects last item in
            sibling "foo"
        """
    )
    p.add_argument(
        "--depth", metavar="<depth>",
        type=int, default=2,
        help="""
            levels to show beneath selection; 0 for recursive; default:
            %(default)r
        """
    )
    return p


@mando
def cmd_update(datadir=None):
    datadir = datadir or ""
    if datadir:
        datadir = f"\n\nData directory:\n  {datadir!r}"
    p = argparse.ArgumentParser(
        prog="update",
        description="Modify a config entry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""
            This command does not allow making wholesale changes to / (root).
            Either invoke it separately per main category or edit the config
            file directly and reload.{datadir}
        """).format(datadir=datadir)
    )
    cu_meg = p.add_mutually_exclusive_group()
    cu_meg.add_argument(
        "--remove",
        action="store_true",
        help="remove <path> or saved selection"
    )
    cu_meg.add_argument(
        "--rename",
        action="store_true",
        help="rename an entry"
    )
    cu_meg.add_argument(
        "--reload",
        action="store_true",
        help="update config from module's data directory or <path>"
    )
    cu_meg.add_argument(
        "--export",
        action="store_true",
        help="save current config to the module's data directory or <path>"
    )
    cu_meg.add_argument(
        "--arrange",
        action="store_true",
        help="""
            only affects custom conditions; swap condition at <path> (or last
            selection) for another at <value>; alternatively, if <value> is a
            number, shift condition at <path> (or last selection) +/- however
            many places
        """
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="skip checks when reloading or exporting"
    )
    p.add_argument(
        "--json", dest="as_json",
        action="store_true",
        help="""
            interpret raw values (anything after the {sep} seperator) as JSON
            instead of Python; useful if pasting from a clipboard; with
            --export or --reload, import/export .json instead of .ini files
        """.format(sep=RAWSEP)
    )
    p.add_argument(
        "path", metavar="<path>",
        nargs="?",
        type=strip_suspect,
        help="""
            path to some item (existing or desired); if absent, result of most
            recent "select" query is used; with --reload or --export, refers to
            a location on the file system
        """
    )
    p.add_argument(
        "value", metavar=f"[{RAWSEP}] <value>",
        nargs="?",
        type=strip_suspect,
        help="""
            new value to set; for lists and JSON-like objects, the {S}-sep
            form must be used, which is similar to /quote in that no options
            may follow {S} <value>, and it's exempt from generic shell quoting
            rules (but not those imposed by your client); example: update
            /conditions/custom {S} {{"away_only": True, "body": "custom"}}
        """.format(S=RAWSEP)
    )
    return p


@mando
def cmd_debug_args():
    p = argparse.ArgumentParser(
        prog="debug_args",
        description="Test arg parsing used by commands",
        epilog=f"This is primarily for previewing post-'{RAWSEP}' raw args"
    )
    p.add_argument(
        "command", metavar="<command>"
    )
    p.add_argument(
        "args", metavar="<arg>",
        nargs="*"
    )
    return p


@mando("console")
def cmd_debug_cons():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="debug_cons",
        description="Serve a Python debug console on a local interface",
        epilog=dedent("""\
        console locals:
            pp          pprint.pprint
            pd          pp(dir(<object>))
            pm          pdb.post_mortem     <- see below
            console     Signal.Console()    <- i.e., "self"
            module      Signal.Signal()

        Connect remotely with:

            >$ ssh -f -L 1234:<bindhost>:<port> my.remote.tld \\
                    sleep 10 &&
                rlwrap nc localhost 1234

            >>> isinstance(module._cmod, znc.CPyModule)
            >>> help(znc.CModPython)

        Debug an exception:
            /msg *Signal debug_fail ValueError test

            >>> pm()

            (Pdb) help
            (Pdb) args
            (Pdb) pp dir(self)
            (Pdb) self.put_pretty("Hello")

        """)
    )
    p.add_argument(
        "--stop",
        action="store_true",
        help="stop server"
    )
    console_main = p.add_argument_group("main")
    console_main.add_argument(
        "--bindhost", metavar="<bindhost>",
        default="localhost",
        help="default: %(default)s"
    )
    console_main.add_argument(
        "--port", metavar="<port>",
        type=int,
        help="default: random unprivileged"
    )
    return p


@mando
def cmd_debug_expr():
    p = argparse.ArgumentParser(
        prog="debug_expr",
        description="Test an expression against sample text",
        epilog=f"Use debug_args to preview post-'{RAWSEP}' parsing"
    )
    p.add_argument(
        "--json", dest="as_json",
        action="store_true",
        help="""
            interpret a post-{sep} <expr> as JSON instead of Python
            """.format(sep=RAWSEP)
    )
    p.add_argument(
        "text", metavar="<text>"
    )
    p.add_argument(
        "expression", metavar=f"[{RAWSEP}] <expr>",
        type=strip_suspect,
        help="""
            either the name of a predefined expression from config/expressions
            or one passed in literally using the {S}-sep form. See the <value>
            entry under 'update -h'
        """.format(S=RAWSEP)
    )
    return p


@mando
def cmd_debug_fail():
    p = argparse.ArgumentParser(
        prog="debug_fail",
        description="Fail with exception",
    )
    p.add_argument(
        "exc", metavar="<PythonException>",
        nargs="?",
        default="Exception",
        help="default: %(default)r"
    )
    p.add_argument(
        "msg", metavar="<msg>",
        nargs="*",
        default=("some message",),
        help="default: %(default)s"
    )
    return p


@mando("dbus_send")
def cmd_debug_send():
    p = argparse.ArgumentParser(
        prog="debug_send",
        description="Make a DBus method call to the service daemon",
        epilog="""
            Note: the connection must already be up and running, and the
            interface is inferred from the node/method combo. All args are
            case sensitive.
        """
    )
    p.add_argument(
        "--json", dest="as_json",
        action="store_true",
        help="interpret <method args> as JSON instead of Python"
    )
    p.add_argument(
        "node", metavar="<node>",
        help="""
            shorthand for the last component of the dest or path. For now,
            must either be "Signal," for the service, or "DBus," for the
            daemon (manager).
        """
    )
    p.add_argument(
        "method", metavar="<method name>",
        help="The method tag's \"name\" attribute."
    )
    p.add_argument(
        "raw_string", metavar=f"{RAWSEP} <method args>",
        nargs="?",
        type=strip_suspect,
        help="""
            must follow a "{S}" separator. Format should be comma-separated
            JSON; no need to shell\\ quote or [ book-end ]; must adhere to
            call signature exactly; example: {S} "foo", {{"bar": 42}}, "baz"
        """.format(S=RAWSEP)
    )
    return p


class ParserMakers(namedtuple("CmdOptsParserMakers", _apwrights)):
    _peed = None


apwrights = ParserMakers(**_apwrights)
