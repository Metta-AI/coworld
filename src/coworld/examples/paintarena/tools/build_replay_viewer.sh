#!/usr/bin/env bash
set -euo pipefail

package_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$1"
if [[ "${output_dir}" != /* && ! "${output_dir}" =~ ^[A-Za-z]:[\\/] ]] ||
  [[ "${output_dir}" == "/" || "${output_dir}" == "${package_dir}" ]]; then
  echo "unsafe bundle output: ${output_dir}" >&2
  exit 1
fi

rm -rf "${output_dir}"
mkdir -p "${output_dir}"
cp "${package_dir}/game/client/replay.html" "${output_dir}/index.html"
