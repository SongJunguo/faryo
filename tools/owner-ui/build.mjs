import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { gzipSync } from "node:zlib";

import preact from "@preact/preset-vite";
import { build } from "vite";

const root = path.resolve(import.meta.dirname, "../..");
const entry = path.join(root, "apps/owner/ui/main.tsx");
const output = path.join(
  root,
  "apps/owner/local-tmux-owner/static/owner-ui.js",
);
const noticeOutput = path.join(
  root,
  "apps/owner/local-tmux-owner/static/owner-ui.LICENSE.txt",
);
const preactRoot = path.join(root, "node_modules/preact");
const preactPackage = JSON.parse(
  await readFile(path.join(preactRoot, "package.json"), "utf8"),
);
if (preactPackage.version !== "10.29.8" || preactPackage.license !== "MIT") {
  throw new Error(
    `Unexpected Preact dependency: ${preactPackage.version} ${preactPackage.license}`,
  );
}

const result = await build({
  configFile: false,
  logLevel: "silent",
  plugins: [preact()],
  build: {
    target: "es2022",
    minify: "esbuild",
    sourcemap: false,
    write: false,
    lib: {
      entry,
      name: "FaryoOwnerUIBundle",
      formats: ["iife"],
      fileName: () => "owner-ui.js",
    },
  },
});
const outputs = Array.isArray(result)
  ? result.flatMap((item) => item.output)
  : result.output;
const chunk = outputs.find((item) => item.type === "chunk" && item.isEntry);
if (!chunk || typeof chunk.code !== "string")
  throw new Error("Owner UI entry bundle was not generated");
const bytes = Buffer.from(chunk.code);
const sha256 = createHash("sha256").update(bytes).digest("hex");
const gzipBytes = gzipSync(bytes, { level: 9 }).length;
if (gzipBytes > 24 * 1024)
  throw new Error(`Owner UI bundle exceeds 24 KiB gzip: ${gzipBytes} bytes`);
const license = (
  await readFile(path.join(preactRoot, "LICENSE"), "utf8")
).trim();
const notice = Buffer.from(
  [
    `Preact ${preactPackage.version}`,
    "https://preactjs.com/",
    `Bundle SHA-256: ${sha256}`,
    `Bundle size: ${bytes.length} bytes raw; ${gzipBytes} bytes gzip -9`,
    "Transitive production dependencies: none",
    "",
    license,
    "",
  ].join("\n"),
);
const check = process.argv.includes("--check");
if (check) {
  const [current, currentNotice] = await Promise.all([
    readFile(output),
    readFile(noticeOutput),
  ]);
  if (!current.equals(bytes) || !currentNotice.equals(notice))
    throw new Error(
      "Owner UI bundle or notice is stale; run npm run build:owner-ui",
    );
} else {
  await Promise.all([
    writeFile(output, bytes),
    writeFile(noticeOutput, notice),
  ]);
}
console.log(
  `owner-ui-bundle=${bytes.length} gzip=${gzipBytes} sha256=${sha256}${check ? " check=PASS" : ""}`,
);
