#!/bin/sh
# ClippyMe container entrypoint.
#
# The image runs as root ONLY long enough to normalize ownership of the
# writable, bind-mountable dirs, then drops to the unprivileged appuser.
#
# A host bind mount (./data:/app/data) or a prior `-u root` invocation can leave
# data/ owned by a UID the non-root appuser (999) cannot traverse — that is the
# cause of the `Permission denied: data/config.json` and `data/cache` failures.
# Re-chowning on every boot makes the container self-healing regardless of how
# the host directory got locked.
#
# The privilege drop happens ONLY for the default `uvicorn` server command, so
# `docker compose run --rm -u root backend sh -lc "..."` (the documented
# integration-test path) still gets a real root shell.
set -e

if [ "$(id -u)" = "0" ] && [ "${1:-}" = "uvicorn" ]; then
    for d in /app/data /app/output /app/uploads; do
        mkdir -p "$d"
    done
    # data/ is small (config, cookies, cache, fonts, bin) — safe to recurse.
    chown -R appuser:appuser /app/data 2>/dev/null || true
    # output/ and uploads/ can be large; their contents are already
    # appuser-created, so only the top-level dir needs fixing.
    chown appuser:appuser /app/output /app/uploads 2>/dev/null || true
    exec gosu appuser "$@"
fi

exec "$@"
