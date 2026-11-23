"""Today's tasks from TaskHub (../taskhub), for the dashboard's Tasks tab. Read-only.

Uses the TaskHub client's config, ~/.config/taskhub/config.toml (`url` plus a device `token`, or a
Cloudflare Access `client_id`/`client_secret`), with the same TASKHUB_* environment overrides.

"Today" is what the StackChan voice agent calls today: open tasks that are in progress, due today or
earlier, or scheduled to have started; plus the ones finished today.
"""
import json
import os
import threading
import time
import tomllib
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "taskhub" / "config.toml"
CACHE_SECONDS = 60
DESCRIPTION_MAX = 1500

# Section order on the page; each task lands in the first one it fits.
SECTIONS = [
    ("overdue", "Overdue"),
    ("due", "Due today"),
    ("doing", "In progress"),
    ("blocked", "Blocked"),
    ("started", "Started"),
    ("done", "Done today"),
]


class TaskHubError(Exception):
    pass


def settings():
    data = {}
    if CONFIG_FILE.exists():
        data = tomllib.loads(CONFIG_FILE.read_text())
    s = {k: os.environ.get(f"TASKHUB_{k.upper()}") or data.get(k, "")
         for k in ("url", "token", "client_id", "client_secret")}
    if not s["url"] or not (s["token"] or s["client_id"]):
        raise TaskHubError(f"TaskHub isn't set up on this PC: {CONFIG_FILE} needs a url and a token")
    return s


def _get(s, path):
    headers = {"X-TaskHub": "1", "X-TaskHub-Source": "kddash", "User-Agent": "kddash",
               "Accept": "application/json"}
    if s["token"]:
        headers["Authorization"] = f"Bearer {s['token']}"
    if s["client_id"]:
        headers["CF-Access-Client-Id"] = s["client_id"]
        headers["CF-Access-Client-Secret"] = s["client_secret"]
    req = urllib.request.Request(f"{s['url'].rstrip('/')}/api{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TaskHubError("TaskHub refused the request: check the token in "
                               f"{CONFIG_FILE}") from None
        raise TaskHubError(f"TaskHub answered HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TaskHubError(f"can't reach TaskHub: {getattr(e, 'reason', e)}") from None


def _day(value):
    return date.fromisoformat(value[:10]) if value else None


def _section(t, today):
    start, due = _day(t["start_date"]), _day(t["due_date"])
    if t["status"] == "done":
        return "done" if _day(t.get("done_at")) == today else None
    if due and due < today:
        return "overdue"
    if due == today:
        return "due"
    if t["status"] in ("doing", "blocked"):
        # Blocked tasks show only when they're scheduled; doing ones always (like the voice agent).
        return t["status"] if t["status"] == "doing" or (start and start <= today) else None
    if start and start <= today:
        return "started"
    return None


def _item(t, project, today):
    due = _day(t["due_date"])
    checklist = sorted(t.get("checklist") or [], key=lambda i: i.get("position", 0))
    return {
        "key": t["key"], "title": t["title"], "status": t["status"], "priority": t["priority"] or 0,
        "project": project.get("name", t["project"]), "color": project.get("color") or "#8b93a5",
        "repo": t.get("repo"), "labels": t.get("labels") or [],
        "start": t["start_date"], "due": t["due_date"],
        "days_left": (due - today).days if due else None,
        "checklist": [{"text": i["text"], "done": bool(i["done"])} for i in checklist],
        "description": (t.get("description") or "")[:DESCRIPTION_MAX],
    }


def _fetch():
    s = settings()
    projects = {p["id"]: p for p in _get(s, "/projects")}
    tasks = _get(s, "/tasks?status=todo,doing,blocked,done")
    today = date.today()
    sections = {sid: [] for sid, _ in SECTIONS}
    for t in tasks:
        project = projects.get(t["project"], {})
        if project.get("status", "active") != "active":  # archived project
            continue
        sid = _section(t, today)
        if sid:
            sections[sid].append(_item(t, project, today))
    for items in sections.values():  # most urgent first: priority, then the nearest deadline
        items.sort(key=lambda i: (-i["priority"], i["due"] is None, i["due"] or "", i["key"]))
    return {
        "today": today.isoformat(),
        "updated": time.time(),
        "open": sum(len(v) for k, v in sections.items() if k != "done"),
        "sections": [{"id": sid, "title": title, "tasks": sections[sid]} for sid, title in SECTIONS],
    }


_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


def today_tasks(refresh=False):
    """Today's tasks, at most CACHE_SECONDS old (refresh=True fetches now). When TaskHub can't be
    reached, the last good answer comes back with an `error` added."""
    with _lock:
        fresh = _cache["data"] and time.time() - _cache["at"] < CACHE_SECONDS
        if refresh or not fresh or _cache["data"]["today"] != date.today().isoformat():
            try:
                _cache.update(at=time.time(), data=_fetch())
            except TaskHubError as e:
                if not _cache["data"]:
                    raise
                return {**_cache["data"], "error": str(e)}
        return _cache["data"]
