"""Run outside EC2. No AWS credentials or portal account required."""
import argparse
import json
import os
import smtplib
import ssl
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse


def evaluate(previous, healthy, notify=None, planned_stop=False):
    state = dict(previous)
    if planned_stop:
        return {**state, "observed": "planned-stop", "failures": 0, "successes": 0, "notified_state": "ok", "delivery": "suppressed"}
    state["observed"] = "ok" if healthy else "failed"
    state["failures"] = 0 if healthy else state.get("failures", 0) + 1
    state["successes"] = state.get("successes", 0) + 1 if healthy else 0
    notified = state.get("notified_state", "ok")
    change = "outage" if state["failures"] >= 3 and notified != "failed" else "recovered" if state["successes"] >= 2 and notified == "failed" else None
    if change:
        if notify is None:
            state["delivery"] = "unconfigured"
        else:
            try:
                notify(change)
                state.update(notified_state="failed" if change == "outage" else "ok", delivery="sent")
            except Exception:
                state["delivery"] = "failed"
    return state


def probe(url):
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Use a public HTTPS health URL without credentials or query")
    try:
        # No redirects: unexpected destinations are a failed check.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(url, timeout=8) as response:
            body = response.read(4097)
            return response.status == 200 and len(body) <= 4096 and json.loads(body).get("state") == "ok"
    except Exception:
        return False


def email_notify(kind):
    message = EmailMessage()
    message["Subject"] = "KOSMOS " + kind
    message["From"] = os.environ["ALERT_FROM"]
    message["To"] = os.environ["ALERT_TO"]
    message.set_content("External portal health status changed: " + kind)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv("SMTP_USERNAME"):
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(os.environ["MONITOR_START_AT"])
    stop = datetime.fromisoformat(os.environ["MONITOR_STOP_AT"])
    if start.tzinfo is None or stop.tzinfo is None or start >= stop:
        raise ValueError("Explicit timezone-aware operating window required")
    suppressed = now < start or now >= stop
    if args.state.exists() and args.state.stat().st_size > 16384:
        raise ValueError("Invalid monitor state")
    previous = json.loads(args.state.read_text()) if args.state.exists() else {}
    configured = all(os.getenv(name) for name in ["SMTP_HOST", "ALERT_FROM", "ALERT_TO"])
    state = evaluate(previous, healthy=False if suppressed else probe(os.environ["MONITOR_URL"]), planned_stop=suppressed, notify=email_notify if configured else None)
    state["checked_at"] = now.isoformat()
    args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = args.state.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(args.state)
    print(json.dumps(state))


if __name__ == "__main__":
    main()
