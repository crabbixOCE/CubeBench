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
which reports `0.00%` pass rate on all long-horizon (8-20 moves) tasks in
its README - in my benchmark I find at least one instance of GPT-5.4 solving a task with a (suboptimal) movecount of 24. 

## Results So Far

Tiny samples because I can't afford to run this at scale. I only test a model against a task if it succeeds at the immediate precedent. Also haven't tested anthropic models due to cost.


| Task       | gpt-5.4-high | gemini-3.1-pro-preview-high |
| ---------- | ----------- | --------------------------- |
| cross      |      5/5    |             5/5              |              
| one_face   |      1/2    |             0/2              |           
| one_layer  |      0/2    |             N/A              |   
| f2l        |      N/A    |             N/A              |            
| full_solve |      N/A    |             N/A              |            


GPT-5.4 achieves an average movecount of 5.4, narrowly beating gemini-3.1-pro's 6.2, but note low sample size. 

Gemini-3.1-pro-preview successively refining a cross solution from 5 moves (green cross) down to 3 moves (orange cross). 
Scramble: 


Gpt-5.4 solving the white face. Corner insertions are highly inefficient, using a beginner's technique. 



Areas For Future Work

- Run many more repetitions per task/model. The current batches are too small  
to give stable completion rates or move-count distributions.
- Ablate the harness and state representations more aggressively to see how  
much performance depends on prompt format rather than raw reasoning ability.
- Test stronger tool access. For example: if a model gets a Python runtime,  
does it just implement Kociemba or call an external cube solver?
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