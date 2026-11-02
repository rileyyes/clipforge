// Frontend build with esbuild (Vite's underlying bundler). Usage:
//   node build.mjs          production build into dist/
//   node build.mjs --watch  rebuild on change (backend serves dist/)
import * as esbuild from "esbuild";
import { copyFileSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");
rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/assets", { recursive: true });
copyFileSync("index.html", "dist/index.html");

const options = {
  entryPoints: { main: "src/main.tsx" },
  bundle: true,
  format: "esm",
  outdir: "dist/assets",
  sourcemap: true,
  minify: !watch,
  target: ["chrome110", "firefox115", "safari16"],
  jsx: "automatic",
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("watching for changes…");
} else {
  await esbuild.build(options);
}
