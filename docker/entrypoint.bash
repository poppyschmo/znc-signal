#!/bin/bash

# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>

libexec_dir=/signal-cli-${SIGNAL_CLI_VERSION:-/tmp/fake}
SIGNAL_CLI_EXE=$libexec_dir/bin/signal-cli

rm -f /var/run/dbus.pid

if (( ! $# )) && [[ ${0##*/} == interact ]]; then
    set -- su -l -s /bin/bash signal-cli
fi

if (( ! $# )); then
    : "${SIGNAL_CLI_CONFIG:=$SIGNAL_CLI_HOME/.config/signal}"
    if [[ $SIGNAL_CLI_USERNAME && -e $SIGNAL_CLI_CONFIG ]]; then
        chown -R signal-cli: "$SIGNAL_CLI_HOME" "$SIGNAL_CLI_CONFIG"
        #                                      shellcheck disable=SC2086,SC2163
        export ${!SIGNAL_*}
        cmdline=(
            /usr/bin/supervisord
            --nodaemon --pidfile /var/run/supervisord.pid
            --configuration /etc/supervisord.conf
        )
        set -- "${cmdline[@]}"
    else
        # This only warns (doesn't exit) on failure
        dbus-daemon --system
        sleep 0.1
        if ! [[ -d $libexec_dir && -x $SIGNAL_CLI_EXE &&
                -e /var/run/dbus.pid &&
                -S /var/run/dbus/system_bus_socket ]]; then
            echo Entrypoint check failed
            #                                         shellcheck disable=SC2086
            declare -p ${!SIGNAL_*}
        fi
        set -- bash
    fi
elif ! pgrep -f supervisord &>/dev/null; then
    echo "supervisord is not running"
elif [[ $(supervisorctl status signal-cli) != *@(stop|STOP)* ]]; then
    # Can't pgrep for signal-cli because it's continually stopped/restarted
    # when various checks fail at startup, e.g., account is 'unregistered'
    supervisorctl stop signal-cli  # exits 0 even if already stopped
else
    echo "signal-cli already stopped"
fi >&2

exec "$@"

