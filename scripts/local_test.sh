#!/usr/bin/env bash
# Local end-to-end test with simulated pay-per-event pricing (no Apify account needed).
# Usage: scripts/local_test.sh [input.json]
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
. .venv/bin/activate
export ACTOR_TEST_PAY_PER_EVENT=true
export APIFY_CHARGED_ACTOR_EVENT_COUNTS='{"document-converted":0,"page-converted":0}'
export APIFY_ACTOR_PRICING_INFO="$(python3 -c "import json;print(json.dumps({'pricingModel':'PAY_PER_EVENT','pricingPerEvent':{'actorChargeEvents':json.load(open('.actor/pay_per_event.json'))}}))")"
rm -rf storage/datasets/charging-log
if [ "${1:-}" != "" ]; then
  apify run -p --entrypoint src --input-file "$1"
else
  apify run -p --entrypoint src
fi
python3 scripts/summarize_run.py
