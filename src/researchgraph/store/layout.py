"""Store directory layout and path helpers."""
from __future__ import annotations

from pathlib import Path
import random

BASE32_CHARS = "abcdefghijklmnopqrstuvwxyz234567"


def generate_node_id(prefix: str) -> str:
    """Generate a random node id: <prefix>-<8 lowercase base32 chars>."""
    random_chars = "".join(random.choices(BASE32_CHARS, k=8))
    return f"{prefix}-{random_chars}"


def generate_edge_id() -> str:
    """Generate a random edge id: ed-<8 lowercase base32 chars>."""
    random_chars = "".join(random.choices(BASE32_CHARS, k=8))
    return f"ed-{random_chars}"


class ProjectLayout:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.dot_rg = self.root / ".researchgraph"
        self.profile_file = self.dot_rg / "profile.yaml"
        self.index_file = self.dot_rg / "index.sqlite"
        self.graph = self.root / "graph"
        self.nodes = self.graph / "nodes"
        self.edges = self.graph / "edges"
        self.artifacts = self.root / "artifacts"
        self.gitignore = self.root / ".gitignore"

    def node_file(self, node_id: str) -> Path:
        return self.nodes / f"{node_id}.yaml"

    def edge_file(self, edge_id: str) -> Path:
        return self.edges / f"{edge_id}.yaml"

    def artifact_dir(self, node_id: str) -> Path:
        return self.artifacts / node_id
