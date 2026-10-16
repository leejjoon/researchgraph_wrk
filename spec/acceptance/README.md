# Acceptance scenarios
One file per operation. Each scenario is Given / When / Then and maps to at least one test in `tests/`. "the research profile" means a fresh `rg init --profile research` project with one commit. Actors: `alice` (human, owner), `bob` (human, reviewer), `agent1` (agent). Every scenario must also pass with the index deleted before the When step.
