"""Generate grounded Korean editorial summaries with Groq's free API tier."""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "qwen/qwen3.8-27b"
ANALYSIS_VERSION = 2
CATEGORIES = (
    "AI/에이전트",
    "데이터 플랫폼",
    "국방/공공",
    "산업 적용",
    "엔지니어링",
    "보안/거버넌스",
    "기업/파트너십",
)
UNREADABLE_SUMMARY_MARKERS = (
    "CAPTCHA",
    "보안 인증 페이지",
    "보안 검증 페이지",
    "원문 본문",
)


def validate_analysis(article: dict[str, Any], result: dict[str, Any]) -> None:
    """Keep thin or source-blocked output out of the published archive."""
    summary = str(result.get("summary", "")).strip()
    easy = str(result.get("easy_explainer", "")).strip()
    body_length = len(str(article.get("body", "")).strip())
    if not summary or not easy or result.get("category") not in CATEGORIES:
        raise ValueError("Analysis is missing required Korean content or category")
    if body_length >= 1500 and len(summary) < 220:
        raise ValueError("Summary is too thin for the available source article")
    if any(marker in text for text in (summary, easy) for marker in UNREADABLE_SUMMARY_MARKERS):
        raise ValueError("Summary describes a blocked page instead of the article")


def build_prompt(article: dict[str, Any]) -> str:
    """Build a source-grounded prompt that preserves the article's concrete details."""
    body = str(article.get("body", ""))
    if len(body) > 18000:
        body = body[:12000] + "\n[중간 부분 생략]\n" + body[-6000:]
    return f"""너는 Palantir 기술 및 산업 콘텐츠 전문 에디터다.
아래 공식 Palantir Blog 원문만 근거로 한국어 아카이브 항목을 작성하라.
독자는 '무엇을 발표했나'보다 '어떤 문제를 어떤 방식으로 풀었나'를 알고 싶어 한다.

요약 작성 기준:
- 원문의 핵심 메커니즘이나 업무 흐름을 구체적으로 설명하라. 제품명과 장점만 나열하지 마라.
- 원문에 있는 사례, 입력 데이터, 처리 단계, 사용 주체, 수치 중 중요한 것을 골라 포함하라.
- 실측 성과와 계획/예상 효과를 구별하라. 수치가 없으면 성과를 정량화하거나 달성했다고 쓰지 마라.
- 기술적 제약, 아직 검증되지 않은 부분, 다음 단계가 중요하면 함께 적어라.
- 원문에 없는 숫자, 제품 기능, 성과, 해석을 만들지 마라. 정보가 부족하면 부족한 범위만 설명하라.
- '혁신', '극대화', '변혁' 같은 홍보 문구와 '이 글은 ~를 다룹니다' 같은 메타 설명을 피하라.
- 요약은 서로 다른 사실을 담은 5~7문장으로 작성하되, 짧은 원문을 억지로 늘리지 마라.
- 쉬운 설명은 추상적 비유 대신 원문의 실제 사례를 일상어로 풀어라. 요약에 없는 성과를 덧붙이지 마라.

제목: {article.get('title', '')}
발행일: {article.get('published_at', '')}
원문 설명: {article.get('description', '')}
원문 본문:
{body}

JSON 객체 하나만 반환하라:
{{
  "title_ko": "자연스럽고 사실적인 한국어 제목",
  "summary": "문제, 작동 방식, 원문 사례와 근거, 확인된 결과 또는 남은 과제를 담은 한국어 요약",
  "easy_explainer": "원문의 실제 사례를 바탕으로 비전문가도 이해할 수 있게 쓴 1~2문장",
  "category": "{('|'.join(CATEGORIES))} 중 하나",
  "importance": 1부터 10 사이 정수
}}
"""


def summarize(article: dict[str, Any], api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Analyze one article through Groq's OpenAI-compatible endpoint."""
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", max_retries=0)
    response = client.chat.completions.create(
        model=model or os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        messages=[{"role": "user", "content": build_prompt(article)}],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1400,
    )
    result = json.loads(response.choices[0].message.content or "{}")
    required = {"title_ko", "summary", "easy_explainer", "category", "importance"}
    if not required.issubset(result):
        raise ValueError(f"Incomplete analysis response: {required - set(result)}")
    result["importance"] = max(1, min(10, int(result["importance"])))
    validate_analysis(article, result)
    return result
