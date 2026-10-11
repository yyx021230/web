#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
version="${1:?usage: build_release_package.sh VERSION [OUTPUT_PATH]}"
python_bin="${PYTHON_BIN:-python3}"
"$python_bin" "$repo_root/scripts/check_version_control.py" --repo "$repo_root" --release --tag "v${version}"
commit="$(git -C "$repo_root" rev-parse --short HEAD)"
output="${2:-/tmp/web-source-${version}-${commit}.tar.gz}"
output="$("$python_bin" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$output")"

case "$output" in
  "$repo_root"|"$repo_root"/*)
    echo "Source archive must be outside the repository." >&2
    exit 1
    ;;
esac
if [[ -e "$output" ]]; then
  echo "Refusing to overwrite an existing source archive." >&2
  exit 1
fi

archive_tmp="$(mktemp "${output}.tmp.XXXXXX")"
trap 'rm -f "$archive_tmp"' EXIT
# Source-only export: production packages must also bind a Linux MCP binary.
git -C "$repo_root" archive --format=tar.gz --output="$archive_tmp" HEAD \
  backend frontend scripts docker-compose.yml docker-compose.dev.yml README.md CHANGELOG.md

if tar -tzf "$archive_tmp" | grep -Eq '(^|/)\._'; then
  echo "release package contains forbidden macOS metadata" >&2
  exit 1
fi

gzip -t "$archive_tmp"
# Both files are on the same filesystem; link fails atomically on a collision.
ln "$archive_tmp" "$output"
echo "Source-only archive; not a production package. Deploy via deploy-to-windows.sh." >&2
echo "$output"
