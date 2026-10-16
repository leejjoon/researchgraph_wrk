import datetime
import subprocess
import pytest
from hypothesis import given, settings, strategies as st

from researchgraph.store.io import (
    dump_node,
    load_node,
    dump_edge,
    load_edge,
    canonicalize_node_dict,
    canonicalize_edge_dict,
)

# Hypothesis strategies for generating valid node structures

actors = st.fixed_dictionaries(
    {
        "kind": st.sampled_from(["human", "agent"]),
        "name": st.text(st.characters(categories=["Ll", "Lu", "Nd"]), min_size=1, max_size=20),
    },
    optional={
        "role": st.text(st.characters(categories=["Ll", "Lu"]), min_size=1, max_size=10),
        "model": st.text(st.characters(categories=["Ll", "Lu", "Nd"]), min_size=1, max_size=15),
        "version": st.text(st.characters(categories=["Nd", "Po"]), min_size=1, max_size=10),
    },
)

# RFC 3339 timestamps (seconds precision, UTC)
timestamps = st.datetimes(
    min_value=datetime.datetime(2020, 1, 1),
    max_value=datetime.datetime(2030, 1, 1),
    timezones=st.just(datetime.timezone.utc),
).map(lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ"))

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

approvals_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "actor": actors,
            "role": st.sampled_from(["owner", "reviewer", "human"]),
            "at": timestamps,
            "what": st.text(st.characters(categories=["Ll", "Lu", "Zs"]), min_size=1, max_size=30),
        },
        optional={"note": st.text(st.characters(categories=["Ll", "Lu", "Zs"]), max_size=50)},
    ),
    max_size=3,
)

artifacts_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "path": st.text(st.characters(categories=["Ll", "Lu", "Nd", "Pc", "Po"]), min_size=1, max_size=40),
            "sha256": st.text(st.sampled_from("0123456789abcdef"), min_size=64, max_size=64),
            "bytes": st.integers(min_value=0, max_value=10**9),
            "added_at": timestamps,
            "added_by": actors,
        }
    ),
    max_size=3,
)

budget_strategy = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {},
        optional={
            "tokens": st.integers(min_value=0, max_value=10**6),
            "compute_seconds": st.integers(min_value=0, max_value=10**6),
        },
    ),
)

lease_strategy = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {
            "actor": actors,
            "acquired_at": timestamps,
            "expires_at": timestamps,
        }
    ),
)

base32_chars = "abcdefghijklmnopqrstuvwxyz234567"

node_strategy = st.fixed_dictionaries(
    {
        "id": st.text(st.sampled_from(base32_chars), min_size=8, max_size=8).map(lambda s: f"hy-{s}"),
        "type": st.sampled_from(["Hypothesis", "Task", "Prediction", "Result", "Claim", "Question"]),
        "title": st.text(st.characters(categories=["Ll", "Lu", "Nd", "Zs", "Po"]), min_size=1, max_size=100),
        "body": st.text(st.characters(categories=["Ll", "Lu", "Nd", "Zs", "Po"], include_characters=["\n"]), max_size=200),
        "author": actors,
        "created": timestamps,
        "fields": fields_strategy,
        "status": st.sampled_from(["proposed", "active", "running", "done", "failed", "retired"]),
        "updated": timestamps,
        "approvals": approvals_strategy,
        "artifacts": artifacts_strategy,
        "budget": budget_strategy,
        "lease": lease_strategy,
    }
)

edge_strategy = st.fixed_dictionaries(
    {
        "id": st.text(st.sampled_from(base32_chars), min_size=8, max_size=8).map(lambda s: f"ed-{s}"),
        "type": st.sampled_from(["blocks", "tests", "supersedes", "derived-from", "supports", "cites"]),
        "from": st.text(st.sampled_from(base32_chars), min_size=8, max_size=8).map(lambda s: f"no-{s}"),
        "to": st.text(st.sampled_from(base32_chars), min_size=8, max_size=8).map(lambda s: f"no-{s}"),
        "author": actors,
        "created": timestamps,
        "retired": st.booleans(),
    },
    optional={
        "retired_at": timestamps,
    },
)


@settings(max_examples=1000)
@given(node=node_strategy)
def test_node_roundtrip_1000(node):
    # First dump creates canonical string x
    x = dump_node(node)
    # Then dump(load(x)) must be byte-for-byte identical to x
    loaded = load_node(x)
    rewritten = dump_node(loaded)
    assert rewritten == x, f"Roundtrip mismatch:\n--- Original ---\n{x}\n--- Rewritten ---\n{rewritten}"


@settings(max_examples=200)
@given(edge=edge_strategy)
def test_edge_roundtrip(edge):
    x = dump_edge(edge)
    loaded = load_edge(x)
    rewritten = dump_edge(loaded)
    assert rewritten == x, f"Roundtrip mismatch:\n--- Original ---\n{x}\n--- Rewritten ---\n{rewritten}"


def test_noop_rewrite_git_diff(tmp_path):
    # Initialize a temporary git repository
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)

    node = {
        "id": "hy-test1234",
        "type": "Hypothesis",
        "title": "A hypothesis about gravity",
        "body": "Some markdown description\nwith multiple lines.\n",
        "author": {"kind": "human", "name": "alice"},
        "created": "2026-10-16T12:00:00Z",
        "fields": {"closed": False},
        "status": "proposed",
        "updated": "2026-10-16T12:00:00Z",
        "approvals": [],
        "artifacts": [],
        "budget": None,
        "lease": None,
    }

    node_file = tmp_path / "node.yaml"
    node_file.write_text(dump_node(node), encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True, capture_output=True)

    # Load and rewrite the file
    content = node_file.read_text(encoding="utf-8")
    loaded = load_node(content)
    rewritten = dump_node(loaded)
    node_file.write_text(rewritten, encoding="utf-8")

    # Check git diff is empty
    diff_proc = subprocess.run(["git", "diff", "--exit-code"], cwd=tmp_path, capture_output=True, text=True)
    assert diff_proc.returncode == 0, f"Git diff found after no-op rewrite:\n{diff_proc.stdout}"
