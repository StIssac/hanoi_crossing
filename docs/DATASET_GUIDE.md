# Building and Using Hanoi Crossing Datasets

This guide explains how to collect game episodes, validate their contents, and
prepare player-visible samples for analysis and future learning experiments.
It targets the `hanoi-crossing-episode-v1` archive format. Read the
[README](../README.md) for game rules and CLI reference.

The repository supplies a game engine, uniform random agents, replay, and
interactive play. It does **not** supply a trained policy, a Gymnasium environment,
a PPO trainer, or a dataset training command. The collection and inspection
recipes below are executable examples; the RL integration section describes
work that a separate training application must implement.

## 1. Prepare a reproducible checkout

Run from the repository root:

```sh
uv sync --locked
uv run --locked hanoi-crossing --help
uv run --locked python -m unittest discover -s tests -v
```

The help output must include `random`, `replay`, `play`, and `pvp`. Use the
Episode-enabled checkout before following this guide. Python 3.14 or newer is
required. Consult the README if your local environment needs setup.

Keep the source and Python environment fixed throughout a collection run.
Record the Git revision and retain `uv.lock` with your experiment notes. Archive
metadata also records the source hash and Python version. A seed alone does not
identify a reproducible experiment, and a source hash alone does not restore the
source files. Preserve the matching checkout or patch.

## 2. Collect complete game records

### Collect one random episode

```sh
uv run --locked hanoi-crossing random --n 2 --seed 42 --max-steps 256
```

The command prints the existing run report to stdout and saves a richer Episode
archive under `runs/<episode_id>.json`, relative to the process working directory.
The filename is a generated UUID; the stdout report does not contain the archive
path. Use an isolated working directory or the manifest recipe below to associate
an invocation with its file. A run without a winner is still a useful recorded run.

Random play starts with A and alternates players. Each player samples uniformly
from **all** legal actions, including skip. Both agents share one per-game
`Random(seed)` instance. This is exploration data, not expert demonstrations.
`max_steps` counts atomic action attempts, not pairs of player turns.

### Collect human decisions or a scripted scenario

```sh
uv run --locked hanoi-crossing play --n 2 --human A --seed 42 --max-steps 256
uv run --locked hanoi-crossing pvp --n 2 --max-steps 256
uv run --locked hanoi-crossing replay examples/replay.json
```

Human play uses the same action IDs and engine. A valid ID that requests an
illegal move consumes a turn and produces an event with an error. Help and
malformed terminal input do not produce game events. Quitting, EOF, and a handled
keyboard interrupt preserve completed events as an aborted run; they do not
award the opponent a win. Inspect the exit status as well as any saved file.
During final archive publication, Ctrl-C is deferred until the file is complete;
the process then exits with status 130 while retaining the already-recorded game
outcome. An automated agent's rule-illegal action produces a `failed` archive
with `agent_error`, keeps that attempt, and exits nonzero without retrying.

Local PvP uses a shared terminal. Players must cooperate during handoff; clearing
the display does not prevent access to terminal history. The full archive
contains both players' information and is intended for the experiment operator.

### Build a small, separated dataset

The following recipe launches the registered CLI from a fresh dataset directory,
records every generated file in a manifest, and hashes its bytes. It uses only
the standard library. No private Episode builder is imported.

This is a **12-episode collection example**, not a claim that 12 episodes are
enough for training. Increase the seed ranges and horizon after inspecting
completion rates and storage costs. Different N values should remain identifiable.

Run from the repository root:

