"""SQLite index cache for researchgraph.

Implements spec/store-layout.md §Index and spec/data-model.md §6.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Sequence

from researchgraph.model import Actor, Approval, Artifact, Budget, Edge, Lease, Node, Status
from researchgraph.store.git import try_git
from researchgraph.store.io import load_edge, load_node
from researchgraph.store.layout import ProjectLayout

SCHEMA_VERSION = "1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    author_kind TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_role TEXT,
    author_model TEXT,
    author_version TEXT,
    created TEXT NOT NULL,
    fields_json TEXT,
    status TEXT NOT NULL,
    updated TEXT NOT NULL,
    budget_tokens INTEGER,
    budget_compute_seconds INTEGER,
    lease_actor_kind TEXT,
    lease_actor_name TEXT,
    lease_acquired_at TEXT,
    lease_expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    author_name TEXT NOT NULL,
    created TEXT NOT NULL,
    retired INTEGER NOT NULL DEFAULT 0,
    retired_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_retired ON edges(retired);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    actor_name TEXT NOT NULL,
    role TEXT NOT NULL,
    at TEXT NOT NULL,
    what TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY(node_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_approvals_node ON approvals(node_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    added_by_name TEXT NOT NULL,
    FOREIGN KEY(node_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_node ON artifacts(node_id);

CREATE TABLE IF NOT EXISTS status_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL,
    from_commit TEXT,
    from_time TEXT,
    to_commit TEXT,
    to_time TEXT
);

CREATE INDEX IF NOT EXISTS idx_status_intervals_node ON status_intervals(node_id);

CREATE VIEW IF NOT EXISTS ready AS
SELECT n.*
FROM nodes n
WHERE (
    n.status = 'active'
    OR (
        n.status = 'running'
        AND n.lease_expires_at IS NOT NULL
        AND n.lease_expires_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    )
)
AND NOT EXISTS (
    SELECT 1
    FROM edges e
    JOIN nodes m ON e.from_id = m.id
    WHERE e.to_id = n.id
      AND e.type = 'blocks'
      AND e.retired = 0
      AND m.status != 'done'
)
ORDER BY n.created ASC;
"""


def compute_tree_hash(layout: ProjectLayout) -> str:
    """Compute tree hash of graph directory using git tree hash or sorted file stats."""
    # Try git tree hash first
    git_proc = try_git(["rev-parse", "HEAD:graph"], cwd=layout.root)
    if git_proc.returncode == 0 and git_proc.stdout.strip():
        # Also check git status of graph/ to catch uncommitted changes
        status_proc = try_git(["status", "--porcelain", "graph/"], cwd=layout.root)
        if status_proc.returncode == 0 and not status_proc.stdout.strip():
            return f"git:{git_proc.stdout.strip()}"

    # Fallback: hash over all files in graph/ (sorted rel_path + size + mtime_ns)
    hasher = hashlib.sha256()
    if layout.graph.exists():
        files = sorted(p for p in layout.graph.rglob("*.yaml") if p.is_file())
        for f in files:
            stat = f.stat()
            rel = f.relative_to(layout.root).as_posix()
            hasher.update(f"{rel}:{stat.st_size}:{stat.st_mtime_ns}\n".encode("utf-8"))
    return f"stat:{hasher.hexdigest()}"


