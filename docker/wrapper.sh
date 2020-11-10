#!/bin/sh
#
# See <https://aur.archlinux.org/cgit/aur.git/tree/signal-cli.sh>
# Max fds already set to 2^16

ensure_up() {
    dbus-send --system --type=method_call \
        --dest=org.freedesktop.DBus / org.freedesktop.DBus.GetId
}

is_daemon() {
    for arg; do
        case $arg in daemon) return 0 ;; esac
    done
    return 1
}

EXE=/opt/signal-cli-$SIGNAL_CLI_VERSION/bin/signal-cli

if ! test -x "$EXE"; then
    echo "$EXE missing"
    exit 1;
fi

if is_daemon "$@"; then
    while ! ensure_up >/dev/null 2>&1; do
        echo "Waiting for D-Bus..." >&2
        sleep 5
    done
fi

#                                                     shellcheck disable=SC2086
exec "$EXE" "$@"
