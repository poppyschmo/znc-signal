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

if is_daemon "$@"; then
    while ! ensure_up >/dev/null 2>&1; do
        echo "Waiting for D-Bus..." >&2
        sleep 5
    done
    opts=$SIGNAL_CLI_OPTS
fi

CP=/usr/share/java/libmatthew/unix.jar
CP=$CP$(printf ':%s' /usr/share/java/signal-cli/*.jar)
CMD=$(realpath "$(which java)")
#                                                     shellcheck disable=SC2086
exec "$CMD" $opts -cp "$CP" org.asamk.signal.Main "$@"
