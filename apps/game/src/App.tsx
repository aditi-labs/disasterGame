import { OperatorRoute } from "./routes/operator/OperatorRoute";
import { ProjectorRoute } from "./routes/projector/ProjectorRoute";

// Two screens, one source of truth (the live WorldService):
//   /operator   laptop controls and diagnostics (default)
//   /projector  fullscreen projection over the printed board (?mode=screen for rehearsal)
export function App() {
  const path = window.location.pathname.replace(/\/$/, "");
  return path.endsWith("/projector") ? <ProjectorRoute /> : <OperatorRoute />;
}
