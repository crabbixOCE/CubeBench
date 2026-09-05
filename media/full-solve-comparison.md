# CubeBench full-solve comparison

`full-solve-comparison.mp4` is a 1080 × 1080, 30 fps, silent four-panel replay using the same cubing.js TwistyPlayer browser simulator as the existing single-run renderer.

- GPT-5.5 (xhigh): 168 legal moves, no full solve; ends on its final valid state.
- GPT-5.6 Sol (max): verified completions at 21, 20, and 19 moves; ends at 19 despite timing out without submission.
- GPT-6 Astra (max): verified completions at 21 and 19 moves; ends at 19. Its duplicate final submission is not replayed a second time.

Each successful completion pauses the entire replay for 2.5 seconds. Playback synchronizes move steps and compresses thinking time; it does not compare elapsed run times. Models that finish early remain on their final state.

The graph plots cumulative completed cube-tool calls against the move count of each verified solution. This is tool usage, not token usage or dollar cost: GPT-5.5 and Sol have no recorded token totals, and the traces do not contain per-checkpoint token/cost history. No costs are estimated. GPT-5.5 has no plotted solution point because it did not solve the cube.

The renderer independently applies every accepted move with cubejs, checks for solved states after each move, and compares each returned cubie state against its replay. Move counts use half-turn metric, consistent with these face-turn-only traces. Attempt resets restart the move count but not the cumulative tool-call count.

Regenerate from the repository root:

```sh
node scripts/render_comparison_video.mjs media/full-solve-comparison.mp4
```

The adjacent JSON contains source paths, all replay steps, and verified solution sequences. The PNG shows the final frame. `--preview` renders the opening layout only and permits a placeholder if a source trace is not available yet.
