import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "csv-parse/sync";
import { stringify } from "csv-stringify/sync";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = SCRIPT_DIR;
const DEFAULT_INPUT_CSV = path.resolve(REPO_ROOT, "..", "extracted_grammar_test_cases.csv");
const DEFAULT_OUTPUT_CSV = path.resolve(REPO_ROOT, "..", "results", "harper_results.csv");
const CUSTOM_ROOT = path.join(REPO_ROOT, "custom-grammar");

function getArgument(name, defaultValue = null) {
  const index = process.argv.indexOf(name);

  if (index === -1) {
    return defaultValue;
  }

  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) {
    throw new Error(`Missing value for ${name}`);
  }

  return value;
}

function normalizeText(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value).trim();
}

function readJsonIfExists(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }

  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readTextIfExists(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return null;
  }

  return fs.readFileSync(filePath, "utf8");
}

function parseDictionaryWords(content) {
  const text = normalizeText(content);
  if (!text) {
    return [];
  }

  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed.map((value) => String(value));
    }
  } catch {
    // Fall through to line-based parsing.
  }

  return text
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .filter(Boolean);
}

function collectProtectedRanges(text) {
  const ranges = [];
  const patterns = [
    /https?:\/\/[^\s"<>`]+/giu,
    /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/giu,
    /`[^`]*`/gu,
    /"[^"]*"/gu,
    /\b\d+(?:[.,:/-]\d+)*\b/gu,
    /\b[A-Za-z_]*\d[A-Za-z0-9_]*\b/gu,
  ];

  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      if (match.index === undefined) {
        continue;
      }

      ranges.push({
        start: match.index,
        end: match.index + match[0].length,
      });
    }
  }

  ranges.sort((left, right) => left.start - right.start || left.end - right.end);
  return ranges;
}

function rangesOverlap(left, right) {
  return left.start < right.end && left.end > right.start;
}

function getSuggestionReplacement(suggestion) {
  try {
    return suggestion.get_replacement_text();
  } catch {
    return "";
  }
}

function loadProfile(profileName) {
  const profilePath = path.join(CUSTOM_ROOT, "config", `harper-${profileName}.json`);
  const profile = readJsonIfExists(profilePath);

  if (profile) {
    return { profilePath, profile };
  }

  return {
    profilePath,
    profile: {
      dialect: "American",
      lintConfig: {},
      weirpack: null,
      dictionary: null,
    },
  };
}

function resolveRepoPath(candidate) {
  if (!candidate) {
    return null;
  }

  return path.isAbsolute(candidate) ? candidate : path.resolve(REPO_ROOT, candidate);
}

function loadCustomRulePolicies() {
  const catalogPath = path.join(CUSTOM_ROOT, "RULE_CATALOG.json");
  const catalog = readJsonIfExists(catalogPath) ?? [];
  const policies = new Map();

  for (const entry of catalog) {
    policies.set(entry.rule_id, entry);
  }

  return policies;
}

async function loadDictionary(linter, dictionaryPath) {
  if (!dictionaryPath) {
    return;
  }

  const content = readTextIfExists(dictionaryPath);
  if (content === null) {
    throw new Error(`Dictionary file not found: ${dictionaryPath}`);
  }

  const words = parseDictionaryWords(content);
  if (words.length > 0) {
    await linter.importWords(words);
  }
}

async function loadWeirpack(linter, weirpackPath) {
  if (!weirpackPath) {
    return;
  }

  if (!fs.existsSync(weirpackPath)) {
    throw new Error(`Weirpack file not found: ${weirpackPath}`);
  }

  const failures = await linter.loadWeirpackFromBytes(fs.readFileSync(weirpackPath));
  if (failures && Object.keys(failures).length > 0) {
    throw new Error(`Weirpack tests failed: ${JSON.stringify(failures, null, 2)}`);
  }
}

function analyzeOrganizedFindings(organized, inputText, rulePolicies) {
  const findings = [];
  const ruleIds = new Set();
  const customRuleIds = new Set();
  let builtInFindingCount = 0;
  let customFindingCount = 0;

  for (const [ruleId, lints] of Object.entries(organized)) {
    const isCustom = rulePolicies.has(ruleId);
    ruleIds.add(ruleId);
    if (isCustom) {
      customRuleIds.add(ruleId);
    }

    for (let lintIndex = 0; lintIndex < lints.length; lintIndex += 1) {
      const lint = lints[lintIndex];
      const span = lint.span();
      const suggestions = [];

      try {
        for (const suggestion of lint.suggestions()) {
          suggestions.push({
            replacement: getSuggestionReplacement(suggestion),
            kind: String(suggestion.kind()),
          });
        }
      } catch {
        // Keep going with an empty suggestion list.
      }

      findings.push({
        rule_id: ruleId,
        is_custom: isCustom,
        rule_index: lintIndex,
        start: span.start,
        end: span.end,
        matched_text: Array.from(inputText).slice(span.start, span.end).join(""),
        message: (() => {
          try {
            return lint.message();
          } catch {
            return "";
          }
        })(),
        suggestions,
        suggestion_count: suggestions.length,
      });

      if (isCustom) {
        customFindingCount += 1;
      } else {
        builtInFindingCount += 1;
      }
    }
  }

  findings.sort((left, right) => left.start - right.start || left.end - right.end);

  return {
    findings,
    ruleIds: Array.from(ruleIds).sort((left, right) => left.localeCompare(right)),
    customRuleIds: Array.from(customRuleIds).sort((left, right) => left.localeCompare(right)),
    findingCount: findings.length,
    builtInFindingCount,
    customFindingCount,
  };
}

function isAutoApplyCandidate(ruleId, rulePolicies) {
  const entry = rulePolicies.get(ruleId);
  if (!entry) {
    return true;
  }

  if (entry.status === "detection_only") {
    return false;
  }

  return Boolean(entry.auto_apply);
}

async function applyCorrections(linter, initialText, initialAnalysis, rulePolicies) {
  const protectedRanges = collectProtectedRanges(initialText);
  const candidateFindings = initialAnalysis.findings
    .map((finding, index) => ({ ...finding, index }))
    .sort((left, right) => right.start - left.start || right.end - left.end);

  let correctedText = initialText;
  let currentFindingCount = initialAnalysis.findingCount;
  const appliedRuleIds = [];
  const suggestionOnlyRuleIds = [];
  const rejectedCorrections = [];
  const acceptedCorrections = [];

  for (const finding of candidateFindings) {
    const isCustom = finding.is_custom;
    const autoApply = isAutoApplyCandidate(finding.rule_id, rulePolicies);

    if (isCustom && !autoApply) {
      suggestionOnlyRuleIds.push(finding.rule_id);
      rejectedCorrections.push({
        rule_id: finding.rule_id,
        reason: "custom rule marked suggestion_only or detection_only",
        span: { start: finding.start, end: finding.end },
      });
      continue;
    }

    const overlapsProtected = protectedRanges.some((range) => rangesOverlap(finding, range));
    const overlapsApplied = acceptedCorrections.some((range) => rangesOverlap(finding, range));
    if (overlapsProtected || overlapsApplied) {
      rejectedCorrections.push({
        rule_id: finding.rule_id,
        reason: overlapsProtected ? "protected token span" : "overlapping earlier accepted correction",
        span: { start: finding.start, end: finding.end },
      });
      continue;
    }

    if (!finding.suggestions || finding.suggestions.length === 0) {
      rejectedCorrections.push({
        rule_id: finding.rule_id,
        reason: "no suggestions available",
        span: { start: finding.start, end: finding.end },
      });
      continue;
    }

    const lint = initialAnalysis.lintsByRule[finding.rule_id]?.[finding.rule_index];
    let suggestion = null;
    try {
      suggestion = lint?.suggestions?.()?.[0] ?? null;
    } catch {
      suggestion = null;
    }
    if (!lint || !suggestion) {
      rejectedCorrections.push({
        rule_id: finding.rule_id,
        reason: "missing lint or suggestion object",
        span: { start: finding.start, end: finding.end },
      });
      continue;
    }

    let proposedText = correctedText;
    try {
      proposedText = await linter.applySuggestion(correctedText, lint, suggestion);
    } catch (error) {
      rejectedCorrections.push({
        rule_id: finding.rule_id,
        reason: error instanceof Error ? error.message : String(error),
        span: { start: finding.start, end: finding.end },
      });
      continue;
    }

    const proposedAnalysis = await analyzeCurrentText(linter, proposedText, rulePolicies);
    if (proposedAnalysis.findingCount > currentFindingCount) {
      rejectedCorrections.push({
        rule_id: finding.rule_id,
        reason: "introduced additional objective findings",
        span: { start: finding.start, end: finding.end },
      });
      continue;
    }

    correctedText = proposedText;
    currentFindingCount = proposedAnalysis.findingCount;
    appliedRuleIds.push(finding.rule_id);
    acceptedCorrections.push({ start: finding.start, end: finding.end });
  }

  return {
    correctedText,
    appliedRuleIds: Array.from(new Set(appliedRuleIds)),
    suggestionOnlyRuleIds: Array.from(new Set(suggestionOnlyRuleIds)),
    rejectedCorrections,
  };
}

async function analyzeCurrentText(linter, text, rulePolicies) {
  const organized = await linter.organizedLints(text, {
    language: "plaintext",
    dedup: true,
  });

  const summary = analyzeOrganizedFindings(organized, text, rulePolicies);

  const lintsByRule = {};
  for (const [ruleId, lints] of Object.entries(organized)) {
    lintsByRule[ruleId] = lints;
  }

  return {
    ...summary,
    lintsByRule,
    organized,
  };
}

function buildDecisionMap(acceptedRuleIds, rejectedCorrections) {
  const decisionMap = new Map();

  for (const ruleId of acceptedRuleIds) {
    decisionMap.set(ruleId, {
      applied: true,
      rejected_reason: "",
    });
  }

  for (const item of rejectedCorrections) {
    if (!decisionMap.has(item.rule_id)) {
      decisionMap.set(item.rule_id, {
        applied: false,
        rejected_reason: item.reason,
      });
    }
  }

  return decisionMap;
}

async function main() {
  const inputCsv = getArgument("--input-csv", DEFAULT_INPUT_CSV);
  const outputCsv = getArgument("--output-csv", DEFAULT_OUTPUT_CSV);
  const textColumn = getArgument("--text-column", "input");
  const expectedColumn = getArgument("--expected-column", "expected_output");
  const dialectName = getArgument("--dialect", "American");
  const ruleProfile = getArgument("--rule-profile", "default");
  const explicitWeirpack = getArgument("--weirpack", null);
  const explicitDictionary = getArgument("--dictionary", null);
  const explicitLintConfig = getArgument("--lint-config", null);

  if (!fs.existsSync(inputCsv)) {
    throw new Error(`Input CSV not found: ${inputCsv}`);
  }

  const harper = await import("harper.js");
  const { binary } = await import("harper.js/binary");
  const { LocalLinter, Dialect } = harper;

  const availableDialects = {
    American: Dialect.American,
    British: Dialect.British,
    Australian: Dialect.Australian,
    Canadian: Dialect.Canadian,
    Indian: Dialect.Indian,
  };

  if (!(dialectName in availableDialects)) {
    throw new Error(
      `Unsupported dialect "${dialectName}". ` +
      `Choose from: ${Object.keys(availableDialects).join(", ")}`,
    );
  }

  const profile = loadProfile(ruleProfile);
  const lintConfigPath = resolveRepoPath(explicitLintConfig ?? profile.profile.lintConfigPath ?? null);
  const dictionaryPath = resolveRepoPath(explicitDictionary ?? profile.profile.dictionary ?? null);
  const weirpackPath = resolveRepoPath(explicitWeirpack ?? profile.profile.weirpack ?? null);
  const resolvedLintConfig = lintConfigPath ? readJsonIfExists(lintConfigPath) : profile.profile.lintConfig ?? null;

  const rulePolicies = loadCustomRulePolicies();

  const linter = new LocalLinter({
    binary,
    dialect: availableDialects[dialectName],
  });

  await linter.setup();

  if (resolvedLintConfig && Object.keys(resolvedLintConfig).length > 0) {
    await linter.setLintConfig(resolvedLintConfig);
  }

  await loadDictionary(linter, dictionaryPath);
  await loadWeirpack(linter, weirpackPath);

  const csvText = fs.readFileSync(inputCsv, "utf8");
  const rows = parse(csvText, {
    columns: true,
    skip_empty_lines: true,
    bom: true,
    relax_quotes: true,
    relax_column_count: true,
  });

  if (rows.length === 0) {
    throw new Error("The input CSV contains no data rows.");
  }

  const sampleRow = rows[0];
  if (!(textColumn in sampleRow)) {
    throw new Error(
      `Text column "${textColumn}" was not found. ` +
      `Available columns: ${Object.keys(sampleRow).join(", ")}`,
    );
  }

  const effectiveExpectedColumn = expectedColumn in sampleRow ? expectedColumn : (sampleRow.expected !== undefined ? "expected" : "expected_output");

  const results = [];
  let totalTimeMs = 0;

  try {
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const inputText = normalizeText(row[textColumn]);
      const expectedText = normalizeText(row[effectiveExpectedColumn]);
      const startedAt = process.hrtime.bigint();

      let correctedText = inputText;
      let runtimeError = "";
      let initialAnalysis = null;
      let finalAnalysis = null;
      let correctionDetails = {
        correctedText: inputText,
        appliedRuleIds: [],
        suggestionOnlyRuleIds: [],
        rejectedCorrections: [],
      };

      try {
        initialAnalysis = await analyzeCurrentText(linter, inputText, rulePolicies);
        correctionDetails = await applyCorrections(linter, inputText, initialAnalysis, rulePolicies);
        correctedText = correctionDetails.correctedText;
        finalAnalysis = await analyzeCurrentText(linter, correctedText, rulePolicies);
      } catch (error) {
        runtimeError = error instanceof Error ? error.message : String(error);
        if (initialAnalysis === null) {
          initialAnalysis = {
            findings: [],
            ruleIds: [],
            customRuleIds: [],
            findingCount: 0,
            builtInFindingCount: 0,
            customFindingCount: 0,
            lintsByRule: {},
          };
        }
      }

      const endedAt = process.hrtime.bigint();
      const elapsedMs = Number(endedAt - startedAt) / 1_000_000;
      totalTimeMs += elapsedMs;

      const findings = (initialAnalysis?.findings ?? []).map((finding) => {
      const decision = correctionDetails?.rejectedCorrections?.find((item) => item.rule_id === finding.rule_id && item.span.start === finding.start && item.span.end === finding.end);
        const applied = correctionDetails?.appliedRuleIds?.includes(finding.rule_id) ?? false;
        return {
          ...finding,
          applied,
          rejected_reason: decision ? decision.reason : "",
        };
      });

      const ruleIds = initialAnalysis?.ruleIds ?? [];
      const customRuleIds = initialAnalysis?.customRuleIds ?? [];

      results.push({
        ...row,
        benchmark_row: index + 1,
        checker: "harper",
        dialect: dialectName,
        rule_profile: ruleProfile,
        expected: expectedText,
        corrected_text: correctedText,
        changed: correctedText !== inputText,
        finding_count: initialAnalysis?.findingCount ?? 0,
        built_in_finding_count: initialAnalysis?.builtInFindingCount ?? 0,
        custom_finding_count: initialAnalysis?.customFindingCount ?? 0,
        rule_ids: JSON.stringify(ruleIds),
        custom_rule_ids: JSON.stringify(customRuleIds),
        findings_json: JSON.stringify(findings),
        rejected_corrections_json: JSON.stringify(correctionDetails?.rejectedCorrections ?? []),
        processing_time_ms: elapsedMs.toFixed(3),
        runtime_error: runtimeError,
        exact_match: expectedText !== "" ? correctedText === expectedText : false,
        clean_sentence_changed: expectedText !== "" ? inputText === expectedText && correctedText !== inputText : false,
        auto_applied_rule_ids: JSON.stringify(correctionDetails?.appliedRuleIds ?? []),
        suggestion_only_rule_ids: JSON.stringify(correctionDetails?.suggestionOnlyRuleIds ?? []),
        detection_changed: (finalAnalysis?.findingCount ?? 0) < (initialAnalysis?.findingCount ?? 0),
      });

      process.stdout.write(`\rHarper: ${index + 1}/${rows.length}`);
    }
  } finally {
    await linter.dispose();
  }

  fs.mkdirSync(path.dirname(outputCsv), { recursive: true });
  fs.writeFileSync(
    outputCsv,
    stringify(results, { header: true }),
    "utf8",
  );

  console.log();
  console.log(`Saved: ${outputCsv}`);
  console.log(`Rows: ${results.length}`);
  console.log(`Total processing time: ${totalTimeMs.toFixed(2)} ms`);
  console.log(`Average per row: ${(totalTimeMs / results.length).toFixed(3)} ms`);
}

main().catch((error) => {
  console.error();
  console.error("Harper benchmark failed:");
  console.error(error);
  process.exit(1);
});
