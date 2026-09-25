"""Where model answers come from. Four modes, one interface:

- exchange: the default AI path, at no API cost. Each request (system prompt, user message, JSON
            schema) is written to a file. Claude Code answers it by writing JSON to another file,
            and the next `law-radar digest-step` picks the answer up. Used by /digest and to
            record the golden fixtures.
- replay:   read saved answers only. CI runs in this mode.
- live:     call the Claude API. Optional, needs ANTHROPIC_API_KEY.
- record:   call the API and save each answer (optional, same key).

Whatever the source, every answer is validated against the same pydantic model, then goes
through the same citation validator and linter.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel

from .cost import CostTracker

T = TypeVar("T", bound=BaseModel)
PROMPTS = Path(__file__).resolve().parent / "prompts"
ROOT = Path(__file__).resolve().parent.parent
CLAUDE_CODE = "claude-code"
GENERATOR = {"exchange": "claude-code", "replay": "replay", "live": "api", "record": "api"}


class LLMError(Exception):
    """A model answer is unusable for this document."""


class MissingRecording(LLMError):
    """No saved answer for this request (replay), or the answer is still to be written (exchange)."""


class Pending(MissingRecording):
    """Exchange mode: a request file was written and is waiting for an answer."""


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def strict_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """JSON schema for structured outputs: no titles or defaults, every object closed and fully required."""
    schema = copy.deepcopy(model.model_json_schema())

    def fix(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                fix(item)
            return
        if not isinstance(node, dict):
            return
        node.pop("title", None)
        node.pop("default", None)
        if "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
            for sub in node["properties"].values():
                fix(sub)
        for key in ("items", "anyOf", "allOf", "oneOf"):
            if key in node:
                fix(node[key])
        for sub in node.get("$defs", {}).values():
            fix(sub)

    fix(schema)
    return schema


def request_hash(system: str, user: str, output: Type[BaseModel]) -> str:
    """Fingerprint of a request, stored with each answer so a stale recording is caught."""
    payload = json.dumps([system, user, strict_schema(output)], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:120]


def request_markdown(step: str, key: str, answer_path: Path, system: str, user: str,
                     output: Type[BaseModel], error: Optional[str] = None) -> str:
    fix_note = ""
    if error:
        fix_note = (f"\n**Your previous answer was rejected:** {error}\n"
                    "Write a corrected answer. This is the last attempt for this request.\n")
    return (
        f"# law-radar request: {step} for {key}\n\n"
        f"Answer this request as the model would. Follow the system prompt and the user message below.\n"
        f"Write only a JSON object that matches the schema at the end, to this file:\n\n"
        f"    {answer_path}\n\n"
        f"Do not read or change any other file.\n{fix_note}\n"
        f"## System prompt\n\n{system}\n\n"
        f"## User message\n\n{user}\n\n"
        f"## JSON schema for the answer\n\n```json\n{json.dumps(strict_schema(output), indent=1)}\n```\n"
    )


class LLM:
    def __init__(self, mode: str = "live", recordings: Optional[Path] = None,
                 tracker: Optional[CostTracker] = None, pending: Optional[Path] = None):
        if mode not in GENERATOR:
            raise ValueError(mode)
        self.mode = mode
        self.generator = GENERATOR[mode]
        self.recordings = recordings or ROOT / "tests" / "fixtures" / "recorded"
        self.pending = pending or (self.recordings.parent / "pending")
        self.tracker = tracker or CostTracker()
        self._client = None

    def _path(self, step: str, key: str) -> Path:
        return self.recordings / f"{step}__{slug(key)}.json"

    def structured(self, *, step: str, key: str, model: str, system: str, user: str,
                   output: Type[T], max_tokens: int = 16000, effort: Optional[str] = None) -> T:
        path = self._path(step, key)
        if self.mode in ("replay", "exchange"):
            return self._saved(step, key, path, system, user, output)

        data, usage = self._call(model=model, system=system, user=user, output=output,
                                 max_tokens=max_tokens, effort=effort)
        try:
            result = output.model_validate(data)
        except ValueError as exc:            # pydantic.ValidationError subclasses ValueError
            raise LLMError(f"output does not match the schema: {exc}") from exc
        if self.mode == "record":
            self._save(path, step, key, model, usage, data, request_hash(system, user, output))
        return result

    # -- saved answers (replay and exchange) ---------------------------------

    def _save(self, path: Path, step: str, key: str, model: str, usage: Dict[str, int], data: Any,
              req_hash: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"step": step, "key": key, "model": model, "request_sha256": req_hash,
                                    "usage": usage, "output": data}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    def _saved(self, step: str, key: str, path: Path, system: str, user: str, output: Type[T]) -> T:
        request = self.pending / f"{path.stem}.md"
        rejected = self.recordings / "rejected" / path.name
        if not path.exists():
            if self.mode == "replay":
                raise MissingRecording(f"no recording at {path}")
            if not request.exists():
                self._write_request(request, step, key, path, system, user, output)
            raise Pending(str(request))

        current = request_hash(system, user, output)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            wrapped = isinstance(saved, dict) and "output" in saved and "step" in saved
            if wrapped and saved.get("request_sha256", current) != current:
                if self.mode == "replay":
                    raise MissingRecording(f"stale recording {path}: the prompt or input changed since it was made")
                stale = self.recordings / "stale" / path.name       # exchange: ask again
                stale.parent.mkdir(parents=True, exist_ok=True)
                path.replace(stale)
                self._write_request(request, step, key, path, system, user, output)
                raise Pending(str(request))
            data = saved["output"] if wrapped else saved
            result = output.model_validate(data)
        except ValueError as exc:            # bad JSON or wrong shape
            if self.mode == "replay":
                raise LLMError(f"{path}: {exc}") from exc
            if rejected.exists():             # second bad answer: give up on this request
                raise LLMError(f"{path}: rejected twice: {exc}") from exc
            rejected.parent.mkdir(parents=True, exist_ok=True)
            path.replace(rejected)
            self._write_request(request, step, key, path, system, user, output, error=str(exc)[:2000])
            raise Pending(str(request)) from exc

        if self.mode == "exchange":
            if not wrapped:                   # store in the same format as API recordings
                self._save(path, step, key, CLAUDE_CODE, {}, data, current)
            if request.exists():
                request.unlink()
        else:
            self.tracker.add(saved.get("model", CLAUDE_CODE) if wrapped else CLAUDE_CODE,
                             saved.get("usage", {}) if wrapped else {})
        return result

    def _write_request(self, request: Path, step: str, key: str, answer: Path, system: str, user: str,
                       output: Type[BaseModel], error: Optional[str] = None) -> None:
        request.parent.mkdir(parents=True, exist_ok=True)
        answer.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(request_markdown(step, key, answer.resolve(), system, user, output, error),
                           encoding="utf-8")

    # -- Claude API (optional) ----------------------------------------------

    def _api(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _call(self, *, model: str, system: str, user: str, output: Type[BaseModel],
              max_tokens: int, effort: Optional[str]):
        import anthropic

        output_config: Dict[str, Any] = {"format": {"type": "json_schema", "schema": strict_schema(output)}}
        if effort:
            output_config["effort"] = effort
        try:
            resp = self._api().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
            )
        except anthropic.AuthenticationError as exc:
            raise SystemExit(f"Anthropic API key rejected: {exc.message}") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"bad request: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"rate limited: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"connection error: {exc}") from exc

        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        }
        self.tracker.add(model, usage)        # billed even when the output is unusable
        if resp.stop_reason == "refusal":
            raise LLMError("model declined the request")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"output cut off at max_tokens={max_tokens}")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMError("no text block in the response")
        try:
            return json.loads(text), usage
        except json.JSONDecodeError as exc:
            raise LLMError(f"invalid JSON: {exc}") from exc
