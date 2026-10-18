"""Register the printed map artwork (nepalmap.png) to the scenario world frame.

The physical board is nepalmap.png printed full-bleed at 24 x 18 in, with the four
ArUco markers pasted over its corners. Print UV is therefore the artwork's own pixel
frame divided by its size. This script measures, instead of guessing:

1. print -> world: an affine fit of the scenario's mapped OSM rivers and roads
   (``waterways_board.json`` / ``roads_board.json``) onto the river and road pixels of
   the artwork, by robust chamfer distance (coarse grid, then Nelder-Mead). The optimum
   is refitted on two disjoint halves of the mapped features (alternate pieces) and
   compared at every scenario site, to report how far it moves when half of the
   evidence is withheld.
2. Optional (``--photo``): marker centres in print UV, by registering a photo of the
   real board to the artwork (SIFT + RANSAC homography) and detecting the markers in it.

Outputs ``perception/board_mapping.json`` and, with ``--photo``, updates the marker
block of ``perception/board_registration.json``. Re-run ``perception.service --calibrate``
at the venue if the markers were moved after the photo was taken.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
MAJOR_ROADS = {"primary", "unclassified", "tertiary", "residential", "track", "service"}
INCH_MM = 25.4


def masks(image):
    px = image.astype(int)
    b, g, r = px[..., 0], px[..., 1], px[..., 2]
    river = (((b - r) > 70) & (b > 200) & (g > 170)).astype(np.uint8)
    spread = px.max(2) - px.min(2)
    road = ((spread < 14) & (px.max(2) > 185) & (px.max(2) < 230)).astype(np.uint8)
    return river, road


def densify(line, step=0.001):
    line = np.asarray(line, float)
    out = []
    for a, c in zip(line[:-1], line[1:]):
        k = max(1, int(np.linalg.norm(c - a) / step))
        out.extend(a + (c - a) * t for t in np.linspace(0, 1, k, endpoint=False))
    out.append(line[-1])
    return np.array(out)


def lines(feature):
    geometry = feature["geometry"]
    return [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]


def world_features(data):
    waterways = json.loads((data / "waterways_board.json").read_text(encoding="utf-8"))["features"]
    roads = json.loads((data / "roads_board.json").read_text(encoding="utf-8"))["features"]
    rivers = [densify(l) for f in waterways if f["properties"].get("waterway") == "river" for l in lines(f)]
    major = [densify(l) for f in roads if f["properties"].get("highway") in MAJOR_ROADS for l in lines(f)]
    return rivers, major


def split_points(lines_, step=0.04):
    """Cut each line into ~0.04 UV pieces and deal them alternately into two sets."""
    pieces = [line[i:i + max(2, int(step / 0.001))] for line in lines_ for i in range(0, len(line), max(2, int(step / 0.001)))]
    return np.concatenate(pieces[0::2]), np.concatenate(pieces[1::2])


def project(p, uv):
    return uv @ np.array([[p[0], p[1]], [p[3], p[4]]]).T + np.array([p[2], p[5]])


def fit(river_pts, road_pts, dt_river, dt_road, size, start=None):
    """Affine world UV -> artwork px minimising capped one-way chamfer distance."""
    width, height = size

    def one_way(p, pts, dt, cap):
        q = project(p, pts)
        inside = (q[:, 0] >= 0) & (q[:, 0] < width - 1) & (q[:, 1] >= 0) & (q[:, 1] < height - 1)
        if inside.sum() < 150:
            return cap
        qi = q[inside].astype(int)
        return np.minimum(dt[qi[:, 1], qi[:, 0]], cap).mean()

    def cost(p, cap):
        return one_way(p, road_pts, dt_road, cap) + one_way(p, river_pts, dt_river, cap)

    if start is not None:
        p = np.array(start, float)
        for cap in (10, 5):
            p = minimize(lambda q: cost(q, cap), p, method="Nelder-Mead",
                         options={"xatol": 1e-3, "fatol": 1e-5, "maxiter": 8000, "adaptive": True}).x
        return p
    # Coarse similarity search, anchored where the main rivers meet in both frames.
    confluence_world = np.array([0.4410883, 0.5059600])
    confluence_px = np.array([0.5608, 0.5276]) * [width, height]
    best = None
    for s in np.linspace(1800, 2600, 17) * width / 1448:
        for th in np.radians(np.linspace(-3, 3, 5)):
            rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
            for dx in np.arange(-120, 121, 30) * width / 1448:
                for dy in np.arange(-120, 121, 30) * width / 1448:
                    t = confluence_px + [dx, dy] - s * rot @ confluence_world
                    p = [s * rot[0, 0], s * rot[0, 1], t[0], s * rot[1, 0], s * rot[1, 1], t[1]]
                    value = cost(p, 20)
                    if best is None or value < best[0]:
                        best = (value, p)
    p = best[1]
    for cap in (20, 10, 5):
        p = minimize(lambda q: cost(q, cap), p, method="Nelder-Mead",
                     options={"xatol": 1e-3, "fatol": 1e-5, "maxiter": 8000, "adaptive": True}).x
    return p


def residuals(p, pts, dt, size):
    q = project(p, pts)
    inside = (q[:, 0] >= 0) & (q[:, 0] < size[0] - 1) & (q[:, 1] >= 0) & (q[:, 1] < size[1] - 1)
    d = dt[q[inside, 1].astype(int), q[inside, 0].astype(int)]
    return {"median_px": float(np.median(d)), "p75_px": float(np.percentile(d, 75)), "points": int(inside.sum())}


def world_to_print_matrix(p, size):
    """Row-major 3x3 homography: world UV -> print UV (normalised by artwork size)."""
    w, h = size
    return np.array([[p[0] / w, p[1] / w, p[2] / w], [p[3] / h, p[4] / h, p[5] / h], [0, 0, 1.0]])


def markers_from_photo(photo_path, art_gray, size):
    photo = cv2.imread(str(photo_path), cv2.IMREAD_GRAYSCALE)
    if photo is None:
        raise SystemExit(f"cannot read photo {photo_path}")
    sift = cv2.SIFT_create(8000)
    ka, da = sift.detectAndCompute(art_gray, None)
    kp, dp = sift.detectAndCompute(photo, None)
    good = [a for a, b in cv2.BFMatcher().knnMatch(dp, da, k=2) if a.distance < 0.75 * b.distance]
    src = np.float32([kp[g.queryIdx].pt for g in good])
    dst = np.float32([ka[g.trainIdx].pt for g in good])
    homography, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    ok = inliers.ravel() == 1
    err = np.linalg.norm(cv2.perspectiveTransform(src[ok][None], homography)[0] - dst[ok], axis=1)
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMax = 80
    params.minMarkerPerimeterRate = 0.02
    params.polygonalApproxAccuracyRate = 0.05
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), params)
    pad = 60
    padded = cv2.copyMakeBorder(photo, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    corners, ids, _ = detector.detectMarkers(padded)
    found = {}
    for c, marker_id in zip(corners, [] if ids is None else ids.ravel()):
        if int(marker_id) not in (10, 11, 12, 13):
            continue
        pts = cv2.perspectiveTransform(c - pad, homography)[0] / size
        found[int(marker_id)] = pts
    return found, {"matches": len(good), "inliers": int(ok.sum()), "median_px": float(np.median(err)),
                   "p90_px": float(np.percentile(err, 90))}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artwork", type=Path, default=ROOT / "nepalmap.png")
    parser.add_argument("--scenario", default="nepal_rasuwa_hot_v1")
    parser.add_argument("--paper-in", type=float, nargs=2, default=(24.0, 18.0), metavar=("W", "H"))
    parser.add_argument("--photo", type=Path, help="Photo of the real board, used to locate the pasted markers")
    parser.add_argument("--measured-by", required=True)
    parser.add_argument("--mapping-out", type=Path, default=ROOT / "perception/board_mapping.json")
    parser.add_argument("--registration", type=Path, default=ROOT / "perception/board_registration.json")
    parser.add_argument("--max-site-disagreement-uv", type=float, default=0.01)
    args = parser.parse_args()

    art = cv2.imread(str(args.artwork))
    if art is None:
        raise SystemExit(f"cannot read artwork {args.artwork}")
    size = (art.shape[1], art.shape[0])
    data = ROOT / "scenarios" / args.scenario / "data"
    river, road = masks(art)
    dt_river = cv2.distanceTransform(1 - river, cv2.DIST_L2, 5)
    dt_road = cv2.distanceTransform(1 - road, cv2.DIST_L2, 5)
    river_lines, road_lines = world_features(data)
    river_pts, road_pts = np.concatenate(river_lines), np.concatenate(road_lines)
    (river_a, river_b), (road_a, road_b) = split_points(river_lines), split_points(road_lines)

    full = fit(river_pts, road_pts, dt_river, dt_road, size)
    # Stability: refit the optimum with half of the mapped features withheld.
    half_a = fit(river_a, road_a, dt_river, dt_road, size, start=full)
    half_b = fit(river_b, road_b, dt_river, dt_road, size, start=full)
    sites = json.loads((data / "sites.json").read_text(encoding="utf-8"))
    site_uv = np.array([s["board_uv"] for s in sites if s["kind"] != "control_start_pad"])
    to_uv = lambda p: project(p, site_uv) / size
    disagreement = float(max(np.linalg.norm(to_uv(half_a) - to_uv(full), axis=1).max(),
                             np.linalg.norm(to_uv(half_b) - to_uv(full), axis=1).max()))
    stats = {"river": residuals(full, river_pts, dt_river, size), "road": residuals(full, road_pts, dt_road, size),
             "held_out_features": {"a_on_b_road": residuals(half_a, road_b, dt_road, size),
                                   "b_on_a_road": residuals(half_b, road_a, dt_road, size)},
             "split_half_site_disagreement_max_print_uv": disagreement}
    print(json.dumps(stats, indent=2))
    if disagreement > args.max_site_disagreement_uv:
        raise SystemExit(f"Split-half fits disagree by {disagreement:.4f} print UV at a site; not written.")

    world_to_print = world_to_print_matrix(full, size)
    print_to_world = np.linalg.inv(world_to_print)
    print_to_world /= print_to_world[2, 2]
    now = datetime.now(timezone.utc).isoformat()
    mapping = {
        "schema": "floodshift.print_world_mapping.v1", "status": "MEASURED", "scenario_id": args.scenario,
        "print_to_world": [float(n) for n in print_to_world.ravel()],
        "measured_by": args.measured_by, "measured_on": now,
        "source": f"{args.artwork.name}: the exact artwork printed full-bleed on the board ({args.paper_in[0]:g} x {args.paper_in[1]:g} in)",
        "method": "scripts/register_print_artwork.py: affine chamfer fit of scenario OSM rivers and major roads onto the artwork's river/road pixels",
        "artwork_px": list(size),
        "validation": stats,
    }
    args.mapping_out.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.mapping_out}")

    if args.photo:
        found, quality = markers_from_photo(args.photo, cv2.cvtColor(art, cv2.COLOR_BGR2GRAY), size)
        print("photo registration", quality, "markers", sorted(found))
        if sorted(found) != [10, 11, 12, 13]:
            raise SystemExit("All four board markers must be visible in the photo; registration not updated.")
        width_mm, height_mm = args.paper_in[0] * INCH_MM, args.paper_in[1] * INCH_MM
        reg = json.loads(args.registration.read_text(encoding="utf-8"))
        sides_mm = {}
        for marker in reg["markers"]:
            pts = found[marker["id"]]
            mm = pts * [width_mm, height_mm]
            sides_mm[marker["id"]] = float(np.mean([np.linalg.norm(mm[k] - mm[(k + 1) % 4]) for k in range(4)]))
            marker.update(center_uv=[round(float(n), 4) for n in pts.mean(0)], verified=True,
                          position_source=f"photo {args.photo.name} registered to {args.artwork.name}")
        reg["status"] = "MEASURED"
        reg["status_note"] = ("Marker centres measured by registering the board photo to the printed artwork "
                              "(scripts/register_print_artwork.py). Paper size from the print specification. "
                              "Re-run perception.service --calibrate if markers were moved after the photo.")
        reg["board"].update(width_mm=round(width_mm, 1), height_mm=round(height_mm, 1),
                            dimensions_source=f"print specification {args.paper_in[0]:g} x {args.paper_in[1]:g} in; artwork aspect {size[1] / size[0]:.4f}")
        # The pasted markers differ in size and sit slightly rotated, so one shared edge length
        # would make corner-based registration worse than the exact four-centre fit.
        reg["aruco"]["marker_size_mm"] = None
        reg["aruco"]["marker_sizes_mm"] = {str(k): round(v, 1) for k, v in sorted(sides_mm.items())}
        reg["aruco"]["marker_size_note"] = ("Per-marker printed edges measured from the registered photo (mm). They differ, so "
                                            "registration uses the four measured centres (all four markers must be visible); "
                                            "the projector masks each marker by its own measured size.")
        reg["measured"].update(measured_on=now, measured_by=args.measured_by, camera_source=f"still photo {args.photo.name}",
                               notes=f"photo->artwork homography: {quality['inliers']} SIFT inliers, median {quality['median_px']:.2f} px")
        args.registration.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {args.registration}")


if __name__ == "__main__":
    main()
