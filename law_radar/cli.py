"""Command line: law-radar run | digest-step | record-fixtures | issue | notify | site | bdns | lint | schema"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .config import ROOT, Config, ConfigError, load_config, load_datasets
from .cost import CostTracker
from .http import PoliteClient
from .llm import LLM, Pending, slug
from .models import Digest, Document
from .pipeline import run_pipeline
from .publish import files
from .state import State
from .steps.lint import lint

DEFAULT_LOOKBACK_DAYS = 7
OVERLAP_DAYS = 1          # Cellar can index an act a day late; seen.json absorbs the overlap
WAITING_EXIT_CODE = 3     # digest-step / record-fixtures: answers still to write


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def build_sources(cfg: Config, client: PoliteClient) -> List:
    sources = []
    if cfg.sources.eu.enabled:
        from .sources.eu_cellar import EUCellarSource
        sources.append(EUCellarSource(client, include_corrigenda=cfg.sources.eu.include_corrigenda))
    if cfg.sources.fr.enabled:
        from .sources.fr_dila import FRDilaSource
        sources.append(FRDilaSource(client, cfg.sources.fr.natures, cfg.sources.fr.exclude_headings))
    if cfg.sources.es.enabled:
        from .sources.es_boe import ESBoeSource
        sources.append(ESBoeSource(client, cfg.sources.es.sections, cfg.sources.es.section3_epigraphs))
    return sources


def _load_cfg(path: Optional[str]) -> Optional[Config]:
    try:
        return load_config(path)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _api_ready() -> Optional[str]:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return "the anthropic package is not installed (pip install -e \".[api]\")"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set"
    return None


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args.config)
    if cfg is None:
        return 2
    llm: Optional[LLM] = None
    if not args.no_ai:
        mode = "replay" if args.replay else ("record" if args.record else "live")
        if mode != "replay":
            problem = _api_ready()
            if problem:
                print(f"API mode is optional and not set up: {problem}.\n"
                      "Run with --no-ai, then use /digest in Claude Code for the summaries.", file=sys.stderr)
                return 2
        llm = LLM(mode=mode, recordings=Path(args.replay) if args.replay else None, tracker=CostTracker())

    today = args.today or dt.date.today()
    state = State.load(Path(args.state))
    until = args.until or today
    if args.since:
        since = args.since
    elif state.last_until:
        since = state.last_until - dt.timedelta(days=OVERLAP_DAYS)
    else:
        since = until - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS)

    client = PoliteClient()
    matches: List[Document] = []
    try:
        digest = run_pipeline(cfg, build_sources(cfg, client), state, today=today, since=since, until=until,
                              datasets=load_datasets(), llm=llm, no_ai=args.no_ai, log=print,
                              matches_out=matches)
    finally:
        client.close()

    out = Path(args.out)
    md, js = files.write(digest, out)
    if args.no_ai:
        files.write_matches(digest, matches, out)
    if not args.dry_run:
        state.save(today, until)
    c = digest.run.counts
    print(f"\n{digest.week}: {c.fetched} fetched, {c.new} new, {c.keyword_pass} keyword matches, "
          f"{c.model_pass} relevant, {c.published} published.")
    print(f"Wrote {md} and {js}" + (" (state not saved: dry run)" if args.dry_run else ""))
    print(llm.tracker.summary() if llm else "No-AI mode: no model calls, $0.00. Run /digest in Claude Code for summaries.")
    return 0


# ---------------------------------------------------------------------------
# digest-step: the Claude Code path used by /digest
# ---------------------------------------------------------------------------

class StoredSource:
    """Serves the week's saved matches; fetches each text once from the real source and caches it."""

    def __init__(self, source_id: str, market: str, docs: List[Document], real, cache: Path):
        self.id, self.market, self._docs, self._real, self._cache = source_id, market, docs, real, cache

    def fetch_since(self, since, until=None) -> List[Document]:
        return list(self._docs)

    def fetch_text(self, doc: Document) -> Document:
        path = self._cache / f"{slug(doc.id)}.json"
        if path.exists():
            return Document.model_validate_json(path.read_text(encoding="utf-8"))
        full = self._real.fetch_text(doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full.model_dump_json(), encoding="utf-8")
        return full


