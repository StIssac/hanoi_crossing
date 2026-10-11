# Working on Hanoi Crossing

## Source of truth and current scope

- Read the affected code and [README.md](README.md) before making changes. Its
  [rules](README.md#rules), [data model](README.md#data-model),
  [Python API](README.md#python-api-contract), and
  [input/output contract](README.md#input-and-output) define the agreed behavior.
  The class and sequence diagrams explain the module boundaries and call flow.
- The current repository implements immutable data models, constructor
  validation, exports, and interface stubs. Gameplay and both frontends remain
  unimplemented. Do not describe a passing model test as a working game.
- Implement only the requested stage. Keep a pending function's explicit
  `NotImplementedError` until its behavior is implemented; never substitute a
  fabricated successful result. Update the README status when that changes.
- Treat the supplied assignment as requirements to interpret, not permission to
  submit work, contact people, or perform unrelated external actions.

## Implementation boundaries

- Keep the four data classes in `engine.py`: `GameState`, `Observation`, `Action`,
  and `StepResult`. They are frozen, slotted, and deeply immutable. Validate
  mutable or malformed inputs rather than retaining them or silently coercing
  them. Keep tuple order consistent with the documented constants.
- Keep `new_game`, `observe`, `legal_actions`, and `step` as functions with
  explicit state or observation arguments. Use no mutable game globals,
  engine-owned random generator, turn scheduler, file I/O, or frontend imports.
- `observe` is the boundary between referee state and player information.
  `legal_actions` and `random_player.choose_action` receive only an observation;
  the strategy also receives its injected `random.Random` instance.
- `step` validates the submitted action against the actual state. Preserve the
  documented distinction between malformed input and a wasted illegal turn,
  error precedence, unchanged-state identity, and checks for either winner.
- The CLI owns parsing, external turn order, run limits, RNG creation, and
  serialization. Do not duplicate game rules in the CLI or random player.
- Preserve state isolation across games. Any future service must serialize
  observation/action processing per game outside the engine. Do not add an RL
  environment, web service, strategy framework, or extra classes in anticipation
  of that future work.
- Prefer the standard library and the smallest complete change. This project
  currently has no runtime dependencies. Do not add one for functionality the
  standard library already covers adequately.
- Keep the core below 500 physical Python lines, including comments and blank
  lines. Count `engine.py`, `__init__.py`, and any future module containing model,
  validation, rule, or adjudication logic. Moving rules elsewhere does not remove
  them from this count.

## Interfaces, fixtures, and tests

- Trace callers before changing an interface. Update public exports, affected
  tests, README tables/diagrams, and examples together. Keep the established JSON
  contract unless the requested work changes it; document any such change.
- Exercise engine behavior directly with standard-library `unittest`. Add small
  behavioral tests for nontrivial new logic and regressions, including error
  paths; do not use only CLI tests as evidence for the engine.
- Replace the corresponding stub-exception assertions when implementing a
  function. Preserve the model validation and immutability tests.
- Gameplay tests must cover information visibility, arbitrary external turn
  order, invalid-action state preservation, disk conservation, both players'
  win checks, and terminal behavior as specified in the README. Random/replay
  tests must cover legal sampling, reproducibility, stop reasons, and actual
  replay output. Use separate states and RNG instances when checking isolation.
- The current JSON examples are hand-authored contract fixtures. Their shape
  checks do not prove that a replay ran. Once the runner exists, compare its
  real output with the expected fixture.
- Keep `uv.lock` in Git. Do not commit environments, caches, generated artifacts,
  credentials, or unrelated changes. Keep the README AI-assistance disclosure
  accurate as work progresses.

## Validation and reporting

Use uv with the Python version recorded in `.python-version`:

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
git diff --check
wc -l src/hanoi_crossing/engine.py src/hanoi_crossing/__init__.py
```

If core code is added to another module, include it in the line count. The
[setup notes](README.md#setup) document the observed macOS hidden-`.pth` problem
and the external-environment workaround; do not alter package imports or global
Python settings to hide an environment problem.

Report what changed, checks actually run, and remaining implementation limits.
Separate model/interface checks, gameplay tests, and end-to-end frontend checks.
Do not claim that planned commands, hand-authored output, or unrendered diagrams
were executed or rendered. Keep Git commits and external actions within the
human user's requested scope.
