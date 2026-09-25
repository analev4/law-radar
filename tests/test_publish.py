"""Issue, Pages table and optional channels. No network: gh, HTTP and SMTP are faked."""
import datetime as dt
import json
import subprocess

from law_radar.config import ROOT, load_config
from law_radar.fixtures import GOLDEN_TODAY, golden_sources
from law_radar.llm import LLM
from law_radar.models import Digest, NoAiEntry, Window, IcpRef
from law_radar.pipeline import run_pipeline
from law_radar.publish import issue, notify, site
from law_radar.publish.files import write
from law_radar.publish.markdown import render
from law_radar.state import State

RECORDED = ROOT / "tests" / "fixtures" / "recorded"


def golden_digest(cfg, datasets, tmp_path) -> Digest:
    return run_pipeline(cfg, golden_sources(), State(tmp_path / "s"), today=GOLDEN_TODAY,
                        since=GOLDEN_TODAY - dt.timedelta(days=7), until=GOLDEN_TODAY, datasets=datasets,
                        llm=LLM(mode="replay", recordings=RECORDED), log=lambda _: None)


def match_digest(week="2026-W41") -> Digest:
    return Digest(week=week, window=Window(since="2026-09-28", until="2026-10-05"), mode="no-ai",
                  icp=IcpRef(name="Ledgerly", config_sha256="x"), nothing_relevant=False,
                  entries=[NoAiEntry(id="fr:JORFTEXT1", market="FR", doc_type="Arrêté",
                                     title_original="Arrêté relatif aux cotisations", published="2026-10-02",
                                     url="https://www.legifrance.gouv.fr/jorf/id/JORFTEXT1",
                                     matched_keywords=["cotisation*"])])


# -- Pages -------------------------------------------------------------------

def test_site_table(cfg, datasets, tmp_path):
    out = tmp_path / "digests"
    write(golden_digest(cfg, datasets, tmp_path), out)
    write(match_digest(), out)
    index = site.build(out, tmp_path / "site", today=dt.date(2026, 10, 5))
    page = index.read_text()
    rows = json.loads((tmp_path / "site" / "laws.json").read_text())
    assert [r["id"] for r in rows][:3] == ["fr:JORFTEXT000053634597", "eu:32023L0970", "es:BOE-A-2026-3815"]
    assert rows[-1]["id"] == "fr:JORFTEXT1" and rows[-1]["read"] is False       # not-read matches last
    for header in ("Market", "Law", "Who is affected", "Next deadline", "Score", "Top list recipe", "Source"):
        assert header in page
    assert "not read yet" in page and "Not legal advice" in page
    assert "<script" in page and "http" not in page.split("<script")[1].split("</script>")[0]   # no external JS


def test_site_escapes_html(tmp_path):
    d = match_digest()
    d.entries[0].title_original = '<img src=x onerror="alert(1)">'
    write(d, tmp_path / "digests")
    page = site.build(tmp_path / "digests", tmp_path / "site").read_text()
    assert "<img src=x" not in page and "&lt;img" in page


# -- Issue -------------------------------------------------------------------

class FakeGh:
    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing or []

    def __call__(self, cmd, input=None, capture_output=True, text=True, check=True):
        self.calls.append((cmd[1:], input))
        out = json.dumps(self.existing) if cmd[1:3] == ["issue", "list"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


def test_issue_is_created_then_updated():
    gh = FakeGh()
    assert issue.publish("# Law radar: week 40\n", "2026-W40", runner=gh) == "created"
    create = next(c for c in gh.calls if c[0][:2] == ["issue", "create"])
    assert create[0][create[0].index("--title") + 1] == "Law radar: week 40"
    assert create[1].startswith("<!-- law-radar:2026-W40 -->")

    gh = FakeGh(existing=[{"number": 7, "body": "<!-- law-radar:2026-W40 -->\nold"},
                          {"number": 3, "body": "<!-- law-radar:2025-W40 -->\nlast year"}])
    assert issue.publish("# new body\n", "2026-W40", runner=gh) == "updated"
    edit = next(c for c in gh.calls if c[0][:2] == ["issue", "edit"])
    assert edit[0][2] == "7" and "new body" in edit[1]


def test_long_digest_is_cut_at_an_entry():
    md = "# Law radar: week 40\n" + "".join(f"\n---\n\n### Law {i}\n" + "x" * 5000 for i in range(20))
    body = issue.issue_body(md, "2026-W40", file_url="https://github.com/o/r/blob/main/digests/2026-40.md")
    assert len(body) <= issue.GITHUB_BODY_LIMIT
    assert body.endswith("[Read the full digest](https://github.com/o/r/blob/main/digests/2026-40.md).*")
    assert "\n---\n\n### Law" in body and body.count("### Law") < 20


# -- Optional channels -------------------------------------------------------

def test_channels_are_off_by_default(cfg):
    assert notify.run_all(cfg, match_digest(), env={}) == {"slack": "off", "email": "off", "notion": "off"}


def test_enabled_channel_without_secrets_is_skipped(cfg):
    cfg = cfg.model_copy(deep=True)
    cfg.delivery.slack.enabled = True
    assert notify.run_all(cfg, match_digest(), env={})["slack"].startswith("skipped")


def test_slack_payload():
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

    def post(url, json, timeout):
        sent.update(url=url, body=json)
        return Resp()

    assert notify.slack(match_digest(), {"SLACK_WEBHOOK_URL": "https://hooks.example/x"}, post=post) == "sent"
    assert sent["url"] == "https://hooks.example/x"
    assert sent["body"]["text"].startswith("Law radar: week 41: 1 law.")
    assert "Not legal advice" in sent["body"]["text"]


def test_email_message():
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append(("tls",))

        def login(self, user, pw):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(("send", msg["Subject"], msg["To"], msg.get_content()))

    env = {"SMTP_HOST": "smtp.example", "SMTP_USER": "bot@example", "SMTP_PASSWORD": "pw", "MAIL_TO": "a@x, b@y"}
    assert notify.email(match_digest(), env, smtp_factory=FakeSMTP) == "sent"
    assert sent[0] == ("connect", "smtp.example", 587) and ("tls",) in sent
    subject, to, content = sent[-1][1:]
    assert subject == "Law radar: week 41" and to == "a@x, b@y" and "Not legal advice" in content


def test_notion_skips_existing_rows(cfg, datasets, tmp_path):
    import httpx
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body))
        if request.url.path.endswith("/query"):
            exists = body["filter"]["rich_text"]["equals"] == "eu:32023L0970"
            return httpx.Response(200, json={"results": [{}] if exists else []})
        return httpx.Response(200, json={"id": "page"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    digest = golden_digest(cfg, datasets, tmp_path)
    result = notify.notion(digest, {"NOTION_TOKEN": "t", "NOTION_DATABASE_ID": "db"}, client=client)
    assert result == "sent: 2 new row(s)"
    created = [b for p, b in seen if p == "/v1/pages"]
    assert {c["properties"]["Law ID"]["rich_text"][0]["text"]["content"] for c in created} == {
        "fr:JORFTEXT000053634597", "es:BOE-A-2026-3815"}
