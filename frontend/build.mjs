// Bundles the PWA into dist/ (served by the backend). `node build.mjs [--watch]`
import { cpSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
let esbuild;
try { esbuild = await import("esbuild"); } catch { esbuild = require(process.env.ESBUILD_PATH || "esbuild"); }

const watch = process.argv.includes("--watch");
const version = Date.now().toString(36);
rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });
cpSync("public", "dist", { recursive: true });
// stamp the service-worker cache version so iPhones pick up new builds
writeFileSync("dist/sw.js", readFileSync("public/sw.js", "utf8").replace("__VERSION__", version));
writeFileSync("dist/index.html", readFileSync("public/index.html", "utf8").replaceAll("__VERSION__", version));

const opts = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  outdir: "dist",
  entryNames: "app",
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  target: ["safari15", "chrome100", "firefox100"],
  jsx: "automatic",
  loader: { ".svg": "text" },
  external: ["/fonts/*"],
  define: { "process.env.NODE_ENV": watch ? '"development"' : '"production"' },
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(":") : [],
  logLevel: "info",
};
if (watch) {
  const ctx = await esbuild.context(opts);
  await ctx.watch();
} else {
  await esbuild.build(opts);
}
