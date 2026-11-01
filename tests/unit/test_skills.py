import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / ".codex/skills"
CHINESE_PATTERN = re.compile(r"[\u3400-\u9fff]")
FRONTMATTER_PATTERN = re.compile(
    r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$",
    re.DOTALL,
)


def load_skills():
    skills = []
    for directory in sorted(SKILLS_ROOT.iterdir()):
        if not directory.is_dir():
            continue
        source = (directory / "SKILL.md").read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(source)
        assert match, f"{directory.name} 缺少 YAML frontmatter"
        skills.append(
            {
                "directory": directory.name,
                "frontmatter": yaml.safe_load(match.group(1)),
                "body": match.group(2),
                "source": source,
            }
        )
    return skills


def test_chinese_skills_parse_and_match_directory_names():
    skills = load_skills()
    assert len(skills) >= 3

    for skill in skills:
        frontmatter = skill["frontmatter"]
        assert re.fullmatch(
            r"[a-z0-9-]{1,64}",
            frontmatter["name"],
        )
        assert frontmatter["name"] == skill["directory"]
        assert isinstance(frontmatter["description"], str)
        assert CHINESE_PATTERN.search(frontmatter["description"])
        assert skill["body"].strip()
        assert "\ufffd" not in skill["source"]

