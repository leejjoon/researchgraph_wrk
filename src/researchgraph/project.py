"""Project store operations.

Implements spec/operations.md, spec/store-layout.md, and spec/data-model.md.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Sequence
import yaml

from researchgraph.model import (
    Actor,
    Edge,
    Node,
    RuleViolation,
    Status,
)
from researchgraph.profiles.base import Profile
from researchgraph.store.atomic import write_atomic
from researchgraph.store.git import (
    get_git_actor,
    git_commit_files,
    run_git,
    try_git,
)
from researchgraph.store.index import Index, compute_tree_hash, open_or_rebuild_index
from researchgraph.store.io import (
    dump_edge,
    dump_node,
    load_edge,
    load_node,
)
from researchgraph.store.layout import (
    ProjectLayout,
    generate_edge_id,
    generate_node_id,
)

CYCLE_CHECK_EDGE_TYPES = frozenset({"blocks", "derived-from", "supersedes", "cites"})


def _current_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Project:
    def __init__(self, root: Path | str, profile: Profile, read_only: bool = False) -> None:
        self.layout = ProjectLayout(root)
        self.profile = profile
        self.read_only = read_only
        self._index: Index | None = None

    @property
    def index(self) -> Index:
        if self._index is None or not self.layout.index_file.exists():
            self._index = open_or_rebuild_index(self.layout)
        else:
            try:
                self._index.conn.total_changes
            except Exception:
                self._index = open_or_rebuild_index(self.layout)
        return self._index


    def is_stale(self) -> bool:
        """Check if index is stale compared to files."""
        return self.index.is_stale(self.layout)


    @classmethod
    def init(
        cls,
        path: Path | str,
        profile_name: str = "research",
        actor: Actor | None = None,
    ) -> Project:
        """Initialize a new researchgraph project."""
        root = Path(path).resolve()
        root.mkdir(parents=True, exist_ok=True)
        layout = ProjectLayout(root)

        # Initialize git if not present
        if not (root / ".git").exists():
            run_git(["init"], cwd=root)

        # Create directories
        layout.dot_rg.mkdir(parents=True, exist_ok=True)
        layout.nodes.mkdir(parents=True, exist_ok=True)
        layout.edges.mkdir(parents=True, exist_ok=True)
        layout.artifacts.mkdir(parents=True, exist_ok=True)

        # Load profile
        profile = Profile.load(profile_name)

        # Write profile.yaml
        profile_data = {"name": profile.name, "version": profile.version}
        write_atomic(layout.profile_file, yaml.safe_dump(profile_data, sort_keys=False))

        # Update .gitignore
        gitignore_entry = ".researchgraph/index.sqlite\n"
        if layout.gitignore.exists():
            existing = layout.gitignore.read_text(encoding="utf-8")
            if ".researchgraph/index.sqlite" not in existing:
                layout.gitignore.write_text(existing + gitignore_entry, encoding="utf-8")
        else:
            layout.gitignore.write_text(gitignore_entry, encoding="utf-8")

        # Initial commit
        if actor is None:
            actor = get_git_actor(root)

        git_commit_files(
            [layout.profile_file, layout.gitignore],
            "rg: init",
            actor,
            cwd=root,
        )

        proj = cls(root=root, profile=profile)
        proj.index.rebuild(layout)
        return proj


    @classmethod
    def open(cls, path: Path | str, read_only: bool = False) -> Project:
        """Open an existing project from path or any ancestor directory."""
        current = Path(path).resolve()
        while True:
            profile_file = current / ".researchgraph" / "profile.yaml"
            if profile_file.exists():
                break
            if current.parent == current:
                raise RuleViolation(
                    rule="not_a_project",
                    message=f"No researchgraph project found at {path} or its parents",
                )
            current = current.parent

        profile_data = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
        name = profile_data.get("name", "research")
        profile = Profile.load(name)

        # Check pinned version
        pinned_version = profile_data.get("version", "1.0")
        if pinned_version > profile.version:
            raise RuleViolation(
                rule="profile_too_new",
                message=f"Pinned profile version {pinned_version} is newer than installed {profile.version}",
            )

        proj = cls(root=current, profile=profile, read_only=read_only)
        if proj.index.is_stale(proj.layout):
            proj.index.rebuild(proj.layout)
        return proj


    def get_node(self, node_id: str) -> Node | None:
        """Load a node from file."""
        file_path = self.layout.node_file(node_id)
        if not file_path.exists():
            return None
        data = load_node(file_path.read_text(encoding="utf-8"))
        return Node.from_dict(data)

    def get_edge(self, edge_id: str) -> Edge | None:
        """Load an edge from file."""
        file_path = self.layout.edge_file(edge_id)
        if not file_path.exists():
            return None
        data = load_edge(file_path.read_text(encoding="utf-8"))
        return Edge.from_dict(data)

    def list_nodes(self) -> list[Node]:
        """List all nodes directly from disk."""
        nodes = []
        if self.layout.nodes.exists():
            for f in sorted(self.layout.nodes.glob("*.yaml")):
                data = load_node(f.read_text(encoding="utf-8"))
                nodes.append(Node.from_dict(data))
        return nodes

    def list_edges(self) -> list[Edge]:
        """List all edges directly from disk."""
        edges = []
        if self.layout.edges.exists():
            for f in sorted(self.layout.edges.glob("*.yaml")):
                data = load_edge(f.read_text(encoding="utf-8"))
                edges.append(Edge.from_dict(data))
        return edges

    def _check_endpoints(
        self,
        edge_type: str,
        from_node: Node,
        to_node: Node,
    ) -> None:
        """Validate edge endpoints according to profile and core edge rules."""
        allowed_edges = self.profile.all_edge_types()
        rule = allowed_edges.get(edge_type)
        if rule is None:
            raise RuleViolation(
                rule="edge_endpoints",
                message=f"Unknown edge type: {edge_type}",
            )

        # Check special rule: supersedes must be same type
        if edge_type == "supersedes" and from_node.type != to_node.type:
            raise RuleViolation(
                rule="edge_endpoints",
                message=f"supersedes edge requires same node types, got {from_node.type} -> {to_node.type}",
            )

        # Check allowed endpoint pairs
        matched = False
        for allowed_from, allowed_to in rule.allowed:
            from_ok = (allowed_from == "*") or (allowed_from == from_node.type)
            to_ok = (allowed_to == "*") or (allowed_to == to_node.type)
            if from_ok and to_ok:
                matched = True
                break

        if not matched:
            raise RuleViolation(
                rule="edge_endpoints",
                message=f"Edge '{edge_type}' not allowed from {from_node.type} to {to_node.type}",
                ids=[from_node.id, to_node.id],
            )

    def _check_cycle(self, new_edges: Sequence[tuple[str, str, str]]) -> None:
        """Check for directed cycles in blocks, derived-from, supersedes, cites edges."""
        # Build adjacency list from existing active edges + new edges
        adj: dict[str, set[str]] = {}
        for edge in self.list_edges():
            if not edge.retired and edge.type in CYCLE_CHECK_EDGE_TYPES:
                adj.setdefault(edge.from_id, set()).add(edge.to_id)

        for edge_type, f_id, t_id in new_edges:
            if edge_type in CYCLE_CHECK_EDGE_TYPES:
                adj.setdefault(f_id, set()).add(t_id)

        # Standard cycle detection using DFS
        visited: dict[str, int] = {}  # 0: visiting, 1: visited

        def dfs(node: str) -> bool:
            visited[node] = 0
            for neighbor in adj.get(node, ()):
                state = visited.get(neighbor)
                if state == 0:
                    return True  # cycle found
                if state is None:
                    if dfs(neighbor):
                        return True
            visited[node] = 1
            return False

        all_nodes = set(adj.keys()) | {t for targets in adj.values() for t in targets}
        for n in all_nodes:
            if n not in visited:
                if dfs(n):
                    raise RuleViolation(
                        rule="cycle",
                        message="Adding edge would create a directed cycle in dependency graph",
                    )

    def propose(
        self,
        type: str,
        title: str,
        body: str = "",
        fields: dict[str, Any] | None = None,
        edges: list[dict[str, Any]] | None = None,
        actor: Actor | None = None,
        commit: bool = True,
    ) -> tuple[Node, list[Edge]]:
        """Propose a new node and optional edges."""
        if self.read_only:
            raise RuleViolation(rule="read_only", message="Cannot write to read-only project")

        if actor is None:
            actor = get_git_actor(self.layout.root)

        # 1. Validate node type
        nt = self.profile.get_node_type(type)
        if nt is None:
            raise RuleViolation(rule="unknown_type", message=f"Unknown node type: {type}")

        # 2. Validate fields
        node_fields = dict(fields or {})
        self.profile.validate_fields(type, node_fields)

        # 3. Determine status
        initial_status = Status.PROPOSED if nt.requires_gate else Status.ACTIVE

        # 4. Prepare node
        node_id = generate_node_id(nt.prefix)
        now = _current_timestamp()

        node = Node(
            id=node_id,
            type=type,
            title=title,
            body=body,
            author=actor,
            created=now,
            fields=node_fields,
            status=initial_status,
            updated=now,
            approvals=[],
            artifacts=[],
            budget=None,
            lease=None,
        )

        # 5. Prepare edges and validate endpoints
        created_edges: list[Edge] = []
        cycle_edges_to_check: list[tuple[str, str, str]] = []

        if edges:
            for e_spec in edges:
                e_type = e_spec["type"]
                # Determine from and to
                if "to" in e_spec:
                    f_node = node
                    t_id = e_spec["to"]
                    t_node = self.get_node(t_id)
                    if t_node is None:
                        raise RuleViolation(
                            rule="edge_endpoints",
                            message=f"Target node {t_id} does not exist",
                            ids=[t_id],
                        )
                elif "from" in e_spec:
                    t_node = node
                    f_id = e_spec["from"]
                    f_node = self.get_node(f_id)
                    if f_node is None:
                        raise RuleViolation(
                            rule="edge_endpoints",
                            message=f"Source node {f_id} does not exist",
                            ids=[f_id],
                        )
                else:
                    raise RuleViolation(
                        rule="edge_endpoints",
                        message="Edge must specify either 'to' or 'from'",
                    )

                self._check_endpoints(e_type, f_node, t_node)
                cycle_edges_to_check.append((e_type, f_node.id, t_node.id))

                edge_id = generate_edge_id()
                created_edge = Edge(
                    id=edge_id,
                    type=e_type,
                    from_id=f_node.id,
                    to_id=t_node.id,
                    author=actor,
                    created=now,
                    retired=False,
                )
                created_edges.append(created_edge)

        # Check cycle
        if cycle_edges_to_check:
            self._check_cycle(cycle_edges_to_check)

        # 6. Atomic writes
        node_file = self.layout.node_file(node.id)
        write_atomic(node_file, dump_node(node.to_dict()))

        edge_files: list[Path] = []
        for edge in created_edges:
            efile = self.layout.edge_file(edge.id)
            write_atomic(efile, dump_edge(edge.to_dict()))
            edge_files.append(efile)

        # 7. Commit if requested
        if commit:
            files_to_commit = [node_file, *edge_files]
            git_commit_files(
                files_to_commit,
                f"rg: propose {node.id}",
                actor,
                cwd=self.layout.root,
            )

        # Update index cache after commit so tree_hash reflects clean git state
        self.index.insert_node(node)
        for edge in created_edges:
            self.index.insert_edge(edge)
        self.index.set_meta("tree_hash", compute_tree_hash(self.layout))

        return node, created_edges


    def ready(self) -> list[Node]:
        """Query ready nodes, oldest first."""
        rows = self.index.get_ready_nodes()
        nodes = []
        for row in rows:
            node = self.get_node(row["id"])
            if node:
                nodes.append(node)
        return nodes

