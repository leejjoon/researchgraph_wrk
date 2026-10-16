"""Canonical YAML serialization and deserialization for nodes and edges.

Follows spec/store-layout.md and spec/data-model.md:
- YAML 1.2, UTF-8, 2-space indent
- Keys in fixed normative order
- No anchors / aliases
- No flow style for mappings
- Timestamps RFC 3339 UTC with Z
"""
from __future__ import annotations

import datetime
import re
from typing import Any, TextIO
import yaml

RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

NODE_KEY_ORDER = [
    "id",
    "type",
    "title",
    "body",
    "author",
    "created",
    "fields",
    "status",
    "updated",
    "approvals",
    "artifacts",
    "budget",
    "lease",
]

EDGE_KEY_ORDER = [
    "id",
    "type",
    "from",
    "to",
    "author",
    "created",
    "retired",
    "retired_at",
]

ACTOR_KEY_ORDER = ["kind", "name", "role", "model", "version"]
APPROVAL_KEY_ORDER = ["actor", "role", "at", "what", "note"]
ARTIFACT_KEY_ORDER = ["path", "sha256", "bytes", "added_at", "added_by"]
BUDGET_KEY_ORDER = ["tokens", "compute_seconds"]
LEASE_KEY_ORDER = ["actor", "acquired_at", "expires_at"]


class CanonicalDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> int:
        return super().increase_indent(flow=False, indentless=False)

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _format_datetime(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _str_representer(dumper: CanonicalDumper, data: str) -> yaml.Node:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    if RFC3339_RE.match(data):
        return dumper.represent_scalar("tag:yaml.org,2002:timestamp", data, style="")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _datetime_representer(dumper: CanonicalDumper, data: datetime.datetime) -> yaml.Node:
    text = _format_datetime(data)
    return dumper.represent_scalar("tag:yaml.org,2002:timestamp", text, style="")


def _date_representer(dumper: CanonicalDumper, data: datetime.date) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:timestamp", data.isoformat(), style="")


def _none_representer(dumper: CanonicalDumper, data: None) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


yaml.add_representer(str, _str_representer, Dumper=CanonicalDumper)
yaml.add_representer(datetime.datetime, _datetime_representer, Dumper=CanonicalDumper)
yaml.add_representer(datetime.date, _date_representer, Dumper=CanonicalDumper)
yaml.add_representer(type(None), _none_representer, Dumper=CanonicalDumper)


def _order_dict(data: dict[str, Any], preferred: list[str] | None = None) -> dict[str, Any]:
    if preferred is None:
        preferred = sorted(data.keys())
    result: dict[str, Any] = {}
    for key in preferred:
        if key in data:
            result[key] = data[key]
    for key in sorted(data.keys()):
        if key not in result:
            result[key] = data[key]
    return result


def _canonicalize_value(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _canonicalize_value(v) for k, v in sorted(val.items())}
    if isinstance(val, list):
        return [_canonicalize_value(item) for item in val]
    if isinstance(val, datetime.datetime):
        return _format_datetime(val)
    return val


def _canonicalize_actor(actor: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(actor, dict):
        return actor
    ordered = _order_dict(actor, ACTOR_KEY_ORDER)
    return {k: _canonicalize_value(v) for k, v in ordered.items()}


def canonicalize_node_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively order keys in a node dictionary to normative canonical order."""
    out: dict[str, Any] = {}
    top = _order_dict(data, NODE_KEY_ORDER)

    for k, v in top.items():
        if k == "author":
            out[k] = _canonicalize_actor(v)
        elif k == "approvals" and isinstance(v, list):
            approvals = []
            for item in v:
                if isinstance(item, dict):
                    app = _order_dict(item, APPROVAL_KEY_ORDER)
                    if "actor" in app and isinstance(app["actor"], dict):
                        app["actor"] = _canonicalize_actor(app["actor"])
                    approvals.append({ak: _canonicalize_value(av) for ak, av in app.items()})
                else:
                    approvals.append(_canonicalize_value(item))
            out[k] = approvals
        elif k == "artifacts" and isinstance(v, list):
            artifacts = []
            for item in v:
                if isinstance(item, dict):
                    art = _order_dict(item, ARTIFACT_KEY_ORDER)
                    if "added_by" in art and isinstance(art["added_by"], dict):
                        art["added_by"] = _canonicalize_actor(art["added_by"])
                    artifacts.append({ak: _canonicalize_value(av) for ak, av in art.items()})
                else:
                    artifacts.append(_canonicalize_value(item))
            out[k] = artifacts
        elif k == "budget":
            if isinstance(v, dict):
                b = _order_dict(v, BUDGET_KEY_ORDER)
                out[k] = {bk: _canonicalize_value(bv) for bk, bv in b.items()}
            else:
                out[k] = _canonicalize_value(v)
        elif k == "lease":
            if isinstance(v, dict):
                ls = _order_dict(v, LEASE_KEY_ORDER)
                if "actor" in ls and isinstance(ls["actor"], dict):
                    ls["actor"] = _canonicalize_actor(ls["actor"])
                out[k] = {lk: _canonicalize_value(lv) for lk, lv in ls.items()}
            else:
                out[k] = _canonicalize_value(v)
        elif k == "fields" and isinstance(v, dict):
            out[k] = {fk: _canonicalize_value(fv) for fk, fv in sorted(v.items())}
        else:
            out[k] = _canonicalize_value(v)
    return out


def canonicalize_edge_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively order keys in an edge dictionary to normative canonical order."""
    out: dict[str, Any] = {}
    top = _order_dict(data, EDGE_KEY_ORDER)
    for k, v in top.items():
        if k == "author":
            out[k] = _canonicalize_actor(v)
        else:
            out[k] = _canonicalize_value(v)
    return out


def dump_node(node: dict[str, Any]) -> str:
    """Dump a node dict to canonical YAML string."""
    ordered = canonicalize_node_dict(node)
    return yaml.dump(
        ordered,
        Dumper=CanonicalDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def dump_edge(edge: dict[str, Any]) -> str:
    """Dump an edge dict to canonical YAML string."""
    ordered = canonicalize_edge_dict(edge)
    return yaml.dump(
        ordered,
        Dumper=CanonicalDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


def load_yaml(source: str | TextIO) -> dict[str, Any]:
    """Load a YAML string or stream using fast SafeLoader."""
    if hasattr(source, "read"):
        data = yaml.load(source, Loader=SafeLoader)
    else:
        data = yaml.load(str(source), Loader=SafeLoader)
    return data or {}



def load_node(source: str | TextIO) -> dict[str, Any]:
    """Load and return a node dictionary."""
    data = load_yaml(source)
    return canonicalize_node_dict(data)


def load_edge(source: str | TextIO) -> dict[str, Any]:
    """Load and return an edge dictionary."""
    data = load_yaml(source)
    return canonicalize_edge_dict(data)
