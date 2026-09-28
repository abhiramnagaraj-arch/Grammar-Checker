import fs from "node:fs";
import path from "node:path";
import {
  CUSTOM_ROOT,
  collectWeirStatistics,
  readJson,
  readWeirFilesFromRulesDir,
  validateCatalog,
  validateLexicon,
  validateManifest,
} from "./shared.mjs";

function fail(message) {
  throw new Error(message);
}

function validateRuleFile(filePath, content) {
  if (!/^\s*expr\s+main\b/mu.test(content)) {
    fail(`Missing expr main in ${filePath}`);
  }

  for (const required of ["let message", "let description", "let kind", "let becomes"]) {
    if (!content.includes(required)) {
      fail(`Missing ${required} in ${filePath}`);
    }
  }

  if (/^\s*let\s+status\s+"disabled"\s*$/m.test(content)) {
    return;
  }

  const { testCount, allowsCount } = collectWeirStatistics(content);
  if (testCount < 5) {
    fail(`Rule has fewer than 5 positive tests: ${filePath}`);
  }

  if (allowsCount < 10) {
    fail(`Rule has fewer than 10 allows tests: ${filePath}`);
  }
}

function main() {
  const manifest = readJson(path.join(CUSTOM_ROOT, "manifest.json"));
  validateManifest(manifest);

  const catalog = readJson(path.join(CUSTOM_ROOT, "RULE_CATALOG.json"));
  validateCatalog(catalog);

  for (const lexiconPath of [
    path.join(CUSTOM_ROOT, "lexicons", "irregular_verbs.json"),
    path.join(CUSTOM_ROOT, "lexicons", "uncountable_nouns.json"),
    path.join(CUSTOM_ROOT, "lexicons", "comparison_forms.json"),
    path.join(CUSTOM_ROOT, "lexicons", "preposition_patterns.json"),
    path.join(CUSTOM_ROOT, "lexicons", "article_exceptions.json"),
  ]) {
    const value = readJson(lexiconPath);
    validateLexicon(value, path.basename(lexiconPath));
  }

  const rules = readWeirFilesFromRulesDir(path.join(CUSTOM_ROOT, "rules"));
  if (rules.length === 0) {
    fail("No Weir rules were found under custom-grammar/rules.");
  }

  for (const rule of rules) {
    validateRuleFile(rule.filePath, rule.content);
  }

  console.log(`Validated ${rules.length} custom Weir rule files.`);
}

main();
