// Eleventy 3 config for the showcase page. Browser files are copied from the locked node_modules;
// the page never loads anything from a CDN.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { RenderPlugin } from "@11ty/eleventy";
import { EVIDENCE, figure, monthLabel, usd } from "./figures.mjs";

// The story files and contracts are read from the repository, never from the build's input folder,
// so a test that builds a copy of `site/` still renders the committed passages.
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const STORY = join(ROOT, "docs/showcase/story");
const MARKER = /<!-- passage: ([a-z0-9-]+) -->/g;

// A passage runs from its marker to the next marker or the end of the file.
function passageText(file, id) {
  const text = readFileSync(join(STORY, file), "utf8");
  const marks = [...text.matchAll(MARKER)];
  const index = marks.findIndex((mark) => mark[1] === id);
  if (index === -1) throw new Error(`story passage ${id} is not in ${file}`);
  const end = index + 1 < marks.length ? marks[index + 1].index : text.length;
  return text.slice(marks[index].index + marks[index][0].length, end).trim();
}

const escapeHtml = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// D7: the contract count and shared version, read at build time so the copy never goes stale.
function contracts() {
  const folder = join(ROOT, "contracts");
  const files = readdirSync(folder).filter((name) => name.endsWith(".odcs.yaml"));
  const versions = new Set(
    files.map((name) => readFileSync(join(folder, name), "utf8").match(/^version: (.+)$/m)[1]),
  );
  if (versions.size !== 1) throw new Error(`contracts do not share one version: ${[...versions]}`);
  return { count: files.length, version: [...versions][0] };
}

export default function (eleventyConfig) {
  // The company builds stage their input under the git-ignored local/ (ADR 0044), so the build
  // must not skip git-ignored paths; site/_site is the one ignored path a build must still skip.
  eleventyConfig.setUseGitIgnore(false);
  eleventyConfig.ignores.add("site/_site/**");
  eleventyConfig.addPlugin(RenderPlugin);
  eleventyConfig.addGlobalData("contracts", contracts);
  eleventyConfig.addGlobalData("evidence", EVIDENCE);
  eleventyConfig.addFilter("monthLabel", monthLabel);
  eleventyConfig.addFilter("usd", usd);
  eleventyConfig.addFilter("figure", figure);
  // One shortcode renders a story passage: "block" as Markdown, "inline" as the inside of its one
  // paragraph, "text" as escaped plain text for attributes and titles.
  eleventyConfig.addAsyncShortcode("passage", async function (file, id, mode = "block") {
    const text = passageText(file, id);
    if (mode === "text") return escapeHtml(text);
    const render = await RenderPlugin.String.call(this, text, "md");
    const html = (await render({})).trim();
    if (mode === "block") return html;
    const inner = html.match(/^<p>([\s\S]*)<\/p>$/);
    if (mode !== "inline" || inner === null || inner[1].includes("<p>")) {
      throw new Error(`story passage ${id} in ${file} cannot render as ${mode}`);
    }
    return inner[1];
  });
  eleventyConfig.addPassthroughCopy({
    "node_modules/d3/dist/d3.min.js": "assets/vendor/d3.min.js",
    "node_modules/@observablehq/plot/dist/plot.umd.min.js": "assets/vendor/plot.umd.min.js",
    "site/assets/park-month-chart.mjs": "assets/park-month-chart.mjs",
    "site/assets/favicon.svg": "assets/favicon.svg",
    "site/assets/img": "assets/img",
    "site/assets/css": "assets/css",
    "site/assets/js": "assets/js",
  });
  return {
    dir: { input: "site", output: "site/_site", data: "_data" },
  };
}
