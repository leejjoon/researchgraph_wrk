import pytest
from researchgraph.model import RuleViolation
from researchgraph.profiles.base import Profile


def test_load_research_profile():
    profile = Profile.load("research")
    assert profile.name == "research"
    assert profile.version == "1.0"

    expected_types = {
        "Question": ("qu", False),
        "Hypothesis": ("hy", True),
        "Prediction": ("pr", True),
        "Task": ("ta", False),
        "Result": ("re", False),
        "Claim": ("cl", True),
        "Instruction": ("in", False),
        "Failure": ("fl", False),
        "Note": ("no", False),
    }

    assert len(profile.node_types) == len(expected_types)
    for nt in profile.node_types:
        assert nt.name in expected_types
        expected_prefix, expected_gate = expected_types[nt.name]
        assert nt.prefix == expected_prefix
        assert nt.requires_gate == expected_gate

    assert set(profile.roles) == {"owner", "reviewer"}
    assert len(profile.gates) == 3


def test_load_tasks_profile():
    profile = Profile.load("tasks")
    assert profile.name == "tasks"
    assert set(nt.name for nt in profile.node_types) == {"Task", "Result", "Note"}
    assert len(profile.gates) == 0


def test_load_nonexistent_profile():
    with pytest.raises(ValueError, match="not found"):
        Profile.load("nonexistent")


def test_validate_fields_valid():
    profile = Profile.load("research")
    # Valid Question fields
    profile.validate_fields("Question", {"closed": True})
    profile.validate_fields("Question", {})

    # Valid Task fields
    profile.validate_fields("Task", {"kind": "experiment", "targets": ["ta-12345678"]})

    # Valid Result fields
    profile.validate_fields("Result", {"held_out": True, "runs": 3})


def test_validate_fields_invalid():
    profile = Profile.load("research")

    # Question has additionalProperties: False
    with pytest.raises(RuleViolation) as exc_info:
        profile.validate_fields("Question", {"unexpected_field": 123})
    assert exc_info.value.rule == "schema"

    # Task targets must be an array of strings
    with pytest.raises(RuleViolation) as exc_info:
        profile.validate_fields("Task", {"targets": "not-an-array"})
    assert exc_info.value.rule == "schema"

    # Unknown type
    with pytest.raises(RuleViolation) as exc_info:
        profile.validate_fields("Widget", {})
    assert exc_info.value.rule == "unknown_type"
