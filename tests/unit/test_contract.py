from pathlib import Path

import pytest

from ui_test_poc.contract import (
    ContractError,
    build_target_url,
    has_data_path,
    load_contract,
    resolve_template,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "tests/contracts/LOGIN-001.yaml"
VALID_ENV = {
    "WEB_BASE_URL": "http://127.0.0.1:4173",
    "DEMO_USER": "demo",
    "DEMO_PASSWORD": "demo123",
}


def test_loads_valid_contract():
    contract, secrets = load_contract(CONTRACT_PATH, VALID_ENV)

    assert contract["id"] == "LOGIN-001"
    assert contract["target"]["baseUrl"] == "http://127.0.0.1:4173/"
    assert contract["data"]["username"] == "demo"
    assert sorted(secrets) == sorted(["demo", "demo123"])


def test_rejects_missing_base_url_environment():
    with pytest.raises(ContractError, match="WEB_BASE_URL"):
        load_contract(
            CONTRACT_PATH,
            {
                "DEMO_USER": "demo",
                "DEMO_PASSWORD": "demo123",
            },
        )


def test_rejects_origin_outside_allowlist():
    with pytest.raises(ContractError, match="allowedOrigins"):
        load_contract(
            CONTRACT_PATH,
            {
                **VALID_ENV,
                "WEB_BASE_URL": "http://localhost:4173",
            },
        )


def test_rejects_missing_secret():
    with pytest.raises(ContractError, match="DEMO_PASSWORD"):
        load_contract(
            CONTRACT_PATH,
            {
                "WEB_BASE_URL": "http://127.0.0.1:4173",
                "DEMO_USER": "demo",
            },
        )


def test_rejects_explore_mode():
    with pytest.raises(ContractError, match="mode: verify"):
        load_contract(
            ROOT / "tests/fixtures/EXPLORE-001.yaml",
            VALID_ENV,
        )


def test_resolves_nested_templates_and_javascript_primitives():
    data = {
        "account": {"name": "演示用户"},
        "enabled": True,
        "attempts": 3,
    }

    assert (
        resolve_template(
            "${data.account.name}:${data.enabled}:${data.attempts}",
            data,
        )
        == "演示用户:true:3"
    )
    assert has_data_path(data, "account.name")
    assert not has_data_path(data, "account.missing")


def test_builds_url_from_contract_base():
    assert (
        build_target_url(
            "http://127.0.0.1:4173/",
            "/login?from=contract",
        )
        == "http://127.0.0.1:4173/login?from=contract"
    )


def test_loads_mobile_contract_with_page_switch():
    contract, secrets = load_contract(
        ROOT / "tests/contracts/JD-SEARCH-001.yaml",
        {"JD_BASE_URL": "https://re.m.jd.com"},
    )

    assert secrets == []
    assert contract["browser"]["isMobile"] is True
    assert contract["browser"]["viewport"] == {
        "width": 390,
        "height": 844,
    }
    assert contract["steps"][-1]["action"] == "switchPage"
    assert contract["assertions"][-1]["locator"]["nth"] == 0