```sh
uv run --locked python - <<'PY'
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

cli = shutil.which("hanoi-crossing")
if cli is None:
    raise SystemExit("Run this recipe through uv in the configured repository.")

base = Path("runs/datasets").resolve()
base.mkdir(parents=True, exist_ok=True)
root = Path(tempfile.mkdtemp(prefix="random-v1-", dir=base))
splits = {"train": range(4), "validation": range(4, 5), "test": range(5, 6)}
entries = []
source_versions = set()

for split, seeds in splits.items():
    for n in (2, 3):
        work = root / split / f"n{n}"
        work.mkdir(parents=True)
        for seed in seeds:
            before = set((work / "runs").glob("*.json"))
            subprocess.run(
                [cli, "random", "--n", str(n), "--seed", str(seed),
                 "--max-steps", "256"],
                cwd=work, stdout=subprocess.DEVNULL, check=True,
            )
            created = set((work / "runs").glob("*.json")) - before
            if len(created) != 1:
                raise RuntimeError(f"Expected one new archive, found {len(created)}")
            path = created.pop()
            raw = path.read_bytes()
            episode = json.loads(raw)
            meta = episode["metadata"]
            if (meta["n"], meta["seed"]) != (n, seed):
                raise RuntimeError("Archive does not match the requested run")
            if meta["source_sha256"] is None:
                raise RuntimeError("Source fingerprint is unavailable; preserve provenance first")
            source_versions.add((meta["source_sha256"], meta["python_version"]))
            entries.append({
                "path": str(path.relative_to(root)), "split": split,
                "episode_id": episode["episode_id"], "n": n, "seed": seed,
                "sha256": hashlib.sha256(raw).hexdigest(),
            })

if len(source_versions) != 1:
    raise RuntimeError("Source or Python version changed during collection")
manifest = {"manifest_version": 1, "entries": entries}
with (root / "manifest.json").open("x", encoding="utf-8") as stream:
    json.dump(manifest, stream, indent=2, allow_nan=False)
    stream.write("\n")
print(f"Dataset: {root}")
print(f"Episodes: {len(entries)}")
PY
```

The resulting layout is:

```text
runs/datasets/random-v1-<unique>/
    manifest.json
    train/n2/runs/<episode_id>.json
    train/n3/runs/<episode_id>.json
    validation/n2/runs/<episode_id>.json
    validation/n3/runs/<episode_id>.json
    test/n2/runs/<episode_id>.json
    test/n3/runs/<episode_id>.json
```

The CLI always uses `runs/` within its working directory; there is no dataset
output-directory option in this recipe. Python calls to `run_random(...)` and
`run_replay(...)` return the compatible, smaller reports and perform no file I/O.
Those reports are not Episode archives and should not be renamed as if they were.

Each invocation gets a fresh dataset directory, so repeating the recipe does not
overwrite an earlier collection. A failed batch may leave useful raw episodes,
but a missing manifest means that batch did not complete. Do not silently include
it in a published dataset.

## 3. Understand the archive

An Episode contains `schema_version`, `episode_id`, `metadata`, `events`, and
`end`. It is ordinary JSON, not a tensor file or a replay input document.

| Location | Meaning |
| --- | --- |
| `metadata.n`, `mode`, `seed`, `max_steps` | Run configuration; values can be null when not applicable. |
| `metadata.schedule` | Alternating play with first player A, or an explicit replay player sequence. |
| `metadata.versions` | Rules, action-ID, and observation format versions. |
| `metadata.agents` | Agent type and policy version for each seat. |
| `metadata.source_sha256`, `python_version` | Source fingerprint and interpreter version; unknown provenance must remain identifiable. |
| `events` | One entry per completed call to the engine's atomic transition function. |
| `end` | Final referee state, winner, status, stop reason, attempt count, and unexecuted replay tail. |

An event for A lifting its smallest starting disk at N=2 looks like this:

```json
{
  "ply": 0,
  "player": "A",
  "observation": {
    "player": "A",
    "visible_poles": [[3, 1], [], []],
    "hand": null,
    "winner": null
  },
  "action_mask": [true, true, false, false, false, false, false],
  "action": {"kind": "lift", "pole": "1a"},
  "action_id": 1,
  "error": null,
  "policy_data": null
}
```

