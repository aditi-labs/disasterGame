"""Fit a print/world homography from real measured landmarks, checking held-out points."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.physical import transform


def fit(points):
    if len(points) < 6:
        raise ValueError("At least six measured landmark pairs required: four fit, two or more validation points")
    rows, values = [], []
    for point in points:
        if not point.get("label") or not all(len(point[k]) == 2 and all(np.isfinite(n) and 0 <= n <= 1 for n in point[k]) for k in ("print_uv", "world_uv")):
            raise ValueError("Every landmark needs a label and finite print_uv/world_uv within the board")
    for point in points[:4]:
        x, y = point["print_uv"]
        u, v = point["world_uv"]
        rows.extend([[x,y,1,0,0,0,-u*x,-u*y], [0,0,0,x,y,1,-v*x,-v*y]])
        values.extend([u,v])
    matrix = [*np.linalg.solve(rows, values).tolist(), 1.0]
    errors = [float(np.linalg.norm(np.array(transform(matrix, p["print_uv"])) - p["world_uv"])) for p in points[4:]]
    if max(errors) > .01:
        raise ValueError(f"Validation error {max(errors):.5f} world UV exceeds 0.01. Recheck measured landmarks")
    return matrix, {"point_count": len(errors), "max_error_uv": max(errors), "rms_uv": float(np.sqrt(np.mean(np.square(errors))))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, type=Path, help="JSON array of six or more measured labelled landmark pairs")
    parser.add_argument("--measured-by", required=True)
    parser.add_argument("--source", required=True, help="Physical print/source and measurement evidence")
    parser.add_argument("--scenario", default="nepal_rasuwa_hot_v1")
    parser.add_argument("--output", type=Path, default=Path("perception/board_mapping.json"))
    args = parser.parse_args()
    points = json.loads(args.points.read_text(encoding="utf-8"))
    matrix, validation = fit(points)
    result = {"schema": "floodshift.print_world_mapping.v1", "status": "MEASURED", "scenario_id": args.scenario,
        "print_to_world": matrix, "measured_by": args.measured_by,
        "measured_on": datetime.now(timezone.utc).isoformat(), "source": args.source,
        "landmarks": points, "validation": validation}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}; held-out max error {validation['max_error_uv']:.6f} world UV. Restart the backend and verify on the board.")


if __name__ == "__main__":
    main()
