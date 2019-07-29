#!/bin/sh

# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>


rm -f /etc/supervisord.d/*.conf
[ "$DEBUG_SUPER" ] &&
    ln -s /usr/local/share/supervisord/*.conf /etc/supervisord.d

if [ $# -eq 0 ] && [ "${0##*/}" = interact ]; then
    set -- su -l -s /bin/sh signal-cli
fi

if [ $# -eq 0 ]; then
    : "${SIGNAL_CLI_CONFIG:=$SIGNAL_CLI_HOME/.local/share/signal-cli}"
    if [ "$SIGNAL_CLI_USERNAME" ] && [ -e "$SIGNAL_CLI_CONFIG" ]; then
        chown -R signal-cli: "$SIGNAL_CLI_HOME" "$SIGNAL_CLI_CONFIG"
        export SIGNAL_CLI_HOME \
            SIGNAL_CLI_CONFIG \
            SIGNAL_CLI_OPTS \
            SIGNAL_CLI_USERNAME \
            SIGNAL_CLI_VERSION
        set -- /usr/bin/supervisord \
            --nodaemon --pidfile /var/run/supervisord.pid \
            --configuration /etc/supervisord.conf
    else
        printf '\x1b[31mProblem starting container\x1b[m\n'
        echo "Use 'docker exec -it <container> sh -l' to investigate"
        set -x
        env | sort | grep SIGNAL_CLI
        set -- sleep 1d
    fi >&2
elif ! pgrep -f supervisord >/dev/null 2>&1; then
    echo "supervisord is not running"
elif supervisorctl status signal-cli | grep -i stop; then
    # Can't pgrep for signal-cli because it's continually stopped/restarted
    # when various checks fail at startup, e.g., account is 'unregistered'
    supervisorctl stop signal-cli  # exits 0 even if already stopped
else
    echo "signal-cli already stopped"
fi >&2

exec "$@"
