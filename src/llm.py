from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from .errors import LLMError
from .http_client import HttpClient
from .models import IPOAnalysis, IPOEvidence, NewsEvent, RHPSection


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LOGGER = logging.getLogger(__name__)


class OpenRouterAnalyst:
    def __init__(
        self,
        http: HttpClient,
        api_key: str,
        model: str,
        prompt_path: Path,
        temperature: float = 0.1,
        max_tokens: int = 8000,
        reasoning_effort: str | None = "none",
        reasoning_max_tokens: int | None = None,
    ) -> None:
        self.http = http
        self.api_key = api_key
        self.model = model
        self.prompt = prompt_path.read_text(encoding="utf-8")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.reasoning_max_tokens = reasoning_max_tokens

    def analyze(self, evidence: IPOEvidence) -> IPOAnalysis:
        llm_evidence = self._compact_evidence(evidence)
        request_body = self._request_body(llm_evidence, self.reasoning_effort)
        LOGGER.info(
            "OpenRouter analysis request: model=%s, max_tokens=%s, reasoning_effort=%s, reasoning_max_tokens=%s, sources=%s, rhp_sections=%s, financial_rows=%s, news_events=%s",
            self.model,
            self.max_tokens,
            self.reasoning_effort,
            self.reasoning_max_tokens,
            len(llm_evidence.sources),
            len(llm_evidence.rhp_sections),
            len(llm_evidence.financials),
            len(llm_evidence.news_events),
        )
        response = self._send(request_body)
        LOGGER.info("OpenRouter response received: status=%s", response.status_code)

        if (
            response.status_code == 400
            and self.reasoning_effort == "none"
            and "Reasoning is mandatory" in response.text
        ):
            LOGGER.warning("OpenRouter requires reasoning for this model; retrying with reasoning_effort=low")
            request_body = self._request_body(llm_evidence, "low")
            response = self._send(request_body)
            LOGGER.info("OpenRouter retry response received: status=%s", response.status_code)

        if response.status_code >= 400:
            detail = response.text[:1200]
            raise LLMError(
                f"OpenRouter returned HTTP {response.status_code}: {detail}"
            )

        try:
            return self._parse_response(response)
        except LLMError as exc:
            LOGGER.warning("OpenRouter response validation failed; retrying once with stricter JSON instruction: %s", exc)
            retry_body = self._request_body(llm_evidence, self.reasoning_effort)
            retry_body["messages"][1]["content"] = (
                self._build_user_message(llm_evidence)
                + "\n\nReturn a raw JSON object only. Do not return schema metadata, markdown, prose, arrays of schema blocks, or quoted JSON objects inside fields."
            )
            retry_response = self._send(retry_body)
            LOGGER.info("OpenRouter validation retry response received: status=%s", retry_response.status_code)
            if retry_response.status_code >= 400:
                detail = retry_response.text[:1200]
                raise LLMError(
                    f"OpenRouter validation retry returned HTTP {retry_response.status_code}: {detail}"
                ) from exc
            return self._parse_response(retry_response)

    def _parse_response(self, response) -> IPOAnalysis:
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            content = message.get("content")
            usage = payload.get("usage") or {}
            if usage:
                LOGGER.info(
                    "OpenRouter usage: prompt_tokens=%s, completion_tokens=%s, total_tokens=%s",
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    usage.get("total_tokens"),
                )
            if not content:
                finish_reason = payload["choices"][0].get("finish_reason")
                routed_model = payload.get("model", self.model)
                refusal = message.get("refusal")
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                detail_parts = [
                    f"model={routed_model}",
                    f"finish_reason={finish_reason}",
                ]
                if refusal:
                    detail_parts.append(f"refusal={str(refusal)[:300]}")
                if reasoning:
                    detail_parts.append(f"reasoning_preview={str(reasoning)[:300]}")
                raise LLMError(
                    "OpenRouter returned an empty analysis response ("
                    + "; ".join(detail_parts)
                    + ")"
                )
            if isinstance(content, str):
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as exc:
                    finish_reason = payload["choices"][0].get("finish_reason")
                    routed_model = payload.get("model", self.model)
                    preview = content[:500].replace("\n", " ")
                    raise LLMError(
                        "OpenRouter JSON response was invalid "
                        f"(model={routed_model}; finish_reason={finish_reason}; preview={preview})"
                    ) from exc
            else:
                data = content
            return IPOAnalysis.model_validate(data)
        except (KeyError, IndexError, ValidationError) as exc:
            raise LLMError(f"OpenRouter response failed strict validation: {exc}") from exc

    def _request_body(
        self,
        evidence: IPOEvidence,
        reasoning_effort: str | None,
    ) -> dict:
        schema = IPOAnalysis.model_json_schema()
        request_body = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.prompt,
                },
                {
                    "role": "user",
                    "content": self._build_user_message(evidence),
                },
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ipo_analysis",
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True},
            "plugins": [{"id": "response-healing"}],
        }
        if reasoning_effort or self.reasoning_max_tokens:
            request_body["reasoning"] = {
                "exclude": True,
            }
            if self.reasoning_max_tokens:
                request_body["reasoning"]["max_tokens"] = self.reasoning_max_tokens
            elif reasoning_effort:
                request_body["reasoning"]["effort"] = reasoning_effort
        return request_body

    def _send(self, request_body: dict):
        return self.http.request(
            "POST",
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": "Personal IPO Research Agent",
            },
            json=request_body,
        )

    @staticmethod
    def _compact_evidence(evidence: IPOEvidence) -> IPOEvidence:
        compact_sections = [
            RHPSection(
                id=section.id,
                title=section.title,
                text=section.text[:2500],
                start_page=section.start_page,
                end_page=section.end_page,
            )
            for section in evidence.rhp_sections[:8]
        ]
        compact_news = [
            NewsEvent(
                id=event.id,
                event_type=event.event_type,
                published_at=event.published_at,
                title=event.title,
                summary=event.summary[:500] if event.summary else None,
                source_name=event.source_name,
                source_url=event.source_url,
                materiality=event.materiality,
                score=event.score,
                source_ids=event.source_ids,
            )
            for event in evidence.news_events[:5]
        ]
        return evidence.model_copy(
            update={
                "rhp_sections": compact_sections,
                "news_events": compact_news,
                "warnings": [
                    *evidence.warnings,
                    "LLM received compact RHP excerpts after the first OpenRouter response hit its output length limit; the generated PDF still includes the full collected evidence appendix.",
                ],
            }
        )

    @staticmethod
    def _build_user_message(evidence: IPOEvidence) -> str:
        evidence_json = json.dumps(
            evidence.model_dump(mode="json", exclude={"ipo": {"raw_data"}}),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            "Analyze this IPO using ONLY the supplied evidence package. "
            "Do not browse, use model memory for current facts, or invent missing values. "
            "Use evidence_ids from RHP sections and sources whenever a section, risk, or red flag "
            "makes a material factual claim. If evidence is mixed, show the conflict. If evidence "
            "is missing, record it under data_gaps and lower confidence.\n\n"
            f"EVIDENCE_PACKAGE_JSON:\n{evidence_json}"
        )
