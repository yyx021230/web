#!/bin/sh
set -eu

dataset_id='745f1046-8234-4349-b785-1893dbed6bed'
tenant_id='e26eb051-74fd-4a24-aa59-5b2f448e5d1b'
payload_dir="${1:-/tmp/leapmotor-kb-20260819}"

dataset_token="$(docker exec docker-db_postgres-1 psql -U postgres -d dify -Atc \
  "select token from api_tokens where type='dataset' and tenant_id='${tenant_id}' order by created_at desc limit 1")"

if [ -z "$dataset_token" ]; then
  echo 'ERROR: no dataset API token found' >&2
  exit 1
fi

for payload in "$payload_dir"/*.json; do
  filename="$(basename "$payload")"
  response="$(curl -sS -X POST \
    "http://127.0.0.1/v1/datasets/${dataset_id}/document/create-by-text" \
    -H "Authorization: Bearer ${dataset_token}" \
    -H 'Content-Type: application/json' \
    --data-binary "@${payload}")"
  case "$response" in
    *'"document"'*) echo "IMPORTED ${filename} ${response}" ;;
    *) echo "FAILED ${filename} ${response}" >&2; exit 1 ;;
  esac
done