`observation` is the acting player's view **before** the action. Its three stacks
are ordered `(own start, shared, own goal)`, each from bottom to top. It contains
the player's own hand, not the opponent's hand. N is available in run metadata;
it must not be inferred from the currently visible inventory.

The stable action vocabulary is:

| ID | Meaning |
| --- | --- |
| 0 | Skip |
| 1 / 2 / 3 | Lift from own start / shared / own goal |
| 4 / 5 / 6 | Place on own start / shared / own goal |

The mask always has seven Boolean entries in this order. `true` means currently
legal. An ID is never an index into a changing list of legal actions. Terminal
observations have no legal actions; an ongoing observation always permits skip.

The raw `action` is authoritative for replay. An attempt to access an invisible
pole is representable in replay JSON but not in the seven player-relative IDs:
its `action_id` is null and its error is `invisible_pole`. Other rule-illegal
actions can have a non-null ID with a false mask entry. Keep these events for
auditing; do not silently convert them into legal policy examples.

`policy_data` is null for the current random and human agents. When supplied by
a future agent, its `log_prob` and `value` must describe the actual behavior policy
at collection time, using the same observation and action mask. Missing values
do not mean zero. Preserve the matching policy/checkpoint identity separately
when developing a training application.

## 4. Validate before using the data

Checks should establish that files are intact and that the trace agrees with the
engine. They do not establish that the behavior is intelligent or the dataset is
large enough. Use the matching source version for validation; a disagreement
after changing rules is not permission to rewrite old records.

Set the dataset path printed by the collection recipe:

```sh
export HANOI_DATASET='/absolute/path/to/random-v1-<unique>'
```

Run this checker through the same checkout. It is a consistency check for local,
generated archives, not a complete validator for arbitrary untrusted files. Do
not run it with Python's `-O` flag, which disables its assertions.

```sh
uv run --locked python - <<'PY'
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from hanoi_crossing import (
    ACTION_IDS, PLAYERS, POLE_IDS, Action, action_to_id,
    legal_actions, new_game, observe, step,
)

root = Path(os.environ["HANOI_DATASET"])
manifest = json.loads((root / "manifest.json").read_text())
assert manifest["manifest_version"] == 1
totals = Counter()
trace_splits = {}
seed_splits = {}
for entry in manifest["entries"]:
    assert entry["split"] in {"train", "validation", "test"}
    raw = (root / entry["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    episode = json.loads(raw)
    assert episode["schema_version"] == "hanoi-crossing-episode-v1"
    assert episode["episode_id"] == entry["episode_id"]
    meta, events, end = episode["metadata"], episode["events"], episode["end"]
    assert (entry["n"], entry["seed"]) == (meta["n"], meta["seed"])
    if meta["mode"] == "random":
        prior = seed_splits.setdefault(meta["seed"], entry["split"])
        assert prior == entry["split"], "A random seed crosses dataset splits"
    state = new_game(meta["n"])
    trace = []
    for index, event in enumerate(events):
        assert state.winner is None, "An event occurs after a terminal state"
        assert event["ply"] == index
        player = event["player"]
        obs = observe(state, player)
        expected_obs = {
            "player": player, "visible_poles": [list(s) for s in obs.visible_poles],
            "hand": obs.hand, "winner": obs.winner,
        }
        assert event["observation"] == expected_obs
        ids = {action_to_id(player, a) for a in legal_actions(obs)}
        assert event["action_mask"] == [i in ids for i in ACTION_IDS]
        action = Action(**event["action"])
        result = step(state, player, action)
        expected_id = (None if result.error == "invisible_pole"
                       else action_to_id(player, action))
        assert event["action_id"] == expected_id
        assert event["error"] == result.error
        if meta["mode"] == "random":
            if result.error is not None:
                assert end["status"] == "failed" and index == len(events) - 1
            else:
                assert expected_id in ids
        trace.append({"player": player, "action": event["action"]})
        state = result.state
    expected_state = {
        "poles": {p: list(s) for p, s in zip(POLE_IDS, state.poles)},
        "hands": dict(zip(PLAYERS, state.hands)), "winner": state.winner,
    }
    assert end["final_state"] == expected_state
    assert end["winner"] == state.winner
    assert end["steps_consumed"] == len(events)
    reason = end["stop_reason"]
    expected_status = {
        "winner": "terminated", "max_steps": "truncated",
        "sequence_exhausted": "truncated", "quit": "aborted",
        "eof": "aborted", "interrupted": "aborted", "agent_error": "failed",
    }[reason]
    assert end["status"] == expected_status
    assert (reason == "winner") == (state.winner is not None)
    if reason == "agent_error":
        assert events and events[-1]["error"] is not None
    fingerprint = hashlib.sha256(json.dumps(
        {"n": meta["n"], "versions": meta["versions"], "turns": trace},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    prior_split = trace_splits.setdefault(fingerprint, entry["split"])
    assert prior_split == entry["split"], "Duplicate trajectory crosses dataset splits"
    totals[(entry["split"], meta["n"], reason)] += 1

for group, count in sorted(totals.items()):
    print(group, count)
print(f"Validated {len(manifest['entries'])} episodes")
PY
```

