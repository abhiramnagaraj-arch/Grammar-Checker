import fs from "node:fs";
import path from "node:path";
import { CUSTOM_ROOT } from "./shared.mjs";

async function main() {
  const { LocalLinter, Dialect } = await import("harper.js");
  const { binary } = await import("harper.js/binary");

  const packPath = path.join(CUSTOM_ROOT, "generated", "custom-grammar.weirpack");
  if (!fs.existsSync(packPath)) {
    throw new Error("Missing custom-grammar.weirpack. Run grammar:pack first.");
  }

  const linter = new LocalLinter({ binary, dialect: Dialect.American });
  await linter.setup();

  const failures = await linter.loadWeirpackFromBytes(fs.readFileSync(packPath));
  await linter.dispose();

  if (failures && Object.keys(failures).length > 0) {
    console.error(JSON.stringify(failures, null, 2));
    throw new Error("Weirpack tests failed.");
  }

  console.log("Weirpack tests passed.");
  console.log(`Loaded custom rule pack from ${packPath}`);
}

main();
