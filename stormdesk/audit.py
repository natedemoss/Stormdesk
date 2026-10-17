"""Read OpenShell's own audit log (OCSF JSON lines) so the console can show it.

Inside a sandbox with `ocsf_json_enabled` set, the supervisor writes one OCSF
v1.8.0 JSON object per line to /var/log/openshell-ocsf.YYYY-MM-DD.log. Field
names below follow OpenShell's docs/observability/ocsf-json-export.mdx.
These records are written by OpenShell, outside our process's control.
"""
import glob
import json
import os

from stormdesk.config import OCSF_LOG_GLOB

CLASSES = {4001: "network", 4002: "http", 4007: "ssh", 1007: "process", 2004: "finding", 5019: "config"}


def _event(rec):
    dst = rec.get("dst_endpoint") or {}
    http = rec.get("http_request") or {}
    url = http.get("url") or {}
    return {
        "time": rec.get("time"),
        "kind": CLASSES.get(rec.get("class_uid"), rec.get("class_name", "event")),
        "action": rec.get("action") or rec.get("disposition") or rec.get("status"),
        "severity": rec.get("severity"),
        "message": rec.get("message", ""),
        "dst": f"{dst.get('domain') or dst.get('ip') or ''}{':' + str(dst['port']) if dst.get('port') else ''}",
        "method": http.get("http_method"),
        "path": url.get("path"),
        "process": ((rec.get("actor") or {}).get("process") or {}).get("name"),
        "rule": (rec.get("firewall_rule") or {}).get("name"),
        "reason": rec.get("status_detail"),
    }


def tail(limit=60):
    """Most recent events, newest first. Returns (events, source) or ([], None)."""
    files = sorted(glob.glob(OCSF_LOG_GLOB))
    if not files:
        return [], None
    lines = []
    for f in reversed(files):
        try:
            with open(f, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(0, fh.tell() - 512_000))
                chunk = fh.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        lines = chunk + lines
        if len(lines) >= limit * 3:
            break
    events = []
    for line in reversed(lines):
        try:
            events.append(_event(json.loads(line)))
        except (json.JSONDecodeError, AttributeError):
            continue
        if len(events) >= limit:
            break
    return events, files[-1]
