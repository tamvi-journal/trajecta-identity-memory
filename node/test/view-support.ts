import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, unlinkSync } from "node:fs";
import { connect } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { InjectedClock } from "../src/clock.ts";
import { floatHex, pyFloatRepr, type JsonValue } from "../src/encoding.ts";
import { IdentityMemory } from "../src/identity.ts";
import { loadProfile } from "../src/profile.ts";
import { parseLossless } from "../src/json.ts";
import { startView, type RunningView } from "../src/view.ts";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
export const CORPUS = resolve(ROOT, "spec/golden-view-v1");
export const PROFILE = loadProfile(resolve(ROOT, "trajecta_identity/profiles/example/profile.json"));
export const HEADERS = [
  "Content-Type",
  "Content-Length",
  "Cache-Control",
  "X-Content-Type-Options",
  "X-Frame-Options",
  "Referrer-Policy",
];
export const sha = (raw: Buffer) => createHash("sha256").update(raw).digest("hex");
export function plain(value: JsonValue): any {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(plain);
  if (value.kind === "object") return Object.fromEntries(value.entries.map(([key, v]) => [key, plain(v)]));
  return value.kind === "int" ? Number(value.value) : value.value;
}
export const readJson = (path: string) => plain(parseLossless(readFileSync(path, "utf8")));
export function inventory(root: string): unknown {
  return readdirSync(root, { recursive: true })
    .map(String)
    .sort()
    .map((name) => {
      const path = resolve(root, name),
        stat = statSync(path, { bigint: true });
      return [name, stat.isDirectory() ? "directory" : [readFileSync(path), stat.mtimeNs]];
    });
}
export function temporary(): string {
  const parent = resolve(ROOT, ".isolation/tmp");
  mkdirSync(parent, { recursive: true });
  return mkdtempSync(resolve(parent, "ts-view-"));
}
export async function request(server: Pick<RunningView, "port">, item: any, host = "127.0.0.1") {
  const headers: [string, string][] = item.headers ?? [["Host", `127.0.0.1:${server.port}`]];
  const rendered = headers.map(
    ([key, value]) =>
      `${key}: ${value
        .replaceAll("{port}", String(server.port))
        .replaceAll("{other}", String((server.port % 65535) + 1))}`,
  );
  const raw =
    `${item.method ?? "GET"} ${item.path ?? "/"} HTTP/1.1\r\n${rendered.join("\r\n")}` +
    `${rendered.length ? "\r\n" : ""}Connection: close\r\n\r\n`;
  const bytes = await new Promise<Buffer>((resolve, reject) => {
    const socket = connect(server.port, host),
      chunks: Buffer[] = [];
    socket.setTimeout(5000, () => socket.destroy(new Error("view response timed out")));
    socket.once("connect", () => socket.write(raw));
    socket.on("data", (chunk) => chunks.push(chunk));
    socket.once("error", reject);
    socket.once("end", () => resolve(Buffer.concat(chunks)));
  });
  const split = bytes.indexOf("\r\n\r\n");
  assert(split >= 0, bytes.toString());
  const lines = bytes.subarray(0, split).toString().split("\r\n");
  const output = Object.fromEntries(
    lines.slice(1).map((line) => {
      const colon = line.indexOf(":");
      return [line.slice(0, colon).toLowerCase(), line.slice(colon + 1).trim()];
    }),
  );
  return {
    status: Number(lines[0].split(" ")[1]),
    headers: Object.fromEntries(HEADERS.map((key) => [key, output[key.toLowerCase()]])),
    body: bytes.subarray(split + 4),
  };
}
export function compare(item: any, actual: Awaited<ReturnType<typeof request>>, directory: string): void {
  const mode = item.comparison ?? "exact",
    expected = item.response;
  if (mode === "G16") assert(actual.status >= 400);
  else assert.equal(actual.status, expected.status, item.label);
  for (const key of HEADERS) {
    const value =
      ["G16", "handler-error"].includes(mode) && key === "Content-Length"
        ? String(actual.body.length)
        : expected.headers[key];
    assert.equal(actual.headers[key], value, `${item.label}: ${key}`);
  }
  if (mode === "exact") assert.deepEqual(actual.body, readFileSync(resolve(directory, expected.body)), item.label);
  else assert(["G16", "handler-error"].includes(mode), `unknown carve-out ${mode}`);
}
export function dumpDatabase(path: string): unknown {
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    const tables: Record<string, unknown> = {};
    const quote = (value: string) => `"${value.replaceAll('"', '""')}"`;
    for (const table of db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all()) {
      const name = String(table.name),
        columns = db.prepare(`PRAGMA table_info(${quote(name)})`).all();
      const pk = columns
        .filter((c) => c.pk)
        .sort((a, b) => Number(a.pk) - Number(b.pk))
        .map((c) => quote(String(c.name)));
      const floats = new Set(columns.filter((c) => String(c.type).toUpperCase().includes("REAL")).map((c) => c.name));
      tables[name] = db
        .prepare(`SELECT * FROM ${quote(name)} ORDER BY ${pk.length ? pk.join(",") : "rowid"}`)
        .all()
        .map((row) =>
          Object.fromEntries(
            Object.entries(row).map(([key, value]) => [
              key,
              typeof value === "number" && floats.has(key) ? { repr: pyFloatRepr(value), hex: floatHex(value) } : value,
            ]),
          ),
        );
    }
    return { tables };
  } finally {
    db.close();
  }
}
