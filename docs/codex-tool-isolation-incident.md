# CubeBench Codex tool-isolation incident — 5 September 2026

CubeBench's Codex setup was intended to allow only cube-tool interaction, with
no execution of model-written code. The original setup did not enforce that.
The setup and verification were insufficient; this was a harness failure.

## What happened

The earlier Astra full-solve replay appeared to jump from a 21-move solution to
a 19-move solution with very few tool calls. Its exported reasoning summaries
mentioned building lookup tables and searching cube orientations. The normal
`codex exec --json` export showed only cube MCP calls, messages and short
reasoning summaries, so the computational work was not visible there.

Those runs used `--ephemeral`, leaving no full session record to inspect. We
ran one fresh Astra/max full-solve diagnostic with persistence enabled:
[`20260905T074615Z_astra_persisted`](../runs/20260905T074615Z_astra_persisted/inspection.md).
It submitted the exact same verified 19-move sequence as the earlier run.

The persisted diagnostic revealed **11 JavaScript `exec` calls and two `wait`
calls**, all absent from its ordinary JSON export. The programs derived cube
move transforms, constructed pruning tables and ran a two-phase search. One
search output records finding the 19-move candidate 3.075 seconds into a deeper
search pass. Later work built an 88,179,840-state corner lookup table. These are
recorded executions and outputs, not just statements in reasoning summaries.

The diagnostic is direct evidence of code-assisted solving. The old ephemeral
run's underlying programs cannot be recovered, so the matching result supports
but does not prove that its implementation was identical. **Earlier Codex
results must not be presented as verified no-code results.** This applies to
interpretation of the existing videos too: they visualize cube interaction,
not the model's total computational work.

## The hole

Sol's earlier full-solve trace likewise describes an in-isolate Kociemba solver,
pruning-table construction and rotated-axis searches, producing verified
21-, 20- and 19-move checkpoints. Its original ephemeral session does not retain
the underlying execution programs. These summaries support the same workaround;
the persisted Astra diagnostic supplies the direct execution evidence.

Two independent runtime controls had been conflated:

- `features.code_mode.enabled = false` did not remove the model catalog's
  `tool_mode: "code_mode_only"` routing.
- The separate `code_mode_host` feature remained enabled. That host provided a
  V8 JavaScript runtime, including persistent `store`/`load` helpers between
  calls. Blocking shell tools did not block it.

A read-only filesystem restricts writes; it does not prevent an in-memory
solver. Prompt instructions to use only cube tools were also not an execution
boundary. The earlier assessment relied too heavily on flags and an incomplete
export instead of testing the effective dispatcher.

## Patch and enforcement

The shared launchers now:

1. Pin a local catalog entry for the requested model, removing code-mode-only
   routing, disabling the model's REPL metadata and removing patch/extra-tool
   metadata. Model identity, base instructions and reasoning level are retained.
2. Explicitly disable the JavaScript host, shell and other execution surfaces.
   Cube tools are called directly through native MCP discovery. Non-executing
   MCP discovery/resource and clarification helpers can remain available.
3. Before inference, run a local mock-model probe against the installed CLI.
   The mock deliberately requests `exec`, `exec_command`, `shell`, `js_repl`
   and `apply_patch`, even though they are not advertised. The dispatcher must
   reject each as unsupported. The probe also checks the exposed/discovered
   tool names and requires a real direct `load_scramble` call to succeed.
4. Refuse inference if any check fails. Save the preflight report and actual
   launch command, and persist the full model session by default.
5. Explicitly tell the model that code execution is disallowed and disabled,
   that it must not search for interpreters, hidden tools or workarounds, and
   that it should reason directly using the four cube tools. This instruction
   prevents wasted exploration; the dispatcher restrictions enforce the rule.

The mock probe consumes no model tokens and does not copy API credentials.
It loads a separate test cube, not the benchmark attempt's cube.

