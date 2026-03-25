#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TRANSLATIONS_DIR="${PROJECT_ROOT}/src/translations"
OUTPUT_DIR="${PROJECT_ROOT}/resources/translations"

if [[ ! -d "${TRANSLATIONS_DIR}" ]]; then
  echo "Fehler: Übersetzungsordner nicht gefunden: ${TRANSLATIONS_DIR}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

if command -v pyside6-lrelease >/dev/null 2>&1; then
  LRELEASE_CMD=(pyside6-lrelease)
elif command -v lrelease >/dev/null 2>&1; then
  LRELEASE_CMD=(lrelease)
else
  echo "Fehler: Kein lrelease gefunden. Installiere Qt Linguist oder PySide6-Tools." >&2
  exit 1
fi

TS_FILES=(
  "${TRANSLATIONS_DIR}/tablion_de_DE.ts"
  "${TRANSLATIONS_DIR}/tablion_en_US.ts"
)

for ts_file in "${TS_FILES[@]}"; do
  if [[ ! -f "${ts_file}" ]]; then
    echo "Warnung: Datei fehlt, überspringe: ${ts_file}" >&2
    continue
  fi

  base_name="$(basename "${ts_file}" .ts)"
  qm_file="${OUTPUT_DIR}/${base_name}.qm"
  echo "Baue: $(basename "${ts_file}") -> $(basename "${qm_file}")"
  "${LRELEASE_CMD[@]}" "${ts_file}" -qm "${qm_file}"
done

echo "Fertig: Übersetzungen kompiliert in ${OUTPUT_DIR}"
