#!/bin/bash
set -Eeuo pipefail

if [[ ! ${CLAMAV_PORT+x} ]]; then
    CLAMAV_PORT=3310
fi
source "$(dirname "$0")/port.sh"
validate_clamav_port
sed "s/@CLAMAV_PORT@/$CLAMAV_PORT/g" /etc/clamav/clamd.conf \
    > /run/clamav/clamd.conf

if ! find /var/lib/clamav -maxdepth 1 -type f \( -name '*.cvd' -o -name '*.cld' \) -print -quit | grep -q .; then
    freshclam --config-file=/etc/clamav/freshclam.conf --stdout --verbose
fi

freshclam --config-file=/etc/clamav/freshclam.conf --daemon --foreground --stdout &
freshclam_pid=$!
clamd --config-file=/run/clamav/clamd.conf --foreground &
clamd_pid=$!

shutdown() {
    trap - TERM INT
    kill -TERM "$clamd_pid" "$freshclam_pid" 2>/dev/null || true
    wait "$clamd_pid" 2>/dev/null || true
    wait "$freshclam_pid" 2>/dev/null || true
}

trap shutdown TERM INT
set +e
wait -n "$clamd_pid" "$freshclam_pid"
status=$?
set -e
shutdown
exit "$status"