def _print_waiting(pending_dir: Path, waiting: List[str]) -> None:
    requests = sorted(pending_dir.glob("*.md")) if pending_dir.exists() else []
    print(f"\nWAITING: {len(requests)} request(s) for {len(waiting)} text(s). Answer each file, then run this again:")
    for r in requests:
        print(f"  {r}")


def cmd_digest_step(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args.config)
    if cfg is None:
        return 2
    out = Path(args.out)
    if args.week:
        stem = args.week.replace("-W", "-")
    else:
        found = sorted(out.glob("*.matches.json"))
        if not found:
            print(f"No matches file in {out}. Run `law-radar run --no-ai` first (the weekly Action does this).")
            return 2
        stem = found[-1].name.split(".")[0]
    mfile = out / f"{stem}.matches.json"
    if not mfile.exists():
        print(f"{mfile} not found. Run `law-radar run --no-ai` for that week first.")
        return 2
    saved = json.loads(mfile.read_text(encoding="utf-8"))
    docs = [Document.model_validate(d) for d in saved["documents"]]
    since, until = _date(saved["window"]["since"]), _date(saved["window"]["until"])

    work = Path(args.work) / stem
    llm = LLM(mode="exchange", recordings=work / "responses", pending=work / "pending")
    client = PoliteClient()
    real = {s.id: s for s in build_sources(cfg, client)}
    sources = [StoredSource(sid, real[sid].market, [d for d in docs if d.source == sid], real[sid], work / "texts")
               for sid in sorted({d.source for d in docs}) if sid in real]
    waiting: List[str] = []
    log = print if args.verbose else (lambda _: None)
    try:
        digest = run_pipeline(cfg, sources, State(work / "scratch-state"), today=until, since=since, until=until,
                              datasets=load_datasets(), llm=llm, log=log,
                              max_documents=cfg.limits.max_documents_claude_code, waiting=waiting)
    finally:
        client.close()

    if waiting:
        _print_waiting(work / "pending", waiting)
        return WAITING_EXIT_CODE

    # Complete: carry the weekly run's fetch counts over, save the digest, keep over-cap texts for next week.
    before = saved.get("counts", {})
    for k in ("fetched", "new", "keyword_pass"):
        if k in before:
            setattr(digest.run.counts, k, before[k])
    over = [d for d in docs if d.id not in {e.id for e in digest.entries}][: digest.run.counts.deferred_by_cap]
    if over:
        state = State.load(Path(args.state))
        known = {d.id for d in state.deferred}
        state.deferred.extend(d for d in over if d.id not in known)
        state.save(dt.date.today(), state.last_until or until)
    md, js = files.write(digest, out, replace=True)     # rebuilt from the week's full list of matches
    c = digest.run.counts
    print(f"\nCOMPLETE: {digest.week}. {c.read} text(s) read, {c.published} law(s) published, "
          f"{c.facts_dropped} fact(s) dropped by the citation check, {c.fields_not_generated} field(s) not generated"
          + (f", {c.deferred_by_cap} text(s) over the cap of {cfg.limits.max_documents_claude_code} kept for next week"
             if c.deferred_by_cap else "") + ".")
    print(f"Wrote {md} and {js}. Review them, then commit and push.")
    return 0


# ---------------------------------------------------------------------------
# record-fixtures: answers for the golden tests
# ---------------------------------------------------------------------------

