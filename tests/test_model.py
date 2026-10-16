from hypothesis import given, settings

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
    NODE_IMMUTABLE_KEYS,
    NODE_MUTABLE_KEYS,
    EDGE_IMMUTABLE_KEYS,
    EDGE_MUTABLE_KEYS,
)
from researchgraph.store.io import dump_node, load_node, dump_edge, load_edge
import tests.strategies as strat


def test_immutable_keys_disjoint():
    assert NODE_IMMUTABLE_KEYS.isdisjoint(NODE_MUTABLE_KEYS)
    assert EDGE_IMMUTABLE_KEYS.isdisjoint(EDGE_MUTABLE_KEYS)


@settings(max_examples=100)
@given(actor=strat.actors)
def test_actor_roundtrip(actor):
    d = actor.to_dict()
    assert Actor.from_dict(d) == actor


@settings(max_examples=100)
@given(app=strat.approvals)
def test_approval_roundtrip(app):
    d = app.to_dict()
    assert Approval.from_dict(d) == app


@settings(max_examples=100)
@given(art=strat.artifacts)
def test_artifact_roundtrip(art):
    d = art.to_dict()
    assert Artifact.from_dict(d) == art


@settings(max_examples=50)
@given(budget=strat.budgets)
def test_budget_roundtrip(budget):
    if budget is None:
        assert Budget.from_dict(None) is None
    else:
        d = budget.to_dict()
        assert Budget.from_dict(d) == budget


@settings(max_examples=50)
@given(lease=strat.leases)
def test_lease_roundtrip(lease):
    if lease is None:
        assert Lease.from_dict(None) is None
    else:
        d = lease.to_dict()
        assert Lease.from_dict(d) == lease


@settings(max_examples=50)
@given(rv=strat.rule_violations)
def test_rule_violation(rv):
    assert isinstance(rv, Exception)
    d = rv.to_dict()
    assert d["rule"] == rv.rule
    assert d["message"] == rv.message
    assert d["ids"] == rv.ids


@settings(max_examples=100)
@given(node=strat.nodes)
def test_node_model_and_io_roundtrip(node):
    d = node.to_dict()
    reconstituted = Node.from_dict(d)
    assert reconstituted.id == node.id
    assert reconstituted.type == node.type
    assert reconstituted.status == node.status

    yaml_str = dump_node(d)
    loaded_dict = load_node(yaml_str)
    assert loaded_dict["id"] == node.id


@settings(max_examples=100)
@given(edge=strat.edges)
def test_edge_model_and_io_roundtrip(edge):
    d = edge.to_dict()
    reconstituted = Edge.from_dict(d)
    assert reconstituted.id == edge.id
    assert reconstituted.type == edge.type
    assert reconstituted.from_id == edge.from_id
    assert reconstituted.to_id == edge.to_id

    yaml_str = dump_edge(d)
    loaded_dict = load_edge(yaml_str)
    assert loaded_dict["id"] == edge.id
