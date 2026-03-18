import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import process from "node:process";

import { Alg, Move } from "cubing/alg";
import { chromium } from "playwright";

const DEFAULT_FPS = 30;
const DEFAULT_WIDTH = 1280;
const DEFAULT_HEIGHT = 720;
const DEFAULT_PORT = 4173;

function logStatus(message) {
  process.stdout.write(`${message}\n`);
}

function parseArgs(argv) {
  const options = {
    fps: DEFAULT_FPS,
    width: DEFAULT_WIDTH,
    height: DEFAULT_HEIGHT,
    port: DEFAULT_PORT,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];

    if (arg === "--events") {
      options.eventsPath = resolve(next);
      index += 1;
      continue;
    }
    if (arg === "--trace") {
      options.tracePath = resolve(next);
      index += 1;
      continue;
    }
    if (arg === "--output") {
      options.outputPath = resolve(next);
      index += 1;
      continue;
    }
    if (arg === "--fps") {
      options.fps = Number(next);
      index += 1;
      continue;
    }
    if (arg === "--width") {
      options.width = Number(next);
      index += 1;
      continue;
    }
    if (arg === "--height") {
      options.height = Number(next);
      index += 1;
      continue;
    }
    if (arg === "--port") {
      options.port = Number(next);
      index += 1;
    }
  }

  if (!options.eventsPath) {
    throw new Error("Missing --events /abs/path/to/events.txt");
  }

  if (!options.tracePath) {
    if (options.eventsPath.endsWith("/events.txt")) {
      options.tracePath = join(dirname(options.eventsPath), "reasoning.txt");
    } else {
      options.tracePath = options.eventsPath.replace(/_events\.txt$/, "_reasoning.txt");
    }
  }

  if (!options.outputPath) {
    if (options.eventsPath.endsWith("/events.txt")) {
      const runDir = dirname(options.eventsPath);
      const runId = basename(runDir);
      options.outputPath = join(dirname(runDir), `${runId}.mp4`);
    } else {
      options.outputPath = options.eventsPath.replace(/_events\.txt$/, ".mp4");
    }
  }

  return options;
}

function parseJsonSection(text, heading) {
  const lines = text.split("\n");
  const startIndex = lines.findIndex((line) => line.trim() === heading);
  if (startIndex === -1) {
    throw new Error(`Could not find section '${heading}' in trace log.`);
  }

  const jsonLines = [];
  let started = false;
  let depth = 0;

  for (let index = startIndex + 2; index < lines.length; index += 1) {
    const line = lines[index];
    if (!started) {
      if (!line.trim()) {
        continue;
      }
      started = true;
    }

    jsonLines.push(line);
    for (const char of line) {
      if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
      }
    }

    if (started && depth === 0) {
      break;
    }
  }

  return JSON.parse(jsonLines.join("\n"));
}

function parseCompactEvents(text) {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const events = [];
  let bufferedOutput = [];

  const flushOutput = () => {
    if (bufferedOutput.length === 0) {
      return;
    }
    events.push({
      type: "model_output",
      text: bufferedOutput.join("\n"),
    });
    bufferedOutput = [];
  };

  for (const line of lines) {
    const toolMatch = line.match(
      /^(load_scramble|get_state|apply_moves|check_task_complete|make_final_submission)\s+(\{.*\})$/,
    );
    if (!toolMatch) {
      bufferedOutput.push(line);
      continue;
    }

    flushOutput();
    events.push({
      type: "tool_call",
      name: toolMatch[1],
      arguments: JSON.parse(toolMatch[2]),
      rawLine: line,
    });
  }

  flushOutput();
  return events;
}

function expandMoves(movesText) {
  if (!movesText.trim()) {
    return [];
  }

  return [...Alg.fromString(movesText).expand().units()]
    .filter((unit) => unit instanceof Move)
    .map((move) => move.toString());
}

function buildFrames({ compactEvents, config, scrambleName, fps }) {
  const frames = [];
  const currentMoves = [];
  const scrambleMoves = expandMoves(config.scramble);
  let eventCounter = 0;

  const pushHold = ({ title, subtitle, seconds = 0.8 }) => {
    const repeat = Math.max(1, Math.round(seconds * fps));
    for (let index = 0; index < repeat; index += 1) {
      frames.push({
        alg: currentMoves.join(" "),
        title,
        subtitle,
      });
    }
  };

  const pushMoveSequence = ({
    title,
    subtitle,
    moves,
    reset = false,
    resetToMoves = [],
    endHoldSeconds = 2,
  }) => {
    if (reset) {
      currentMoves.length = 0;
      currentMoves.push(...resetToMoves);
    }

    pushHold({ title, subtitle, seconds: 0.45 });

    for (const move of moves) {
      currentMoves.push(move);
      const repeat = Math.max(1, Math.round(0.28 * fps));
      for (let index = 0; index < repeat; index += 1) {
        frames.push({
          alg: currentMoves.join(" "),
          title,
          subtitle,
        });
      }
    }

    pushHold({ title, subtitle, seconds: endHoldSeconds });
  };

  const pushInstantState = ({ title, subtitle, moves, reset = false, seconds = 0.9 }) => {
    if (reset) {
      currentMoves.length = 0;
    }

    currentMoves.push(...moves);
    pushHold({ title, subtitle, seconds });
  };

  for (const event of compactEvents) {
    eventCounter += 1;

    if (event.type === "tool_call" && event.name === "load_scramble") {
      pushInstantState({
        title: `Tool call ${eventCounter}: load_scramble`,
        subtitle: `Reset to solved and apply hidden scramble${scrambleName ? `: ${scrambleName}` : ""}`,
        moves: scrambleMoves,
        reset: true,
      });
      continue;
    }

    if (event.type === "tool_call" && event.name === "apply_moves") {
      const moveText = event.arguments.moves ?? "";
      const moves = expandMoves(moveText);
      pushMoveSequence({
        title: `Tool call ${eventCounter}: apply_moves ${moveText}`.trim(),
        subtitle: "",
        moves,
        endHoldSeconds: 1.5,
      });
      continue;
    }

    if (event.type === "tool_call" && event.name === "get_state") {
      pushHold({
        title: `Tool call ${eventCounter}: get_state`,
        subtitle: "Inspect current cube state",
        seconds: 0.85,
      });
      continue;
    }

    if (event.type === "tool_call" && event.name === "check_task_complete") {
      const task = event.arguments.task ?? "unknown";
      pushHold({
        title: `Tool call ${eventCounter}: check_task_complete ${task}`.trim(),
        subtitle: `Validate benchmark task completion: ${task}`,
        seconds: 0.85,
      });
      continue;
    }

    if (event.type === "tool_call" && event.name === "make_final_submission") {
      const moveText = event.arguments.moves ?? "";
      const moves = expandMoves(moveText);
      pushMoveSequence({
        title: `Final submission: ${moveText}`.trim(),
        subtitle: "Render the model's final scored move sequence",
        moves,
        reset: true,
        resetToMoves: scrambleMoves,
        endHoldSeconds: 2.5,
      });
      continue;
    }

    if (event.type === "model_output") {
      pushHold({
        title: "Model output",
        subtitle: event.text,
        seconds: 1.8,
      });
    }
  }

  return frames.map((frame, index) => ({
    ...frame,
    progressText: `Frame ${index + 1} / ${frames.length}`,
  }));
}

