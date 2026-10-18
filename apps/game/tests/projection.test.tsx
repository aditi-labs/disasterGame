import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { BoardSvg } from "../src/game/overlays/BoardSvg";
import { buildBoardModel } from "../src/game/worldAdapter";
import { buildResults } from "../src/game/results";
import { IDLE_VIEW } from "../src/game/clock";
import { applyHomography, calibrationMatrix3d, DEFAULT_CALIBRATION, solveHomography, targetCorners, uvMatrix3d } from "../src/game/homography";
import { looksLikeBridgeToCamera, PALETTE } from "../src/game/palette";
import { BOARD_MARKERS, insideMarkerKeepout, MARKER_LAYOUT_VERIFIED, MARKERS_VERIFIED } from "../src/game/board";
import registration from "../../../perception/board_registration.json";
import { setBoardAspect } from "../src/types/geometry";
import { fixture } from "./fixtures";

describe("projector registration", () => {
  it("maps normalized world points through the measured matrix before pixel keystone", () => {
    const m = [1.1,.1,-.05,.03,.8,.1,.02,-.04,1];
    const width = 1000, height = 800;
    const css = uvMatrix3d(m, width, height).slice(9,-1).split(",").map(Number);
    for (const [u,v] of [[0,0],[1,0],[1,1],[0,1],[.3,.7]]) {
      const x=u*width, y=v*height, w=css[3]*x+css[7]*y+css[15];
      const expected=applyHomography(m.slice(0,8), [u,v]);
      expect((css[0]*x+css[4]*y+css[12])/w).toBeCloseTo(expected[0]*width, 6);
      expect((css[1]*x+css[5]*y+css[13])/w).toBeCloseTo(expected[1]*height, 6);
    }
  });
  const src: [number, number][] = [[0, 0], [1920, 0], [1920, 1080], [0, 1080]];
  it("maps all four measured corners and round-trips points under perspective", () => {
    const dst: [number, number][] = [[32, 10], [1880, 51], [1902, 1031], [20, 1074]];
    const forward = solveHomography(src, dst);
    const inverse = solveHomography(dst, src);
    src.forEach((p, i) => applyHomography(forward, p).forEach((n, j) => expect(n).toBeCloseTo(dst[i][j], 7)));
    applyHomography(inverse, applyHomography(forward, [550, 780])).forEach((n, i) => expect(n).toBeCloseTo([550, 780][i], 7));
  });
  it("keeps default alignment and encodes the same affine/corner transform in CSS", () => {
    expect(targetCorners(DEFAULT_CALIBRATION, 1920, 1080)).toEqual(src);
    const cal = { ...DEFAULT_CALIBRATION, dx: 10, dy: -8, sx: 0.96, sy: 1.03, rot: 1.2 };
    const matrix = calibrationMatrix3d(cal, 1920, 1080).slice(9, -1).split(",").map(Number);
    src.forEach(([x, y], i) => {
      const w = matrix[3] * x + matrix[7] * y + matrix[15];
      expect((matrix[0] * x + matrix[4] * y + matrix[12]) / w).toBeCloseTo(targetCorners(cal, 1920, 1080)[i][0], 5);
    });
  });
  it("rejects degenerate corner measurements", () => expect(() => solveHomography(src, [[0, 0], [0, 0], [0, 0], [0, 0]])).toThrow(/degenerate/));
  it("keeps registration reticles clear of the provisional marker masks", () => {
    for (const marker of BOARD_MARKERS) expect(insideMarkerKeepout(marker.center)).toBe(true);
    for (const uv of [[0.18, 0.18], [0.82, 0.18], [0.82, 0.82], [0.18, 0.82], [0.5, 0.5]] as [number, number][]) expect(insideMarkerKeepout(uv)).toBe(false);
  });
  it("uses Lane B's photo layout without claiming measured positions or print/world alignment", () => {
    expect(BOARD_MARKERS).toEqual(registration.markers.map(m => ({ id: m.id, center: m.center_uv })));
    expect(BOARD_MARKERS.map(m => m.id)).toEqual([10, 11, 13, 12]);
    expect(MARKER_LAYOUT_VERIFIED).toBe(true);
    expect(MARKERS_VERIFIED).toBe(false);
  });
});

describe("projection palette", () => {
  it("detects the legacy yellow range, including both thresholds", () => {
    expect(looksLikeBridgeToCamera("#ffff00")).toBe(true);
    expect(looksLikeBridgeToCamera("#ffaa00")).toBe(true);
    expect(looksLikeBridgeToCamera("#ffffff")).toBe(false);
    expect(looksLikeBridgeToCamera("#080800")).toBe(false);
  });
  it.each(Object.entries(PALETTE))("%s stays outside the legacy bridge HSV filter", (_, hex) => expect(looksLikeBridgeToCamera(hex)).toBe(false));
});

describe("board rendering with actual backend snapshots", () => {
  const { scenario, states } = fixture;
  setBoardAspect(scenario.aspect_ratio);
  const render = (phase: typeof IDLE_VIEW.phase, surface: "screen" | "overlay" = "overlay", syncing = false) => renderToStaticMarkup(
    <BoardSvg scenario={scenario} snapshot={states.connected} model={buildBoardModel(scenario, states.connected, [], false)} clock={{ ...IDLE_VIEW, phase }} reactions={[]} rejections={[]} pending={[]} surface={surface} variant="projector" results={buildResults(scenario, states.connected)} resultsSyncing={syncing} />,
  );
  it("renders screen and projection surfaces without invented flood while idle", () => {
    expect(render("IDLE", "screen")).toContain("layer-basemap");
    expect(render("IDLE")).not.toContain("layer-basemap");
    expect(render("IDLE")).not.toContain("flood-reveal");
    expect(render("CROSSING")).toContain("layer-population");
    expect(render("CROSSING")).not.toMatch(/NaN|undefined/);
    expect(render("CROSSING")).not.toContain('class="timer');
    expect(render("CROSSING", "screen")).not.toContain('class="layer-markers"');
  });
  it("keeps black marker masks after every projected layer and labels pending results", () => {
    const html = render("RESULTS");
    expect(html.indexOf("layer-markers")).toBeGreaterThan(html.indexOf('class="results"'));
    expect(html).toContain("RESPONSE COMPLETE");
    expect(html).toContain("THE FLOOD SETTLES");
    expect(html).not.toContain('class="results-card"');
    expect(render("RESULTS", "overlay", true)).toContain("SYNCING RESULTS");
    expect(html).not.toContain("EVERYONE SAVED");
  });
});
