"""Generate grounded Korean editorial summaries with Groq's free API tier."""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "qwen/qwen3.8-27b"
CATEGORIES = (
    "AI/에이전트",
    "데이터 플랫폼",
    "국방/공공",
    "산업 적용",
    "엔지니어링",
    "보안/거버넌스",
    "기업/파트너십",
)


def build_prompt(article: dict[str, Any]) -> str:
    """Build a compact, source-grounded prompt for one article."""
    body = str(article.get("body", ""))[:14000]
    return f"""너는 Palantir 기술 및 산업 콘텐츠 전문 에디터다.
아래 공식 Palantir Blog 원문만 근거로 한국어 아카이브 항목을 작성하라.
원문에 없는 숫자, 제품 기능, 성과, 해석을 만들지 마라.

제목: {article.get('title', '')}
발행일: {article.get('published_at', '')}
원문 설명: {article.get('description', '')}
원문 본문:
{body}

JSON 객체 하나만 반환하라:
{{
  "title_ko": "자연스럽고 사실적인 한국어 제목",
  "summary": "핵심 사실과 의미를 3~4문장으로 설명",
  "easy_explainer": "비전문가도 이해할 수 있는 쉬운 설명 1~2문장",
  "category": "{('|'.join(CATEGORIES))} 중 하나",
  "importance": 1부터 10 사이 정수
}}
"""


def summarize(article: dict[str, Any], api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Analyze one article through Groq's OpenAI-compatible endpoint."""
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    response = client.chat.completions.create(
        model=model or os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        messages=[{"role": "user", "content": build_prompt(article)}],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=900,
    )
    result = json.loads(response.choices[0].message.content or "{}")
    required = {"title_ko", "summary", "easy_explainer", "category", "importance"}
    if not required.issubset(result):
        raise ValueError(f"Incomplete analysis response: {required - set(result)}")
    result["importance"] = max(1, min(10, int(result["importance"])))
    return result

