"""Generate grounded Korean editorial summaries with Groq's free API tier."""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "qwen/qwen3.8-27b"
ANALYSIS_VERSION = 4
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
    visible_text = [str(result.get("title_ko", "")), summary, easy]
    points = result.get("key_points")
    if points is not None and (not isinstance(points, list) or not 2 <= len(points) <= 5 or any(not isinstance(point, str) or len(point.strip()) < 20 for point in points)):
        raise ValueError("Key points must contain 2-5 substantive Korean facts")
    newsletter = result.get("newsletter")
    if newsletter is not None:
        visible_text.append(json.dumps(newsletter, ensure_ascii=False))
        if not isinstance(newsletter, dict) or len(str(newsletter.get("dek", "")).strip()) < 20:
            raise ValueError("Newsletter is missing its subtitle")
        lead = newsletter.get("lead")
        sections = newsletter.get("sections")
        if not isinstance(lead, list) or len(lead) != 2 or any(not isinstance(p, str) or len(p.strip()) < 40 for p in lead):
            raise ValueError("Newsletter needs two substantive lead paragraphs")
        if not isinstance(sections, list) or not 2 <= len(sections) <= 5:
            raise ValueError("Newsletter needs 2-5 sections")
        for section in sections:
            paragraphs = section.get("paragraphs") if isinstance(section, dict) else None
            if not isinstance(section, dict) or len(str(section.get("heading", "")).strip()) < 8 or not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 3 or any(not isinstance(p, str) or len(p.strip()) < 40 for p in paragraphs):
                raise ValueError("Newsletter section is missing a specific heading or supporting detail")
            source_heading = section.get("source_heading") or ""
            if source_heading and source_heading not in (article.get("source_headings") or []):
                raise ValueError("Newsletter references an unknown source heading")
        if len(str(newsletter.get("closing", "")).strip()) < 40:
            raise ValueError("Newsletter needs a grounded closing paragraph")
        highlights = newsletter.get("highlights")
        paragraphs = lead + [paragraph for section in sections for paragraph in section["paragraphs"]] + [newsletter["closing"]]
        if not isinstance(highlights, list) or not 2 <= len(highlights) <= 3 or any(
            not isinstance(sentence, str)
            or not 30 <= len(sentence.strip()) <= 180
            or not sentence.strip().endswith((".", "?", "!"))
            or not any(sentence in paragraph for paragraph in paragraphs)
            for sentence in highlights
        ) or len(set(highlights)) != len(highlights):
            raise ValueError("Highlights must repeat 2-3 distinct sentences from the newsletter")
        newsletter_length = sum(len(p) for p in lead) + sum(len(p) for section in sections for p in section["paragraphs"]) + len(newsletter["closing"])
        if body_length >= 1500 and newsletter_length < 800:
            raise ValueError("Newsletter is too thin for the available source article")
        if any(marker in json.dumps(newsletter, ensure_ascii=False) for marker in UNREADABLE_SUMMARY_MARKERS):
            raise ValueError("Newsletter describes a blocked page instead of the article")
    if any("원문" in text for text in visible_text):
        raise ValueError("Reader-facing copy must describe Palantir directly")


