#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <command> [args...]" >&2
    exit 2
fi

JAVA_HOME_SELECTED="${JAVA_HOME:-}"
JAVA_CMD=""

_from_java_home() {
    local candidate="$1"
    if [[ -z "${candidate}" ]]; then
        return 1
    fi
    if [[ -x "${candidate}/bin/java" ]]; then
        JAVA_HOME_SELECTED="${candidate}"
        JAVA_CMD="${candidate}/bin/java"
        return 0
    fi
    return 1
}

_mac_java_home() {
    local version="$1"
    if command -v /usr/libexec/java_home >/dev/null 2>&1; then
        local detected
        if detected="$(/usr/libexec/java_home -v "${version}" 2>/dev/null)"; then
            if _from_java_home "${detected}"; then
                return 0
            fi
        fi
    fi
    return 1
}

_find_system_java() {
    if command -v java >/dev/null 2>&1; then
        JAVA_CMD="$(command -v java)"
        JAVA_HOME_SELECTED="$(cd -- "$(dirname -- "${JAVA_CMD}")/.." && pwd)"
        return 0
    fi
    return 1
}

if ! _from_java_home "${JAVA_HOME_SELECTED}"; then
    JAVA_HOME_SELECTED=""
    JAVA_CMD=""
fi

if [[ -z "${JAVA_CMD}" ]]; then
    _mac_java_home "21" || _mac_java_home "17"
fi

if [[ -z "${JAVA_CMD}" ]]; then
    _find_system_java || true
fi

if [[ -z "${JAVA_CMD}" ]]; then
    echo "error: no Java installation found. Install JDK 21 or 17 and retry." >&2
    exit 1
fi

JAVA_VERSION_RAW="$("${JAVA_CMD}" -version 2>&1 | head -n1)"
JAVA_VERSION="$(echo "${JAVA_VERSION_RAW}" | sed -n 's/.*\"\([0-9.]*\)\".*/\1/p')"
JAVA_MAJOR="${JAVA_VERSION%%.*}"

if [[ -z "${JAVA_MAJOR}" ]]; then
    echo "error: unable to parse Java version from '${JAVA_VERSION_RAW}'" >&2
    exit 1
fi

if [[ "${JAVA_MAJOR}" != "17" && "${JAVA_MAJOR}" != "21" ]]; then
    if _mac_java_home "21" || _mac_java_home "17"; then
        JAVA_VERSION_RAW="$("${JAVA_CMD}" -version 2>&1 | head -n1)"
        JAVA_VERSION="$(echo "${JAVA_VERSION_RAW}" | sed -n 's/.*\"\([0-9.]*\)\".*/\1/p')"
        JAVA_MAJOR="${JAVA_VERSION%%.*}"
    fi
fi

if [[ "${JAVA_MAJOR}" != "17" && "${JAVA_MAJOR}" != "21" ]]; then
    echo "error: PySpark requires Java 17 or 21 (found ${JAVA_VERSION_RAW})." >&2
    echo "Install JDK 21 (e.g. 'brew install openjdk@21') or point JAVA_HOME to JDK 17/21." >&2
    exit 1
fi

export JAVA_HOME="${JAVA_HOME_SELECTED}"
export PATH="${JAVA_HOME}/bin:${PATH}"

exec "$@"
