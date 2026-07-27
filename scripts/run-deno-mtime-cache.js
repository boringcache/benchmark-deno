#!/usr/bin/env node

const path = require("path");

const sourcePath = process.argv[2];
if (!sourcePath) {
  console.error("Usage: run-deno-mtime-cache.js SOURCE_PATH");
  process.exit(1);
}

const sourceRoot = path.resolve(sourcePath);
process.chdir(sourceRoot);
process.env["INPUT_CACHE-PATH"] = "./target";

// Execute Deno's pinned action implementation from the Deno checkout. The
// wrapper only supplies the working directory that a nested checkout needs.
require(path.join(sourceRoot, ".github/mtime_cache/action.js"));