Implementation: [`codex_tool_isolation.py`](../scripts/codex_tool_isolation.py).
Independent check: [`check_codex_tool_isolation.py`](../scripts/check_codex_tool_isolation.py).

## Validation and limits

Validated on **Codex CLI 0.153.3** for Astra, Sol and GPT-5.5. All five forced
execution requests were rejected and native cube access worked. A short live
Astra check used only native tool discovery and `load_scramble`; its persisted
session contained no code-execution calls. Twenty-one Codex tests and ten MCP-server
tests passed. See the [validation summary](../runs/no-code-enforcement-summary.json).

This is enforcement against external execution of model-supplied code through
the tested tool environment. The trusted benchmark simulator necessarily runs
code to update and validate the cube. It does not constrain the model's internal
reasoning, and it is not a proof against arbitrary runtime vulnerabilities.
Unexpected exposed tools or a regression in the tested handlers fails the
preflight rather than silently starting another benchmark.

## Fresh patched runs

Batch [`20260905T082551Z_astra_no_code`](../runs/20260905T082551Z_astra_no_code/launch.json)
contains one new Astra/max attempt each for F2L and full solve, using the same fixed
`one_layer_01` scramble, cubie JSON representation, and 900-second limit. They
start in separate fresh homes, with no earlier solution included in their
prompts. Both passed the runtime preflight, explicitly received the no-code and
no-workarounds instruction, and retain their session records.
Both attempts reached the 900-second limit without `make_final_submission`.
Host replay found **zero completed checkpoints for either assigned task**.

| Assigned task | Result | Recorded moves applied | Completed cube calls |
| --- | --- | ---: | ---: |
| F2L | Timed out; no verified F2L completion | 21 | 1 load + 3 move applications |
| Full solve | Timed out; no verified full solve | 33 | 1 load + 5 move applications |

The full-solve attempt did reach an F2L state, independently verified by the
host after the run. That is a partial milestone, not completion of its assigned
full-solve task. Its 33 applied turns can be written as 32 moves by combining
an adjacent pair of B turns, consistent with its progress message.

Both final session audits passed. Each session contains exactly one native
tool-discovery call followed only by direct CubeBench calls. There are no
JavaScript, shell, REPL, patch, hidden-execution or workaround tool calls.
The configuration/catalog hashes match the passing preflight reports, and the
saved launch commands contain both the explicit no-code/no-workarounds prompt
and persistence settings.

Artifacts:

- [Run results](../runs/20260905T082551Z_astra_no_code/status.json)
- [Full post-run session audits](../runs/20260905T082551Z_astra_no_code/session-audit.json)
- [Host verification of the partial F2L milestone](../runs/20260905T082551Z_astra_no_code/partial-milestones.json)
- [F2L trace](../runs/20260905T082551Z_astra_no_code/002_f2l_gpt_6_astra_max/codex-events.jsonl)
- [Full-solve trace](../runs/20260905T082551Z_astra_no_code/004_full_solve_gpt_6_astra_max/codex-events.jsonl)

These are one attempt per task under the patched environment, not an estimate
of the model's general success rate. Neither attempt was resumed or extended.

## Subsequent full-solve success on a fresh scramble

A separate Astra/max run, `20260905T091553Z_astra_no_code`, used a fresh scramble,
the patched environment, a 100,000 reported reasoning-token budget and a
one-hour backstop. It completed normally and submitted a host-verified
**61-move solution**, using **24,146 reasoning tokens**. Neither limit was hit.
It applied 62 moves during the attempt and combined two adjacent turns in the
submitted sequence. At 61 moves the solution is still somewhat inefficient;
there is room to improve beyond achieving completion.

Scramble: `R' F' R2 L D B2 U' F2 R' B L2 F' U2 B L2 F D2 B D2 R2 D2`

[Replay video](../media/astra-no-code-fresh-full-solve.mp4) ·
[Verified run status](../runs/20260905T091553Z_astra_no_code/004_full_solve_gpt_6_astra_max/status.json)
