#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-v0.3.0-beta}"
STAGE="${ROOT}/dist/community/xiangzhongjing-${VERSION}"
ARCHIVE="${ROOT}/dist/community/xiangzhongjing-${VERSION}.zip"

rm -rf "${STAGE}" "${ARCHIVE}"
mkdir -p "${STAGE}"
rsync -a "${ROOT}/" "${STAGE}/" \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '.venv/' \
  --exclude '.mcp-venv/' \
  --exclude '.pytest_cache/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude 'artifacts/' \
  --exclude 'backups/' \
  --exclude 'dist/' \
  --exclude 'docs/private-delivery/' \
  --exclude 'docs/DELIVERY_CHECKLIST.md' \
  --exclude 'docs/HACKATHON_ITERATION_PLAN_2026-08-09.md' \
  --exclude 'docs/MCP_DEPLOYMENT_REPORT_2026-08-10.md' \
  --exclude 'docs/MODULAR_MONOLITH_UPDATE_2026-08-08.md' \
  --exclude 'docs/PRODUCT_EVALUATION.md' \
  --exclude 'docs/TECHNICAL_HANDOFF.md' \
  --exclude 'docs/TECH_LEAD_HANDOFF_2026-08-10.md' \
  --exclude 'docs/UPDATE_REPORT_2026-08-15.md' \
  --exclude 'docs/UPDATE_REPORT_V0.3.0_BETA_2026-08-15.md' \
  --exclude 'docs/mirror-and-book-personas-prd.md' \
  --exclude 'PRD.md' \
  --exclude 'product_skills/.defaults/' \
  --exclude 'scripts/private_delivery/' \
  --exclude 'scripts/install_private_copy.sh' \
  --exclude 'scripts/install_private_copy_windows.ps1' \
  --exclude 'scripts/package_private_full_copy.sh' \
  --exclude 'scripts/seed_v22_candidate.py' \
  --exclude 'scripts/start_private_copy.sh' \
  --exclude 'scripts/start_private_copy_windows.ps1' \
  --exclude 'scripts/stop_private_copy.sh' \
  --exclude 'scripts/stop_private_copy_windows.ps1' \
  --exclude 'scripts/verify_installation_windows.ps1' \
  --exclude 'tests/test_private_delivery_contract.py' \
  --exclude 'knowledge/personal_style_profile.md' \
  --exclude 'knowledge/xiangzhongjing_writing_skill.md' \
  --exclude 'knowledge/xiangzhongjing_writing_skill_published_v2_2.md' \
  --exclude 'knowledge/xiangzhongjing_writing_skill_v2_2_candidate.md' \
  --exclude '*.db' \
  --exclude '*.sqlite' \
  --exclude '*.sqlite3' \
  --exclude '*.enc' \
  --exclude '*.key.txt' \
  --exclude '*.zip' \
  --exclude '*.tar' \
  --exclude '*.tar.gz' \
  --exclude '*.tgz' \
  --exclude '*.7z' \
  --exclude '*.log' \
  --exclude 'uploads/' \
  --exclude 'outputs/' \
  --exclude 'demo_screenshots/' \
  --exclude 'prd_screenshots/'

python3 "${ROOT}/scripts/sanitize_community_package.py" "${STAGE}"
cp "${ROOT}/docs/COMMUNITY_PRD.md" "${STAGE}/PRD.md"
printf '%s\n' "${VERSION#v}" > "${STAGE}/VERSION"

if rg -n --hidden '(sk-[A-Za-z0-9]{20,}|tvly-[A-Za-z0-9]{20,})' "${STAGE}"; then
  echo "检测到疑似真实密钥，已停止打包" >&2
  exit 1
fi

PRIVATE_NAME="$(printf '\345\255\220\345\235\244')"
PRIVATE_LATIN="$(printf '\132\151\153\165\156')"
if rg -n "${PRIVATE_NAME}|Yan ${PRIVATE_NAME}|${PRIVATE_LATIN}|抖音搜${PRIVATE_NAME}" \
  "${STAGE}/api" "${STAGE}/services" "${STAGE}/product_skills" \
  "${STAGE}/static" "${STAGE}/templates"; then
  echo "检测到运行时创作者身份硬编码，已停止打包" >&2
  exit 1
fi

if [[ -n "$(find "${STAGE}" -type f -size +10M -print -quit)" ]]; then
  echo "检测到超过 10MB 的异常单文件，可能混入备份或私有资产，已停止打包" >&2
  exit 1
fi

(cd "$(dirname "${STAGE}")" && zip -qr "${ARCHIVE}" "$(basename "${STAGE}")")
shasum -a 256 "${ARCHIVE}" > "${ARCHIVE}.sha256"
printf '%s\n' "${ARCHIVE}"
