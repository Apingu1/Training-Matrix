import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const assetsDirectory = path.join(webRoot, "dist", "assets");

const assetNames = await readdir(assetsDirectory);
const workerAsset = assetNames.find(
  (name) => name.startsWith("pdf.worker.min-") && name.endsWith(".mjs"),
);

if (!workerAsset) {
  throw new Error("The production build did not emit the PDF.js worker module.");
}

const workerStats = await stat(path.join(assetsDirectory, workerAsset));
if (!workerStats.isFile() || workerStats.size === 0) {
  throw new Error(`The emitted PDF.js worker is invalid: ${workerAsset}`);
}

const nginxConfigs = [
  path.join(webRoot, "nginx.conf"),
  path.resolve(webRoot, "..", "infra", "nginx", "default.conf"),
];

for (const configPath of nginxConfigs) {
  const config = await readFile(configPath, "utf8");
  const mjsLocation = config.match(
    /location\s+[^\{]*\\\.mjs\$\s*\{([\s\S]*?)\}/,
  );

  if (
    !mjsLocation ||
    !/default_type\s+application\/javascript\s*;/.test(mjsLocation[1])
  ) {
    throw new Error(
      `${path.relative(webRoot, configPath)} does not serve .mjs files as application/javascript.`,
    );
  }
}

console.log(`Verified PDF.js worker delivery contract: assets/${workerAsset}`);
