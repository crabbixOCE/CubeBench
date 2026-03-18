import Cube from "cubejs";
import { randomScrambleForEvent } from "cubing/scramble";

const ORIENTATION_TURNS = ["x", "y", "z"];

const FACE_SPECS = [
  {
    name: "U",
    faceletStart: 0,
    crossEdges: [0, 1, 2, 3],
    layerEdges: [0, 1, 2, 3],
    layerCorners: [0, 1, 2, 3],
    blockEdges: [0, 1, 2, 3, 8, 9, 10, 11],
    blockCorners: [0, 1, 2, 3],
  },
  {
    name: "R",
    faceletStart: 9,
    crossEdges: [0, 4, 8, 11],
    layerEdges: [0, 4, 8, 11],
    layerCorners: [0, 3, 4, 7],
    blockEdges: [0, 1, 3, 4, 5, 7, 8, 11],
    blockCorners: [0, 3, 4, 7],
  },
  {
    name: "F",
    faceletStart: 18,
    crossEdges: [1, 5, 8, 9],
    layerEdges: [1, 5, 8, 9],
    layerCorners: [0, 1, 4, 5],
    blockEdges: [0, 1, 2, 4, 5, 6, 8, 9],
    blockCorners: [0, 1, 4, 5],
  },
  {
    name: "D",
    faceletStart: 27,
    crossEdges: [4, 5, 6, 7],
    layerEdges: [4, 5, 6, 7],
    layerCorners: [4, 5, 6, 7],
    blockEdges: [4, 5, 6, 7, 8, 9, 10, 11],
    blockCorners: [4, 5, 6, 7],
  },
  {
    name: "L",
    faceletStart: 36,
    crossEdges: [2, 6, 9, 10],
    layerEdges: [2, 6, 9, 10],
    layerCorners: [1, 2, 5, 6],
    blockEdges: [1, 2, 3, 5, 6, 7, 9, 10],
    blockCorners: [1, 2, 5, 6],
  },
  {
    name: "B",
    faceletStart: 45,
    crossEdges: [3, 7, 10, 11],
    layerEdges: [3, 7, 10, 11],
    layerCorners: [2, 3, 6, 7],
    blockEdges: [0, 2, 3, 4, 6, 7, 10, 11],
    blockCorners: [2, 3, 6, 7],
  },
];

function buildOrientationMoves() {
  const seen = new Set();
  const queue = [{ moves: "", cube: new Cube() }];
  const orientations = [];

  while (queue.length > 0) {
    const { moves, cube } = queue.shift();
    const key = JSON.stringify(cube.toJSON());
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    orientations.push(moves);

    for (const turn of ORIENTATION_TURNS) {
      const next = Cube.fromString(cube.asString());
      next.move(turn);
      queue.push({
        moves: moves ? `${moves} ${turn}` : turn,
        cube: next,
      });
    }
  }

  return orientations;
}

function centerKey(cube) {
  const facelets = cube.asString();
  return FACE_SPECS.map((faceSpec) => facelets[faceSpec.faceletStart + 4]).join("");
}

function buildCenterAligners() {
  const aligners = new Map();

  for (const moves of buildOrientationMoves()) {
    const cube = new Cube();
    if (moves) {
      cube.move(moves);
    }
    aligners.set(centerKey(cube), moves ? Cube.inverse(moves) : "");
  }

  return aligners;
}

const CENTER_ALIGNERS = buildCenterAligners();

function readPayload() {
  const raw = process.argv[2];

  if (!raw) {
    throw new Error("Expected a JSON payload as the first argument.");
  }

  return JSON.parse(raw);
}

function loadCube(payload) {
  if (payload.cube !== "3x3") {
    throw new Error(`Unsupported cube: ${payload.cube}`);
  }

  if (payload.state) {
    return Cube.fromString(payload.state);
  }

  return new Cube();
}

async function generateScramble(payload) {
  if (payload.cube !== "3x3") {
    throw new Error(`Unsupported cube: ${payload.cube}`);
  }

  const scramble = await randomScrambleForEvent("333");
  return scramble.toString();
}

function areEdgeSlotsSolved(cube, indices) {
  return indices.every((index) => cube.ep[index] === index && cube.eo[index] === 0);
}

function areCornerSlotsSolved(cube, indices) {
  return indices.every((index) => cube.cp[index] === index && cube.co[index] === 0);
}

function isOneFaceSolved(cube, faceSpec) {
  const facelets = cube.asString().slice(faceSpec.faceletStart, faceSpec.faceletStart + 9);
  return facelets.split("").every((sticker) => sticker === facelets[4]);
}

function alignToCanonicalOrientation(cube) {
  const aligned = Cube.fromString(cube.asString());
  const alignMoves = CENTER_ALIGNERS.get(centerKey(aligned));
  if (alignMoves === undefined) {
    throw new Error("Unsupported center orientation.");
  }
  if (alignMoves) {
    aligned.move(alignMoves);
  }
  return aligned;
}

function checkTaskComplete(cube, task) {
  const aligned = alignToCanonicalOrientation(cube);

  switch (task) {
    case "cross":
      return FACE_SPECS.some((faceSpec) => areEdgeSlotsSolved(aligned, faceSpec.crossEdges));
    case "one_face":
      return FACE_SPECS.some((faceSpec) => isOneFaceSolved(aligned, faceSpec));
    case "one_layer":
      return FACE_SPECS.some(
        (faceSpec) =>
          areEdgeSlotsSolved(aligned, faceSpec.layerEdges) &&
          areCornerSlotsSolved(aligned, faceSpec.layerCorners),
      );
    case "f2l":
      return FACE_SPECS.some(
        (faceSpec) =>
          areEdgeSlotsSolved(aligned, faceSpec.blockEdges) &&
          areCornerSlotsSolved(aligned, faceSpec.blockCorners),
      );
    case "full_solve":
      return cube.isSolved();
    default:
      throw new Error(`Unsupported task: ${task}`);
  }
}

async function main() {
  const payload = readPayload();
  if (payload.generate_scramble) {
    process.stdout.write(
      `${JSON.stringify({ cube: payload.cube, scramble: await generateScramble(payload) })}\n`,
    );
    return;
  }

  const cube = loadCube(payload);

  if (payload.moves) {
    cube.move(payload.moves);
  }

  const result = {
    cube: payload.cube,
    facelet_string: cube.asString(),
    cubie_json: cube.toJSON(),
    is_solved: cube.isSolved(),
  };

  if (payload.check_task) {
    result.task = payload.check_task;
    result.task_completed = checkTaskComplete(cube, payload.check_task);
  }

  process.stdout.write(`${JSON.stringify(result)}\n`);
}

await main();
