# Operations (normative)

Every operation exists in three doors with the same name and arguments: Python (`Project.<op>(...)`), CLI (`rg <op> ...`, `--json` for machine output), MCP (tool `<op>`, v0.2). Each is marked **read** or **write**. A project opened read-only refuses every write with `RuleViolation(rule="read_only")`.

Every call carries an `actor`: `{kind: human|agent, name, role?, model?, version?}`. CLI derives a human actor from `git config user.name/user.email` unless `--as-agent NAME[:MODEL[:VERSION]]` is given. Roles come from the profile.

Errors are `RuleViolation{rule: str, message: str, ids: [str]}`; the CLI prints them as JSON on stderr and exits 2. Nothing is written on error.

## Writes

| Op | Arguments | Effect | Allowed to (default) | Rules it can raise |
| --- | --- | --- | --- | --- |
| `propose` | `type, title, body?, fields?, edges?: [{type, to|from}]` | Create node in `proposed` (or `active` if the profile has no gate for the type). Create edges. | human, agent | `schema`, `edge_endpoints`, `cycle`, `unknown_type` |
| `approve` | `node, what?, note?` | Record approval; if all gates for the pending transition are satisfied, `proposed → active`. | human; profile may delegate per gate | `human_only_approval`, `wrong_role`, `not_proposed`, `already_approved` |
| `reject` | `node, reason` | `proposed → retired`, note recorded. | human | `not_proposed` |
| `supersede` | `node, title?, body?, fields?, inherit_edges?: bool=true, instruction?` | Create replacement node (same type), `supersedes` edge, retire old node and its non-retired edges, recreate inherited edges from the replacement. If `instruction` given, also create an Instruction node with an `instructs` edge to the replacement. | human for any type; agent for Task and Result only | `agent_cannot_supersede_type`, `terminal_status`, `cycle` |
| `instruct` | `node, text` | Create Instruction node + `instructs` edge to a node whose status is `proposed` or `active`. | human | `already_ran` |
| `claim` | `node, lease_seconds=7200` | If `ready(node)`: `active → running`, set lease. | agent, runner (human allowed) | `not_ready`, `lease_held` |
| `release` | `node, note?` | `running → active`, clear lease. Only the lease holder or a human. | agent, runner, human | `not_lease_holder` |
| `complete` | `node, summary, artifacts?: [path]` | `running → done`; hash and record artifacts; clear lease. | lease holder | `not_lease_holder`, `artifact_missing` |
| `fail` | `node, step?, check?, measured?, error?, summary` | `running → failed`; create Failure node + `explains` edge; clear lease. | lease holder | `not_lease_holder` |
| `expand` | `nodes: [id], hint?` | Create one Expansion task (type `Task`, `fields.kind = expansion`, `fields.targets = nodes`) in `active`. The core never executes it. | human | `no_targets` |
| `budget` | `node, tokens?, compute_seconds?` | Set `budget`. Setting both to 0 means stop. | human | — |
| `export` | `out, include_artifacts?: bool, since?` | Write a tar.zst with `graph/`, `.researchgraph/profile.yaml`, status intervals as JSONL, and optionally artifacts. Import of that archive into an empty project must reproduce the files byte for byte. | human | — |

Budget is enforced only as a query (`where --over-budget`) and a `ready` exclusion: a node whose subtree budget is exhausted is not ready. The core does not meter tokens; consumers write usage into `fields` via `complete`/`fail`.

## Reads

| Query | Returns |
| --- | --- |
| `show <id>` | the node or edge, with derived flags `blocked`, `ready`, `stale` |
| `ready` | nodes with `ready(n)`, oldest first |
| `blocked` | nodes with `blocked(n)` and the ids blocking them |
| `queue` | nodes awaiting approval, with the gate and roles that can satisfy it, oldest first |
| `history <id>` | the supersedes chain (both directions) and all status/approval/artifact changes with commits |
| `evidence <claim>` | nodes reachable via `cites` then `derived-from`, with artifacts |
| `stale` | claims with `stale(c)` and the superseding node responsible |
| `weakest <claim>` | the `cites` targets ranked ascending by: number of distinct runs producing them, presence of a held-out flag in `fields`, whether any input is superseded |
| `alternatives <hypothesis>` | other members of its exclusion group with status and supporting/contradicting claims |
| `since <time>` | nodes and edges changed after `time` |
| `where <filter>` | `--type`, `--status`, `--author`, `--field k=v`, `--over-budget` |
| `digest` | counts of running/ready/blocked/awaiting/failed-24h/claims, and the lists behind them |

Every read accepts `--as-of <time|commit>`.

## CLI conventions
- `rg --project PATH` or run inside the project.
- `--json` emits one JSON object (or array) on stdout; without it, a human table.
- `--commit/--no-commit` on writes (default commit).
- `--read-only` opens the project read-only for the whole invocation.
- Exit codes: 0 ok, 2 RuleViolation, 3 project not found or invalid.