function waitForServer(url) {
  return new Promise((resolveServer, reject) => {
    const startedAt = Date.now();

    const tick = async () => {
      try {
        const response = await fetch(url);
        if (response.ok) {
          resolveServer();
          return;
        }
      } catch {
        // keep polling
      }

      if (Date.now() - startedAt > 20_000) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }

      setTimeout(tick, 250);
    };

    tick();
  });
}

function runCommand(command, args) {
  return new Promise((resolveCommand, reject) => {
    const child = spawn(command, args, {
      stdio: "inherit",
      env: process.env,
    });

    child.on("exit", (code) => {
      if (code === 0) {
        resolveCommand();
        return;
      }
      reject(new Error(`${command} ${args.join(" ")} exited with code ${code}`));
    });
  });
}

function spawnPreviewServer(port) {
  const child = spawn(
    "npm",
    ["run", "preview", "--", "--host", "127.0.0.1", "--port", String(port), "--strictPort"],
    {
      stdio: "pipe",
      env: process.env,
    },
  );

  child.stdout.on("data", () => {});
  child.stderr.on("data", () => {});
  return child;
}

function runFfmpeg({ fps, frameDir, outputPath }) {
  return new Promise((resolveFfmpeg, reject) => {
    const ffmpeg = spawn(
      "ffmpeg",
      [
        "-y",
        "-framerate",
        String(fps),
        "-i",
        join(frameDir, "frame-%06d.png"),
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        outputPath,
      ],
      { stdio: "inherit" },
    );

    ffmpeg.on("exit", (code) => {
      if (code === 0) {
        resolveFfmpeg();
        return;
      }
      reject(new Error(`ffmpeg exited with code ${code}`));
    });
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const eventsText = await readFile(options.eventsPath, "utf8");
  const traceText = await readFile(options.tracePath, "utf8");
  const config = parseJsonSection(traceText, "config");
  const configuredScramble = parseJsonSection(traceText, "configured scramble");
  const compactEvents = parseCompactEvents(eventsText);
  const frames = buildFrames({
    compactEvents,
    config,
    scrambleName: configuredScramble.scramble_name,
    fps: options.fps,
  });

  const frameDir = await mkdtemp(join(tmpdir(), "cubebench-video-"));
  logStatus(`Loaded ${compactEvents.length} events and built ${frames.length} frames.`);
  logStatus("Building frontend bundle...");
  await runCommand("npm", ["run", "build"]);
  logStatus(`Starting preview server on http://127.0.0.1:${options.port}/replay.html ...`);
  const server = spawnPreviewServer(options.port);
  let browser;

  try {
    await waitForServer(`http://127.0.0.1:${options.port}/replay.html`);
    logStatus("Preview server is ready.");

    browser = await chromium.launch();
    const page = await browser.newPage({
      viewport: { width: options.width, height: options.height },
      deviceScaleFactor: 1,
    });

    await page.goto(`http://127.0.0.1:${options.port}/replay.html`, {
      waitUntil: "networkidle",
    });

    await page.evaluate((meta) => window.cubebenchReplay.initialize(meta), {
      kicker: "CubeBench Replay",
      runLabel: `${config.provider} ${config.model_name}`,
    });

    logStatus(`Capturing ${frames.length} frames...`);
    for (let index = 0; index < frames.length; index += 1) {
      await page.evaluate((frame) => window.cubebenchReplay.render(frame), frames[index]);
      await page.screenshot({
        path: join(frameDir, `frame-${String(index).padStart(6, "0")}.png`),
      });

      const frameNumber = index + 1;
      if (frameNumber % 100 === 0 || frameNumber === frames.length) {
        logStatus(`Captured ${frameNumber}/${frames.length} frames`);
      }
    }

    logStatus("Encoding MP4 with ffmpeg...");
    await runFfmpeg({
      fps: options.fps,
      frameDir,
      outputPath: options.outputPath,
    });

    process.stdout.write(`Wrote video to ${options.outputPath}\n`);
  } finally {
    if (browser) {
      await browser.close();
    }
    server.kill("SIGTERM");
    await rm(frameDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
