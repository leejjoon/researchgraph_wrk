"""The bundled 'research' profile.

Implements spec/profiles.md §research profile.
"""
from __future__ import annotations

from typing import Any
from researchgraph.model import RuleViolation
from researchgraph.profiles.base import EdgeType, Gate, NodeType, Profile


def validate_research(project: Any, write: Any) -> None:
    # Will be connected during T07 / operations
    pass


RESEARCH_NODE_TYPES = [
    NodeType(
        name="Question",
        prefix="qu",
        schema={
            "type": "object",
            "properties": {"closed": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
        requires_gate=False,
    ),
    NodeType(
        name="Hypothesis",
        prefix="hy",
        schema={"type": "object", "additionalProperties": True},
        requires_gate=True,
    ),
    NodeType(
        name="Prediction",
        prefix="pr",
        schema={"type": "object", "additionalProperties": True},
        requires_gate=True,
    ),
    NodeType(
        name="Task",
        prefix="ta",
        schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "targets": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        requires_gate=False,
    ),
    NodeType(
        name="Result",
        prefix="re",
        schema={
            "type": "object",
            "properties": {
                "held_out": {"type": "boolean"},
                "runs": {"type": "integer"},
            },
            "additionalProperties": True,
        },
        requires_gate=False,
    ),
    NodeType(
        name="Claim",
        prefix="cl",
        schema={"type": "object", "additionalProperties": True},
        requires_gate=True,
    ),
    NodeType(
        name="Instruction",
        prefix="in",
        schema={"type": "object", "additionalProperties": True},
        requires_gate=False,
    ),
    NodeType(
        name="Failure",
        prefix="fl",
        schema={
            "type": "object",
            "properties": {
                "step": {"type": "string"},
                "check": {"type": "string"},
                "measured": {},
                "error": {"type": "string"},
            },
            "additionalProperties": True,
        },
        requires_gate=False,
    ),
    NodeType(
        name="Note",
        prefix="no",
        schema={"type": "object", "additionalProperties": True},
        requires_gate=False,
    ),
]

RESEARCH_GATES = [
    Gate(transition="activate", node_type="Hypothesis", roles=["human"]),
    Gate(transition="activate", node_type="Prediction", roles=["human"]),
    Gate(transition="activate", node_type="Claim", roles=["human"]),
]

PROFILE = Profile(
    name="research",
    version="1.0",
    node_types=RESEARCH_NODE_TYPES,
    edge_types=[],  # uses core edge types
    gates=RESEARCH_GATES,
    roles=["owner", "reviewer"],
    validators=[validate_research],
)
