#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: verify-public-access.sh https://faryo.example.com/" >&2
}

PUBLIC_URL="${1:-${FARYO_PUBLIC_URL:-}}"
if [[ ! "$PUBLIC_URL" =~ ^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?/?$ ]]; then
  usage
  exit 2
fi

command -v curl >/dev/null 2>&1 || {
  echo "curl is required" >&2
  exit 2
}

PUBLIC_URL="${PUBLIC_URL%/}/"
umask 077
AUDIT_DIR="$(mktemp -d)"
HEADERS="$AUDIT_DIR/headers"
BODY="$AUDIT_DIR/body"

cleanup() {
  unlink "$HEADERS" "$BODY" 2>/dev/null || true
  rmdir "$AUDIT_DIR" 2>/dev/null || true
}
trap cleanup EXIT

curl_exit=0
metrics="$(curl --noproxy '*' --silent --show-error \
  --proto '=https' \
  --connect-timeout 10 \
  --max-time 20 \
  --user-agent 'Mozilla/5.0 Faryo-Access-Audit/1.0' \
  --header 'Accept: text/html,application/xhtml+xml' \
  --dump-header "$HEADERS" \
  --output "$BODY" \
  --write-out '%{http_code} %{ssl_verify_result}' \
  "$PUBLIC_URL")" || curl_exit=$?

if (( curl_exit != 0 )); then
  printf 'tls=FAIL access=UNKNOWN origin-login=UNKNOWN curl-exit=%s\n' "$curl_exit"
  exit 2
fi

read -r http_code tls_result <<<"$metrics"
if [[ "$tls_result" != "0" ]]; then
  printf 'tls=FAIL access=UNKNOWN origin-login=UNKNOWN http=%s\n' "$http_code"
  exit 2
fi

access_redirect=false
if grep -Eqi '^location:[[:space:]]*https://[^/]*\.cloudflareaccess\.com/cdn-cgi/access/' "$HEADERS" \
  || grep -Eqi '^location:[[:space:]]*(https://[^/]+)?/cdn-cgi/access/' "$HEADERS" \
  || grep -Eqi 'cloudflareaccess\.com/cdn-cgi/access/' "$BODY"; then
  access_redirect=true
fi

origin_login=false
if grep -Eqi '^location:[[:space:]]*/login([?#[:space:]]|$)' "$HEADERS" \
  || grep -Fqi 'action="/login"' "$BODY" \
  || grep -Fqi "action='/login'" "$BODY"; then
  origin_login=true
fi

if [[ "$access_redirect" == true && "$origin_login" == false ]]; then
  printf 'tls=PASS access=PASS origin-login=BLOCKED http=%s\n' "$http_code"
  exit 0
fi

if [[ "$origin_login" == true ]]; then
  printf 'tls=PASS access=MISSING origin-login=EXPOSED http=%s\n' "$http_code"
  exit 3
fi

printf 'tls=PASS access=INCONCLUSIVE origin-login=UNKNOWN http=%s\n' "$http_code"
exit 4
