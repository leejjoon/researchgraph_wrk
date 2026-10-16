"""CLI for researchgraph."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
import click

from researchgraph import __version__
from researchgraph.model import Actor, RuleViolation
from researchgraph.project import Project


def _parse_agent(agent_str: str | None) -> Actor | None:
    if not agent_str:
        return None
    parts = agent_str.split(":")
    name = parts[0]
    model = parts[1] if len(parts) > 1 else None
    version = parts[2] if len(parts) > 2 else None
    return Actor(kind="agent", name=name, model=model, version=version)


def _handle_error(e: Exception, json_output: bool) -> None:
    if isinstance(e, RuleViolation):
        if json_output:
            click.echo(json.dumps(e.to_dict()), err=True)
        else:
            click.echo(str(e), err=True)
        sys.exit(2)
    click.echo(f"Error: {e}", err=True)
    sys.exit(3)


@click.group()
@click.version_option(__version__, "-v", "--version", prog_name="rg")
@click.option("--project", "project_path", default=".", help="Path to project directory")
@click.option("--json", "json_output", is_flag=True, help="Emit output as JSON")
@click.option("--read-only", is_flag=True, help="Open project in read-only mode")
@click.option("--as-agent", "agent_spec", help="Act as agent: NAME[:MODEL[:VERSION]]")
@click.pass_context
def main(
    ctx: click.Context,
    project_path: str,
    json_output: bool,
    read_only: bool,
    agent_spec: str | None,
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["project_path"] = project_path
    ctx.obj["json"] = json_output
    ctx.obj["read_only"] = read_only
    ctx.obj["actor"] = _parse_agent(agent_spec)


@main.command()
@click.option("--profile", default="research", help="Profile name (default: research)")
@click.pass_context
def init(ctx: click.Context, profile: str) -> None:
    """Initialize a new researchgraph repository."""
    project_path = ctx.obj["project_path"]
    json_output = ctx.obj["json"]
    actor = ctx.obj["actor"]
    try:
        project = Project.init(path=project_path, profile_name=profile, actor=actor)
        if json_output:
            click.echo(json.dumps({"status": "initialized", "profile": profile, "root": str(project.layout.root)}))
        else:
            click.echo(f"Initialized researchgraph project ({profile}) at {project.layout.root}")
    except Exception as e:
        _handle_error(e, json_output)


@main.command()
@click.argument("type")
@click.argument("title")
@click.option("--body", default="", help="Markdown body text")
@click.option("--fields", "fields_json", default=None, help="JSON string for fields")
@click.option("--commit/--no-commit", default=True, help="Commit changes (default: True)")
@click.option("-e", "--edge", "edge_specs", multiple=True, help="Edge spec: TYPE:to=ID or TYPE:from=ID")
@click.pass_context
def propose(
    ctx: click.Context,
    type: str,
    title: str,
    body: str,
    fields_json: str | None,
    commit: bool,
    edge_specs: tuple[str, ...],
) -> None:
    """Propose a new node."""
    project_path = ctx.obj["project_path"]
    json_output = ctx.obj["json"]
    read_only = ctx.obj["read_only"]
    actor = ctx.obj["actor"]

    try:
        project = Project.open(project_path, read_only=read_only)
        fields = json.loads(fields_json) if fields_json else {}

        parsed_edges = []
        for e in edge_specs:
            # Format: TYPE:to=ID or TYPE:from=ID
            parts = e.split(":", 1)
            e_type = parts[0]
            target_spec = parts[1] if len(parts) > 1 else ""
            if target_spec.startswith("to="):
                parsed_edges.append({"type": e_type, "to": target_spec[3:]})
            elif target_spec.startswith("from="):
                parsed_edges.append({"type": e_type, "from": target_spec[5:]})
            else:
                parsed_edges.append({"type": e_type, "to": target_spec})

        node, edges = project.propose(
            type=type,
            title=title,
            body=body,
            fields=fields,
            edges=parsed_edges,
            actor=actor,
            commit=commit,
        )

        if json_output:
            click.echo(json.dumps(node.to_dict()))
        else:
            click.echo(f"Proposed {node.type} {node.id}: {node.title} [{node.status}]")
    except Exception as e:
        _handle_error(e, json_output)


if __name__ == "__main__":
    main()
