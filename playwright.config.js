import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dataDirectory = mkdtempSync(join(tmpdir(), "libraos-playwright-"));
const python = process.env.LIBRAOS_PYTHON || "python";
const port = process.env.LIBRAOS_TEST_PORT || "8001";

process.on("exit", () => {
  rmSync(dataDirectory, { recursive: true, force: true });
});

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: `"${python}" -m uvicorn server.main:app --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      LIBRAOS_DATA_DIR: dataDirectory,
    },
  },
});
