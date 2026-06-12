#!/usr/bin/env bash
set -euo pipefail

# Deploy/update this project on the BandwagonHost VPS.
#
# Modes:
#   pull   - ask VPS to fetch origin/main and hard-reset to it; requires GitHub remote to be updated.
#   patch  - upload all local commits ahead of origin/<branch> as a patch series and
#            apply them on VPS via git am; useful when GitHub push is temporarily unavailable.
#   status - show VPS repo status.
#
# Required env or file:
#   BANDWAGON_API_KEY       KiwiVM/BandwagonHost API key. Do NOT commit it.
#   BANDWAGON_API_KEY_FILE  Optional file containing the key; default:
#                           ~/.config/paper-llm/bandwagon_api_key
# Optional env:
#   BANDWAGON_VEID     Default: 2131405
#   VPS_APP_DIR        Default: /opt/wireless-channel-recommender/app
#   VPS_BRANCH         Default: main
#   RUN_PYTEST         Set to 1 to run pytest on VPS; default uses compileall only.

MODE="${1:-pull}"
BANDWAGON_VEID="${BANDWAGON_VEID:-2131405}"
VPS_APP_DIR="${VPS_APP_DIR:-/opt/wireless-channel-recommender/app}"
VPS_BRANCH="${VPS_BRANCH:-main}"
API_BASE="https://api.64clouds.com/v1"
BANDWAGON_API_KEY_FILE="${BANDWAGON_API_KEY_FILE:-$HOME/.config/paper-llm/bandwagon_api_key}"

if [[ -z "${BANDWAGON_API_KEY:-}" && -f "$BANDWAGON_API_KEY_FILE" ]]; then
  BANDWAGON_API_KEY="$(tr -d '\r\n' < "$BANDWAGON_API_KEY_FILE")"
fi

if [[ -z "${BANDWAGON_API_KEY:-}" ]]; then
  echo "ERROR: BANDWAGON_API_KEY is not set and key file was not found." >&2
  echo "Set one of:" >&2
  echo "  export BANDWAGON_API_KEY='***'" >&2
  echo "  printf '%s' '***' > '$BANDWAGON_API_KEY_FILE'" >&2
  echo "Then run:" >&2
  echo "  bash scripts/deploy_vps.sh status" >&2
  exit 2
fi

repo_root() {
  git rev-parse --show-toplevel
}

api_exec() {
  local command="$1"
  local response_file
  response_file="$(mktemp)"
  curl -fsS --noproxy '*' -X POST "$API_BASE/basicShell/exec" \
    --data-urlencode "veid=$BANDWAGON_VEID" \
    --data-urlencode "api_key=$BANDWAGON_API_KEY" \
    --data-urlencode "command=$command" \
    -o "$response_file"
  python3 - "$response_file" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
message = payload.get("message", "")
if message:
    print(message, end="" if message.endswith("\n") else "\n")
err = int(payload.get("error", 0) or 0)
if err:
    sys.exit(err)
PY
  rm -f "$response_file"
}

remote_validate_cmd() {
  cat <<'REMOTE'
set -euo pipefail
if command -v uv >/dev/null 2>&1; then
  PY='uv run python'
elif [ -x .venv/bin/python ]; then
  PY='.venv/bin/python'
else
  PY='python3'
fi
$PY -m compileall -q src/zotero_arxiv_daily scripts tests
if [ "${RUN_PYTEST:-0}" = "1" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv run pytest -q
  elif [ -x .venv/bin/python ]; then
    .venv/bin/python -m pytest -q
  else
    python3 -m pytest -q
  fi
fi
REMOTE
}

remote_status() {
  api_exec "cd '$VPS_APP_DIR' && git status --short --branch && echo ---HEAD--- && git log --oneline -n 3 && echo ---PYTHON--- && (command -v uv || true) && (test -x .venv/bin/python && .venv/bin/python --version || python3 --version)"
}

remote_pull() {
  local validate
  validate="$(remote_validate_cmd)"
  api_exec "cd '$VPS_APP_DIR' && git fetch origin '$VPS_BRANCH' && git reset --hard 'origin/$VPS_BRANCH' && $validate && git status --short --branch && echo VPS_UPDATE_OK"
}

remote_patch() {
  local root patch_url tmp_patch
  root="$(repo_root)"
  cd "$root"

  if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree is not clean. Commit or stash changes before patch deploy." >&2
    git status --short
    exit 3
  fi

  git fetch origin "$VPS_BRANCH" || true
  local range="origin/${VPS_BRANCH}..HEAD"
  local commit_count
  commit_count="$(git rev-list --count "$range")"
  if [[ "$commit_count" = "0" ]]; then
    echo "ERROR: no local commits ahead of origin/${VPS_BRANCH}; use pull mode instead." >&2
    exit 3
  fi

  tmp_patch="$(mktemp --suffix=.patch)"
  git format-patch --stdout "$range" > "$tmp_patch"
  patch_url="$(curl -fsS -F "c=@${tmp_patch}" https://paste.rs | tr -d '\r\n')"
  rm -f "$tmp_patch"

  if [[ ! "$patch_url" =~ ^https:// ]]; then
    echo "ERROR: failed to upload patch to paste.rs: $patch_url" >&2
    exit 4
  fi
  echo "Uploaded patch: $patch_url"

  local validate
  validate="$(remote_validate_cmd)"
  api_exec "set -euo pipefail
cd '$VPS_APP_DIR'
git fetch origin '$VPS_BRANCH' || true
git reset --hard 'origin/$VPS_BRANCH'
curl -fsSL '$patch_url' -o /tmp/paper_llm_deploy.patch
python3 - <<'PY'
from pathlib import Path
p = Path('/tmp/paper_llm_deploy.patch')
lines = p.read_text(encoding='utf-8', errors='ignore').splitlines(True)
start = next((i for i, line in enumerate(lines) if line.startswith('From ')), None)
if start is None:
    raise SystemExit('Could not find git patch start')
# paste.rs sometimes returns a multipart wrapper; keep the final boundary out.
bounds = [i for i, line in enumerate(lines) if line.startswith('--------------------------')]
end = max(bounds) if bounds else len(lines)
p.write_text(''.join(lines[start:end]), encoding='utf-8')
PY
git am -3 /tmp/paper_llm_deploy.patch
$validate
git status --short --branch
echo VPS_PATCH_DEPLOY_OK"
}

case "$MODE" in
  status)
    remote_status
    ;;
  pull)
    remote_pull
    ;;
  patch)
    remote_patch
    ;;
  *)
    echo "Usage: BANDWAGON_API_KEY=... bash scripts/deploy_vps.sh {status|pull|patch}" >&2
    exit 2
    ;;
esac
