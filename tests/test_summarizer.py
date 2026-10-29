import pytest

from palantir_news.summarizer import build_prompt, validate_analysis


def test_prompt_requests_concrete_mechanism_and_evidence():
    prompt = build_prompt({"title": "Example", "body": "Source detail"})

    assert "어떤 문제를 어떤 방식으로 풀었나" in prompt
    assert "실측 성과와 계획/예상 효과를 구별" in prompt
    assert "Source detail" in prompt
    assert "newsletter" in prompt


def test_prompt_keeps_end_of_long_article():
    prompt = build_prompt({"body": "A" * 13000 + "M" * 8000 + "Z" * 1000})

    assert "[중간 부분 생략]" in prompt
    assert "Z" * 1000 in prompt
    assert "M" * 8000 not in prompt


def test_long_source_rejects_thin_summary():
    article = {"body": "Detailed source evidence. " * 100}
    result = {"summary": "제품을 소개합니다.", "easy_explainer": "실제 사례를 쉽게 설명합니다.", "category": "데이터 플랫폼"}

    with pytest.raises(ValueError, match="too thin"):
        validate_analysis(article, result)


def test_blocked_page_summary_is_rejected_even_if_long():
    article = {"body": "Readable article. " * 100}
    result = {
        "summary": "원문 본문은 접근이 차단되어 확인할 수 없습니다. " * 10,
        "easy_explainer": "실제 사례를 쉽게 설명합니다.",
        "category": "데이터 플랫폼",
    }

    with pytest.raises(ValueError, match="blocked page"):
        validate_analysis(article, result)

    result["summary"] = "원문의 문제와 구현 단계를 구체적으로 설명합니다. " * 10
    result["easy_explainer"] = "원문 본문은 접근이 차단됐습니다."
    with pytest.raises(ValueError, match="blocked page"):
        validate_analysis(article, result)


def test_short_announcement_can_have_concise_grounded_summary():
    article = {"body": "A short factual announcement."}
    result = {
        "summary": "신제품의 공개 일정과 대상 사용자를 설명합니다.",
        "easy_explainer": "제품 공개 사실을 알리는 짧은 글입니다.",
        "category": "기업/파트너십",
    }

    validate_analysis(article, result)


def test_newsletter_requires_substance_and_known_source_heading():
    article = {"body": "Detailed source evidence. " * 100, "source_headings": ["Implementation"]}
    paragraph = "조직은 데이터와 업무 개념을 연결해 공통 기준을 세웁니다. 여러 애플리케이션이 같은 객체 정의를 재사용해 해석 작업을 줄입니다. " * 5
    result = {
        "summary": paragraph * 2,
        "easy_explainer": paragraph,
        "category": "데이터 플랫폼",
        "newsletter": {
            "dek": "데이터를 업무 개념에 연결하는 방법을 살펴봅니다.",
            "lead": [paragraph, paragraph],
            "highlights": ["조직은 데이터와 업무 개념을 연결해 공통 기준을 세웁니다.", "원문에 없는 문장을 모델이 새로 지어낸 경우에는 하이라이트로 발행하면 안 됩니다."],
            "sections": [
                {"heading": "서로 다른 데이터를 같은 객체로 연결", "source_heading": "Implementation", "paragraphs": [paragraph]},
                {"heading": "업무 앱에서 정의를 재사용", "source_heading": "", "paragraphs": [paragraph]},
            ],
            "closing": paragraph,
        },
    }
    with pytest.raises(ValueError, match="Highlights"):
        validate_analysis(article, result)
    result["newsletter"]["highlights"][1] = "여러 애플리케이션이 같은 객체 정의를 재사용해 해석 작업을 줄입니다."
    validate_analysis(article, result)
    result["newsletter"]["sections"][0]["source_heading"] = "Invented"
    with pytest.raises(ValueError, match="unknown source heading"):
        validate_analysis(article, result)
