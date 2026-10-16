import subprocess
from pathlib import Path
import pytest

from researchgraph.model import Actor, RuleViolation, Status
from researchgraph.project import Project


@pytest.fixture
def clean_repo(tmp_path):
    # Set up git user
    subprocess.run(["git", "config", "--global", "user.name", "Test User"], check=True)
    subprocess.run(["git", "config", "--global", "user.email", "test@example.com"], check=True)
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return project_dir


def test_acceptance_propose_1_python(clean_repo):
    """1. Given the research profile. When alice proposes a Hypothesis 'H1'.
    Then a file graph/nodes/hy-*.yaml exists with status proposed, author alice,
    and the commit message starts with rg: propose."""
    alice = Actor(kind="human", name="alice")
    project = Project.init(clean_repo, profile_name="research", actor=alice)

    node, edges = project.propose(
        type="Hypothesis",
        title="H1",
        actor=alice,
        commit=True,
    )

    assert node.status == Status.PROPOSED
    assert node.author.name == "alice"
    assert node.id.startswith("hy-")

    node_file = project.layout.node_file(node.id)
    assert node_file.exists()

    # Verify git commit
    log_proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=clean_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    commit_msg = log_proc.stdout.strip()
    assert commit_msg.startswith("rg: propose")
    assert node.id in commit_msg


def test_acceptance_propose_1_cli(clean_repo):
    """CLI version of acceptance scenario 1."""
    # Init via CLI
    init_res = subprocess.run(
        ["rg", "--project", str(clean_repo), "init"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert init_res.returncode == 0

    # Propose via CLI
    prop_res = subprocess.run(
        [
            "rg",
            "--project",
            str(clean_repo),
            "propose",
            "Hypothesis",
            "H1",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert prop_res.returncode == 0
    assert "Proposed Hypothesis hy-" in prop_res.stdout

    # Check files exist
    nodes_dir = clean_repo / "graph" / "nodes"
    hy_files = list(nodes_dir.glob("hy-*.yaml"))
    assert len(hy_files) == 1

    # Check commit
    log_proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=clean_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert log_proc.stdout.strip().startswith("rg: propose")


def test_acceptance_propose_2_task_active_no_gate(clean_repo):
    """2. Given the same. When agent1 proposes a Task 'T1' with no edges.
    Then status is active (Task has no gate)."""
    alice = Actor(kind="human", name="alice")
    agent1 = Actor(kind="agent", name="agent1")
    project = Project.init(clean_repo, profile_name="research", actor=alice)

    node, edges = project.propose(
        type="Task",
        title="T1",
        actor=agent1,
    )
    assert node.status == Status.ACTIVE
    assert node.id.startswith("ta-")


def test_acceptance_propose_3_with_edges(clean_repo):
    """3. Given H1 proposed. When agent1 proposes a Prediction 'P1' with edge tests -> H1.
    Then the edge file exists."""
    alice = Actor(kind="human", name="alice")
    agent1 = Actor(kind="agent", name="agent1")
    project = Project.init(clean_repo, profile_name="research", actor=alice)

    h1, _ = project.propose(type="Hypothesis", title="H1", actor=alice)
    p1, p1_edges = project.propose(
        type="Prediction",
        title="P1",
        edges=[{"type": "tests", "to": h1.id}],
        actor=agent1,
    )

    assert len(p1_edges) == 1
    edge = p1_edges[0]
    assert edge.type == "tests"
    assert edge.from_id == p1.id
    assert edge.to_id == h1.id
    assert project.layout.edge_file(edge.id).exists()


def test_acceptance_propose_4_unknown_type(clean_repo):
    """4. When anyone proposes a node of unknown type 'Widget'. Then RuleViolation unknown_type, no files written."""
    alice = Actor(kind="human", name="alice")
    project = Project.init(clean_repo, profile_name="research", actor=alice)

    with pytest.raises(RuleViolation) as exc_info:
        project.propose(type="Widget", title="My widget", actor=alice)
    assert exc_info.value.rule == "unknown_type"

    # Ensure no node files written
    assert len(list(project.layout.nodes.glob("*.yaml"))) == 0


def test_acceptance_propose_5_schema_violation(clean_repo):
    """5. When alice proposes a Hypothesis whose fields violate the schema. Then RuleViolation schema."""
    alice = Actor(kind="human", name="alice")
    project = Project.init(clean_repo, profile_name="research", actor=alice)

    # Question has schema additionalProperties: False, closed: bool
    with pytest.raises(RuleViolation) as exc_info:
        project.propose(type="Question", title="Q1", fields={"unexpected": True}, actor=alice)
    assert exc_info.value.rule == "schema"


def test_acceptance_propose_6_cycle(clean_repo):
    """6. Given tasks A and B with blocks A -> B. When agent1 proposes an edge blocks B -> A. Then RuleViolation cycle."""
    agent1 = Actor(kind="agent", name="agent1")
    project = Project.init(clean_repo, profile_name="research", actor=agent1)

    task_a, _ = project.propose(type="Task", title="Task A", actor=agent1)
    task_b, _ = project.propose(
        type="Task",
        title="Task B",
        edges=[{"type": "blocks", "from": task_a.id}],  # task_a blocks task_b
        actor=agent1,
    )

    with pytest.raises(RuleViolation) as exc_info:
        project.propose(
            type="Task",
            title="Task C",
            edges=[
                {"type": "blocks", "from": task_b.id},  # task_b -> task_c
                {"type": "blocks", "to": task_a.id},    # task_c -> task_a => CYCLE!
            ],
            actor=agent1,
        )
    assert exc_info.value.rule == "cycle"


def test_acceptance_propose_7_edge_endpoints(clean_repo):
    """7. When agent1 proposes an edge answers from a Task to a Question. Then RuleViolation edge_endpoints."""
    agent1 = Actor(kind="agent", name="agent1")
    project = Project.init(clean_repo, profile_name="research", actor=agent1)

    q1, _ = project.propose(type="Question", title="Q1", actor=agent1)
    with pytest.raises(RuleViolation) as exc_info:
        project.propose(
            type="Task",
            title="Task 1",
            edges=[{"type": "answers", "to": q1.id}],  # answers is only Hypothesis -> Question
            actor=agent1,
        )
    assert exc_info.value.rule == "edge_endpoints"
