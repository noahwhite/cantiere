#!/usr/bin/env bash
# Export docs/requirements.md to docs/requirements.docx and docs/requirements.pdf.
#
#   scripts/export-requirements.sh          regenerate both exports in place
#   scripts/export-requirements.sh --check  regenerate into a temporary directory and fail
#                                           when the text of either committed export differs
#
# Text is compared, not bytes, because export metadata is not part of the content.
# Every tool is pinned by version and SHA-256 and cached outside the repository.
# Supported hosts: Linux x86_64 and aarch64, with curl, tar, xz, sha256sum and python3.
set -euo pipefail

PANDOC_VERSION=3.13
TYPST_VERSION=0.15.1
PYPDF_VERSION=6.9.2
PYPDF_SHA256=662cf29bcb419a36a1365232449624ab40b7c2d0cfc28e54f42eeecd1fd7e844

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)
    PANDOC_ASSET=pandoc-${PANDOC_VERSION}-linux-amd64.tar.gz
    PANDOC_SHA256=38aa33b325a2bc96a4c39409631212db55702f564250bcdbead180b3bf646389
    TYPST_ASSET="typst-x86_64-unknown-linux-musl.tar.xz"
    TYPST_SHA256=a6d077d0a95eed5a2eba715b2dae06be954f624ccbf85758a03f389ded33118c
    ;;
  Linux-aarch64)
    PANDOC_ASSET=pandoc-${PANDOC_VERSION}-linux-arm64.tar.gz
    PANDOC_SHA256=21e1d4ba09bd0b334590d204580fd4f6629b21be4ab6a32b26cc98982e9e0c68
    TYPST_ASSET="typst-aarch64-unknown-linux-musl.tar.xz"
    TYPST_SHA256=5aa8d74a3d906e60ea12a66ac2f37f8eef1b14cbad7182a745e393a10c23dcee
    ;;
  *)
    echo "export-requirements: unsupported host $(uname -s)-$(uname -m); use Linux x86_64 or aarch64" >&2
    exit 2
    ;;
esac

mode=generate
case "${1-}" in
  "") ;;
  --check) mode=check ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tools="${XDG_CACHE_HOME:-$HOME/.cache}/cantiere-export-tools"
mkdir -p "$tools"

# fetch <url> <sha256> <file>: download once, verify the checksum every time.
fetch() {
  if [ ! -f "$3" ]; then
    curl -fsSL --retry 3 -o "$3.part" "$1"
    mv "$3.part" "$3"
  fi
  if ! echo "$2  $3" | sha256sum -c --quiet -; then
    rm -f "$3"
    echo "export-requirements: checksum mismatch for $1" >&2
    exit 1
  fi
}

pandoc_dir="$tools/pandoc-$PANDOC_VERSION"
if [ ! -x "$pandoc_dir/bin/pandoc" ]; then
  fetch "https://github.com/jgm/pandoc/releases/download/$PANDOC_VERSION/$PANDOC_ASSET" "$PANDOC_SHA256" "$tools/$PANDOC_ASSET"
  rm -rf "$pandoc_dir"
  mkdir -p "$pandoc_dir"
  tar -xzf "$tools/$PANDOC_ASSET" -C "$pandoc_dir" --strip-components=1
fi
pandoc="$pandoc_dir/bin/pandoc"

typst_dir="$tools/typst-$TYPST_VERSION"
if [ ! -x "$typst_dir/typst" ]; then
  fetch "https://github.com/typst/typst/releases/download/v$TYPST_VERSION/$TYPST_ASSET" "$TYPST_SHA256" "$tools/$TYPST_ASSET"
  rm -rf "$typst_dir"
  mkdir -p "$typst_dir"
  tar -xJf "$tools/$TYPST_ASSET" -C "$typst_dir" --strip-components=1
fi
typst="$typst_dir/typst"

# A fixed timestamp keeps the export metadata stable between runs.
export SOURCE_DATE_EPOCH=0

# pandoc writes its intermediate Typst file to the current directory.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# export_to <dir>: write requirements.docx and requirements.pdf into <dir>.
# Typst runs with its embedded fonts only, so neither export depends on the host's fonts, and
# with root / so it can read the files pandoc extracts to a temporary directory.
export_to() {
  # Without rsvg-convert pandoc embeds the SVG diagram with no PNG fallback, which Word before
  # 2016 cannot show, so the docx gets a PNG of it rendered by Typst instead.
  printf '#set page(width: auto, height: auto, margin: 0pt)\n#image("%s")\n' "$repo/docs/architecture.svg" > "$work/diagram.typ"
  "$typst" compile --ignore-system-fonts --root / --ppi 200 "$work/diagram.typ" "$work/architecture.png"
  printf 'function Image(img)\n  if img.src == "architecture.svg" then img.src = "architecture.png" end\n  return img\nend\n' > "$work/diagram-png.lua"
  "$pandoc" -f gfm --shift-heading-level-by=-1 "$repo/docs/requirements.md" --resource-path="$repo/docs:$work" \
    --lua-filter="$work/diagram-png.lua" -o "$1/requirements.docx"
  # Let long tables break across pages, and set table text flush left instead of centred and
  # justified.
  printf '#show figure: set block(breakable: true)\n#show table.cell: set align(left)\n#show table.cell: set par(justify: false)\n' > "$work/tables.typ"
  "$pandoc" -f gfm --shift-heading-level-by=-1 "$repo/docs/requirements.md" --resource-path="$repo/docs" \
    --include-in-header="$work/tables.typ" \
    --pdf-engine="$typst" --pdf-engine-opt=--ignore-system-fonts --pdf-engine-opt=--root=/ \
    -o "$1/requirements.pdf"
}

if [ "$mode" = generate ]; then
  export_to "$repo/docs"
  echo "export-requirements: wrote docs/requirements.docx and docs/requirements.pdf"
  exit 0
fi

venv="$tools/pypdf-$PYPDF_VERSION"
if [ ! -x "$venv/bin/python" ]; then
  rm -rf "$venv"
  python3 -m venv "$venv"
  echo "pypdf==$PYPDF_VERSION --hash=sha256:$PYPDF_SHA256" > "$venv/requirements.txt"
  "$venv/bin/python" -m pip install --quiet --disable-pip-version-check --no-deps --require-hashes -r "$venv/requirements.txt"
fi

mkdir "$work/fresh"
export_to "$work/fresh"

# text_of <file> <out>: the export's text, rewrapped so a difference shows as a readable diff.
text_of() {
  "$venv/bin/python" -I "$repo/scripts/export-text.py" "$1" > "$2"
}

status=0
for ext in docx pdf; do
  committed="$repo/docs/requirements.$ext"
  if [ ! -f "$committed" ]; then
    echo "export-requirements: docs/requirements.$ext is missing" >&2
    status=1
    continue
  fi
  text_of "$committed" "$work/committed.$ext.txt"
  text_of "$work/fresh/requirements.$ext" "$work/fresh.$ext.txt"
  if ! diff -u --label "committed docs/requirements.$ext" --label "regenerated from docs/requirements.md" \
      "$work/committed.$ext.txt" "$work/fresh.$ext.txt" > "$work/$ext.diff"; then
    echo "export-requirements: docs/requirements.$ext is stale; run scripts/export-requirements.sh and commit the result" >&2
    head -n 60 "$work/$ext.diff" >&2
    status=1
  else
    echo "export-requirements: docs/requirements.$ext matches docs/requirements.md"
  fi
done
exit "$status"
