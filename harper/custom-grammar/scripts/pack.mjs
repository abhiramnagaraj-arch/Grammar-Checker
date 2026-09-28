import fs from "node:fs";
import path from "node:path";
import { packWeirpackFiles } from "harper.js";
import {
  CUSTOM_ROOT,
  listFilesRecursive,
  isDisabledWeirRule,
  readText,
  writeText,
  flattenRuleFilename,
} from "./shared.mjs";

function main() {
  const generatedDir = path.join(CUSTOM_ROOT, "generated");
  const rulesDir = path.join(generatedDir, "rules");
  const files = new Map();

  const manifestPath = path.join(generatedDir, "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error("Missing generated manifest. Run grammar:generate first.");
  }

  files.set("manifest.json", readText(manifestPath));

  for (const filePath of listFilesRecursive(rulesDir, (candidate) => candidate.endsWith(".weir"))) {
    const relative = path.relative(rulesDir, filePath);
    const content = readText(filePath);
    if (isDisabledWeirRule(content)) {
      continue;
    }
    files.set(`rules/${flattenRuleFilename(relative)}`, content);
  }

  const bytes = packWeirpackFiles(files);
  const outputPath = path.join(generatedDir, "custom-grammar.weirpack");
  fs.writeFileSync(outputPath, bytes);
  console.log(`Packed ${files.size - 1} rule files into ${outputPath}`);
}

main();
