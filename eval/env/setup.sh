set -eu
. /scenario/env.sh
docker compose -f /lab/compose.yaml -f /scenario/compose.yaml up -d --build --quiet-pull
sleep "$BASELINE_SEC"
sh /scenario/inject.sh
sleep "$SETTLE_SEC"