An identical trajectory can arise from different seeds. If the cross-split check
fails, keep all copies in one split or remove duplicates from the derived
dataset, recording that choice. Preserve the raw source records. For curated
replays and human sessions, also group all derivatives of the same source session.
For this collection protocol, each random seed belongs to one split across all N
values. The checker enforces that rule and verifies the manifest's N and seed
against the archive before trusting its split labels.

For each collection, inspect at least: wins by seat, truncation, abort, and failure counts,
episode lengths, action-ID frequencies including skip, and illegal-action counts.
Group these by N and agent pairing. A collection consisting mostly of cutoffs is
not evidence of a drawing strategy or of a learned policy.

### Reuse an archive as a replay

The `replay` command expects `{n, turns}`, not the entire Episode. This example
replays the consumed events through the public Python API, without writing a
second archive:

```sh
uv run --locked python - <<'PY'
import json
import os
from pathlib import Path
from hanoi_crossing.cli import run_replay

root = Path(os.environ["HANOI_DATASET"])
entry = json.loads((root / "manifest.json").read_text())["entries"][0]
episode = json.loads((root / entry["path"]).read_text())
turns = [{"player": e["player"], "action": e["action"]}
         for e in episode["events"]]
report = run_replay({"n": episode["metadata"]["n"], "turns": turns})
assert report["state"] == episode["end"]["final_state"]
assert [s["error"] for s in report["steps"]] == [e["error"] for e in episode["events"]]
print(report["stop_reason"], report["steps_consumed"])
PY
```

For an unfinished random run, replay will stop with `sequence_exhausted` rather
than `max_steps`; this is expected. Do not append `unexecuted_turns` when verifying
an interrupted prefix, because doing so would continue the original run. Keep the
tail in the raw archive for separate analysis.

## 5. Export player-visible samples

Split complete episodes **before** expanding them into player records. Both A's
and B's records from one episode must stay in the same split. The seed ranges in
the collection recipe define a provisional split; the consistency check also
rejects exact duplicate trajectories that cross it.

This exporter writes a new JSONL file with one legal decision per line. It keeps
the episode and split identifiers, uses only the actor's observation as model
input, and preserves unknown outcomes. It skips aborted/failed episodes and rejected
actions for this particular derived view; their raw archives remain intact.

