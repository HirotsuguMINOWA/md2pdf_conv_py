#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRY_SCRIPT="$SCRIPT_DIR/src/md2pdf.py"

exec pyinstaller \
  --onefile \
  --clean \
  --specpath "$SCRIPT_DIR" \
  --distpath "$SCRIPT_DIR/dist" \
  --workpath "$SCRIPT_DIR/build" \
  "$ENTRY_SCRIPT"