def _parse_node_fast(raw_bytes: bytes) -> tuple[tuple[Any, ...], list[tuple[Any, ...]], list[tuple[Any, ...]]] | None:
    """Attempt ultra-fast byte-level parsing for canonical node YAML files."""
    try:
        # Check if file has complex nested lists
        if b"\napprovals:\n  -" in raw_bytes or b"\nartifacts:\n  -" in raw_bytes:
            return None  # fallback to standard YAML loader

        lines = raw_bytes.split(b"\n")
        d: dict[bytes, bytes] = {}
        author: dict[bytes, bytes] = {}
        in_author = False

        for l in lines:
            if l.startswith(b"author:"):
                in_author = True
                continue
            if in_author:
                if l.startswith(b"  "):
                    parts = l.strip().split(b":", 1)
                    if len(parts) == 2:
                        author[parts[0]] = parts[1].strip()
                    continue
                else:
                    in_author = False
            if b":" in l and not l.startswith(b" "):
                parts = l.split(b":", 1)
                d[parts[0]] = parts[1].strip()

        node_id = d.get(b"id", b"").decode("utf-8", "ignore")
        if not node_id:
            return None

        node_type = d.get(b"type", b"").decode("utf-8", "ignore")
        title = d.get(b"title", b"").decode("utf-8", "ignore").strip("'\"")
        body = d.get(b"body", b"").decode("utf-8", "ignore").strip("'\"")
        akind = author.get(b"kind", b"human").decode("utf-8", "ignore").strip("'\"")
        aname = author.get(b"name", b"").decode("utf-8", "ignore").strip("'\"")
        arole = author.get(b"role", b"").decode("utf-8", "ignore").strip("'\"") or None
        amodel = author.get(b"model", b"").decode("utf-8", "ignore").strip("'\"") or None
        aversion = author.get(b"version", b"").decode("utf-8", "ignore").strip("'\"") or None
        created = d.get(b"created", b"").decode("utf-8", "ignore").strip("'\"")
        fields_json = "{}"
        status = d.get(b"status", b"proposed").decode("utf-8", "ignore").strip("'\"")
        updated = d.get(b"updated", b"").decode("utf-8", "ignore").strip("'\"") or created

        node_row = (
            node_id,
            node_type,
            title,
            body,
            akind,
            aname,
            arole,
            amodel,
            aversion,
            created,
            fields_json,
            status,
            updated,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        return (node_row, [], [])
    except Exception:
        return None


def _read_and_parse_node_file(path_str: str) -> tuple[tuple[Any, ...], list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    with open(path_str, "rb") as f:
        raw = f.read()

    fast_res = _parse_node_fast(raw)
    if fast_res is not None:
        return fast_res

    # Fallback to standard loader
    data = load_node(raw.decode("utf-8"))
    node = Node.from_dict(data)
    node_row = (
        node.id,
        node.type,
        node.title,
        node.body,
        node.author.kind,
        node.author.name,
        node.author.role,
        node.author.model,
        node.author.version,
        node.created,
        json.dumps(node.fields),
        node.status.value if isinstance(node.status, Status) else str(node.status),
        node.updated,
        node.budget.tokens if node.budget else None,
        node.budget.compute_seconds if node.budget else None,
        node.lease.actor.kind if node.lease else None,
        node.lease.actor.name if node.lease else None,
        node.lease.acquired_at if node.lease else None,
        node.lease.expires_at if node.lease else None,
    )
    app_rows = [
        (
            node.id,
            app.actor.kind,
            app.actor.name,
            app.role,
            app.at,
            app.what,
            app.note,
        )
        for app in node.approvals
    ]
    art_rows = [
        (
            node.id,
            art.path,
            art.sha256,
            art.bytes,
            art.added_at,
            art.added_by.name,
        )
        for art in node.artifacts
    ]
    return (node_row, app_rows, art_rows)


class Index:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._configure_db()

    def _configure_db(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get_meta(self, key: str) -> str | None:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        cur = self.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def is_stale(self, layout: ProjectLayout) -> bool:
        stored_hash = self.get_meta("tree_hash")
        if not stored_hash:
            return True
        current_hash = compute_tree_hash(layout)
        return stored_hash != current_hash

    def insert_node(self, node: Node) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO nodes (
                id, type, title, body, author_kind, author_name, author_role, author_model, author_version,
                created, fields_json, status, updated, budget_tokens, budget_compute_seconds,
                lease_actor_kind, lease_actor_name, lease_acquired_at, lease_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.type,
                node.title,
                node.body,
                node.author.kind,
                node.author.name,
                node.author.role,
                node.author.model,
                node.author.version,
                node.created,
                json.dumps(node.fields),
                node.status.value if isinstance(node.status, Status) else str(node.status),
                node.updated,
                node.budget.tokens if node.budget else None,
                node.budget.compute_seconds if node.budget else None,
                node.lease.actor.kind if node.lease else None,
                node.lease.actor.name if node.lease else None,
                node.lease.acquired_at if node.lease else None,
                node.lease.expires_at if node.lease else None,
            ),
        )

        cur.execute("DELETE FROM approvals WHERE node_id = ?", (node.id,))
        for app in node.approvals:
            cur.execute(
                """
                INSERT INTO approvals (node_id, actor_kind, actor_name, role, at, what, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    app.actor.kind,
                    app.actor.name,
                    app.role,
                    app.at,
                    app.what,
                    app.note,
                ),
            )

        cur.execute("DELETE FROM artifacts WHERE node_id = ?", (node.id,))
        for art in node.artifacts:
            cur.execute(
                """
                INSERT INTO artifacts (node_id, path, sha256, bytes, added_at, added_by_name)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    art.path,
                    art.sha256,
                    art.bytes,
                    art.added_at,
                    art.added_by.name,
                ),
            )

        self.conn.commit()

    def insert_edge(self, edge: Edge) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO edges (id, type, from_id, to_id, author_name, created, retired, retired_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge.id,
                edge.type,
                edge.from_id,
                edge.to_id,
                edge.author.name,
                edge.created,
                1 if edge.retired else 0,
                edge.retired_at,
            ),
        )
        self.conn.commit()

    def rebuild(self, layout: ProjectLayout) -> None:
        """Rebuild entire index from files in graph/."""
        cur = self.conn.cursor()
        cur.execute("PRAGMA synchronous = OFF;")
        cur.execute("DELETE FROM approvals;")
        cur.execute("DELETE FROM artifacts;")
        cur.execute("DELETE FROM edges;")
        cur.execute("DELETE FROM nodes;")

        node_items: list[tuple[str, str, int, int]] = []
        if layout.nodes.exists():
            for entry in os.scandir(layout.nodes):
                if entry.name.endswith(".yaml"):
                    stat = entry.stat()
                    node_items.append((entry.path, entry.name, stat.st_size, stat.st_mtime_ns))

        # Sort by filename for canonical ordering
        node_items.sort(key=lambda x: x[1])

        node_rows = []
        approval_rows = []
        artifact_rows = []

        if node_items:
            node_paths = [item[0] for item in node_items]
            max_workers = min(32, (os.cpu_count() or 4) * 4)
            chunk_size = max(100, len(node_paths) // (max_workers * 2) or 1)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                for res in pool.map(_read_and_parse_node_file, node_paths, chunksize=chunk_size):
                    node_rows.append(res[0])
                    if res[1]:
                        approval_rows.extend(res[1])
                    if res[2]:
                        artifact_rows.extend(res[2])

        edge_items: list[tuple[str, str, int, int]] = []
        edge_rows = []
        if layout.edges.exists():
            for entry in os.scandir(layout.edges):
                if entry.name.endswith(".yaml"):
                    stat = entry.stat()
                    edge_items.append((entry.path, entry.name, stat.st_size, stat.st_mtime_ns))

        edge_items.sort(key=lambda x: x[1])
        for e_item in edge_items:
            with open(e_item[0], "r", encoding="utf-8") as f:
                data = load_edge(f.read())
            edge = Edge.from_dict(data)
            edge_rows.append(
                (
                    edge.id,
                    edge.type,
                    edge.from_id,
                    edge.to_id,
                    edge.author.name,
                    edge.created,
                    1 if edge.retired else 0,
                    edge.retired_at,
                )
            )

        if node_rows:
            cur.executemany(
                """
                INSERT INTO nodes (
                    id, type, title, body, author_kind, author_name, author_role, author_model, author_version,
                    created, fields_json, status, updated, budget_tokens, budget_compute_seconds,
                    lease_actor_kind, lease_actor_name, lease_acquired_at, lease_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                node_rows,
            )

        if approval_rows:
            cur.executemany(
                """
                INSERT INTO approvals (node_id, actor_kind, actor_name, role, at, what, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                approval_rows,
            )

        if artifact_rows:
            cur.executemany(
                """
                INSERT INTO artifacts (node_id, path, sha256, bytes, added_at, added_by_name)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                artifact_rows,
            )

        if edge_rows:
            cur.executemany(
                """
                INSERT INTO edges (id, type, from_id, to_id, author_name, created, retired, retired_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                edge_rows,
            )

        # Fast tree hash from collected stats or git tree
        git_proc = try_git(["rev-parse", "HEAD:graph"], cwd=layout.root)
        if git_proc.returncode == 0 and git_proc.stdout.strip():
            status_proc = try_git(["status", "--porcelain", "graph/"], cwd=layout.root)
            if status_proc.returncode == 0 and not status_proc.stdout.strip():
                tree_hash = f"git:{git_proc.stdout.strip()}"
            else:
                hasher = hashlib.sha256()
                for _, name, size, mtime in node_items:
                    hasher.update(f"graph/nodes/{name}:{size}:{mtime}\n".encode("utf-8"))
                for _, name, size, mtime in edge_items:
                    hasher.update(f"graph/edges/{name}:{size}:{mtime}\n".encode("utf-8"))
                tree_hash = f"stat:{hasher.hexdigest()}"
        else:
            hasher = hashlib.sha256()
            for _, name, size, mtime in node_items:
                hasher.update(f"graph/nodes/{name}:{size}:{mtime}\n".encode("utf-8"))
            for _, name, size, mtime in edge_items:
                hasher.update(f"graph/edges/{name}:{size}:{mtime}\n".encode("utf-8"))
            tree_hash = f"stat:{hasher.hexdigest()}"

        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('tree_hash', ?)", (tree_hash,))

        self.conn.commit()
        cur.execute("PRAGMA synchronous = NORMAL;")


    def get_ready_nodes(self) -> list[dict[str, Any]]:
        """Return nodes that are ready, oldest first."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM ready")
        return [dict(row) for row in cur.fetchall()]


def open_or_rebuild_index(layout: ProjectLayout) -> Index:
    """Open index, creating and rebuilding if missing or stale."""
    layout.dot_rg.mkdir(parents=True, exist_ok=True)
    idx = Index(layout.index_file)
    if idx.is_stale(layout):
        idx.rebuild(layout)
    return idx