```sh
uv run --locked python - <<'PY'
from collections import Counter
import json
import os
from pathlib import Path

root = Path(os.environ["HANOI_DATASET"])
manifest = json.loads((root / "manifest.json").read_text())
counts = Counter()
with (root / "policy_samples.jsonl").open("x", encoding="utf-8") as output:
    for entry in manifest["entries"]:
        ep = json.loads((root / entry["path"]).read_text())
        status = ep["end"]["status"]
        if status in ("aborted", "failed"):
            counts[f"{status}_episodes_excluded"] += 1
            continue
        winner = ep["end"]["winner"]
        for event in ep["events"]:
            action_id = event["action_id"]
            if (event["error"] is not None or action_id is None
                    or not event["action_mask"][action_id]):
                counts["rejected_actions_excluded"] += 1
                continue
            player = event["player"]
            row = {
                "episode_id": ep["episode_id"], "split": entry["split"],
                "ply": event["ply"], "player": player, "n": ep["metadata"]["n"],
                "observation": event["observation"],
                "action_mask": event["action_mask"], "action_id": action_id,
                "behavior": ep["metadata"]["agents"][player],
                "outcome": None if winner is None else (1 if winner == player else -1),
                "stop_reason": ep["end"]["stop_reason"],
            }
            output.write(json.dumps(row, allow_nan=False) + "\n")
            counts["samples"] += 1
print(dict(counts))
PY
```

Run the consistency checker before this exporter. The exclusive `"x"` mode
prevents silently overwriting a previous export; a failed export may leave an
incomplete output, which must not be treated as a finished dataset.

`outcome` is an episode-result label from that player's perspective, **not** a
per-step reward and not a claim that the selected action was good. An unknown
outcome is null, not zero. `policy_samples.jsonl` is a tabular decision dataset;
it has neither next observations nor PPO advantages and is not an RL replay buffer.

### What these samples support

| Use | Appropriate interpretation |
| --- | --- |
| Pipeline and encoding tests | Verify loading, masks, fixed IDs, and model input shapes. |
| Behavior cloning | Learn the recorded policy's behavior; random labels teach a random baseline. Human demonstrations need separate quality assessment. |
| Outcome prediction | Use completed episodes and treat results as dependent on the behavior policy and opponent, not as optimal state values. |
| Regression analysis | Replay failures and compare engine outputs under a deliberately selected rules version. |
| Future RL experiments | Retain provenance and trajectories; build an environment adapter and collect the algorithm's required data. |

Do not train only on winning random episodes and describe their actions as expert
labels. That selection changes the data distribution and still does not identify
which actions caused a win. Keep wins, losses, and cutoffs distinguishable.

## 6. Encode observations without leaking hidden information

Use `observation`, N, and the player's identity as policy inputs. Keep
`episode_id`, source hashes, final states, winner-derived targets, and the
opponent's event records out of the feature tensor. The combined archive is a
referee view, even though each individual event contains a valid player view.

For a fixed supported maximum N, a simple custom encoder can reserve `2 * N_max`
positions for each of the three visible stacks, preserving bottom-to-top order.
Pad unused positions with zero and retain stack lengths or padding masks. A
player can acquire the other player's disks, so reserving only N positions per
stack is insufficient. Encode the hand separately with an explicit empty value,
and keep the seven-element legal-action mask separate from padding masks.

Reject observations above the encoder's supported N instead of clipping disks.
Version the encoder and its scaling rules. If using a recurrent policy, preserve
each player's observation/action history in order and reset its memory per
episode. Do not let A's recurrent state become B's state.

## 7. Use trajectories correctly in a future RL application

### Align transitions to the same learner

One archive event is one atomic attempt by the scheduled actor. An RL decision
transition for A normally spans A's action and the opponent's response:

```text
A observation -> A action -> terminal check
                         -> B action -> terminal check -> next A observation
```

The next global event contains B's observation; it is not A's next observation.
For an explicit replay schedule, locate the next event for the same player rather
than assuming alternation. If the game ends before that player's next turn,
project the terminal state with `observe(final_state, player)` and mark the
transition terminated. A player that never acted has no action transition to label.

At each decision boundary, store the learner's observation, action mask, action,
reward, next observation and mask, terminal/truncation flags, and policy/opponent
versions. Keep links to the source episode and ply range. Future recurrent PPO
also needs correctly initialized sequence state and episode-start boundaries;
the current archive does not record recurrent hidden states.

