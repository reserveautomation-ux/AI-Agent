#!/usr/bin/env bash
# Quick post-deploy check:  scripts/smoke.sh https://workforce-api.onrender.com [https://workforce-web.onrender.com]
set -uo pipefail

API="${1:?usage: $0 <api-url> [web-url]}"
WEB="${2:-}"
fail=0

check() {
  local name="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok   $name"
  else
    echo "FAIL $name (expected $expected, got $got)"
    fail=1
  fi
}

check "API health" "200" "$(curl -s -o /dev/null -w '%{http_code}' "$API/health")"
check "API rejects requests without sign-in" "401" "$(curl -s -o /dev/null -w '%{http_code}' "$API/tasks")"
if [ -n "$WEB" ]; then
  check "Web app loads" "200" "$(curl -s -o /dev/null -w '%{http_code}' "$WEB/login")"
  allowed=$(curl -s -o /dev/null -w '%{http_code}' -X OPTIONS "$API/tasks" \
    -H "Origin: $WEB" -H "Access-Control-Request-Method: GET")
  check "API allows the web app (CORS)" "200" "$allowed"
fi

exit $fail
