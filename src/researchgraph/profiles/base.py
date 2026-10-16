"""Base classes and registry for researchgraph profiles.

Implements spec/profiles.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib.metadata
from typing import Any, Callable
import jsonschema

from researchgraph.model import RuleViolation


@dataclass
class NodeType:
    name: str  # e.g. "Hypothesis"
    prefix: str  # e.g. "hy"
    schema: dict[str, Any]  # JSON Schema for node.fields
    requires_gate: bool  # proposed -> active needs approve


@dataclass
class EdgeType:
    name: str
    allowed: list[tuple[str, str]]  # (from type, to type); "*" wildcard


CORE_EDGE_TYPES: list[EdgeType] = [
    EdgeType(name="blocks", allowed=[("*", "*")]),
    EdgeType(name="tests", allowed=[("Prediction", "Hypothesis"), ("Task", "Hypothesis")]),
    EdgeType(name="supersedes", allowed=[(t, t) for t in [
        "Question", "Hypothesis", "Prediction", "Task", "Result", "Claim", "Instruction", "Failure", "Note"
    ]] + [("*", "*")]),  # profile validates X -> X of same type
    EdgeType(name="derived-from", allowed=[("*", "*")]),
    EdgeType(name="supports", allowed=[("Claim", "Hypothesis")]),
    EdgeType(name="contradicts", allowed=[("Claim", "Hypothesis")]),
    EdgeType(name="discovered-from", allowed=[("*", "*")]),
    EdgeType(name="instructs", allowed=[("Instruction", "*")]),
    EdgeType(name="explains", allowed=[("Failure", "*")]),
    EdgeType(name="cites", allowed=[("Claim", "*")]),  # Claim -> Result or artifact-bearing node
    EdgeType(name="answers", allowed=[("Hypothesis", "Question")]),
]


@dataclass
class Gate:
    transition: str  # "activate" | "run" | "complete"
    node_type: str  # or "*"
    roles: list[str]  # roles that may satisfy it; "human" means any human
    agents_allowed: bool = False


@dataclass
class Profile:
    name: str
    version: str
    node_types: list[NodeType]
    edge_types: list[EdgeType]  # added to the core set
    gates: list[Gate]
    roles: list[str]
    validators: list[Callable[[Any, Any], None]] = field(default_factory=list)  # raise RuleViolation
    expansion_hook: Callable | None = None  # NOT called by the core; documented for consumers
    renderers: dict[str, Callable] = field(default_factory=dict)  # v0.2
    event_hooks: list[Callable] = field(default_factory=list)  # called after a committed write
    agent_guidance: str = ""
    migrations: dict[str, Callable] = field(default_factory=dict)  # from-version -> fn(project)

    def get_node_type(self, name: str) -> NodeType | None:
        for nt in self.node_types:
            if nt.name == name:
                return nt
        return None

    def validate_fields(self, type_name: str, fields: dict[str, Any]) -> None:
        nt = self.get_node_type(type_name)
        if nt is None:
            raise RuleViolation(
                rule="unknown_type",
                message=f"Unknown node type: {type_name}",
            )
        try:
            jsonschema.validate(instance=fields, schema=nt.schema)
        except jsonschema.ValidationError as e:
            raise RuleViolation(
                rule="schema",
                message=f"Fields schema validation failed for {type_name}: {e.message}",
            ) from e

    def all_edge_types(self) -> dict[str, EdgeType]:
        edges: dict[str, EdgeType] = {et.name: et for et in CORE_EDGE_TYPES}
        for et in self.edge_types:
            edges[et.name] = et
        return edges

    @classmethod
    def load(cls, name: str) -> Profile:
        """Load profile by name from entry points or fallback bundled profiles."""
        # Try entry points first
        eps = importlib.metadata.entry_points(group="researchgraph.profiles")
        for ep in eps:
            if ep.name == name:
                obj = ep.load()
                if isinstance(obj, Profile):
                    return obj
                if callable(obj):
                    return obj()

        # Fallback to direct import for bundled profiles
        if name == "research":
            from researchgraph.profiles.research import PROFILE
            return PROFILE
        if name == "tasks":
            from researchgraph.profiles.tasks import PROFILE
            return PROFILE

        raise ValueError(f"Profile '{name}' not found")
