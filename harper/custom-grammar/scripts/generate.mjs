import fs from "node:fs";
import path from "node:path";
import {
  CUSTOM_ROOT,
  flattenRuleFilename,
  listFilesRecursive,
  isDisabledWeirRule,
  readJson,
  readText,
  sortObject,
  writeJson,
  writeText,
} from "./shared.mjs";

function main() {
  const generatedDir = path.join(CUSTOM_ROOT, "generated");
  fs.mkdirSync(generatedDir, { recursive: true });

  const rulesDir = path.join(CUSTOM_ROOT, "rules");
  const outputRulesDir = path.join(generatedDir, "rules");
  fs.rmSync(outputRulesDir, { recursive: true, force: true });
  fs.mkdirSync(outputRulesDir, { recursive: true });

  const sourceFiles = listFilesRecursive(rulesDir, (filePath) => filePath.endsWith(".weir"));
  const mapping = [];
  const excluded = [];

  for (const sourcePath of sourceFiles) {
    const relativePath = path.relative(rulesDir, sourcePath);
    const content = readText(sourcePath);
    if (isDisabledWeirRule(content)) {
      excluded.push(relativePath);
      continue;
    }

    const flattenedName = flattenRuleFilename(relativePath);
    const targetPath = path.join(outputRulesDir, flattenedName);
    writeText(targetPath, content);
    mapping.push({
      source: relativePath,
      packaged: `rules/${flattenedName}`,
    });
  }

  writeJson(path.join(generatedDir, "build-report.json"), sortObject({
    rule_count: mapping.length,
    excluded_rule_count: excluded.length,
    excluded_sources: excluded,
    source_to_packaged: mapping,
  }));

  const manifest = readJson(path.join(CUSTOM_ROOT, "manifest.json"));
  writeJson(path.join(generatedDir, "manifest.json"), manifest);

  console.log(`Generated ${mapping.length} flattened Weir source files.`);
}

main();
