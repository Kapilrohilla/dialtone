"""The `call.disposition` webhook (KAP-46): POSTed to the workspace's webhook URL each time a call's
disposition is set or changed (by the AI, the system or a person).

The body is JSON; `X-Signature: sha256=<hex>` is the HMAC-SHA256 of the raw body with the workspace's
webhook secret. Delivery runs on a background thread (the server has no worker queue), with three tries;
a failure is logged and never affects the call.
"""
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from django.core.serializers.json import DjangoJSONEncoder

from .models import Call, DispositionChange

logger = logging.getLogger(__name__)

EVENT = "call.disposition"
TIMEOUT_S = 10
RETRY_DELAYS_S = (0, 5, 30)


def payload(call: Call, change: DispositionChange, previous: str) -> dict:
    version = call.agent_version
    snapshot = version.snapshot if version is not None and isinstance(version.snapshot, dict) else {}
    by = change.changed_by
    return {
        "event": EVENT,
        "call": {"room": call.room, "caller": call.caller, "called": call.called, "started_at": call.started_at,
                 "ended_at": call.ended_at},
        "agent": {"id": snapshot.get("agent_id"), "name": snapshot.get("name"),
                  "version": version.number if version is not None else None},
        "disposition": {"code": change.code, "name": change.name, "group": change.group, "fields": change.fields,
                        "source": change.source, "note": change.note,
                        "changed_by": (by.email or by.username) if by else None},
        "previous_code": previous or None,
        "at": change.created_at,
    }


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def deliver(url: str, secret: str, body: bytes) -> bool:
    headers = {"Content-Type": "application/json", "User-Agent": "dialtone-webhooks", "X-Event": EVENT,
               "X-Signature": sign(secret, body)}
    for delay in RETRY_DELAYS_S:
        if delay:
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (admin-set URL)
                if 200 <= resp.status < 300:
                    return True
        except (urllib.error.URLError, OSError, ValueError) as e:
            logger.warning("webhook: %s to %s failed: %s", EVENT, url, e)
    logger.error("webhook: gave up on %s to %s", EVENT, url)
    return False


def queue_disposition_event(call_id: int, change_id: int, previous: str) -> None:
    """After a disposition change commits: send the event if the workspace has a webhook URL. Never raises."""
    try:
        call = Call.objects.select_related("workspace", "agent_version").filter(pk=call_id).first()
        ws = call.workspace if call is not None else None
        if ws is None or not ws.webhook_url or not ws.webhook_secret:
            return
        change = DispositionChange.objects.select_related("changed_by").get(pk=change_id)
        body = json.dumps(payload(call, change, previous), cls=DjangoJSONEncoder).encode()
        threading.Thread(target=deliver, args=(ws.webhook_url, ws.webhook_secret, body), daemon=True,
                         name=f"webhook-{call_id}").start()
    except Exception:
        logger.exception("webhook: could not queue %s for call %s", EVENT, call_id)
