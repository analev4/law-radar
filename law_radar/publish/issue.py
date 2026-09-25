"""The weekly GitHub Issue, "Law radar: week NN", through the gh CLI (preinstalled on GitHub runners).

GitHub emails the repository's watchers when an Issue is opened, so the Issue is the alert.
One Issue per ISO week: the first run opens it, later runs (for example after /digest) edit it.
A hidden marker in the body ties the Issue to its year and week, so week 40 of 2027 gets a new one.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

GITHUB_BODY_LIMIT = 65_000          # GitHub's limit is 65,536 characters
LABEL = "law-radar"

Runner = Callable[..., subprocess.CompletedProcess]


def marker(week: str) -> str:
    return f"<!-- law-radar:{week} -->"


def issue_title(week: str) -> str:
    return f"Law radar: week {week.split('-W')[1]}"


def issue_body(markdown: str, week: str, file_url: Optional[str] = None) -> str:
    body = f"{marker(week)}\n{markdown}"
    if len(body) <= GITHUB_BODY_LIMIT:
        return body
    note = "\n\n---\n\n*The digest is too long for one Issue. " + (
        f"[Read the full digest]({file_url}).*" if file_url else "Read the full digest in the digests folder.*")
    cut = body[: GITHUB_BODY_LIMIT - len(note)]
    last_entry = cut.rfind("\n---\n")                  # cut at an entry boundary
    return (cut[:last_entry] if last_entry > 0 else cut) + note


def _gh(runner: Runner, gh: str, args: List[str], stdin: Optional[str] = None) -> str:
    result = runner([gh] + args, input=stdin, capture_output=True, text=True, check=True)
    return result.stdout


def publish(markdown: str, week: str, runner: Runner = subprocess.run, gh: str = "gh",
            file_url: Optional[str] = None) -> str:
    """Open the week's Issue, or edit it if it exists. Returns "created" or "updated"."""
    body = issue_body(markdown, week, file_url)
    _gh(runner, gh, ["label", "create", LABEL, "--color", "1f5f8b",
                     "--description", "Weekly law-radar digest", "--force"])
    listed = json.loads(_gh(runner, gh, ["issue", "list", "--label", LABEL, "--state", "all",
                                         "--limit", "200", "--json", "number,body"]) or "[]")
    existing = next((i for i in listed if marker(week) in (i.get("body") or "")), None)
    if existing:
        _gh(runner, gh, ["issue", "edit", str(existing["number"]), "--body-file", "-"], stdin=body)
        return "updated"
    _gh(runner, gh, ["issue", "create", "--title", issue_title(week), "--label", LABEL, "--body-file", "-"],
        stdin=body)
    return "created"


def digest_file_url(md_path: Path) -> Optional[str]:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/blob/main/digests/{md_path.name}"
