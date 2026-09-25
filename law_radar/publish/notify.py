"""Optional delivery channels, all off by default: Slack webhook, email over SMTP, Notion database.

Each one runs only when it is enabled in the ICP config's `delivery` section AND its secrets are
set as environment variables. A missing secret skips the channel with a message; it never fails
the weekly run. These adapters are tested against mocked services only.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Callable, Dict, List, Optional

import httpx

from ..config import Config
from ..models import Digest, Entry, NoAiEntry
from .markdown import fmt_date, render, title

NOTION_VERSION = "2022-06-28"


def summary_lines(digest: Digest) -> List[str]:
    lines = []
    for e in digest.entries:
        if isinstance(e, Entry):
            score = f"{e.scorecard.points}/{e.scorecard.max_points}" if e.scorecard else "no score"
            deadline = f", next deadline {fmt_date(e.when.next_deadline)}" if e.when.next_deadline else ""
            lines.append(f"{e.market}: {e.headline.text} (score {score}{deadline}) {e.url}")
        elif isinstance(e, NoAiEntry):
            lines.append(f"{e.market}: {e.title_original} (keyword match, not read yet) {e.url}")
    return lines


def summary_text(digest: Digest, link: Optional[str] = None) -> str:
    if digest.nothing_relevant:
        return f"{title(digest)}: nothing relevant this week."
    head = f"{title(digest)}: {len(digest.entries)} {'law' if len(digest.entries) == 1 else 'laws'}."
    tail = [f"Full digest: {link}"] if link else []
    return "\n".join([head] + [f"- {line}" for line in summary_lines(digest)] + tail + [digest.disclaimer])


# -- Slack -------------------------------------------------------------------

def slack(digest: Digest, env: Dict[str, str], post: Callable = httpx.post, link: Optional[str] = None) -> str:
    url = env.get("SLACK_WEBHOOK_URL")
    if not url:
        return "skipped: SLACK_WEBHOOK_URL not set"
    resp = post(url, json={"text": summary_text(digest, link)}, timeout=30)
    resp.raise_for_status()
    return "sent"


# -- Email -------------------------------------------------------------------

def email(digest: Digest, env: Dict[str, str], smtp_factory: Callable = smtplib.SMTP) -> str:
    missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO") if not env.get(k)]
    if missing:
        return f"skipped: {', '.join(missing)} not set"
    msg = EmailMessage()
    msg["Subject"] = title(digest)
    msg["From"] = env.get("MAIL_FROM") or env["SMTP_USER"]
    msg["To"] = ", ".join(a.strip() for a in env["MAIL_TO"].split(",") if a.strip())
    msg.set_content(render(digest))
    with smtp_factory(env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
        smtp.send_message(msg)
    return "sent"


# -- Notion ------------------------------------------------------------------

def notion_properties(e: Entry, week: str) -> dict:
    props = {
        "Name": {"title": [{"text": {"content": e.headline.text[:2000]}}]},
        "Law ID": {"rich_text": [{"text": {"content": e.id}}]},
        "Market": {"select": {"name": e.market}},
        "Week": {"rich_text": [{"text": {"content": week}}]},
        "Source": {"url": e.url},
    }
    if e.scorecard:
        props["Score"] = {"number": e.scorecard.points}
    if e.when.next_deadline:
        props["Next deadline"] = {"date": {"start": e.when.next_deadline.isoformat()}}
    return props


def notion(digest: Digest, env: Dict[str, str], client: Optional[httpx.Client] = None) -> str:
    token, database = env.get("NOTION_TOKEN"), env.get("NOTION_DATABASE_ID")
    if not token or not database:
        return "skipped: NOTION_TOKEN or NOTION_DATABASE_ID not set"
    http = client or httpx.Client(timeout=30)
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}
    created = 0
    for e in digest.entries:
        if not isinstance(e, Entry):
            continue
        found = http.post(f"https://api.notion.com/v1/databases/{database}/query", headers=headers,
                          json={"filter": {"property": "Law ID", "rich_text": {"equals": e.id}}})
        found.raise_for_status()
        if found.json().get("results"):
            continue                                   # already in the database
        resp = http.post("https://api.notion.com/v1/pages", headers=headers,
                         json={"parent": {"database_id": database}, "properties": notion_properties(e, digest.week)})
        resp.raise_for_status()
        created += 1
    return f"sent: {created} new row(s)"


def run_all(cfg: Config, digest: Digest, env: Optional[Dict[str, str]] = None,
            link: Optional[str] = None) -> Dict[str, str]:
    env = dict(os.environ) if env is None else env
    results: Dict[str, str] = {}
    channels = [("slack", cfg.delivery.slack.enabled, lambda: slack(digest, env, link=link)),
                ("email", cfg.delivery.email.enabled, lambda: email(digest, env)),
                ("notion", cfg.delivery.notion.enabled, lambda: notion(digest, env))]
    for name, enabled, send in channels:
        if not enabled:
            results[name] = "off"
            continue
        try:
            results[name] = send()
        except Exception as exc:  # noqa: BLE001 - an optional channel must never fail the weekly run
            results[name] = f"failed: {exc}"
    return results
