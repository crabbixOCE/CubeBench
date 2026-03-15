# CubeBench

This repo now has two parts:

- a minimal browser app for loading a text file of cube moves and replaying it with `cubing.js`
- a Python LLM harness that uses `cubejs` as the cube simulator and exposes `load_scramble()`, `get_state()`, `apply_moves()`, and `check_task_complete()` as tools

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

Fill in the provider key you want to use, then run:

```bash
uv run cubebench-harness --config config.yaml
```

The default [`config.yaml`](/home/alexs/projects/CubeBench/config.yaml) is set
to a Google run on a white-cross benchmark scramble. Provider-specific prompt
builders live in:

- [`python/cubebench_harness/prompting.py`](/home/alexs/projects/CubeBench/python/cubebench_harness/prompting.py)
- [`python/cubebench_harness/providers/openai_provider.py`](/home/alexs/projects/CubeBench/python/cubebench_harness/providers/openai_provider.py)
- [`python/cubebench_harness/providers/anthropic_provider.py`](/home/alexs/projects/CubeBench/python/cubebench_harness/providers/anthropic_provider.py)
- [`python/cubebench_harness/providers/google_provider.py`](/home/alexs/projects/CubeBench/python/cubebench_harness/providers/google_provider.py)

State-representation conversion is modular in
[`python/cubebench_harness/converters.py`](/home/alexs/projects/CubeBench/python/cubebench_harness/converters.py).
Each representation now also defines its own interpretation contract
(face/color mapping, array ordering, and decoding notes), which is injected
into the system prompt and echoed in state-returning tool responses. That keeps
prompt wording decoupled from the concrete cube encoding so representations can
be swapped or added independently.
Benchmark tasks are now explicit task ids: `white_cross`, `f2l`, and
`full_solve`. Task completion is validated by `cubejs` through the
`check_task_complete({"task": ...})` tool.
The harness logs tool calls and final output to `runs/*_events.txt`, and
provider reasoning or thought summaries to `runs/*_reasoning.txt`.

## Move file format

The loader accepts any algorithm syntax that `cubing` can parse, plus lines or
trailing fragments starting with `#` for plain-text comments. `cubejs` state
reporting is based on the expanded move list, so the viewer can still load an
algorithm even if `cubejs` cannot summarize the final state for a particular
notation.

Sample file: `public/algorithms/demo.txt`

## Replay Video Rendering

You can render a run log into an annotated MP4 without screen capture. The
pipeline is:

- parse the compact `runs/*_events.txt` tool-call log
- recover scramble/config metadata from the verbose `runs/*_reasoning.txt` trace
- render annotated cube frames in a headless Chromium session using `cubing.js`
- encode those frames to H.264 with `ffmpeg`

Install the browser once:

```bash
npx playwright install chromium
```

Render a run:

```bash
npm run render-run-video -- \
  --events /absolute/path/to/runs/<run>_events.txt \
  --trace /absolute/path/to/runs/<run>_reasoning.txt \
  --output /absolute/path/to/runs/<run>.mp4
```

The replay page is [`replay.html`](/home/alexs/projects/CubeBench/replay.html)
and the renderer is
[`scripts/render_run_video.mjs`](/home/alexs/projects/CubeBench/scripts/render_run_video.mjs).
