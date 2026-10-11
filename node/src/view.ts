/** Frozen view-api/v1. HTTP reads never track access; G15 is the explicit exception. */
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer, IncomingMessage, ServerResponse, type Server } from "node:http";
import type { Socket } from "node:net";
import { stateOf } from "./activation.ts";
import { PINNED } from "./authority.ts";
import {
  codePointSlice,
  compareCodePoint,
  orderedObject,
  pyFloat,
  pyInt,
  pyJsonDumps,
  pyRound,
  pyStrip,
} from "./encoding.ts";
import { ValueError } from "./errors.ts";
import type { IdentityMemory } from "./identity.ts";
import { parseLossless } from "./json.ts";
import { outputJson } from "./mcp.ts";
import type { Row } from "./store.ts";

const PAGE = readFileSync(new URL("../assets/view.html", import.meta.url));
const asciiLower = (value: string): string => value.replace(/[A-Z]/g, (c) => c.toLowerCase());
function headerEnd(raw: Buffer): { index: number; length: number } | null {
  const match = /\r?\n\r?\n/u.exec(raw.toString("latin1"));
  return match ? { index: match.index, length: match[0].length } : null;
}

export function snapshot(memory: IdentityMemory): unknown {
  if (memory.store.schemaInfo().state === "uninitialized") memory.bootstrap();
  const nodes = memory.store
    .currentView()
    .filter((row) => row.domain !== "anchor")
    .map((row) => ({
      record_id: row.record_id,
      domain: row.domain,
      title: row.title,
      summary: row.summary,
      revision: pyInt(Number(row.revision_number)),
      state: stateOf(row, memory.activation, PINNED),
      accessibility: pyFloat(pyRound(Number(row.accessibility), 3)),
      access_count: pyInt(Number(row.access_count)),
    }));
  nodes.sort(
    (a, b) =>
      b.accessibility.value - a.accessibility.value || compareCodePoint(String(a.record_id), String(b.record_id)),
  );
  const relations = memory.store
    .activeRelationRows()
    .filter((row) => !String(row.to_record_id).startsWith("anchor:"))
    .map((row) => ({ from: row.from_record_id, type: row.relation_type, to: row.to_record_id }));
  const core = memory.store.currentView("core");
  const status = memory.status();
  const statusRows = memory.store.currentView().filter((row) => row.domain !== "anchor");
  // Counter keys come from stored domain names; even a domain named "confidence"
  // is an integer counter, not a field whose name selects a floating-point value.
  const counters = (key: (row: Row) => string) => {
    // Map preserves current_view's order and treats numeric/prototype-looking domain
    // names as ordinary keys, just like Python's dictionaries.
    const counts = new Map<string, number>();
    for (const row of statusRows) {
      const name = key(row);
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return orderedObject(Array.from(counts, ([name, count]) => [name, pyInt(count)]));
  };
  return {
    profile: memory.profile.name,
    agent: memory.profile.agent,
    owner: memory.profile.owner,
    status: {
      ...status,
      records: counters((row) => String(row.domain)),
      activation: counters((row) => stateOf(row, memory.activation, PINNED)),
    },
    core: core.length
      ? {
          title: core[0].title,
          summary: core[0].summary,
          detail: parseLossless(String(core[0].content)),
          revisions: pyInt(memory.store.historicalView("core").length),
        }
      : null,
    timeline: memory.timeline(200),
    nodes,
    relations,
    open_core_proposals: memory.openCoreProposals(),
    open_discussions: memory.openDiscussions(),
    open_loops: memory.openLoops(),
  };
}

function unquotePlus(value: string): string {
  const bytes: number[] = [];
  for (let i = 0; i < value.length; ) {
    if (value[i] === "%" && /^[0-9a-fA-F]{2}$/.test(value.slice(i + 1, i + 3))) {
      bytes.push(Number.parseInt(value.slice(i + 1, i + 3), 16));
      i += 3;
    } else {
      const char = String.fromCodePoint(value.codePointAt(i)!);
      bytes.push(...Buffer.from(char === "+" ? " " : char, "utf8"));
      i += char.length;
    }
  }
  return Buffer.from(bytes).toString("utf8");
}

/** parse_qs defaults discard blank values, retain duplicates, and replace invalid UTF-8. */
export function parseCue(query: string): string {
  for (const field of query.split("&")) {
    const equals = field.indexOf("=");
    if (equals < 0) continue;
    const key = unquotePlus(field.slice(0, equals));
    const value = unquotePlus(field.slice(equals + 1));
    if (key === "cue" && value !== "") return codePointSlice(pyStrip(value), 2000);
  }
  return "";
}

function parsedTarget(target: string): { path: string; query: string } {
  // Python urlparse keeps encoded paths and dot segments, unlike WHATWG URL.
  target = target.replace(/[\r\n\t]/gu, "").replace(/^[\x00-\x20]+/u, "");
  target = target.replace(/^[A-Za-z][A-Za-z0-9+.-]*:/u, "");
  if (target.startsWith("//")) target = target.slice(2).replace(/^[^/?#]*/u, "");
  target = target.split("#", 1)[0];
  const question = target.indexOf("?");
  return {
    path: (question < 0 ? target : target.slice(0, question)).replace(/;[^/]*$/u, ""),
    query: question < 0 ? "" : target.slice(question + 1),
  };
}

/** All statuses and methods share the six contract headers. */
function send(response: ServerResponse, status: number, body: Buffer, contentType: string): void {
  response.shouldKeepAlive = false;
  response.writeHead(status, {
    Connection: "close",
    "Content-Type": contentType,
    "Content-Length": String(body.length),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
  });
  response.end(response.req.method === "HEAD" ? undefined : body);
}

export type RunningView = { server: Server; port: number; url: string; close(): Promise<void> };
export async function startView(
  memory: IdentityMemory,
  { host = "127.0.0.1", port = 8767 }: { host?: string; port?: number } = {},
): Promise<RunningView> {
  if (!["127.0.0.1", "localhost", "::1"].includes(host))
    throw new ValueError("the memory view only binds to localhost");
  memory.close();
  let boundPort: number;
  const wire = new WeakMap<Socket, Buffer>();
  const answered = new WeakSet<Socket>();
  const handle = (request: IncomingMessage, response: ServerResponse) => {
    if (answered.has(request.socket)) return;
    answered.add(request.socket);
    // Node trims trailing header whitespace; Python's email parser preserves it.
    // Recover that value before the exact P21 comparison. Python closes each HTTP/1.0
    // response, so there is one request per socket and no persistent framing state.
    const prefix = wire.get(request.socket);
    const end = prefix ? headerEnd(prefix) : null;
    let rawHeaders = request.rawHeaders;
    if (prefix && end) {
      const lines = prefix.subarray(0, end.index).toString("latin1").split(/\r?\n/u).slice(1);
      // http.client._read_headers counts every physical line, including the
      // terminating blank line, before parsing fields or running P21.
      if (lines.length + 1 > 100) {
        send(response, 431, Buffer.from("Too many headers"), "text/plain");
        return;
      }
      rawHeaders = [];
      for (const line of lines) {
        if (/^[ \t]/u.test(line) && rawHeaders.length) rawHeaders[rawHeaders.length - 1] += "\r\n" + line;
        else {
          const colon = line.indexOf(":");
          rawHeaders.push(line.slice(0, colon), line.slice(colon + 1).replace(/^[ \t]+/u, ""));
        }
      }
    }
    const headers = (name: string): string[] => {
      const values: string[] = [];
      for (let i = 0; i < rawHeaders.length; i += 2)
        if (asciiLower(rawHeaders[i]) === name) values.push(rawHeaders[i + 1]);
      return values;
    };
    const hosts = headers("host"),
      origins = headers("origin");
    const local = host === "::1" ? "[::1]" : "127.0.0.1";
    if (hosts.length !== 1 || ![`${local}:${boundPort}`, `localhost:${boundPort}`].includes(asciiLower(hosts[0]))) {
      send(response, 403, Buffer.from("forbidden host"), "text/plain; charset=utf-8");
      return;
    }
    if (origins.length && (origins.length !== 1 || asciiLower(origins[0]) !== asciiLower("http://" + hosts[0]))) {
      send(response, 403, Buffer.from("forbidden origin"), "text/plain; charset=utf-8");
      return;
    }
    if (request.method !== "GET") {
      send(response, 501, Buffer.from("Unsupported method"), "text/plain");
      return;
    }
    try {
      // BaseHTTPRequestHandler collapses a leading // before calling urlparse.
      const target = (request.url ?? "").replace(/^\/{2,}/u, "/");
      const { path: route, query } = parsedTarget(target);
      let value: unknown;
      if (route === "/" || route === "/index.html") {
        send(response, 200, PAGE, "text/html; charset=utf-8");
        return;
      } else if (route === "/api/snapshot") value = snapshot(memory);
      else if (route === "/api/retrieve") {
        const cue = parseCue(query);
        if (!cue) value = { packet: "" };
        else {
          const result = memory.retrieve(cue, { track: false });
          value = { packet: result.packet, items: result.items };
        }
      } else {
        send(response, 404, Buffer.from("not found"), "text/plain");
        return;
      }
      send(response, 200, Buffer.from(pyJsonDumps(outputJson(value)), "utf8"), "application/json; charset=utf-8");
    } catch (error) {
      send(response, 500, Buffer.from(String((error as Error).message), "utf8"), "text/plain");
    } finally {
      memory.close();
    }
  };
  const server = createServer({ requireHostHeader: false, maxHeaderSize: 65536 }, handle);
  // Suppress node:http's automatic interim/error responses until P21 has run.
  server.on("checkContinue", handle);
  server.on("checkExpectation", handle);
  server.on("connection", (socket) => {
    socket.prependListener("data", (chunk: Buffer) => {
      const previous = wire.get(socket) ?? Buffer.alloc(0);
      if (headerEnd(previous) || previous.length > 65536) return;
      const joined = Buffer.concat([previous, chunk]);
      const end = headerEnd(joined);
      wire.set(socket, joined.subarray(0, end ? end.index + end.length : 65537));
    });
  });
  // CONNECT is emitted separately by node:http, but it has the same P21/G16 boundary.
  server.on("connect", (request, socket) => {
    const response = new ServerResponse(request);
    response.assignSocket(socket);
    response.shouldKeepAlive = false;
    response.once("finish", () => socket.end());
    handle(request, response);
  });
  const refusedSockets = new WeakSet<object>();
  server.on("clientError", (error, socket) => {
    if (!socket.writable) return;
    if (answered.has(socket)) return;
    if (refusedSockets.has(socket)) return;
    refusedSockets.add(socket);
    const request = new IncomingMessage(socket);
    const response = new ServerResponse(request);
    response.assignSocket(socket);
    response.shouldKeepAlive = false;
    response.once("finish", () => socket.end());
    const failure = error as Error & { code?: string; rawPacket?: Buffer };
    const received = wire.get(socket) ?? failure.rawPacket;
    const pythonLineEndings = received && /(?:^|[^\r])\n/u.test(received.toString("latin1"));
    if (!received || (failure.code !== "HPE_INVALID_METHOD" && !pythonLineEndings)) {
      send(response, 400, Buffer.from("Bad Request"), "text/plain");
      return;
    }
    // llhttp has a finite method vocabulary and requires CRLF. Python also accepts
    // LF and guards arbitrary valid method tokens (for example BREW). Keep that boundary,
    // including when the request's headers arrive in a later network chunk.
    let pending = received;
    const parse = (chunk?: Buffer) => {
      if (chunk) pending = Buffer.concat([pending, chunk]);
      const end = headerEnd(pending);
      if (!end && pending.length <= 65536) return;
      socket.off("data", parse);
      const lines = pending
        .subarray(0, end?.index ?? 0)
        .toString("latin1")
        .split(/\r?\n/u);
      const first = /^([!#$%&'*+.^_`|~0-9A-Za-z-]+) (\S+) HTTP\/1\.[01]$/u.exec(lines.shift() ?? "");
      if (!end || !first || lines.some((line) => !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+:/u.test(line))) {
        send(response, 400, Buffer.from("Bad Request"), "text/plain");
        return;
      }
      request.method = first[1];
      request.url = first[2];
      request.rawHeaders = lines.flatMap((line) => {
        const colon = line.indexOf(":");
        return [line.slice(0, colon), line.slice(colon + 1).replace(/^[ \t]+/u, "")];
      });
      handle(request, response);
    };
    socket.on("data", parse);
    parse();
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen({ host: host === "localhost" ? "127.0.0.1" : host, port }, () => {
      server.off("error", reject);
      boundPort = (server.address() as { port: number }).port;
      resolve();
    });
  });
  return {
    server,
    port: boundPort!,
    url: `http://${host === "::1" ? "[::1]" : host}:${boundPort!}/`,
    close: () => new Promise<void>((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

export function openBrowser(url: string): void {
  const [command, args] =
    process.platform === "darwin"
      ? ["open", [url]]
      : process.platform === "win32"
        ? ["cmd", ["/c", "start", "", url]]
        : ["xdg-open", [url]];
  try {
    const child = spawn(command, args, { stdio: "ignore" });
    child.on("error", () => {});
    child.unref();
  } catch {
    /* Browser availability is not a condition for serving. */
  }
}

export async function serve(
  memory: IdentityMemory,
  options: { host?: string; port?: number; openBrowser?: boolean; stdout?: (value: string) => void } = {},
): Promise<void> {
  const running = await startView(memory, options);
  let interrupt: () => void;
  const stopped = new Promise<void>((resolve) => {
    interrupt = resolve;
  });
  process.once("SIGINT", interrupt!);
  try {
    (options.stdout ?? ((value) => process.stdout.write(value)))(
      `Identity memory view for ${memory.profile.agent}: ${running.url}  (Ctrl+C to stop)\n`,
    );
    if (options.openBrowser !== false) openBrowser(running.url);
    await stopped;
  } finally {
    process.off("SIGINT", interrupt!);
    await running.close();
  }
}
