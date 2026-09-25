"""Exchange mode: requests go to files, answers come back as files, the same checks apply."""
import json

import pytest

from law_radar.llm import LLM, LLMError, Pending
from law_radar.models import FilterOutput


def ask(llm):
    return llm.structured(step="filter", key="eu:TEST", model="m", system="SYSTEM TEXT", user="USER TEXT",
                          output=FilterOutput)


def test_request_file_then_answer(tmp_path):
    llm = LLM(mode="exchange", recordings=tmp_path / "responses", pending=tmp_path / "pending")
    with pytest.raises(Pending) as exc:
        ask(llm)
    request = tmp_path / "pending" / "filter__eu_TEST.md"
    assert str(request) in str(exc.value)
    body = request.read_text()
    assert "SYSTEM TEXT" in body and "USER TEXT" in body and '"relevant"' in body
    answer = tmp_path / "responses" / "filter__eu_TEST.json"
    assert str(answer.resolve()) in body

    answer.write_text(json.dumps({"relevant": False, "reason": "The text sets fishing quotas only."}))
    result = ask(llm)
    assert result.relevant is False
    saved = json.loads(answer.read_text())
    assert saved["model"] == "claude-code" and saved["output"]["relevant"] is False   # stored like a recording
    assert not request.exists()
    assert LLM(mode="replay", recordings=tmp_path / "responses").generator == "replay"
    assert ask(LLM(mode="replay", recordings=tmp_path / "responses")).relevant is False


def test_malformed_answer_gets_one_retry(tmp_path):
    llm = LLM(mode="exchange", recordings=tmp_path / "responses", pending=tmp_path / "pending")
    answer = tmp_path / "responses" / "filter__eu_TEST.json"
    answer.parent.mkdir(parents=True)
    answer.write_text('{"relevant": "maybe"}')
    with pytest.raises(Pending):
        ask(llm)
    request = (tmp_path / "pending" / "filter__eu_TEST.md").read_text()
    assert "previous answer was rejected" in request
    answer.write_text("not json")
    with pytest.raises(LLMError) as exc:
        ask(llm)
    assert not isinstance(exc.value, Pending) and "rejected twice" in str(exc.value)


def test_replay_never_writes_requests(tmp_path):
    llm = LLM(mode="replay", recordings=tmp_path / "responses", pending=tmp_path / "pending")
    with pytest.raises(LLMError):
        ask(llm)
    assert not (tmp_path / "pending").exists()


def test_stale_recording_is_caught(tmp_path):
    llm = LLM(mode="exchange", recordings=tmp_path / "responses", pending=tmp_path / "pending")
    with pytest.raises(Pending):
        ask(llm)
    (tmp_path / "responses" / "filter__eu_TEST.json").write_text(json.dumps({"relevant": True, "reason": "x"}))
    ask(llm)                                                    # accepted and fingerprinted
    changed = lambda m: m.structured(step="filter", key="eu:TEST", model="m", system="NEW PROMPT",
                                     user="USER TEXT", output=FilterOutput)
    with pytest.raises(LLMError) as exc:
        changed(LLM(mode="replay", recordings=tmp_path / "responses"))
    assert "stale" in str(exc.value)
    with pytest.raises(Pending):                                # exchange mode asks again
        changed(llm)
    assert (tmp_path / "responses" / "stale" / "filter__eu_TEST.json").exists()
