#!/bin/sh
set -eu

KIBANA_URL="${KIBANA_URL:-http://kibana:5601}"
DASHBOARD_FILE="/dashboards/hap-daikin-dashboard.ndjson"

echo "waiting for Kibana at ${KIBANA_URL}"
until curl -fsS "${KIBANA_URL}/api/status" >/dev/null; do
  sleep 5
done

echo "creating Daikin sensor data view"
curl -fsS \
  -X POST "${KIBANA_URL}/api/data_views/data_view" \
  -H "kbn-xsrf: hap-daikin-ac" \
  -H "Content-Type: application/json" \
  -d '{"data_view":{"id":"hap-daikin-sensors","title":"hap-daikin-sensors-*","name":"Daikin RM4 Sensors","timeFieldName":"@timestamp"}}' \
  >/dev/null || true

echo "importing Daikin dashboard"
curl -fsS \
  -X POST "${KIBANA_URL}/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: hap-daikin-ac" \
  -F "file=@${DASHBOARD_FILE}" \
  >/dev/null

echo "Kibana dashboard import complete"
