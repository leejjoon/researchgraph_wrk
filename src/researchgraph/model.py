"""Data model types and invariants definitions.

Implements spec/data-model.md and spec/operations.md.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    RETIRED = "retired"


NODE_IMMUTABLE_KEYS: frozenset[str] = frozenset(
    {"id", "type", "title", "body", "author", "created", "fields"}
)
NODE_MUTABLE_KEYS: frozenset[str] = frozenset(
    {"status", "updated", "approvals", "artifacts", "budget", "lease"}
)

EDGE_IMMUTABLE_KEYS: frozenset[str] = frozenset(
    {"id", "type", "from", "to", "author", "created"}
)
EDGE_MUTABLE_KEYS: frozenset[str] = frozenset({"retired", "retired_at"})


@dataclass
class Actor:
    kind: str  # "human" | "agent"
    name: str
    role: str | None = None
    model: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"kind": self.kind, "name": self.name}
        if self.role is not None:
            d["role"] = self.role
        if self.model is not None:
            d["model"] = self.model
        if self.version is not None:
            d["version"] = self.version
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Actor:
        return cls(
            kind=data["kind"],
            name=data["name"],
            role=data.get("role"),
            model=data.get("model"),
            version=data.get("version"),
        )


@dataclass
class Approval:
    actor: Actor
    role: str
    at: str  # RFC 3339 timestamp
    what: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "actor": self.actor.to_dict(),
            "role": self.role,
            "at": self.at,
            "what": self.what,
        }
        if self.note is not None:
            d["note"] = self.note
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Approval:
        actor_data = data["actor"]
        actor = Actor.from_dict(actor_data) if isinstance(actor_data, dict) else actor_data
        return cls(
            actor=actor,
            role=data["role"],
            at=str(data["at"]),
            what=data["what"],
            note=data.get("note"),
        )


@dataclass
class Artifact:
    path: str
    sha256: str
    bytes: int
    added_at: str  # RFC 3339 timestamp
    added_by: Actor

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "added_at": self.added_at,
            "added_by": self.added_by.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        added_by_data = data["added_by"]
        added_by = (
            Actor.from_dict(added_by_data)
            if isinstance(added_by_data, dict)
            else added_by_data
        )
        return cls(
            path=data["path"],
            sha256=data["sha256"],
            bytes=int(data["bytes"]),
            added_at=str(data["added_at"]),
            added_by=added_by,
        )


@dataclass
class Budget:
    tokens: int | None = None
    compute_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.tokens is not None:
            d["tokens"] = self.tokens
        if self.compute_seconds is not None:
            d["compute_seconds"] = self.compute_seconds
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Budget | None:
        if data is None:
            return None
        return cls(
            tokens=data.get("tokens"),
            compute_seconds=data.get("compute_seconds"),
        )


@dataclass
class Lease:
    actor: Actor
    acquired_at: str  # RFC 3339 timestamp
    expires_at: str  # RFC 3339 timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor.to_dict(),
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Lease | None:
        if data is None:
            return None
        actor_data = data["actor"]
        actor = Actor.from_dict(actor_data) if isinstance(actor_data, dict) else actor_data
        return cls(
            actor=actor,
            acquired_at=str(data["acquired_at"]),
            expires_at=str(data["expires_at"]),
        )


@dataclass
class RuleViolation(Exception):
    rule: str
    message: str
    ids: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        ids_str = f" (ids: {', '.join(self.ids)})" if self.ids else ""
        return f"RuleViolation[{self.rule}]: {self.message}{ids_str}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "message": self.message,
            "ids": list(self.ids),
        }


@dataclass
class Node:
    id: str
    type: str
    title: str
    body: str
    author: Actor
    created: str
    fields: dict[str, Any] = field(default_factory=dict)
    status: Status | str = Status.PROPOSED
    updated: str = ""
    approvals: list[Approval] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    budget: Budget | None = None
    lease: Lease | None = None

    def __post_init__(self) -> None:
        if not self.updated:
            self.updated = self.created
        if isinstance(self.status, str) and not isinstance(self.status, Status):
            try:
                self.status = Status(self.status)
            except ValueError:
                pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "author": self.author.to_dict(),
            "created": self.created,
            "fields": self.fields,
            "status": self.status.value if isinstance(self.status, Status) else str(self.status),
            "updated": self.updated,
            "approvals": [a.to_dict() for a in self.approvals],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "budget": self.budget.to_dict() if self.budget else None,
            "lease": self.lease.to_dict() if self.lease else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        author_data = data["author"]
        author = Actor.from_dict(author_data) if isinstance(author_data, dict) else author_data
        approvals = [
            Approval.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("approvals") or []
        ]
        artifacts = [
            Artifact.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("artifacts") or []
        ]
        budget = Budget.from_dict(data.get("budget")) if data.get("budget") else None
        lease = Lease.from_dict(data.get("lease")) if data.get("lease") else None

        return cls(
            id=data["id"],
            type=data["type"],
            title=data.get("title", ""),
            body=data.get("body", ""),
            author=author,
            created=str(data["created"]),
            fields=dict(data.get("fields") or {}),
            status=data.get("status", Status.PROPOSED),
            updated=str(data.get("updated") or data["created"]),
            approvals=approvals,
            artifacts=artifacts,
            budget=budget,
            lease=lease,
        )


@dataclass
class Edge:
    id: str
    type: str
    from_id: str
    to_id: str
    author: Actor
    created: str
    retired: bool = False
    retired_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "from": self.from_id,
            "to": self.to_id,
            "author": self.author.to_dict(),
            "created": self.created,
            "retired": self.retired,
        }
        if self.retired_at is not None:
            d["retired_at"] = self.retired_at
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Edge:
        author_data = data["author"]
        author = Actor.from_dict(author_data) if isinstance(author_data, dict) else author_data
        return cls(
            id=data["id"],
            type=data["type"],
            from_id=data.get("from") or data.get("from_id", ""),
            to_id=data.get("to") or data.get("to_id", ""),
            author=author,
            created=str(data["created"]),
            retired=bool(data.get("retired", False)),
            retired_at=str(data["retired_at"]) if data.get("retired_at") else None,
        )
