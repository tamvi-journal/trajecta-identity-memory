import assert from "node:assert/strict";
import { rmSync } from "node:fs";
import test from "node:test";
import { IdentityMemory } from "../src/identity.ts";
import { InjectedClock } from "../src/clock.ts";
import { startView, parseCue } from "../src/view.ts";
import { PROFILE, temporary, request, inventory, HEADERS } from "./view-support.ts";
import { resolve } from "node:path";

for (const [fields, folds, evilHost, expected] of [
  [99, 0, false, 200],
  [100, 0, false, 431],
  [101, 0, false, 431],
  [98, 1, false, 200],
  [99, 1, false, 431],
  [100, 0, true, 431],
] as const) {
  for (const fragmentSize of [0, 3]) {
    test(`Python header-line budget: ${fields} fields, ${folds} folds, evil Host=${evilHost}, chunks=${fragmentSize || "whole"}`, async () => {
      const root = temporary(),
        memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"), { clock: new InjectedClock() });
      memory.bootstrap();
      memory.close();
      const before = inventory(root),
        server = await startView(memory, { port: 0 });
      try {
        // Host is included in fields; no Connection or other implicit header is sent.
        const headers: [string, string][] = [["Host", evilHost ? "evil.example" : "127.0.0.1:{port}"]];
        for (let i = 1; i < fields; i++) headers.push([`X-${i}`, "value"]);
        if (folds) headers[headers.length - 1][1] += "\r\n continuation";
        const response = await request(server, { headers, connectionClose: false, fragmentSize });
        // G17 retains llhttp's stricter obs-fold refusal; no framing acceptance changes.
        if (folds) assert(response.status >= 400);
        else assert.equal(response.status, expected);
        for (const key of HEADERS) assert.equal(typeof response.headers[key], "string");
        assert.equal(response.headers["Cache-Control"], "no-store");
        assert.equal(response.headers["X-Content-Type-Options"], "nosniff");
        assert.equal(response.headers["X-Frame-Options"], "DENY");
        assert.equal(response.headers["Referrer-Policy"], "no-referrer");
        assert.equal(response.headers["Content-Length"], String(response.body.length));
        if (!folds && expected === 431) {
          assert.deepEqual(response.body, Buffer.from("Too many headers"));
          assert.equal(response.headers["Content-Type"], "text/plain");
        }
        assert.deepEqual(inventory(root), before);
      } finally {
        await server.close();
        memory.close();
        rmSync(root, { recursive: true, force: true });
      }
    });
  }
}

