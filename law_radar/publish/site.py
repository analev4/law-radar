"""Static GitHub Pages table built from digests/*.json. No framework: one HTML file plus the data.

One row per law, the latest digest wins. Default order: laws with a forcing mechanism first, then
next deadline (soonest first, none last), then scorecard points.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
from typing import Dict, List, Optional

from ..models import Digest, Entry, NoAiEntry


def _row_from_entry(e: Entry, week: str) -> dict:
    sc = e.scorecard
    recipe = e.list_recipes[0] if e.list_recipes else None
    last = e.when.deadlines[-1].date if e.when.deadlines else None
    return {
        "id": e.id, "week": week, "read": True, "market": e.market, "doc_type": e.doc_type,
        "title": e.title_original, "headline": e.headline.text, "who": e.who.text, "url": e.url,
        "published": e.published.isoformat(),
        "next_deadline": e.when.next_deadline.isoformat() if e.when.next_deadline else None,
        "last_deadline": last.isoformat() if last else None,
        "points": sc.points if sc else None, "max_points": sc.max_points if sc else None,
        "sinks": bool(sc and sc.sinks),
        "recipe": (f"{recipe.dataset_name}: {recipe.filter}. Number: {recipe.metric}."
                   + (" Weak signal." if recipe.signal_strength == "weak" else "")) if recipe else None,
        "confidence": e.confidence.level,
    }


def _row_from_match(e: NoAiEntry, week: str) -> dict:
    return {
        "id": e.id, "week": week, "read": False, "market": e.market, "doc_type": e.doc_type,
        "title": e.title_original, "headline": None, "who": None, "url": e.url,
        "published": e.published.isoformat(), "next_deadline": None, "last_deadline": None,
        "points": None, "max_points": None, "sinks": False, "recipe": None, "confidence": None,
    }


def collect_rows(digest_dir: Path) -> List[dict]:
    rows: Dict[str, dict] = {}
    for path in sorted(digest_dir.glob("*.json")):
        if path.name.endswith(".matches.json"):
            continue
        digest = Digest.model_validate_json(path.read_text(encoding="utf-8"))
        for e in digest.entries:
            row = _row_from_entry(e, digest.week) if isinstance(e, Entry) else _row_from_match(e, digest.week)
            old = rows.get(row["id"])
            if old is None or row["read"] or not old["read"]:   # a read entry is never replaced by a bare match
                rows[row["id"]] = row
    return sorted(rows.values(), key=sort_key)


def sort_key(r: dict) -> tuple:
    return (not r["read"], r["sinks"], r["next_deadline"] is None, r["next_deadline"] or "9999",
            -(r["points"] or 0), r["id"])


def _deadline_cell(r: dict) -> str:
    if r["next_deadline"]:
        return f'<time datetime="{r["next_deadline"]}">{_fmt(r["next_deadline"])}</time>'
    if r["last_deadline"]:
        return f'<span class="muted">passed {_fmt(r["last_deadline"])}</span>'
    return '<span class="muted">none in the text</span>'


def _fmt(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


def render(rows: List[dict], generated: dt.date, repo_url: Optional[str] = None) -> str:
    esc = html.escape
    body = []
    for r in rows:
        if r["read"]:
            law = (f'<a href="{esc(r["url"])}">{esc(r["headline"] or r["title"])}</a>'
                   f'<div class="sub">{esc(r["doc_type"])} · {esc(r["title"][:140])}</div>')
            score = (f'{r["points"]}/{r["max_points"]}' + (' <span class="muted">no forcing mechanism</span>'
                                                           if r["sinks"] else "")) if r["points"] is not None else ""
            who = esc(r["who"] or "")
            recipe = esc(r["recipe"] or "")
        else:
            law = (f'<a href="{esc(r["url"])}">{esc(r["title"][:160])}</a>'
                   f'<div class="sub">{esc(r["doc_type"])} · keyword match, not read yet</div>')
            score, who, recipe = '<span class="muted">not read</span>', "", ""
        body.append(
            f'<tr data-market="{esc(r["market"])}" data-read="{"1" if r["read"] else "0"}">'
            f'<td class="mk" data-label="Market">{esc(r["market"])}</td><td class="law" data-label="Law">{law}</td>'
            f'<td data-label="Who is affected">{who}</td>'
            f'<td class="nowrap" data-label="Next deadline" data-sort="{r["next_deadline"] or r["last_deadline"] or ""}">'
            f'{_deadline_cell(r)}</td>'
            f'<td class="nowrap" data-label="Score" data-sort="{r["points"] if r["points"] is not None else -1}">{score}</td>'
            f'<td data-label="Top list recipe">{recipe}</td>'
            f'<td class="nowrap" data-label="Source"><a href="{esc(r["url"])}">source</a></td></tr>'
        )
    markets = sorted({r["market"] for r in rows})
    options = "".join(f'<option value="{esc(m)}">{esc(m)}</option>' for m in markets)
    repo = f' · <a href="{esc(repo_url)}">repository</a>' if repo_url else ""
    return TEMPLATE.format(rows="\n".join(body) or '<tr><td colspan="7" class="muted">No laws flagged yet.</td></tr>',
                           count=sum(1 for r in rows if r["read"]), matches=sum(1 for r in rows if not r["read"]),
                           generated=_fmt(generated.isoformat()), options=options, repo=repo)


def build(digest_dir: Path, out_dir: Path, today: Optional[dt.date] = None,
          repo_url: Optional[str] = None) -> Path:
    rows = collect_rows(digest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "laws.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    index = out_dir / "index.html"
    index.write_text(render(rows, today or dt.date.today(), repo_url), encoding="utf-8")
    return index


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Law radar</title>
<style>
:root {{ --bg:#fbfbf9; --fg:#1d1d1b; --muted:#6b6b66; --line:#e3e2dc; --accent:#1f5f8b; --head:#f1f0ea; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#161614; --fg:#ecebe6; --muted:#9a9993; --line:#2e2d29; --accent:#7fb4dc; --head:#201f1c; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
p.lede {{ margin:0 0 16px; color:var(--muted); }}
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin:0 0 12px; }}
.controls input, .controls select {{ font:inherit; padding:6px 8px; border:1px solid var(--line); background:var(--bg); color:var(--fg); border-radius:6px; }}
.controls input {{ flex:1 1 220px; min-width:0; }}
.wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; }}
table {{ border-collapse:collapse; width:100%; min-width:860px; }}
th, td {{ text-align:left; vertical-align:top; padding:10px 12px; border-bottom:1px solid var(--line); }}
th {{ background:var(--head); font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap; position:sticky; top:0; }}
th[aria-sort] {{ color:var(--accent); }}
tr:last-child td {{ border-bottom:0; }}
td.law {{ min-width:260px; }}
td.mk {{ font-weight:600; }}
.sub {{ color:var(--muted); font-size:13px; margin-top:2px; }}
.muted {{ color:var(--muted); }}
.nowrap {{ white-space:nowrap; }}
a {{ color:var(--accent); }}
footer {{ color:var(--muted); font-size:13px; margin-top:16px; }}
@media (max-width: 720px) {{
  table {{ min-width:0; }}
  thead {{ display:none; }}
  table, tbody, tr, td {{ display:block; width:100%; }}
  tr {{ border-bottom:1px solid var(--line); padding:6px 0; }}
  tr:last-child {{ border-bottom:0; }}
  td {{ border:0; padding:4px 12px; white-space:normal; }}
  td:empty {{ display:none; }}
  td::before {{ content:attr(data-label); display:block; font-size:12px; color:var(--muted); }}
  td.law::before, td.mk::before {{ display:none; }}
  .wrap {{ overflow:visible; }}
}}
</style>
</head>
<body>
<main>
<h1>Law radar</h1>
<p class="lede">{count} laws read and cited, {matches} keyword matches not read yet. Updated {generated}{repo}.</p>
<div class="controls">
  <input id="q" type="search" placeholder="Filter by any word" aria-label="Filter">
  <select id="market" aria-label="Market"><option value="">All markets</option>{options}</select>
  <select id="read" aria-label="Status"><option value="">Read and not read</option><option value="1">Read only</option><option value="0">Not read only</option></select>
</div>
<div class="wrap">
<table id="laws">
<thead><tr><th>Market</th><th>Law</th><th>Who is affected</th><th>Next deadline</th><th>Score</th><th>Top list recipe (hypothesis)</th><th>Source</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<footer>Not legal advice. law-radar flags and summarises official texts. Read the source before acting.
Sources: EUR-Lex / Publications Office of the EU (CC BY 4.0); DILA, Journal officiel (Licence Ouverte 2.0);
Basado en datos de la Agencia Estatal Boletín Oficial del Estado.</footer>
</main>
<script>
(function () {{
  var q = document.getElementById("q"), market = document.getElementById("market"), read = document.getElementById("read");
  var tbody = document.querySelector("#laws tbody");
  function apply() {{
    var term = q.value.toLowerCase();
    Array.prototype.forEach.call(tbody.rows, function (tr) {{
      var ok = (!term || tr.textContent.toLowerCase().indexOf(term) !== -1)
        && (!market.value || tr.dataset.market === market.value)
        && (!read.value || tr.dataset.read === read.value);
      tr.hidden = !ok;
    }});
  }}
  [q, market, read].forEach(function (el) {{ el.addEventListener("input", apply); }});
  document.querySelectorAll("#laws th").forEach(function (th, i) {{
    th.addEventListener("click", function () {{
      var asc = th.getAttribute("aria-sort") !== "ascending";
      document.querySelectorAll("#laws th").forEach(function (h) {{ h.removeAttribute("aria-sort"); }});
      th.setAttribute("aria-sort", asc ? "ascending" : "descending");
      var rows = Array.prototype.slice.call(tbody.rows);
      rows.sort(function (a, b) {{
        var x = a.cells[i].dataset.sort !== undefined ? a.cells[i].dataset.sort : a.cells[i].textContent;
        var y = b.cells[i].dataset.sort !== undefined ? b.cells[i].dataset.sort : b.cells[i].textContent;
        var nx = parseFloat(x), ny = parseFloat(y);
        var c = (!isNaN(nx) && !isNaN(ny) && String(nx) === x && String(ny) === y) ? nx - ny : String(x).localeCompare(String(y));
        return asc ? c : -c;
      }});
      rows.forEach(function (r) {{ tbody.appendChild(r); }});
    }});
  }});
}})();
</script>
</body>
</html>
"""
