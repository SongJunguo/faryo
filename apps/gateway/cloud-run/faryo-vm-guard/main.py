import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ID = os.environ["PROJECT_ID"]
ZONE = os.environ["ZONE"]
INSTANCE = os.environ["INSTANCE_NAME"]
HEALTH_URL = os.environ["HEALTH_URL"]
HEALTH_TOKEN = os.environ["HEALTH_TOKEN"]
FAILURE_THRESHOLD = int(os.environ.get("FAILURE_THRESHOLD", "3"))
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "600"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "8"))

COMPUTE_BASE = "https://compute.googleapis.com/compute/v1"
LABEL_FAILURES = "faryo-guard-failures"
LABEL_COOLDOWN = "faryo-guard-cooldown"
LABEL_LAST_RESET = "faryo-guard-last-reset"


def metadata_token() -> str:
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["access_token"]


def google_request(method: str, url: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {metadata_token()}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def instance_url() -> str:
    return f"{COMPUTE_BASE}/projects/{PROJECT_ID}/zones/{ZONE}/instances/{INSTANCE}"


def get_instance() -> dict:
    return google_request("GET", instance_url())


def set_instance_labels(instance: dict, labels: dict[str, str]) -> dict:
    return google_request(
        "POST",
        instance_url() + "/setLabels",
        {"labels": labels, "labelFingerprint": instance["labelFingerprint"]},
    )


def reset_instance() -> dict:
    return google_request("POST", instance_url() + "/reset", {})


def probe_health() -> tuple[bool, dict]:
    req = urllib.request.Request(
        HEALTH_URL,
        headers={
            "X-Faryo-Guard-Token": HEALTH_TOKEN,
            "User-Agent": "Faryo-VM-Guard/1.0",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
        elapsed_ms = round((time.monotonic() - started) * 1000)
        payload = json.loads(raw) if raw else {}
        ok = status == 200 and payload.get("ok") is True
        return ok, {"status": status, "elapsedMs": elapsed_ms, "payload": payload}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        return False, {"status": exc.code, "error": body}
    except Exception as exc:
        return False, {"error": type(exc).__name__, "detail": str(exc)}


def parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


def run_guard() -> tuple[int, dict]:
    now = int(time.time())
    healthy, probe = probe_health()
    instance = get_instance()
    labels = dict(instance.get("labels") or {})
    failures = parse_int(labels.get(LABEL_FAILURES), 0)
    cooldown_until = parse_int(labels.get(LABEL_COOLDOWN), 0)

    if healthy:
        if failures or cooldown_until:
            labels[LABEL_FAILURES] = "0"
            labels[LABEL_COOLDOWN] = "0"
            set_instance_labels(instance, labels)
        return 200, {"ok": True, "action": "healthy", "probe": probe, "failures": 0}

    failures += 1
    labels[LABEL_FAILURES] = str(failures)

    if cooldown_until > now:
        set_instance_labels(instance, labels)
        return 200, {
            "ok": False,
            "action": "cooldown",
            "probe": probe,
            "failures": failures,
            "cooldownUntil": cooldown_until,
        }

    if failures < FAILURE_THRESHOLD:
        set_instance_labels(instance, labels)
        return 200, {"ok": False, "action": "counted_failure", "probe": probe, "failures": failures}

    labels[LABEL_FAILURES] = "0"
    labels[LABEL_COOLDOWN] = str(now + COOLDOWN_SECONDS)
    labels[LABEL_LAST_RESET] = str(now)
    set_instance_labels(instance, labels)
    operation = reset_instance()
    return 200, {
        "ok": False,
        "action": "reset",
        "probe": probe,
        "failures": failures,
        "cooldownUntil": now + COOLDOWN_SECONDS,
        "operation": operation.get("name"),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.handle_run()

    def do_POST(self) -> None:
        self.handle_run()

    def log_message(self, fmt: str, *args: object) -> None:
        print(fmt % args, flush=True)

    def handle_run(self) -> None:
        try:
            status, payload = run_guard()
        except Exception as exc:
            status = 500
            payload = {
                "ok": False,
                "action": "guard_error",
                "error": type(exc).__name__,
                "detail": str(exc),
            }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
