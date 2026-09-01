from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".cursor" / "skills" / "project-bootstrap" / "SKILL.md"


def test_bootstrap_skill_exists_and_matches_folder_name() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: project-bootstrap" in text
    assert "ALWAYS use at the start of every conversation" in text


def test_bootstrap_skill_points_at_public_docs_only() -> None:
    text = SKILL.read_text(encoding="utf-8")
    required = [
        "AGENTS.md",
        "README.md",
        "config.example.yaml",
        "LICENSE",
        ".cursor/skills/plan-and-review/SKILL.md",
    ]
    for relative in required:
        assert relative in text
        assert (ROOT / relative).is_file(), relative
    assert "docs/handoff.md" not in text
    assert "docs/product-notes.md" not in text


def test_private_studio_docs_are_not_shipped() -> None:
    assert not (ROOT / "docs" / "handoff.md").exists()
    assert not (ROOT / "docs" / "product-notes.md").exists()
    assert not (ROOT / "homeserver_paid").exists()


def test_readme_has_no_internal_memo_links() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/handoff.md" not in text
    assert "docs/product-notes.md" not in text
    assert "PalaceSystemFree" in text


def test_agents_md_requires_bootstrap_skill() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "project-bootstrap" in text
    assert "Composer 2.5" in text
    assert "plan-and-review" in text
    assert "docs/handoff.md" not in text
    assert "docs/product-notes.md" not in text


def test_plan_and_review_skill_exists() -> None:
    skill = ROOT / ".cursor" / "skills" / "plan-and-review" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: plan-and-review" in text
    assert "composer-2.5" in text
    assert "palworld_admin/" in text
