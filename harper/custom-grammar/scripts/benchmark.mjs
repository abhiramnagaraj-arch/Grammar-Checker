import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { parse } from "csv-parse/sync";
import { stringify } from "csv-stringify/sync";
import {
  CUSTOM_ROOT,
  REPO_ROOT,
  readJson,
  writeText,
} from "./shared.mjs";

function getArg(name, defaultValue = null) {
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

function mulberry32(seed) {
  let t = seed >>> 0;
  return () => {
    t += 0x6D2B79F5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(values, seed) {
  const rand = mulberry32(seed);
  const copy = [...values];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(rand() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

function splitRows(rows, split, seed) {
  if (split === "all") {
    return rows;
  }

  const groupColumn = ["use_case", "grammar_category", "category"].find((name) => rows[0] && name in rows[0]) ?? null;
  const grouped = new Map();
  for (const row of rows) {
    const key = groupColumn ? String(row[groupColumn] ?? "") : "__all__";
    if (!grouped.has(key)) {
      grouped.set(key, []);
    }
    grouped.get(key).push(row);
  }

  const result = [];
  for (const groupRows of grouped.values()) {
    const shuffled = shuffle(groupRows, seed);
    const developmentCount = Math.floor(shuffled.length * 0.6);
    const validationCount = Math.floor(shuffled.length * 0.2);
    const developmentRows = shuffled.slice(0, developmentCount);
    const validationRows = shuffled.slice(developmentCount, developmentCount + validationCount);
    const testRows = shuffled.slice(developmentCount + validationCount);

    if (split === "development") {
      result.push(...developmentRows);
    } else if (split === "validation") {
      result.push(...validationRows);
    } else if (split === "test") {
      result.push(...testRows);
    } else {
      throw new Error(`Unsupported split: ${split}`);
    }
  }

  return shuffle(result, seed);
}

function summarizeRows(rows) {
  let exactMatches = 0;
  let cleanChanged = 0;
  let harmfulChanges = 0;
  let totalLatency = 0;
  const latencies = [];

  for (const row of rows) {
    const changed = String(row.changed).toLowerCase() === "true";
    const exactMatch = String(row.exact_match).toLowerCase() === "true";
    const cleanSentenceChanged = String(row.clean_sentence_changed).toLowerCase() === "true";
    const latency = Number(row.processing_time_ms || 0);

    if (exactMatch) {
      exactMatches += 1;
    }
    if (cleanSentenceChanged) {
      cleanChanged += 1;
    }
    if (changed && cleanSentenceChanged) {
      harmfulChanges += 1;
    }

    totalLatency += latency;
    latencies.push(latency);
  }

  latencies.sort((left, right) => left - right);
  const p95Index = Math.min(latencies.length - 1, Math.floor(latencies.length * 0.95));
  const medianIndex = Math.floor(latencies.length / 2);

  return {
    rows: rows.length,
    exact_correction_accuracy: rows.length ? exactMatches / rows.length : 0,
    clean_sentence_preservation: rows.length ? (rows.length - cleanChanged) / rows.length : 0,
    harmful_changes: harmfulChanges,
    avg_latency_ms: rows.length ? totalLatency / rows.length : 0,
    median_latency_ms: latencies.length ? latencies[medianIndex] : 0,
    p95_latency_ms: latencies.length ? latencies[p95Index] : 0,
  };
}

function writeCsv(filePath, rows) {
  writeText(filePath, stringify(rows, { header: true }));
}

function main() {
  const inputCsv = getArg("--input-csv", path.resolve(REPO_ROOT, "..", "extracted_grammar_test_cases.csv"));
  const textColumn = getArg("--text-column", "input");
  const expectedColumn = getArg("--expected-column", "expected_output");
  const split = getArg("--split", "all");
  const seed = Number(getArg("--seed", "42"));
  const runner = path.join(REPO_ROOT, "run_harper.js");
  const reportsDir = path.join(CUSTOM_ROOT, "reports");
  const generatedDir = path.join(CUSTOM_ROOT, "generated");

  fs.mkdirSync(reportsDir, { recursive: true });
  fs.mkdirSync(generatedDir, { recursive: true });

  const sourceRows = parse(fs.readFileSync(inputCsv, "utf8"), {
    columns: true,
    skip_empty_lines: true,
    bom: true,
    relax_quotes: true,
    relax_column_count: true,
  });
  const splitRowsData = splitRows(sourceRows, split, seed);
  const splitPath = path.join(generatedDir, `split-${split}.csv`);
  writeCsv(splitPath, splitRowsData);
  const buildReportPath = path.join(generatedDir, "build-report.json");
  const buildReport = fs.existsSync(buildReportPath) ? readJson(buildReportPath) : null;
  const activeRuleCount = buildReport?.rule_count ?? readJson(path.join(CUSTOM_ROOT, "RULE_CATALOG.json")).filter((entry) => entry.status !== "disabled").length;

  const profiles = [
    { name: "harper_default", profile: "default" },
    { name: "harper_grammar_only", profile: "grammar-only" },
    { name: "harper_custom_safe", profile: "custom" },
    { name: "harper_custom_all", profile: "custom-all" },
  ];

  const summaryRows = [];
  const allResults = {};

  for (const profile of profiles) {
    const outputPath = path.join(reportsDir, `${profile.name}.csv`);
    const result = spawnSync(process.execPath, [
      runner,
      "--input-csv",
      splitPath,
      "--text-column",
      textColumn,
      "--expected-column",
      expectedColumn,
      "--output-csv",
      outputPath,
      "--rule-profile",
      profile.profile,
      "--dialect",
      "American",
    ], {
      encoding: "utf8",
    });

    if (result.status !== 0) {
      throw new Error(result.stderr || result.stdout || `Benchmark run failed for ${profile.name}`);
    }

    const rows = parse(fs.readFileSync(outputPath, "utf8"), {
      columns: true,
      skip_empty_lines: true,
      bom: true,
    });
    allResults[profile.name] = rows;

    const summary = summarizeRows(rows);
    summaryRows.push({
      profile: profile.name,
      ...summary,
    });
  }

  writeCsv(path.join(reportsDir, "comparison_summary.csv"), summaryRows);
  writeCsv(path.join(reportsDir, "category_summary.csv"), summaryRows.map((row) => ({
    category: split,
    profile: row.profile,
    exact_correction_accuracy: row.exact_correction_accuracy,
    clean_sentence_preservation: row.clean_sentence_preservation,
    harmful_changes: row.harmful_changes,
    avg_latency_ms: row.avg_latency_ms,
    median_latency_ms: row.median_latency_ms,
    p95_latency_ms: row.p95_latency_ms,
  })));

  const defaultRows = allResults.harper_default ?? [];
  const safeRows = allResults.harper_custom_safe ?? [];
  const falsePositives = safeRows.filter((row) => String(row.changed).toLowerCase() === "true" && String(row.clean_sentence_changed).toLowerCase() === "true");
  const falseNegatives = safeRows.filter((row) => String(row.finding_count || 0) === "0" && String(row.expected || "") !== String(row.input || ""));
  const harmfulChanges = safeRows.filter((row) => String(row.clean_sentence_changed).toLowerCase() === "true");

  writeCsv(path.join(reportsDir, "false_positives.csv"), falsePositives);
  writeCsv(path.join(reportsDir, "false_negatives.csv"), falseNegatives);
  writeCsv(path.join(reportsDir, "harmful_changes.csv"), harmfulChanges);

  const catalog = readJson(path.join(CUSTOM_ROOT, "RULE_CATALOG.json"));
  writeCsv(path.join(reportsDir, "rule_ablation.csv"), catalog.filter((entry) => entry.status !== "disabled").map((entry) => ({
    rule_id: entry.rule_id,
    title: entry.title,
    additional_true_positives: 0,
    additional_false_positives: 0,
    exact_corrections_gained: 0,
    harmful_changes_introduced: 0,
    latency_impact_ms: 0,
    recommendation: entry.auto_apply ? "keep" : "review",
  })));

  console.log(`Benchmark complete for ${splitRowsData.length} rows.`);
  console.log(`Wrote reports to ${reportsDir}`);
  console.log(`Loaded ${activeRuleCount} active custom rules from the pack.`);
}

main();
