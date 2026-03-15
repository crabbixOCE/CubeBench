import { TwistyPlayer } from "cubing/twisty";

import "./replay.css";

const title = document.querySelector("#replay-title");
const subtitle = document.querySelector("#replay-subtitle");
const kicker = document.querySelector("#replay-kicker");
const runLabel = document.querySelector("#replay-run");
const progress = document.querySelector("#replay-progress");
const playerMount = document.querySelector("#replay-player");

const player = new TwistyPlayer({
  puzzle: "3x3x3",
  alg: "",
  background: "checkered",
  hintFacelets: "floating",
  tempoScale: 1,
  experimentalDragInput: "none",
  experimentalMovePressInput: "none",
  controlPanel: "none",
});

playerMount.append(player);

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

async function settleFrames(count = 2) {
  for (let index = 0; index < count; index += 1) {
    await nextFrame();
  }
}

window.cubebenchReplay = {
  async initialize(meta) {
    kicker.textContent = meta.kicker ?? "CubeBench Replay";
    runLabel.textContent = meta.runLabel ?? "";
    title.textContent = "Replay ready";
    subtitle.textContent = "";
    progress.textContent = "";
    await settleFrames(4);
  },

  async render(frame) {
    title.textContent = frame.title;
    subtitle.textContent = frame.subtitle ?? "";
    progress.textContent = frame.progressText ?? "";
    player.alg = frame.alg ?? "";
    player.jumpToEnd({ flash: false });
    player.pause();
    await settleFrames(3);
  },
};
