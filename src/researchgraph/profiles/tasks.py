"""The bundled 'tasks' profile.

Implements spec/profiles.md §tasks profile.
"""
from __future__ import annotations

from researchgraph.profiles.base import EdgeType, Gate, NodeType, Profile

TASKS_NODE_TYPES = [
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
        name="Note",
        prefix="no",
        schema={"type": "object", "additionalProperties": True},
        requires_gate=False,
    ),
]

PROFILE = Profile(
    name="tasks",
    version="1.0",
    node_types=TASKS_NODE_TYPES,
    edge_types=[],
    gates=[],
    roles=[],
    validators=[],
)
