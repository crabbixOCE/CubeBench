import { Alg, Move } from "cubing/alg";
import Cube from "cubejs";

export const SAMPLE_FILE_PATH = "/algorithms/demo.txt";

export async function readMovesFile(file) {
  const text = await file.text();

  if (!text.trim()) {
    throw new Error("The selected file is empty.");
  }

  return text;
}

function stripHashComments(rawText) {
  return rawText
    .split("\n")
    .map((line) => line.replace(/\s+#.*$/, "").replace(/^#.*$/, ""))
    .join("\n");
}

function expandToCubeJsMoves(alg) {
  return [...alg.expand().units()]
    .filter((unit) => unit instanceof Move)
    .map((move) => move.toString());
}

function summarizeCubeState(expandedMoves) {
  if (expandedMoves.length === 0) {
    return {
      cubeState: "Solved cube",
      isSolved: true,
      note: "Loaded an empty algorithm.",
      tone: "info",
    };
  }

  const cube = new Cube();
  const cubeJsAlg = expandedMoves.join(" ");

  try {
    cube.move(cubeJsAlg);
  } catch (error) {
    return {
      cubeState: "Unavailable",
      isSolved: false,
      note:
        "Applied to the viewer, but cubejs could not summarize the final state for this notation.",
      tone: "warning",
    };
  }

  return {
    cubeState: cube.asString(),
    isSolved: cube.isSolved(),
    note: "Applied successfully.",
    tone: "success",
  };
}

export function applyMovesText({ rawText, player, sourceLabel }) {
  const normalizedText = stripHashComments(rawText).trim();

  if (!normalizedText) {
    throw new Error("No moves were provided.");
  }

  const alg = Alg.fromString(normalizedText);
  const expandedMoves = expandToCubeJsMoves(alg);
  const summary = summarizeCubeState(expandedMoves);

  player.alg = alg;
  player.jumpToStart({ flash: false });
  player.pause();

  return {
    cubeState: summary.cubeState,
    displayAlg: alg.toString(),
    isSolved: summary.isSolved,
    message: `${summary.note} Viewer updated from ${sourceLabel}.`,
    moveCount: expandedMoves.length,
    sourceLabel,
    tone: summary.tone,
  };
}
