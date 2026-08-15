#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE_NAME="xiangzhongjing-delivery-$(date +%Y%m%d-%H%M%S)"
DIST_DIR="$ROOT_DIR/dist"
STAGING_DIR="$DIST_DIR/$PACKAGE_NAME"
ARCHIVE_PATH="$DIST_DIR/$PACKAGE_NAME.tar.gz"
ZIP_PATH="$DIST_DIR/$PACKAGE_NAME.zip"
CHECKSUM_PATH="$DIST_DIR/$PACKAGE_NAME.sha256"

mkdir -p "$DIST_DIR"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

rsync -a \
  --exclude ".git" \
  --exclude ".DS_Store" \
  --exclude ".env" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "*.log" \
  --exclude "*.sqlite" \
  --exclude "*.sqlite3" \
  --exclude "xiangzhongjing.db" \
  --exclude "templates.json" \
  --exclude "uploads" \
  --exclude "outputs" \
  --exclude "demo_screenshots" \
  --exclude "prd_screenshots" \
  --exclude "dist" \
  "$ROOT_DIR/" "$STAGING_DIR/"

tar -czf "$ARCHIVE_PATH" -C "$DIST_DIR" "$PACKAGE_NAME"
(
  cd "$DIST_DIR"
  /usr/bin/zip -qry "$ZIP_PATH" "$PACKAGE_NAME"
)
(
  cd "$DIST_DIR"
  /usr/bin/shasum -a 256 "$PACKAGE_NAME.tar.gz" "$PACKAGE_NAME.zip" > "$PACKAGE_NAME.sha256"
)
rm -rf "$STAGING_DIR"

print "$ZIP_PATH"
print "$ARCHIVE_PATH"
print "$CHECKSUM_PATH"
