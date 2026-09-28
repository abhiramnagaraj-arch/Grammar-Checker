import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const SCRIPTS_DIR = path.dirname(fileURLToPath(import.meta.url));
export const CUSTOM_ROOT = path.resolve(SCRIPTS_DIR, "..");
export const REPO_ROOT = path.resolve(CUSTOM_ROOT, "..");

export function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

export function writeText(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content, "utf8");
}

export function readJson(filePath) {
  return JSON.parse(readText(filePath));
}

export function writeJson(filePath, value) {
  writeText(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

export function sortObject(value) {
  if (Array.isArray(value)) {
    return value.map(sortObject);
  }

  if (!value || typeof value !== "object" || value instanceof Date) {
    return value;
  }

  return Object.fromEntries(
    Object.keys(value)
      .sort((left, right) => left.localeCompare(right))
      .map((key) => [key, sortObject(value[key])]),
  );
}

export function listFilesRecursive(dirPath, predicate = () => true) {
  const output = [];
  const entries = fs.existsSync(dirPath) ? fs.readdirSync(dirPath, { withFileTypes: true }) : [];

  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      output.push(...listFilesRecursive(fullPath, predicate));
      continue;
    }

    if (predicate(fullPath)) {
      output.push(fullPath);
    }
  }

  return output.sort((left, right) => left.localeCompare(right));
}

export function flattenRuleFilename(relativePath) {
  const withoutExt = relativePath.replace(/\.weir$/u, "");
  return withoutExt.split(path.sep).join("__") + ".weir";
}

export function parseSimpleListValue(text) {
  const trimmed = text.trim();
  if (!trimmed) {
    return [];
  }

  try {
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return trimmed
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .filter(Boolean);
  }
}

export function collectWeirStatistics(source) {
  const lines = source.split(/\r?\n/u);
  let testCount = 0;
  let allowsCount = 0;

  for (const line of lines) {
    const normalized = line.trimStart();
    if (normalized.startsWith("test ")) {
      testCount += 1;
    } else if (normalized.startsWith("allows ")) {
      allowsCount += 1;
    }
  }

  return { testCount, allowsCount };
}

export function isDisabledWeirRule(source) {
  return /^\s*let\s+status\s+"disabled"\s*$/m.test(source);
}

export function validateManifest(manifest) {
  const required = ["author", "version", "description", "license"];
  const missing = required.filter((key) => !(key in manifest));
  if (missing.length > 0) {
    throw new Error(`manifest.json is missing required fields: ${missing.join(", ")}`);
  }
}

export function validateCatalog(catalog) {
  if (!Array.isArray(catalog) || catalog.length === 0) {
    throw new Error("RULE_CATALOG.json must be a non-empty array.");
  }

  const seen = new Set();

  for (const entry of catalog) {
    for (const key of [
      "rule_id",
      "title",
      "grammar_category",
      "implementation",
      "status",
      "confidence",
      "auto_apply",
      "false_positive_risk",
      "source_basis",
      "description",
      "lexicons",
      "positive_test_count",
      "negative_test_count",
      "benchmark_categories",
      "known_limitations",
    ]) {
      if (!(key in entry)) {
        throw new Error(`Catalog entry is missing ${key}: ${JSON.stringify(entry)}`);
      }
    }

    if (seen.has(entry.rule_id)) {
      throw new Error(`Duplicate rule_id in catalog: ${entry.rule_id}`);
    }

    seen.add(entry.rule_id);
  }
}

export function validateLexicon(value, kind) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${kind} lexicon must be an object.`);
  }

  const keys = Object.keys(value);
  const sorted = [...keys].sort((left, right) => left.localeCompare(right));
  if (keys.join("\u0000") !== sorted.join("\u0000")) {
    throw new Error(`${kind} lexicon entries must be sorted alphabetically.`);
  }

  const seen = new Set();
  for (const key of keys) {
    const normalized = key.toLowerCase();
    if (seen.has(normalized)) {
      throw new Error(`${kind} lexicon contains duplicate entries: ${key}`);
    }
    seen.add(normalized);
  }
}

export function readWeirFilesFromRulesDir(rulesDir) {
  const sourceFiles = listFilesRecursive(rulesDir, (filePath) => filePath.endsWith(".weir"));
  return sourceFiles.map((filePath) => ({
    filePath,
    relativePath: path.relative(rulesDir, filePath),
    content: readText(filePath),
  }));
}
