import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["tests/live/*.test.tsx"], testTimeout: 100000, hookTimeout: 20000, pool: "forks", poolOptions: { forks: { singleFork: true } } },
});