def cmd_record(args: argparse.Namespace) -> int:
    from .fixtures import EU_IRRELEVANT, GOLDEN_TODAY, golden_sources, load_eu
    from .steps.model_filter import model_filter

    cfg = load_config(str(ROOT / "icp.example.yaml"))
    recorded = ROOT / "tests" / "fixtures" / "recorded"
    pending = Path(args.scratch) / "pending"
    if args.api:
        problem = _api_ready()
        if problem:
            print(f"--api needs the optional API setup: {problem}.", file=sys.stderr)
            return 2
        llm = LLM(mode="record", recordings=recorded, tracker=CostTracker())
    else:
        llm = LLM(mode="exchange", recordings=recorded, pending=pending)

    waiting: List[str] = []
    digest = run_pipeline(cfg, golden_sources(), State(Path(args.scratch) / "state"), today=GOLDEN_TODAY,
                          since=GOLDEN_TODAY - dt.timedelta(days=7), until=GOLDEN_TODAY,
                          datasets=load_datasets(), llm=llm, log=print, waiting=waiting)
    # The irrelevant text never reaches the model in a normal run (the keyword filter drops it).
    # Record the model filter's answer on it too, so the test covers both layers.
    try:
        verdict = model_filter(llm, cfg, load_eu(EU_IRRELEVANT))
        print(f"filter on {EU_IRRELEVANT}: relevant={verdict.relevant}. {verdict.reason}")
    except Pending:
        waiting.append(f"eu:{EU_IRRELEVANT}")

    if waiting:
        _print_waiting(pending, waiting)
        return WAITING_EXIT_CODE
    md, _ = files.write(digest, Path(args.scratch))
    print(f"\nCOMPLETE: recordings in {recorded}. Scratch digest: {md}")
    if args.api:
        print(llm.tracker.summary())
    return 0


# ---------------------------------------------------------------------------
# publish: Issue, Pages table, optional channels
# ---------------------------------------------------------------------------

def _digest_path(out: Path, week: Optional[str]) -> Optional[Path]:
    if week:
        path = out / f"{week.replace('-W', '-')}.json"
        return path if path.exists() else None
    found = [p for p in sorted(out.glob("*.json")) if not p.name.endswith(".matches.json")]
    return found[-1] if found else None


def cmd_issue(args: argparse.Namespace) -> int:
    from .publish import issue
    cfg = _load_cfg(args.config)
    if cfg is None:
        return 2
    if not cfg.delivery.issue:
        print("Issue delivery is off in the config.")
        return 0
    path = _digest_path(Path(args.out), args.week)
    if path is None:
        print("No digest found.", file=sys.stderr)
        return 2
    digest = Digest.model_validate_json(path.read_text(encoding="utf-8"))
    md = path.with_suffix(".md").read_text(encoding="utf-8")
    if args.dry_run:
        print(issue.issue_title(digest.week))
        print(issue.issue_body(md, digest.week, issue.digest_file_url(path.with_suffix(".md")))[:2000])
        return 0
    result = issue.publish(md, digest.week, gh=os.environ.get("GH_BIN", "gh"),
                           file_url=issue.digest_file_url(path.with_suffix(".md")))
    print(f"{issue.issue_title(digest.week)}: {result}")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    from .publish import issue, notify
    cfg = _load_cfg(args.config)
    if cfg is None:
        return 2
    path = _digest_path(Path(args.out), args.week)
    if path is None:
        print("No digest found.", file=sys.stderr)
        return 2
    digest = Digest.model_validate_json(path.read_text(encoding="utf-8"))
    for channel, result in notify.run_all(cfg, digest, link=issue.digest_file_url(path.with_suffix(".md"))).items():
        print(f"{channel}: {result}")
    return 0


def cmd_site(args: argparse.Namespace) -> int:
    from .publish import site
    repo = os.environ.get("GITHUB_REPOSITORY")
    url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}" if repo else None
    index = site.build(Path(args.digests), Path(args.out), repo_url=url)
    print(f"Wrote {index}")
    return 0


# ---------------------------------------------------------------------------
# datasets: build a list from a catalogue dataset (companies only)
# ---------------------------------------------------------------------------

def cmd_bdns(args: argparse.Namespace) -> int:
    from .datasets import bdns
    client = PoliteClient()
    try:
        raw = bdns.fetch(client, since=args.since, until=args.until, text=args.text,
                         call_number=args.call, max_pages=args.max_pages)
        rows, dropped = bdns.company_only(raw)
    finally:
        client.close()
    path = bdns.export_csv(rows, Path(args.out))
    print(f"{len(rows)} company grant(s) written to {path}; {dropped} record(s) about individuals dropped.")
    print(bdns.ATTRIBUTION)
    return 0


# ---------------------------------------------------------------------------

def cmd_lint(args: argparse.Namespace) -> int:
    errors = lint(args.text, args.sentences)
    print("ok" if not errors else "\n".join(errors))
    return 1 if errors else 0


