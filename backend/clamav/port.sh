validate_clamav_port() {
    if [[ ! ${CLAMAV_PORT+x} || ! "$CLAMAV_PORT" =~ ^[0-9]+$ ]]; then
        echo "CLAMAV_PORT must be an integer between 1 and 65535" >&2
        return 64
    fi

    local port_digits=$CLAMAV_PORT
    while [[ ${#port_digits} -gt 1 && ${port_digits:0:1} == "0" ]]; do
        port_digits=${port_digits:1}
    done
    if [[ ${#port_digits} -gt 5 ]]; then
        echo "CLAMAV_PORT must be an integer between 1 and 65535" >&2
        return 64
    fi

    local port_number=$((10#$port_digits))
    if ((port_number < 1 || port_number > 65535)); then
        echo "CLAMAV_PORT must be an integer between 1 and 65535" >&2
        return 64
    fi

    CLAMAV_PORT=$port_number
    export CLAMAV_PORT
}