For a first training reward definition, use +1 for the learner's win, -1 for its
loss, and 0 while the game continues. This is a training-layer convention, not a
field emitted by the engine. The final reward belongs on the transition that
reaches the terminal boundary, not on every preceding action. A player's action
can make its opponent win, so read `winner` instead of the final event's actor.

Declare the discount unit. If one environment step is a complete learner decision
cycle, gamma is per cycle. If discounting per atomic attempt, preserve the number
of elapsed plies and use the corresponding discounted rewards and gamma power.
Do not alternate between these conventions within a dataset.

### Distinguish terminal, truncated, aborted, and failed episodes

| Archive status | Meaning for a learning application |
| --- | --- |
| `terminated` | A rule-defined winner exists; do not bootstrap beyond this terminal state. |
| `truncated` | Collection stopped without a winner; the game could continue. A valid continuation value may be needed. |
| `aborted` | The run was explicitly interrupted; exclude by default or define a separate partial-trajectory policy. |
| `failed` | An automated agent submitted a rule-illegal action; retain it for debugging and exclude the episode from policy samples. |

Time-limit truncation must not be relabeled as a zero-valued draw. A learning
adapter must distinguish termination from truncation when forming value targets,
as explained in the official [Gymnasium time-limit guide](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits).

The CLI's atomic `max_steps` can stop between the learner and opponent turns.
Projecting that intermediate state into the learner's view does not make it the
learner's next decision state. For future online training, stop collection at
complete learner decision boundaries and preserve the final observation and
behavior-policy value needed for bootstrapping. For existing archives, retain
fully observed transitions and mark incomplete tails; do not invent the missing
opponent action or bootstrap value. `sequence_exhausted` does not specify a
future replay schedule, either.

### PPO requires fresh behavior-policy rollouts

The current random archive is useful for inspection and pipeline tests, but it
cannot simply replace PPO's online rollout collection. Stable-Baselines3's
[on-policy implementation](https://stable-baselines3.readthedocs.io/en/master/_modules/stable_baselines3/common/on_policy_algorithm.html)
collects observations, actions, values, and log probabilities using the current
policy, then updates from that rollout buffer.

A training application must implement the environment adapter, a learned agent,
reward calculation, rollout collection, and optimization. Record actual old log
probabilities and values at sampling time, identify the policy checkpoint, and
apply the same legal mask when sampling and computing training probabilities.
Do not substitute zeros for missing behavior data or recompute old-policy values
using a later checkpoint. The uniform random action probability is knowable from
the legal set, but that does not supply a learned critic or turn the archive into
current-policy PPO data.

Freeze the opponent while collecting a rollout batch and record its version.
Future self-play can update the opponent between batches under an explicit
schedule. Neither a frozen-opponent trainer nor self-play is implemented here.

## 8. Evaluate what the dataset actually measures

Use validation data for development decisions and keep test episodes and test
opponents out of policy selection. Group copied episodes, replay derivatives,
and paired player views together. Keep N, seat, collection policy, and opponent
version available for stratified reports.

Report wins, losses, cutoffs, aborts, and failures separately, along with the number of
episodes, seeds, and independent training runs. Define rate denominators; do not
hide cutoffs by reporting only completed games. When evaluating a learned policy,
run it in both seats against fixed opponents under the same horizon protocol.

Changing the random seed changes sampled actions, not the deterministic initial
board for a fixed N. Held-out seeds therefore measure a narrower form of
generalization than unseen initial positions. N=1 is useful for wiring checks but
has a strong first-move advantage under alternating play; do not use it alone as
evidence of strategic strength. Keep any future new-position, larger-N, or new-
opponent evaluation protocol explicitly separate.

Archive raw Episodes unchanged. Version derived datasets, manifests, encoder
settings, filtering choices, and training code independently. A saved file, a
passing replay check, and a stronger learned policy are three different results.
