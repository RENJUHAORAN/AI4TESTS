import pytest

from ui_test_poc.runner import (
    AssertionFailure,
    StepExecutionError,
    build_context_options,
    classify_status,
    compare,
    redact,
    redact_value,
    switch_to_page,
)


def test_compare_supports_contains_and_regular_expression():
    compare("欢迎回来，演示用户", "欢迎回来", "contains", "文本")
    compare("HTTP://EXAMPLE.COM/Home", r"/home$/i", "matches", "URL")

    with pytest.raises(AssertionError):
        compare("首页", "登录", "equals", "标题")


def test_redaction_handles_nested_actual_values():
    value = {
        "token": "sensitive-token",
        "items": ["before-sensitive-token-after"],
    }
    redacted = redact_value(value, ["sensitive-token"])

    assert redacted == {
        "token": "[REDACTED]",
        "items": ["before-[REDACTED]-after"],
    }
    assert redact("prefix-secret-suffix", ["secret"]) == (
        "prefix-[REDACTED]-suffix"
    )


def test_status_classification_keeps_infrastructure_as_blocked():
    assert classify_status(None) == "passed"
    assert (
        classify_status(StepExecutionError("open", "failed"))
        == "failed"
    )
    assert (
        classify_status(AssertionFailure("url", "failed"))
        == "failed"
    )
    assert classify_status(RuntimeError("browser missing")) == "blocked"


def test_context_options_support_mobile_contracts():
    contract = {
        "target": {"baseUrl": "https://example.test/"},
        "browser": {
            "viewport": {"width": 390, "height": 844},
            "isMobile": True,
            "deviceScaleFactor": 3,
            "hasTouch": True,
            "locale": "zh-CN",
        },
    }

    options = build_context_options(contract)

    assert options == {
        "base_url": "https://example.test/",
        "viewport": {"width": 390, "height": 844},
        "is_mobile": True,
        "device_scale_factor": 3,
        "has_touch": True,
        "locale": "zh-CN",
    }


def test_context_options_keep_desktop_defaults():
    options = build_context_options(
        {"target": {"baseUrl": "http://127.0.0.1:4173/"}}
    )

    assert options["viewport"] == {"width": 1440, "height": 900}
    assert "is_mobile" not in options


def test_switch_to_page_pumps_playwright_event_dispatch():
    class FakePage:
        def __init__(self, url):
            self.url = url

        def wait_for_timeout(self, milliseconds):
            context.pages.append(
                FakePage(
                    "https://re.jd.com/search?keyword=iPhone"
                )
            )

        def wait_for_load_state(self, state, timeout):
            assert state == "domcontentloaded"
            assert timeout > 0

    class FakeContext:
        def __init__(self, pages):
            self.pages = pages

    source = FakePage("https://re.m.jd.com/page/homelike")
    context = FakeContext([source])
    contract = {
        "target": {
            "allowedOrigins": [
                "https://re.m.jd.com",
                "https://re.jd.com",
            ]
        }
    }

    result = switch_to_page(
        context,
        source,
        {
            "url": "https://re.jd.com/search",
            "timeoutMs": 1_000,
        },
        contract,
    )

    assert result.url.startswith("https://re.jd.com/search")

