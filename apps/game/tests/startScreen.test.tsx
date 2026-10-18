import { act, create } from "react-test-renderer";
import { expect, it, vi } from "vitest";
import { StartScreen, type StartScreenProps } from "../src/routes/operator/StartScreen";

const ready: StartScreenProps = { mode: "idle", phase: "IDLE", remainingMs: 75000, ready: true, starting: false, physicalInputReady: false, error: null, onStart: () => {} };
it("provides one START action and no manual game controls", () => {
  const onStart = vi.fn();
  const view = create(<StartScreen {...ready} onStart={onStart} />);
  const buttons = view.root.findAllByType("button");
  expect(buttons).toHaveLength(1);
  expect(buttons[0].children).toEqual(["START"]);
  act(() => buttons[0].props.onClick());
  expect(onStart).toHaveBeenCalledOnce();
  expect(view.root.findAllByType("select")).toHaveLength(0);
  expect(JSON.stringify(view.toJSON())).toContain("Physical input is not ready");
  view.unmount();
});
it("disables START while running and allows another run after completion", () => {
  const view = create(<StartScreen {...ready} mode="running" phase="CROSSING" remainingMs={65000} />);
  expect(view.root.findByType("button").props.disabled).toBe(true);
  act(() => view.update(<StartScreen {...ready} mode="finished" phase="RESULTS" remainingMs={0} />));
  expect(view.root.findByType("button").props.disabled).toBe(false);
  view.unmount();
});
