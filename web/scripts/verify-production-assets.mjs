import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const assetsDirectory = path.join(webRoot, "dist", "assets");

const assetNames = await readdir(assetsDirectory);
const workerAsset = assetNames.find(
  (name) => name.startsWith("pdf.worker.min-") && name.endsWith(".js"),
);

if (!workerAsset) {
  throw new Error("The production build did not emit the bundled PDF.js worker.");
}

const externalWorkerModule = assetNames.find(
  (name) => name.startsWith("pdf.worker.min-") && name.endsWith(".mjs"),
);
if (externalWorkerModule) {
  throw new Error(
    `The production build still depends on an external PDF worker module: ${externalWorkerModule}`,
  );
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

console.log(`Verified bundled PDF.js worker delivery: assets/${workerAsset}`);
