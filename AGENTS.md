# Working on Hanoi Crossing

## Source of truth and current scope

- Read the affected code and [README.md](README.md) before making changes. Its
  [rules](README.md#rules), [data model](README.md#data-model),
  [Python API](README.md#python-api-contract), and
  [input/output contract](README.md#input-and-output) define the agreed behavior.
  The class and sequence diagrams explain the module boundaries and call flow.
- The current repository implements immutable models and the four core engine
  functions: initialization, observation, legal actions, and atomic transitions
  with adjudication, plus fixed player-relative action IDs and conversions.
  Uniform random selection, replay/random runners, human-versus-random play,
  local hot-seat PvP, observation-only Agents, and Episode archives are also
  implemented. Keep direct engine, runner, and real CLI checks distinct.
- Implement only the requested scope. Do not add an intelligent strategy or
  other future features. Update the README when observable behavior changes.
- Treat the supplied assignment as requirements to interpret, not permission to
  submit work, contact people, or perform unrelated external actions.

## Implementation boundaries

- Keep the four data classes in `engine.py`: `GameState`, `Observation`, `Action`,
  and `StepResult`. They are frozen, slotted, and deeply immutable. Validate
  mutable or malformed inputs rather than retaining them or silently coercing
  them. Keep tuple order consistent with the documented constants.
- `GameState` construction centrally validates inventory, stack order, and
  winner consistency. Reject contradictory winner labels or simultaneous winners
  with `ValueError`; do not add a tiebreak or historical reachability search.
  Compute a transition's winner before constructing its new state, with no
  externally visible unadjudicated intermediate `GameState`.
- Keep `new_game`, `observe`, `legal_actions`, and `step` as functions with
  explicit state or observation arguments. Use no mutable game globals,
  engine-owned random generator, turn scheduler, file I/O, or frontend imports.
- `observe` is the boundary between referee state and player information.
  `legal_actions` and `random_player.choose_action` receive only an observation;
  the strategy also receives its injected `random.Random` instance.
- `step` validates the submitted action against the actual state. Preserve the
  documented distinction between malformed input and a wasted illegal turn,
  error precedence, unchanged-state identity, and checks for either winner.
- Preserve `ACTION_IDS = (0, 1, 2, 3, 4, 5, 6)`: skip, lift start/shared/goal,
  then place start/shared/goal. `action_from_id` and `action_to_id` depend only
  on the player and ID/action, not state or legality. Reuse the visibility
  mapping; never use an index into the current legal-action list as a fixed ID.
  Encoding hidden poles raises `ValueError`; submitting such an `Action`
  directly to `step` still returns `invisible_pole` during ongoing play.
  Keep replay JSON in its existing `kind/pole` format.
- The CLI owns parsing, external turn order, run limits, RNG creation, and
  serialization. It also records Episodes and owns archive file I/O. Do not
  duplicate game rules in the CLI or random player.
- Validate the complete replay, including an unexecuted tail, before `new_game`.
  Protocol failures raise `cli.InputError`; do not relabel runtime engine or
  serialization exceptions as input errors. Keep duplicate-key and nonstandard
  JSON-number rejection at the file-decoding boundary. `run_replay` and
  `run_random` perform no I/O; `run_interactive` owns terminal input and output.
  Interactive rendering takes only the human observation. Never print the
  opponent's private poles, hand, or specific actions, even after a win.
  Valid action IDs reach `step` and consume attempts even when rejected. Help,
  malformed input, and quitting do not consume turns. A starts, players
  alternate, and quitting/EOF declares no winner. Local PvP requires explicit
  handoff confirmation before observing/rendering the next player's view.
  Clearing the terminal is convenience, not isolation from scrollback/bystanders.
- Keep `AgentBase` and frozen/slotted `Decision` in `agents.py`, which counts
  toward the core limit. Each player has a separate Agent, reset once per game
  with only public player/n context. Stateful subclasses must clear their own
  memory. `act` receives only the actor's Observation and returns a fixed ID;
  no GameState, Episode, or opponent information. Optional log_prob/value must
  be finite numbers or None; never fabricate missing values as zero.
- `RandomAgent` belongs in `random_player.py` and reuses `choose_action`.
  `HumanAgent` belongs in `cli.py`; quit/EOF are controls, never skip decisions.
  Random/play/PvP share scheduling and recording. Replay retains its arbitrary
  explicit actor sequence and kind/pole actions without going through Agents.
- Random selection is exactly `rng.choice` over the complete legal action
  tuple, including skip, with no heuristic filtering or retries. Use one
  independent `Random(seed)` per run, shared by alternating A/B turns. Freshly
  observe, select, and step on each turn. Agent reset never reseeds this RNG.
  A rejected automated action is a defect: record the failed step, save a failed
  archive in the CLI, exit nonzero, and never retry or emit a successful report.
- Count skips and illegal replay actions as attempts. Stop immediately on any
  winner, including one created by the opponent's action or on the last allowed
  step. Exhaustion and step limits mean no winner, not an automatic draw.
- Preserve state isolation across games. Any future service must serialize
  observation/action processing per game outside the engine. The approved
  AgentBase/Decision adapters are the complete agent scope: no RL environment,
  intelligent strategies, trainer, network PvP, database, or framework expansion.
- Each Episode event is one committed step attempt with pre-action observation,
  fixed seven-bit boolean mask, raw action, derived ID, and error. Build masks
  only from that Observation and legal_actions. Preserve invisible replay actions
  with action_id=None; do not discard the raw action or error. Record optional
  policy data from the actual Decision, not reconstructed guesses.
- State and trace length must share one checkpoint so interrupts cannot archive
  an advanced state with a missing event or an uncommitted event with an old
  state. Help/malformed input/control operations are not steps. Preserve the
  unexecuted replay tail separately. Winner takes priority over limits.
- Default CLI archives are UTF-8 `runs/<uuid>.json`, ignored by Git. Serialize
  before writing, use a same-directory temporary file, flush, and publish
  atomically without overwrite; clean only the current temporary file. Fail
  explicitly on collision/write errors. Preserve batch stdout as one old-format
  report; diagnostics belong on stderr. Never pass archives to Agents or dump
  opponent information onto player screens. Python batch APIs perform no file I/O.
- Archive status separates winner/terminated, limit-or-exhaustion/truncated,
  quit-or-EOF-or-interrupt/aborted, and rule-illegal automated action/failed.
  Handled Ctrl-C saves the last checkpoint and retains exit 130; no automatic
  forfeit or draw. Unknown code/policy provenance is null, not an invented version.
- Future RL conversion must link the same player's actual decision views,
  read recorded actors rather than assuming parity, use winner rather than last
  actor for rewards, and distinguish terminal/truncation/bootstrap. These archives
  are not PPO batches; no RL adapter or training exporter is part of this scope.
- Prefer the standard library and the smallest complete change. This project
  currently has no runtime dependencies. Do not add one for functionality the
  standard library already covers adequately.
- Keep the core below 500 physical Python lines, including comments and blank
  lines. Count `engine.py`, `__init__.py`, `agents.py`, and any future module containing model,
  validation, rule, or adjudication logic. Moving rules elsewhere does not remove
  them from this count. `test_core_size.py` counts every package Python file
  except the two existing frontend modules, so new core helpers count by default.

## Interfaces, fixtures, and tests

- Trace callers before changing an interface. Update public exports, affected
  tests, README tables/diagrams, and examples together. Keep the established JSON
  contract unless the requested work changes it; document any such change.
- Exercise engine behavior directly with standard-library `unittest`. Add small
  behavioral tests for nontrivial new logic and regressions, including error
  paths; do not use only CLI tests as evidence for the engine.
- Preserve the model validation, immutability, and direct gameplay tests.
- Cover all seven IDs for both players, round trips, changing legal-action
  sets, invalid IDs/types/players, and private-pole encoding errors. Count the
  conversion functions, constants, and exports as core Python lines.
- Gameplay tests must cover information visibility, arbitrary external turn
  order, invalid-action state preservation, disk conservation, both players'
  win checks, and terminal behavior as specified in the README. Random/replay
  tests must cover legal sampling, reproducibility, stop reasons, and actual
  replay output. Use separate states and RNG instances when checking isolation.
- The JSON examples are hand-authored contract fixtures. Compare real runner
  and registered CLI output with the expected fixture. Replay sampled random
  trajectories to check identical final states and action results.
- Test the registered console entry point, stdout JSON, stderr diagnostics,
  and exit statuses. Preserve input rejection, no silent internal failures,
  output write/flush errors, and keyboard-interrupt handling.
- Verify agent lifecycle, seeded trajectory parity, Episode replay (including
  hidden actions), PvP handoff/abort boundaries, and archive collisions/errors.
  All CLI tests must run in temporary working directories so automatic archives
  never pollute the repository. Keep [the dataset guide](docs/DATASET_GUIDE.md)
  aligned with the actual schema and public collection commands.
- Keep `uv.lock` in Git. Do not commit environments, caches, generated artifacts,
  credentials, or unrelated changes. Keep the README AI-assistance disclosure
  accurate as work progresses.

## Validation and reporting

Use uv with the Python version recorded in `.python-version`:

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
git diff --check
wc -l src/hanoi_crossing/engine.py src/hanoi_crossing/__init__.py src/hanoi_crossing/agents.py
```

If core code is added to another module, include it in the line count. The
[setup notes](README.md#setup) document the observed macOS hidden-`.pth` problem
and the ignored `.venv` symlink to a persistent external environment. Normal
`uv run` must work without temporary-directory overrides. Do not alter package
imports or global Python settings to hide an environment problem.

Report what changed, checks actually run, and remaining implementation limits.
Separate model/interface checks, gameplay tests, and end-to-end frontend checks.
Do not claim that planned commands, hand-authored output, or unrendered diagrams
were executed or rendered. Keep Git commits and external actions within the
human user's requested scope.
