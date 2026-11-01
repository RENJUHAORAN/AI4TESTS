from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CARDS_ROOT = ROOT / "tests/cards"
CONTRACTS_ROOT = ROOT / "tests/contracts"


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_contract_has_matching_test_card():
    contract_paths = sorted(CONTRACTS_ROOT.glob("*.yaml"))
    assert contract_paths

    for contract_path in contract_paths:
        card_path = CARDS_ROOT / contract_path.name
        assert card_path.is_file(), (
            f"{contract_path.name} 缺少同 ID Test Card: {card_path}"
        )

        contract = load_yaml(contract_path)
        card = load_yaml(card_path)

        assert card["id"] == contract["id"] == contract_path.stem
        for field in ("id", "title", "priority", "given", "when", "then"):
            assert card.get(field), (
                f"{card_path.name} 缺少或未填写字段: {field}"
            )
        assert isinstance(card.get("dataRefs"), list)
        assert isinstance(card.get("constraints"), list)
