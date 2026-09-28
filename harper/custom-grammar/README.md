# Custom Grammar Framework

This directory contains the custom grammar extension layer for Harper.

## Architecture

- `rules/` contains Weir source files, grouped by grammar topic.
- `lexicons/` contains small machine-readable lexical datasets used by narrow rules.
- `schemas/` contains JSON schemas for the rule catalog and lexicons.
- `generated/` is the build output directory for flattened Weir sources, build metadata, and the packaged `.weirpack`.
- `reports/` contains coverage and implementation reports.
- `tests/` contains fixtures and regression notes that are not embedded directly in Weir files.

The custom rules are kept separate from Harper's built-in rules. The runner can load the built-in engine alone, the built-in engine plus a dictionary, or the built-in engine plus a custom Weirpack.

## Build Commands

- `npm run grammar:validate`
- `npm run grammar:generate`
- `npm run grammar:pack`
- `npm run grammar:test`
- `npm run grammar:benchmark`
- `npm run grammar:report`

## Loading

Use the enhanced benchmark runner with:

- `--dialect American`
- `--weirpack PATH`
- `--dictionary PATH`
- `--lint-config PATH`
- `--rule-profile default|grammar-only|custom`
- `--output-csv PATH`

## Notes

- Weir syntax follows the installed Harper/Weir support, which currently includes `expr`, `let message`, `let description`, `let kind`, `let becomes`, optional `let strategy`, optional `let scope`, `test`, and `allows`.
- The custom grammar content in this repository was authored independently.
- The reference PDF is not included in the build output.