def build_prompt(article: dict[str, Any]) -> str:
    """Build a source-grounded prompt that preserves the article's concrete details."""
    body = str(article.get("body", ""))
    if len(body) > 18000:
        body = body[:12000] + "\n[중간 부분 생략]\n" + body[-6000:]
    return f"""너는 Palantir 기술 및 산업 콘텐츠 전문 에디터다.
아래 Palantir 공식 블로그 글만 근거로 한국어 아카이브 항목을 작성하라.
독자는 '무엇을 발표했나'보다 '어떤 문제를 어떤 방식으로 풀었나'를 알고 싶어 한다.

요약 작성 기준:
- Palantir가 설명한 핵심 메커니즘이나 업무 흐름을 구체적으로 설명하라. 제품명과 장점만 나열하지 마라.
- 글에 있는 사례, 입력 데이터, 처리 단계, 사용 주체, 수치 중 중요한 것을 골라 포함하라.
- 실측 성과와 계획/예상 효과를 구별하라. 수치가 없으면 성과를 정량화하거나 달성했다고 쓰지 마라.
- 기술적 제약, 아직 검증되지 않은 부분, 다음 단계가 중요하면 함께 적어라.
- Palantir가 제시하지 않은 숫자, 제품 기능, 성과, 해석을 만들지 마라. 정보가 부족하면 부족한 범위만 설명하라.
- 독자가 바로 내용을 이해하게 써라. '원문', '이 글은', '기사에서는'처럼 글 자체를 설명하는 표현 대신 'Palantir는' 등 실제 주체와 행동을 밝혀라.
- '혁신', '극대화', '변혁' 같은 홍보 문구와 '이 글은 ~를 다룹니다' 같은 메타 설명을 피하라.
- 요약은 서로 다른 사실을 담은 5~7문장으로 작성하되, 짧은 발표를 억지로 늘리지 마라.
- 쉬운 설명은 추상적 비유 대신 Palantir가 소개한 사례를 일상어로 풀어라. 요약에 없는 성과를 덧붙이지 마라.
- 뉴스레터 본문은 도입 2문단, 구체적 소제목 2~5개와 각각 1~3문단, 마무리 1문단으로 쓴다.
- 제목은 근거가 있을 때 질문형이나 대비형으로 쓰고, 부제는 무엇을 어떻게 살피는지 한 문장으로 적는다.
- 도입 첫 문단에서 실제 문제나 장면을 제시하고, 둘째 문단에서 이 글의 핵심 질문과 취재 출처를 밝힌다.
- 소제목에는 그 절에서 설명할 내용이 드러나야 한다. '핵심 기술', '의미와 전망' 같은 빈 제목을 피하라.
- 기술 용어 옆에는 쉬운 풀이를 붙이고, 메커니즘과 Palantir가 소개한 사례를 문단으로 연결한다. 목록만 나열하지 마라.
- 마무리는 검증된 의미와 아직 확인되지 않은 범위를 구분한다. 근거 없이 미래 성과를 예언하지 마라.
- 본문에서 노란색으로 강조할 핵심 문장 2~3개를 고른다. 별도의 상단 강조 목록은 만들지 않는다. 반드시 네가 쓴 도입·본문·마무리에 이미 등장한 완전한 문장을 글자 하나 바꾸지 말고 그대로 복사하라. 새로운 주장을 추가하지 마라.
- Palantir 글이 인터뷰가 아니면 문답, 직접 인용, 가상의 인물을 만들지 마라. 글을 길게 번역하거나 베끼지 말고 독자적인 한국어 해설로 재구성하라.
- 이미지의 내용을 보지 못했으므로 이미지를 해석하지 마라. source_heading은 아래 제공된 소제목과 정확히 일치할 때만 넣어라.

제목: {article.get('title', '')}
발행일: {article.get('published_at', '')}
Palantir 소개 문구: {article.get('description', '')}
글의 소제목: {json.dumps(article.get('source_headings') or [], ensure_ascii=False)}
Palantir 블로그 내용:
{body}

JSON 객체 하나만 반환하라:
{{
  "title_ko": "자연스럽고 사실적인 한국어 제목",
  "summary": "문제, 작동 방식, Palantir의 사례와 근거, 확인된 결과 또는 남은 과제를 담은 한국어 요약",
  "newsletter": {{
    "dek": "기술 주제와 독자가 얻을 관점을 담은 한 문장 부제",
    "lead": ["문제나 장면을 보여주는 2~3문장", "핵심 질문과 Palantir의 발표 맥락을 알려주는 2~3문장"],
    "highlights": ["도입이나 본문에서 그대로 복사한 핵심 문장 1", "본문에서 그대로 복사한 핵심 문장 2"],
    "sections": [
      {{"heading": "내용이 드러나는 구체적 소제목", "source_heading": "제공된 소제목과 일치하는 값 또는 빈 문자열", "paragraphs": ["Palantir 발표에 근거한 2~3문장", "작동 방식이나 사례를 풀어주는 2~3문장"]}}
    ],
    "closing": "확인된 의미와 남은 한계를 구분하는 2~3문장"
  }},
  "easy_explainer": "Palantir가 소개한 사례를 바탕으로 비전문가도 이해할 수 있게 쓴 1~2문장",
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
        max_tokens=3500,
    )
    result = json.loads(response.choices[0].message.content or "{}")
    required = {"title_ko", "summary", "newsletter", "easy_explainer", "category", "importance"}
    if not required.issubset(result):
        raise ValueError(f"Incomplete analysis response: {required - set(result)}")
    result["importance"] = max(1, min(10, int(result["importance"])))
    validate_analysis(article, result)
    return result