for (const method of ["POST", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD", "CONNECT", "BREW"]) {
  test(`P21 every method guards before routing and stays pure: ${method}`, async () => {
    const root = temporary();
    const memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"), { clock: new InjectedClock() });
    memory.bootstrap();
    memory.close();
    const before = inventory(root),
      server = await startView(memory, { port: 0 });
    try {
      for (const headers of [[["Host", "evil.example"]], [["Host", "127.0.0.1:{port}"]]]) {
        const response = await request(server, { method, path: "/api/snapshot", headers });
        assert(headers[0][1] === "evil.example" ? response.status === 403 : response.status >= 400);
        assert.equal(response.headers["X-Frame-Options"], "DENY");
        assert.equal(response.headers["Referrer-Policy"], "no-referrer");
        assert.equal(response.headers["Cache-Control"], "no-store");
        assert.equal(response.headers["X-Content-Type-Options"], "nosniff");
        for (const key of HEADERS) assert.equal(typeof response.headers[key], "string");
        if (method === "HEAD") assert.equal(response.body.length, 0);
        assert.deepEqual(inventory(root), before);
      }
    } finally {
      await server.close();
      memory.close();
      rmSync(root, { recursive: true, force: true });
    }
  });
}

test("P21 IPv6 loopback uses brackets and the actually bound port", async (t) => {
  const root = temporary(),
    memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
  let server;
  try {
    try {
      server = await startView(memory, { host: "::1", port: 0 });
    } catch (error) {
      if (["EADDRNOTAVAIL", "EAFNOSUPPORT", "EPROTONOSUPPORT"].includes((error as NodeJS.ErrnoException).code ?? "")) {
        t.skip(`IPv6 loopback unavailable: ${(error as Error).message}`);
        return;
      }
      throw error;
    }
    assert.equal(server.url, `http://[::1]:${server.port}/`);
    const response = await request(server, { headers: [["Host", "[::1]:{port}"]] }, "::1");
    assert.equal(response.status, 200);
    for (const key of HEADERS) assert.equal(typeof response.headers[key], "string");
    assert.deepEqual(inventory(root), []);
  } finally {
    if (server) await server.close();
    memory.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("bind refusal occurs before creating a store", async () => {
  const root = temporary(),
    memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
  try {
    await assert.rejects(startView(memory, { host: "0.0.0.0", port: 0 }), {
      name: "ValueError",
      message: "the memory view only binds to localhost",
    });
    assert.deepEqual(inventory(root), []);
  } finally {
    memory.close();
    rmSync(root, { recursive: true, force: true });
  }
});

for (const [query, expected] of [
  ["cue=&cue=b", "b"],
  ["cue&cue=b", "b"],
  ["cue=%20&cue=b", ""],
  ["c%75e=first+light", "first light"],
  ["cue=%EF%BB%BF", "\ufeff"],
  ["cue=%E2%82", "\ufffd"],
  ["cue=%FF", "\ufffd"],
  ["cue=%C0%AF", "\ufffd\ufffd"],
  ["cue=%ED%A0%80", "\ufffd\ufffd\ufffd"],
  ["cue=%G1", "%G1"],
  ["cue=%", "%"],
])
  test(`parse_qs boundary ${query}`, () => assert.equal(parseCue(query), expected));

for (const [name, headers] of [
  ["host trailing space", [["Host", "127.0.0.1:{port} "]]],
  ["host trailing tab", [["Host", "127.0.0.1:{port}\t"]]],
  [
    "origin trailing space",
    [
      ["Host", "127.0.0.1:{port}"],
      ["Origin", "http://127.0.0.1:{port} "],
    ],
  ],
] as const)
  test(`P21 exact parsed header value: ${name}`, async () => {
    const root = temporary(),
      memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
    const server = await startView(memory, { port: 0 });
    try {
      const response = await request(server, { headers });
      assert.equal(response.status, 403);
      assert.deepEqual(inventory(root), []);
    } finally {
      await server.close();
      memory.close();
      rmSync(root, { recursive: true, force: true });
    }
  });

import { connect } from "node:net";
import { serve } from "../src/view.ts";

test("arbitrary method guard survives fragmented method and headers", async () => {
  const root = temporary(),
    memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
  const server = await startView(memory, { port: 0 });
  try {
    const response = await new Promise<Buffer>((resolve, reject) => {
      const socket = connect(server.port, "127.0.0.1"),
        chunks: Buffer[] = [];
      socket.once("error", reject);
      socket.setTimeout(5000, () => socket.destroy(new Error("fragmented method timed out")));
      socket.on("data", (bytes) => chunks.push(bytes));
      socket.once("end", () => resolve(Buffer.concat(chunks)));
      socket.once("connect", () => {
        socket.write("BR");
        setTimeout(() => {
          socket.write("EW /api/snapshot HTTP/1.1\r\nHost:");
          setTimeout(() => socket.write(" evil.example\r\n\r\n"), 10);
        }, 10);
      });
    });
    assert.match(response.toString(), /^HTTP\/1\.1 403/u);
    assert(response.toString().endsWith("forbidden host"));
    assert.deepEqual(inventory(root), []);
  } finally {
    await server.close();
    memory.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("IPv6 serve prints and serves the bracketed bound URL", async (t) => {
  const root = temporary(),
    memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
  let printed = "",
    response;
  const completed = [] as Promise<void>[];
  try {
    try {
      await serve(memory, {
        host: "::1",
        port: 0,
        openBrowser: false,
        stdout(line) {
          printed = line;
          const port = Number(/\[::1\]:(\d+)/u.exec(line)![1]);
          completed.push(
            request({ port }, { headers: [["Host", "[::1]:{port}"]] }, "::1")
              .then((value) => {
                response = value;
              })
              .finally(() => {
                process.emit("SIGINT");
              }),
          );
        },
      });
    } catch (error) {
      if (["EADDRNOTAVAIL", "EAFNOSUPPORT", "EPROTONOSUPPORT"].includes((error as NodeJS.ErrnoException).code ?? "")) {
        t.skip(`IPv6 loopback unavailable: ${(error as Error).message}`);
        return;
      }
      throw error;
    }
    await Promise.all(completed);
    assert.match(
      printed,
      /^Identity memory view for example-agent: http:\/\/\[::1\]:[1-9][0-9]*\/  \(Ctrl\+C to stop\)\n$/u,
    );
    assert.equal(response!.status, 200);
    assert.deepEqual(inventory(root), []);
  } finally {
    memory.close();
    rmSync(root, { recursive: true, force: true });
  }
});

for (const [path, expected] of [
  ["http://example.invalid/index.html", 200],
  ["//example.invalid/index.html", 404],
  ["/index.html;p#fragment", 200],
  ["///index.html", 200],
] as const) {
  test(`urlparse path boundary ${path}`, async () => {
    const root = temporary(),
      memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
    const server = await startView(memory, { port: 0 });
    try {
      assert.equal((await request(server, { path })).status, expected);
      assert.deepEqual(inventory(root), []);
    } finally {
      await server.close();
      memory.close();
      rmSync(root, { recursive: true, force: true });
    }
  });
}

for (const expectation of ["100-continue", "unexpected"]) {
  test(`P21 guard and common policy precede Expect: ${expectation}`, async () => {
    const root = temporary(),
      memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
    const server = await startView(memory, { port: 0 });
    try {
      const response = await request(server, {
        method: "POST",
        path: "/api/snapshot",
        headers: [
          ["Host", "evil.example"],
          ["Expect", expectation],
        ],
      });
      assert.equal(response.status, 403);
      assert.equal(response.headers["X-Frame-Options"], "DENY");
      assert.equal(response.headers["Referrer-Policy"], "no-referrer");
      assert.deepEqual(response.body, Buffer.from("forbidden host"));
      assert.deepEqual(inventory(root), []);
    } finally {
      await server.close();
      memory.close();
      rmSync(root, { recursive: true, force: true });
    }
  });
}

test("stored domain names cannot change integer counter JSON types or key order", async () => {
  const root = temporary(),
    memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"), { clock: new InjectedClock() });
  memory.bootstrap();
  memory.store.createCurrent({
    recordId: "counter",
    recordClass: "event",
    domain: "confidence",
    title: "Counter",
    actor: "test",
    reason: "synthetic",
    evidence: { evidence_type: "outside", source_ref: "test", content_summary: "test" },
    idempotencyKey: "counter",
  });
  for (const domain of ["2", "10", "1", "__proto__", "constructor", "toString"])
    memory.store.createCurrent({
      recordId: "counter:" + domain,
      recordClass: "event",
      domain,
      title: "Counter",
      actor: "test",
      reason: "synthetic",
      evidence: { evidence_type: "outside", source_ref: "test", content_summary: "test" },
      idempotencyKey: "counter:" + domain,
    });
  const server = await startView(memory, { port: 0 }),
    before = inventory(root);
  try {
    const response = await request(server, { path: "/api/snapshot" });
    assert.equal(response.status, 200);
    assert.match(
      response.body.toString(),
      /"records": \{"1": 1, "10": 1, "2": 1, "__proto__": 1, "confidence": 1, "constructor": 1, /u,
    );
    assert.match(response.body.toString(), /"toString": 1/u);
    assert.deepEqual(inventory(root), before);
  } finally {
    await server.close();
    memory.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("HTTP/1.0 close semantics never dispatch a pipelined second request", async () => {
  const root = temporary(),
    memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
  const server = await startView(memory, { port: 0 });
  try {
    await new Promise<void>((resolve, reject) => {
      const socket = connect(server.port, "127.0.0.1");
      socket.once("error", reject);
      socket.setTimeout(5000, () => socket.destroy(new Error("pipeline response timed out")));
      socket.resume();
      socket.once("close", resolve);
      socket.once("connect", () =>
        socket.write(
          `GET / HTTP/1.1\r\nHost: 127.0.0.1:${server.port}\r\n\r\n` +
            "GET /api/snapshot HTTP/1.1\r\nHost: evil.example\r\n\r\n",
        ),
      );
    });
    assert.deepEqual(inventory(root), []);
  } finally {
    await server.close();
    memory.close();
    rmSync(root, { recursive: true, force: true });
  }
});

for (const [method, value, expected] of [
  ["GET", "127.0.0.1:{port}", 200],
  ["GET", "127.0.0.1:{port} ", 403],
  ["BREW", "evil.example", 403],
] as const) {
  test(`P21 Python-accepted LF-only framing: ${method} ${value}`, async () => {
    const root = temporary(),
      memory = new IdentityMemory(PROFILE, resolve(root, "store.sqlite3"));
    const server = await startView(memory, { port: 0 });
    try {
      const response = await request(server, { method, headers: [["Host", value]], lineSeparator: "\n" });
      assert.equal(response.status, expected);
      assert.deepEqual(inventory(root), []);
    } finally {
      await server.close();
      memory.close();
      rmSync(root, { recursive: true, force: true });
    }
  });
}
