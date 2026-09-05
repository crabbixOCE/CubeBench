# CubeBench

## Overview

CubeBench is a Rubik's Cube benchmark for agentic LLMs. I think this is an interesting benchmark because it's a spatial reasoning task that can be efficiently, losslessly represented with language - a minimal representation of cube state is only 54 characters. It's also relatively difficult to benchmax, since we can generate scrambles on the fly and arbitrarily design new tasks (e.g., random state to random state), different cube sizes/shapes, so I expect it to be difficult to saturate. 

The current benchmark setup uses:

- `cubejs` as the ground-truth simulator
- modular cube-state representations, with `cubie_json` used by default
- tool-based interaction through `load_scramble`, `apply_moves`,
`check_task_complete`, and `make_final_submission`
- a maximum of 50 turns
- task families with increasing horizon. In each case the objective is the lowest movecount (WCA Outer-block turn metric):
  - `cross`: solve the four edge-pieces on any side
  - `one_face`: solve one full face, ignoring corner/edge permuation
  - `one_layer`: solve one full layer with correct corner/edge permutation
  - `f2l`: solve the first two layers (i.e., any 3x3x2 block)
  - `full_solve`: solve the whole cube

Previous Rubik's Cube evaluations I've found are closer to static or one-shot
probes than to an interactive search benchmark. The key distinction in this iteration is the multi-turn agentic setup, wherein models have access to a simulated cube to test move sequences. 
The closest prior work is
[Princeton-AI2-Lab/CubeBench](https://github.com/Princeton-AI2-Lab/CubeBench),
which reports `0.00%` pass rate on all long-horizon (8–20 moves) tasks in
its README. This benchmark instead lets models inspect and manipulate the cube
across multiple tool calls.

## Latest Result

GPT-6 Astra (`max` reasoning) solved a fresh scramble in the patched no-code
Codex environment and submitted a **verified 61-move solution**, using **24,146
reasoning tokens**. The run had a budget of 100,000 reported reasoning tokens
and a one-hour backstop; it finished before either limit.

https://github.com/user-attachments/assets/8b2b7226-f90b-4113-8ae6-2d07c4783425


The replay shows the actual attempt followed by the submitted solution. Astra
applied 62 moves while solving, then combined two adjacent turns to submit 61.
The solution is still somewhat inefficient at **61 moves**, so there is plenty
of room to improve move count as well as completion rate. This is one successful
attempt, not an estimate of its general success rate.

Scramble: `R' F' R2 L D B2 U' F2 R' B L2 F' U2 B L2 F D2 B D2 R2 D2`

### Code-execution workaround in earlier runs

Earlier Sol and Astra runs found short solutions through solver-style search
in an environment intended to forbid code execution. Sol's summaries describe
an in-isolate Kociemba solver, pruning tables and rotated-axis searches. A
persisted Astra diagnostic confirmed the loophole directly: it executed
JavaScript to build lookup tables and run a two-phase solver, finding a 19-move
solution. The original ephemeral runs did not retain the complete execution
record, so Sol's exact executed program cannot be reconstructed from its
summaries alone.

Disabling shell access and `code_mode.enabled` had left a separate JavaScript
host available through the models' `code_mode_only` routing. Ordinary Codex JSON
exports omitted those execution calls. This was a **harness isolation failure**;
the earlier short solutions should not be treated as verified no-code results.

The patched launchers disable that host, remove code-mode-only routing, expose
the cube tools directly, and reject runs unless a local execution-blocking probe
passes. Prompts explicitly say code execution is disallowed and disabled, and
full sessions are retained for inspection. The 61-move result above uses this
patched environment. See the [incident note](docs/codex-tool-isolation-incident.md)
for the evidence and enforcement details.

## Animations

https://github.com/user-attachments/assets/78ee4a66-3690-40d3-8ec3-95fec56e904e

Gemini-3.1-pro-preview successively refining a cross solution from 5 moves (green cross) down to 3 moves (orange cross). 
Scramble: D L' B U2 R' F2 U' F2 R2 F R2 B R2 B' U2 D2 B' D2 F2 L B'


https://github.com/user-attachments/assets/bfb71518-9b01-4410-b2ad-154aab9852e5

Gpt-5.4 solving the white face. Corner insertions are highly inefficient, using a beginner's technique. 
Scramble: U' R B' U2 D2 F' R' B' U R' L2 D' R2 F2 D2 R2 F2 U' F2 D2 B2



## Areas For Future Work

- Run many more repetitions per task/model. The current batches are too small  
to give stable completion rates or move-count distributions.
- Ablate the harness and state representations more aggressively to see how  
much performance depends on prompt format rather than raw reasoning ability.
- Compare explicitly code-enabled solver runs against the patched no-code
benchmark, keeping the two conditions separate.
- Push harder on the long-horizon tasks. `one_layer`, `f2l`, and `full_solve`  
are the part of the benchmark that matters most.

## Repo Contents

This repo has two main parts:

- a minimal browser app for loading a text file of cube moves and replaying it  
with `cubing.js`
- a Python LLM harness that uses `cubejs` as the cube simulator and exposes  
`load_scramble()`, `apply_moves()`, `check_task_complete()`, and  
`make_final_submission()` as tools

## Dependencies

This repo uses npm dependencies instead of git submodules:

- `cubing` for the browser viewer and algorithm parser
- `cubejs` for applying expanded moves and reporting the resulting cube state

That is the more appropriate integration path here because both libraries are  
published packages and are intended to be consumed by a bundler.

## Run

```bash
npm install
npm run dev
```

Then open the local Vite URL, load a `.txt` file, and the sequence will be  
applied to the embedded `cubing.js` player.

## Python Harness

Set up the Python environment with `uv`:

```bash
uv sync
cp .env.example .env
```

Fill in the provider keys you want to use, then run:

```bash
uv run cubebench-harness --config config.yaml
```

### Codex usage

The Codex smoke launcher uses ChatGPT-authenticated Codex usage instead of a
Platform API key. It renders `codex_home/config.toml.template` into the separate
`~/.codex-cubebench` home, seeds that home from the existing Codex login with
private file permissions, removes API-key variables from the child environment,
and runs Codex in an empty read-only workspace.

The launchers enforce a **no model-supplied code execution** tool environment.
They pin a local model-catalog entry with code-mode-only routing removed, disable
the JavaScript host, shell, REPL, patch, browser and other execution surfaces,
and expose the four CubeBench MCP tools through native tool discovery. Codex's
non-executing MCP discovery/resource and clarification helpers remain available.
The trusted cube simulator still runs code to implement the benchmark tools.

Before each inference run, a local mock model deliberately requests JavaScript,
shell, REPL and patch execution. The launcher proceeds only if the installed
dispatcher rejects every request, the exposed tool list contains no unexpected
tools, and a direct cube call succeeds. This probe does not use model tokens or
API credentials. Its report is saved under each attempt's `tool-isolation/`.
Session persistence is enabled by default so the full tool record survives.

Run the same check independently, without a model call:

```bash
.venv/bin/python scripts/check_codex_tool_isolation.py --model gpt-6-astra
```

This enforcement was verified with Codex CLI 0.153.3. Local model metadata changes
tool routing, not the model identity, weights, reasoning effort or cube task.
The runtime probe fails closed on incompatible future versions. Tests establish
the exposed handlers' behavior; they are not a proof against arbitrary runtime
vulnerabilities.

**Historical caveat:** the earlier Astra run used JavaScript to construct and run
a solver. `features.code_mode.enabled = false` and a read-only sandbox did not
prevent it: the model catalog selected `code_mode_only` and the separate
`code_mode_host` feature remained enabled. Its ordinary JSON export omitted those
JavaScript calls. Earlier results cannot be assumed to be no-code results.
See the [incident note](docs/codex-tool-isolation-incident.md) for the evidence,
patch, validation and fresh Astra rerun results. Benchmark prompts now also
explicitly forbid code execution and searches for execution workarounds.

Inspect the planned model/task without starting a model call. Runtime isolation
overrides are added after the preflight, and the final invocation is saved as
`launch-command.json` in the attempt directory:

```bash
.venv/bin/python scripts/run_codex_cross.py --dry-run
```

Run the deterministic Luna/max cross smoke test:

```bash
.venv/bin/python scripts/run_codex_cross.py
```

Run the fixed F2L/full-solve comparison in parallel, or inspect its four
attempts first without starting inference:

```bash
.venv/bin/python scripts/run_codex_batch.py --dry-run --config config.codex-f2l-full-cube.yaml
.venv/bin/python scripts/run_codex_batch.py --config config.codex-f2l-full-cube.yaml
```

Run only Astra/max on both tasks, with a fresh isolated home for each attempt:

```bash
.venv/bin/python scripts/run_codex_astra_no_code.py
```

To run only the GPT-5.5/xhigh F2L smoke attempt on the same fixed scramble:

```bash
.venv/bin/python scripts/run_codex_f2l.py --dry-run
.venv/bin/python scripts/run_codex_f2l.py
```

The corresponding single full-solve attempt (requested `max`, effective
Codex `xhigh`) is:

```bash
.venv/bin/python scripts/run_codex_full_solve.py --dry-run
.venv/bin/python scripts/run_codex_full_solve.py
```

The Codex launchers replay every completed `apply_moves` checkpoint on the
host. If a process times out after proving F2L but before calling
`make_final_submission`, the shortest verified checkpoint is recovered and
marked with `solution_source: recovered_checkpoint`; otherwise the latest legal
candidate is retained for diagnosis without being marked successful.

Each attempt gets a private Codex home and read-only workspace and is saved as
soon as it finishes, including timed-out partial traces. The default time limit
is 15 minutes. For a single Astra full solve with a longer budget and a supplied
fresh scramble:

```bash
.venv/bin/python scripts/run_codex_astra_no_code.py \
  --task full_solve --timeout-seconds 3600 --reasoning-token-budget 100000 \
  --scramble "R' F' R2 L D B2 U' F2 R' B L2 F' U2 B L2 F D2 B D2 R2 D2"
```

The token watchdog stops at the first reported reasoning total at or above the
budget; an in-flight response can overshoot. The wall-clock backstop remains
independent. Live counters are saved in `budget-status.json`.

The launchers preserve Codex JSONL events and verified `status.json` records
under `runs/<timestamp>_codex_luna_cross/` or
`runs/<timestamp>_codex_f2l_full_cube/`. The tracked definitions are
`config.codex-luna-cross.yaml` and `config.codex-f2l-full-cube.yaml`;
credentials are never stored in the repo.

To plot successful runs from an existing batch directory:

```bash
uv run cubebench-plot-results runs/20260315T085024Z_config
```

That reads `status.json`, uses `total_output_tokens_used` as a reasoning-effort  
proxy, counts moves from each successful solution string, and writes  
`reasoning_effort_vs_move_count.png` into the run directory by default.

The default `[config.yaml](config.yaml)` is set up for a small benchmark batch.  
Top-level `tasks` and `model_names` are arrays, `n_runs_per_task` controls how  
many scrambles are generated per task, and each task/run scramble is shared  
across all configured models for that task. Model strings can carry  
provider-specific reasoning hints, for example `gpt-5.4-low`,  
`gpt-5.4-high`, `gpt-5.4-xhigh`, or `gemini-3.1-pro-preview-high`.  
Provider-specific prompt builders live in:

- `[python/cubebench_harness/prompting.py](python/cubebench_harness/prompting.py)`
- `[python/cubebench_harness/providers/openai_provider.py](python/cubebench_harness/providers/openai_provider.py)`
- `[python/cubebench_harness/providers/anthropic_provider.py](python/cubebench_harness/providers/anthropic_provider.py)`
- `[python/cubebench_harness/providers/google_provider.py](python/cubebench_harness/providers/google_provider.py)`

State-representation conversion is modular in  
`[python/cubebench_harness/converters.py](python/cubebench_harness/converters.py)`.  
Each representation defines its own interpretation contract (face/color  
mapping, array ordering, and decoding notes), which is injected into the system  
prompt and echoed in state-returning tool responses. That keeps prompt wording  
decoupled from the concrete cube encoding so representations can be swapped or  
added independently.

Benchmark tasks are explicit task ids: `cross`, `one_face`, `one_layer`,  
`f2l`, and `full_solve`. The first four are colour-neutral: they accept any  
whole-cube orientation where the corresponding face, layer, or `3x3x2` block is  
solved. Task completion is validated by `cubejs` through the  
`check_task_complete({"task": ...})` tool.

Each benchmark invocation writes into its own `runs/<timestamp>_config/`  
directory. That directory contains:

- `manifest.json` with the expanded run plan and generated scrambles
- `status.json` with per-run task, scramble, solution, model, success, and  
output-token totals
- `artifacts/<run-id>/events.txt` with compact tool calls and final output
- `artifacts/<run-id>/reasoning.txt` with verbose provider traces and run  
metadata

## Move File Format

The loader accepts any algorithm syntax that `cubing` can parse, plus lines or  
trailing fragments starting with `#` for plain-text comments. `cubejs` state  
reporting is based on the expanded move list, so the viewer can still load an  
algorithm even if `cubejs` cannot summarize the final state for a particular  
notation.

Sample file: `public/algorithms/demo.txt`

## Replay Video Rendering

You can render a run log into an annotated MP4 without screen capture. The  
pipeline is:

- parse the compact `artifacts/<run-id>/events.txt` tool-call log
- recover scramble/config metadata from the verbose  
`artifacts/<run-id>/reasoning.txt` trace
- render annotated cube frames in a headless Chromium session using `cubing.js`
- encode those frames to H.264 with `ffmpeg`

Install the browser once:

```bash
npx playwright install chromium
```

Render a run:

```bash
npm run render-run-video -- \
  --events /absolute/path/to/runs/<batch-id>/artifacts/<run-id>/events.txt \
  --trace /absolute/path/to/runs/<batch-id>/artifacts/<run-id>/reasoning.txt \
  --output /absolute/path/to/runs/<batch-id>/<run-id>.mp4
```

The replay page is `[replay.html](replay.html)` and the renderer is  
`[scripts/render_run_video.mjs](scripts/render_run_video.mjs)`.
