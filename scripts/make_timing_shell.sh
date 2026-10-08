#!/bin/sh
case "${BENCHBOX_MAKE_TIMINGS:-}" in
	0|off|false|no) exec /bin/sh "$@" ;;
esac
if command -v python3 >/dev/null 2>&1; then
	exec python3 "$(dirname "$0")/make_timing.py" run -- /bin/sh "$@"
fi
exec /bin/sh "$@"