def cmd_schema(args: argparse.Namespace) -> int:
    path = ROOT / "schema" / "digest.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(Digest.model_json_schema(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="law-radar", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fetch and filter this week's texts and write the digest")
    r.add_argument("--config", help="path to icp.yaml (default: ./icp.yaml or the ICP_YAML env var)")
    r.add_argument("--no-ai", action="store_true",
                   help="keyword matches only, no model calls, no cost (the default weekly run)")
    r.add_argument("--since", type=_date, help="start of the window (YYYY-MM-DD)")
    r.add_argument("--until", type=_date, help="end of the window (YYYY-MM-DD), default today")
    r.add_argument("--today", type=_date, help=argparse.SUPPRESS)
    r.add_argument("--record", action="store_true", help="optional API mode: save the answers too")
    r.add_argument("--replay", metavar="DIR", help="use saved answers from DIR instead of calling a model")
    r.add_argument("--out", default=str(ROOT / "digests"), help="output folder for the digest files")
    r.add_argument("--state", default=str(ROOT / "state"), help="state folder (seen.json and friends)")
    r.add_argument("--dry-run", action="store_true", help="don't update state")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("digest-step", help="Claude Code path (/digest): write model requests or build the AI digest")
    d.add_argument("--week", help="ISO week, e.g. 2026-W40 (default: the latest matches file)")
    d.add_argument("--config", help="path to icp.yaml (default: ./icp.yaml or the ICP_YAML env var)")
    d.add_argument("--out", default=str(ROOT / "digests"))
    d.add_argument("--state", default=str(ROOT / "state"))
    d.add_argument("--work", default=str(ROOT / ".cache" / "claude"), help="request/answer folder (gitignored)")
    d.add_argument("--verbose", action="store_true")
    d.set_defaults(func=cmd_digest_step)

    rec = sub.add_parser("record-fixtures", help="write the golden-test answers (Claude Code by default)")
    rec.add_argument("--api", action="store_true", help="record through the optional Claude API instead")
    rec.add_argument("--scratch", default=str(ROOT / ".cache" / "record"))
    rec.set_defaults(func=cmd_record)

    iss = sub.add_parser("issue", help="open or update the weekly GitHub Issue (uses the gh CLI)")
    iss.add_argument("--week", help="ISO week, e.g. 2026-W40 (default: the latest digest)")
    iss.add_argument("--config")
    iss.add_argument("--out", default=str(ROOT / "digests"))
    iss.add_argument("--dry-run", action="store_true", help="print the title and body instead of calling gh")
    iss.set_defaults(func=cmd_issue)

    no = sub.add_parser("notify", help="send the digest to the optional channels switched on in the config")
    no.add_argument("--week")
    no.add_argument("--config")
    no.add_argument("--out", default=str(ROOT / "digests"))
    no.set_defaults(func=cmd_notify)

    si = sub.add_parser("site", help="build the static Pages table from digests/*.json")
    si.add_argument("--digests", default=str(ROOT / "digests"))
    si.add_argument("--out", default=str(ROOT / "site"))
    si.set_defaults(func=cmd_site)

    bd = sub.add_parser("bdns", help="Spain: grants awarded to companies (BDNS), as CSV. Individuals are dropped")
    bd.add_argument("--since", type=_date, help="grants awarded from this date (YYYY-MM-DD)")
    bd.add_argument("--until", type=_date)
    bd.add_argument("--text", help="words to search in the grant call's description")
    bd.add_argument("--call", help="BDNS call number (numeroConvocatoria)")
    bd.add_argument("--max-pages", type=int, default=5, help="pages of 50 records (default 5)")
    bd.add_argument("--out", default=str(ROOT / ".cache" / "lists" / "bdns.csv"))
    bd.set_defaults(func=cmd_bdns)

    li = sub.add_parser("lint", help="check a sentence against the writing rules")
    li.add_argument("text")
    li.add_argument("--sentences", type=int, default=None)
    li.set_defaults(func=cmd_lint)

    sc = sub.add_parser("schema", help="regenerate schema/digest.schema.json")
    sc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
