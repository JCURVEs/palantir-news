import pytest

from palantir_news.summarizer import build_prompt, validate_analysis


def test_prompt_requests_concrete_mechanism_and_evidence():
    prompt = build_prompt({"title": "Example", "body": "Source detail"})

    assert "어떤 문제를 어떤 방식으로 풀었나" in prompt
    assert "실측 성과와 계획/예상 효과를 구별" in prompt
    assert "Source detail" in prompt


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
