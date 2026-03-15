import Cube from "cubejs";

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

function areEdgeSlotsSolved(cube, indices) {
  return indices.every((index) => cube.ep[index] === index && cube.eo[index] === 0);
}

function areCornerSlotsSolved(cube, indices) {
  return indices.every((index) => cube.cp[index] === index && cube.co[index] === 0);
}

function checkTaskComplete(cube, task) {
  switch (task) {
    case "white_cross":
      return areEdgeSlotsSolved(cube, [0, 1, 2, 3]);
    case "f2l":
      return (
        areEdgeSlotsSolved(cube, [0, 1, 2, 3, 8, 9, 10, 11]) &&
        areCornerSlotsSolved(cube, [0, 1, 2, 3])
      );
    case "full_solve":
      return cube.isSolved();
    default:
      throw new Error(`Unsupported task: ${task}`);
  }
}

function main() {
  const payload = readPayload();
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

main();
