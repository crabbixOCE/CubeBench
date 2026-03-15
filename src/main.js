import { TwistyPlayer } from "cubing/twisty";

import {
  applyMovesText,
  readMovesFile,
  SAMPLE_FILE_PATH,
} from "./move-file.js";
import "./styles.css";

const fileInput = document.querySelector("#moves-file");
const editor = document.querySelector("#moves-editor");
const applyEditorButton = document.querySelector("#apply-editor");
const loadSampleButton = document.querySelector("#load-sample");
const resetViewButton = document.querySelector("#reset-view");
const moveCount = document.querySelector("#move-count");
const cubeStatus = document.querySelector("#cube-status");
const sourceLabel = document.querySelector("#source-label");
const message = document.querySelector("#message");
const cubeState = document.querySelector("#cube-state");
const playerMount = document.querySelector("#player-mount");

const player = new TwistyPlayer({
  puzzle: "3x3x3",
  alg: "",
  background: "checkered",
  hintFacelets: "floating",
});

playerMount.append(player);

function renderResult(result) {
  editor.value = result.displayAlg;
  moveCount.textContent = String(result.moveCount);
  cubeStatus.textContent = result.isSolved
    ? "Solved after execution"
    : "Unsolved after execution";
  sourceLabel.textContent = result.sourceLabel;
  cubeState.textContent = result.cubeState ?? "Unavailable";
  message.textContent = result.message;
  message.dataset.tone = result.tone;
}

function handleFailure(error) {
  message.textContent = error instanceof Error ? error.message : String(error);
  message.dataset.tone = "error";
}

async function applyText(rawText, sourceLabelText) {
  try {
    const result = applyMovesText({
      rawText,
      player,
      sourceLabel: sourceLabelText,
    });

    renderResult(result);
  } catch (error) {
    handleFailure(error);
  }
}

fileInput.addEventListener("change", async (event) => {
  const [file] = event.target.files ?? [];

  if (!file) {
    return;
  }

  try {
    const rawText = await readMovesFile(file);
    await applyText(rawText, file.name);
  } catch (error) {
    handleFailure(error);
  }
});

applyEditorButton.addEventListener("click", async () => {
  await applyText(editor.value, "Editor");
});

loadSampleButton.addEventListener("click", async () => {
  try {
    const response = await fetch(SAMPLE_FILE_PATH);

    if (!response.ok) {
      throw new Error(`Failed to fetch sample: ${response.status}`);
    }

    const rawText = await response.text();
    await applyText(rawText, "Sample file");
  } catch (error) {
    handleFailure(error);
  }
});

resetViewButton.addEventListener("click", () => {
  player.jumpToStart({ flash: false });
  player.pause();
});

await applyText("R U R' U'\nF2", "Default");
