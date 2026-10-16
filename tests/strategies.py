"""Hypothesis strategies for researchgraph data model types.

Follows spec/data-model.md and spec/operations.md.
"""
from __future__ import annotations

import datetime
from hypothesis import strategies as st

from researchgraph.model import (
    Actor,
    Approval,
    Artifact,
    Budget,
    Edge,
    Lease,
    Node,
    RuleViolation,
    Status,
)

BASE32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"

statuses = st.sampled_from(list(Status))

# RFC 3339 timestamps (UTC with Z)
timestamps = st.datetimes(
    min_value=datetime.datetime(2020, 1, 1),
    max_value=datetime.datetime(2030, 1, 1),
    timezones=st.just(datetime.timezone.utc),
).map(lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ"))

actors = st.builds(
    Actor,
    kind=st.sampled_from(["human", "agent"]),
    name=st.text(st.characters(categories=["Ll", "Lu", "Nd"]), min_size=1, max_size=20),
    role=st.one_of(st.none(), st.text(st.characters(categories=["Ll", "Lu"]), min_size=1, max_size=10)),
    model=st.one_of(st.none(), st.text(st.characters(categories=["Ll", "Lu", "Nd"]), min_size=1, max_size=15)),
    version=st.one_of(st.none(), st.text(st.characters(categories=["Nd", "Po"]), min_size=1, max_size=10)),
)

approvals = st.builds(
    Approval,
    actor=actors,
    role=st.sampled_from(["owner", "reviewer", "human"]),
    at=timestamps,
    what=st.text(st.characters(categories=["Ll", "Lu", "Zs"]), min_size=1, max_size=30),
    note=st.one_of(st.none(), st.text(st.characters(categories=["Ll", "Lu", "Zs"]), max_size=50)),
)

artifacts = st.builds(
    Artifact,
    path=st.text(st.characters(categories=["Ll", "Lu", "Nd", "Pc", "Po"]), min_size=1, max_size=40),
    sha256=st.text(st.sampled_from("0123456789abcdef"), min_size=64, max_size=64),
    bytes=st.integers(min_value=0, max_value=10**9),
    added_at=timestamps,
    added_by=actors,
)

budgets = st.one_of(
    st.none(),
    st.builds(
        Budget,
        tokens=st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
        compute_seconds=st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
    ),
)

leases = st.one_of(
    st.none(),
    st.builds(
        Lease,
        actor=actors,
        acquired_at=timestamps,
        expires_at=timestamps,
    ),
)

rule_violations = st.builds(
    RuleViolation,
    rule=st.sampled_from([
        "schema",
        "edge_endpoints",
        "cycle",
        "unknown_type",
        "human_only_approval",
        "wrong_role",
        "not_proposed",
        "already_approved",
        "agent_cannot_supersede_type",
        "terminal_status",
        "already_ran",
        "not_ready",
        "lease_held",
        "not_lease_holder",
        "artifact_missing",
        "no_targets",
        "read_only",
    ]),
    message=st.text(st.characters(categories=["Ll", "Lu", "Nd", "Zs"]), min_size=1, max_size=100),
    ids=st.lists(
        st.text(st.sampled_from(BASE32_ALPHABET), min_size=8, max_size=8).map(lambda s: f"no-{s}"),
        max_size=3,
    ),
)

node_ids = st.text(st.sampled_from(BASE32_ALPHABET), min_size=8, max_size=8).map(
    lambda s: f"hy-{s}"
)

edge_ids = st.text(st.sampled_from(BASE32_ALPHABET), min_size=8, max_size=8).map(
    lambda s: f"ed-{s}"
)

json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000000, max_value=1000000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000.0, max_value=1000.0).map(lambda f: round(f, 4)),
    st.text(st.characters(exclude_categories=["Cs", "Cc"]), max_size=50),
)

fields_strategy = st.dictionaries(
    keys=st.text(st.characters(categories=["Ll", "Lu", "Nd"]), min_size=1, max_size=15),
    values=json_primitives,
    max_size=5,
)

nodes = st.builds(
    Node,
    id=node_ids,
    type=st.sampled_from(["Hypothesis", "Task", "Prediction", "Result", "Claim", "Question"]),
    title=st.text(st.characters(categories=["Ll", "Lu", "Nd", "Zs", "Po"]), min_size=1, max_size=100),
    body=st.text(st.characters(categories=["Ll", "Lu", "Nd", "Zs", "Po"], include_characters=["\n"]), max_size=200),
    author=actors,
    created=timestamps,
    fields=fields_strategy,
    status=statuses,
    updated=timestamps,
    approvals=st.lists(approvals, max_size=3),
    artifacts=st.lists(artifacts, max_size=3),
    budget=budgets,
    lease=leases,
)

edges = st.builds(
    Edge,
    id=edge_ids,
    type=st.sampled_from([
        "blocks",
        "tests",
        "supersedes",
        "derived-from",
        "supports",
        "contradicts",
        "discovered-from",
        "instructs",
        "explains",
        "cites",
        "answers",
    ]),
    from_id=node_ids,
    to_id=node_ids,
    author=actors,
    created=timestamps,
    retired=st.booleans(),
    retired_at=st.one_of(st.none(), timestamps),
)
