#!/bin/sh
set -eu

WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
WEB_THREADS="${WEB_THREADS:-4}"
WEB_TIMEOUT="${WEB_TIMEOUT:-900}"
WEB_GRACEFUL_TIMEOUT="${WEB_GRACEFUL_TIMEOUT:-10}"
WEB_MAX_REQUESTS="${WEB_MAX_REQUESTS:-1000}"
WEB_MAX_REQUESTS_JITTER="${WEB_MAX_REQUESTS_JITTER:-100}"

for value in \
  "$WEB_CONCURRENCY" \
  "$WEB_THREADS" \
  "$WEB_TIMEOUT" \
  "$WEB_GRACEFUL_TIMEOUT" \
  "$WEB_MAX_REQUESTS" \
  "$WEB_MAX_REQUESTS_JITTER"
do
  case "$value" in
    ''|*[!0-9]*)
      echo "Gunicorn configuration values must be non-negative integers" >&2
      exit 1
      ;;
  esac
done

exec uv run --no-sync gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --worker-class gthread \
  --workers "$WEB_CONCURRENCY" \
  --threads "$WEB_THREADS" \
  --timeout "$WEB_TIMEOUT" \
  --graceful-timeout "$WEB_GRACEFUL_TIMEOUT" \
  --max-requests "$WEB_MAX_REQUESTS" \
  --max-requests-jitter "$WEB_MAX_REQUESTS_JITTER" \
  --access-logfile - \
  --error-logfile - \
  --capture-output
