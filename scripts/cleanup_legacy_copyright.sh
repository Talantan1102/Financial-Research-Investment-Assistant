#!/usr/bin/env bash
# Cleanup legacy company copyright header from tracked code files.
#
# Two header formats handled (per audit 2026-05-03):
#   .py files (2-line, # comment style):
#       # Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
#       # 未经授权,禁止转售或仿制。
#   .tsx/.ts/.jsx/.js/.scss/.css/.html files (4-line, /** */ block):
#       /**
#        * Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
#        * 未经授权,禁止转售或仿制。
#        */
#
# Self-excluded:
#   - This script itself (LEGACY_STRING value contains the string)
#   - docs/superpowers/plans/* (plan docs legitimately contain the string for documentation)
#
# Other .md files with the string are SKIPPED (no handler defined).
#
# Usage:
#   bash scripts/cleanup_legacy_copyright.sh           # dry-run
#   bash scripts/cleanup_legacy_copyright.sh --apply   # actually edit files

set -euo pipefail

LEGACY_STRING="深圳市深维智见教育科技有限公司"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

# Get all tracked files containing the legacy string,
# excluding self + plan docs.
# Use a temp file for compatibility with bash 3.x (macOS default).
_TMPFILE=$(mktemp)
git ls-files \
  | grep -vE '^docs/superpowers/plans/|^scripts/cleanup_legacy_copyright\.sh$' \
  | xargs -I{} grep -l "$LEGACY_STRING" {} 2>/dev/null \
  > "$_TMPFILE" || true

FILE_COUNT=$(wc -l < "$_TMPFILE" | tr -d ' ')

echo "Found $FILE_COUNT code files containing legacy copyright (excluding plan docs + self)."

if [[ "$FILE_COUNT" -eq 0 ]]; then
  rm "$_TMPFILE"
  echo "Nothing to do."
  exit 0
fi

if [[ $APPLY -eq 0 ]]; then
  echo "DRY-RUN. Files (first 20):"
  head -20 "$_TMPFILE" | sed 's/^/  /'
  REMAINING=$((FILE_COUNT - 20))
  [[ $REMAINING -gt 0 ]] && echo "  ... and $REMAINING more"
  rm "$_TMPFILE"
  echo ""
  echo "Re-run with --apply to actually edit."
  exit 0
fi

CLEANED=0
SKIPPED=0
while IFS= read -r f; do
  case "$f" in
    *.py)
      # 2-line # comment block (lines 1-2)
      head -n 2 "$f" | grep -q "$LEGACY_STRING" || {
        echo "SKIP (.py legacy not in first 2 lines): $f"
        SKIPPED=$((SKIPPED+1))
        continue
      }
      sed -i.bak '1,2d' "$f"
      rm "${f}.bak"
      CLEANED=$((CLEANED+1))
      ;;
    *.tsx|*.ts|*.jsx|*.js|*.scss|*.css|*.html)
      # 4-line /** ... */ block (lines 1-4)
      head -n 4 "$f" | grep -q "$LEGACY_STRING" || {
        echo "SKIP (legacy not in first 4 lines): $f"
        SKIPPED=$((SKIPPED+1))
        continue
      }
      sed -i.bak '1,4d' "$f"
      rm "${f}.bak"
      CLEANED=$((CLEANED+1))
      ;;
    *.md)
      echo "SKIP (md no handler): $f"
      SKIPPED=$((SKIPPED+1))
      ;;
    *)
      echo "SKIP (unknown extension): $f"
      SKIPPED=$((SKIPPED+1))
      ;;
  esac
done < "$_TMPFILE"
rm "$_TMPFILE"

echo ""
echo "Cleaned: $CLEANED files"
echo "Skipped: $SKIPPED files"
echo "Run 'git diff --stat' to review."
