#!/bin/bash

# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>


rm -f /etc/supervisord.d/*.conf
[[ $DEBUG_SUPER ]] &&
    ln -s /usr/local/share/supervisord/*.conf /etc/supervisord.d

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
        dbus-daemon --system
        sleep 0.1
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

