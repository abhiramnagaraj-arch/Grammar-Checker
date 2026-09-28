import fs from "node:fs";
import path from "node:path";
import {
  CUSTOM_ROOT,
  readJson,
  sortObject,
  writeJson,
  writeText,
} from "./shared.mjs";

function main() {
  const catalog = readJson(path.join(CUSTOM_ROOT, "RULE_CATALOG.json"));
  const reportDir = path.join(CUSTOM_ROOT, "reports");
  const buildReportPath = path.join(CUSTOM_ROOT, "generated", "build-report.json");

  const sourceToPackaged = fs.existsSync(buildReportPath)
    ? readJson(buildReportPath)
    : { rule_count: catalog.length, source_to_packaged: [] };
  const activeRuleCount = sourceToPackaged.rule_count ?? catalog.filter((entry) => entry.status !== "disabled").length;

  writeJson(path.join(reportDir, "build_report.json"), sortObject({
    rule_count: activeRuleCount,
    active_rule_count: activeRuleCount,
    catalog_rule_count: catalog.length,
    excluded_rule_count: sourceToPackaged.excluded_rule_count ?? 0,
    excluded_sources: sourceToPackaged.excluded_sources ?? [],
    source_to_packaged: sourceToPackaged.source_to_packaged ?? [],
  }));

  const coverage = [
    "grammar_category,built_in_harper_coverage,custom_coverage,unsupported,native_rule_candidate,contextual_fallback",
    "auxiliary,partial,high,false,false,false",
    "articles,partial,medium,false,true,true",
    "comparison,partial,high,false,false,false",
    "countability,partial,medium,false,true,true",
    "determiners,partial,high,false,false,false",
    "prepositions,partial,medium,false,true,true",
    "pronouns,partial,medium,false,true,true",
    "repetition,partial,high,false,false,false",
    "punctuation,partial,medium,false,false,false",
    "agreement,partial,low,false,true,true",
  ].join("\n");

  writeText(path.join(reportDir, "coverage_matrix.csv"), `${coverage}\n`);
  console.log(`Wrote reports for ${activeRuleCount} active custom rules.`);
}

main();
