/** Test-only HTTP adapter with the same reset-at-request clock as Python's corpus. */
import "../../node/src/sqlite-warning.ts";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
const { IdentityMemory } = await import("../../node/src/identity.ts");
const { InjectedClock } = await import("../../node/src/clock.ts");
const { loadProfile } = await import("../../node/src/profile.ts");
const { startView } = await import("../../node/src/view.ts");
let clock = new InjectedClock();
const memory = new IdentityMemory(
  loadProfile(fileURLToPath(new URL("../../trajecta_identity/profiles/example/profile.json", import.meta.url))),
  resolve("store.sqlite3"),
  {
    surface: "view",
    displayDatabase: "store.sqlite3",
    clock: {
      seconds: () => clock.seconds(),
      micros: () => clock.micros(),
    },
  },
);
const running = await startView(memory, { port: 0 });
running.server.prependListener("request", () => {
  clock = new InjectedClock();
});
process.stdout.write(String(running.port) + "\n");
