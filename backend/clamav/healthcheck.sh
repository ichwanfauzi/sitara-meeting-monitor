#!/bin/bash
set -Eeuo pipefail

source "$(dirname "$0")/port.sh"
validate_clamav_port

if ! exec 3<>"/dev/tcp/127.0.0.1/$CLAMAV_PORT"; then
    exit 1
fi
printf 'PING\n' >&3
IFS= read -r -t 2 response <&3
[[ "$response" == "PONG" ]]
