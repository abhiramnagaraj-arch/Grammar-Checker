#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LANGUAGETOOL_HOME="${LANGUAGETOOL_HOME:-/opt/LanguageTool}"
LANGUAGETOOL_PORT="${LANGUAGETOOL_PORT:-8082}"
LANGUAGETOOL_CONFIG="${LANGUAGETOOL_CONFIG:-$REPO_ROOT/server.properties}"
LANGUAGETOOL_JAR="${LANGUAGETOOL_JAR:-$LANGUAGETOOL_HOME/languagetool-server.jar}"
LANGUAGETOOL_NGRAMS="${LANGUAGETOOL_NGRAMS:-}"

if ! command -v java >/dev/null 2>&1; then
  echo "Missing Java runtime: 'java' was not found on PATH." >&2
  echo "Install Java first, then rerun this script." >&2
  exit 1
fi

if [[ ! -f "$LANGUAGETOOL_CONFIG" ]]; then
  echo "Missing server.properties: $LANGUAGETOOL_CONFIG" >&2
  echo "Edit the sample file in the repository root or pass LANGUAGETOOL_CONFIG=/absolute/path/to/server.properties" >&2
  exit 1
fi

if [[ ! -f "$LANGUAGETOOL_JAR" ]]; then
  echo "Missing LanguageTool server jar: $LANGUAGETOOL_JAR" >&2
  echo "Set LANGUAGETOOL_HOME or LANGUAGETOOL_JAR to your LanguageTool installation." >&2
  exit 1
fi

if [[ -n "$LANGUAGETOOL_NGRAMS" ]]; then
  if [[ ! -d "$LANGUAGETOOL_NGRAMS" ]]; then
    echo "Missing LanguageTool n-gram parent directory: $LANGUAGETOOL_NGRAMS" >&2
    exit 1
  fi
  if [[ ! -d "$LANGUAGETOOL_NGRAMS/en" ]]; then
    echo "Missing English n-gram directory: $LANGUAGETOOL_NGRAMS/en" >&2
    exit 1
  fi
fi

echo "LanguageTool home: $LANGUAGETOOL_HOME"
echo "LanguageTool config: $LANGUAGETOOL_CONFIG"
echo "LanguageTool port: $LANGUAGETOOL_PORT"
if [[ -n "$LANGUAGETOOL_NGRAMS" ]]; then
  echo "LanguageTool n-grams: enabled at $LANGUAGETOOL_NGRAMS"
else
  echo "LanguageTool n-grams: disabled"
fi

exec java -cp "$LANGUAGETOOL_JAR" \
  org.languagetool.server.HTTPServer \
  --config "$LANGUAGETOOL_CONFIG" \
  --port "$LANGUAGETOOL_PORT"
