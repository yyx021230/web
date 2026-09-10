#!/bin/sh
set -eu

dataset_id='745f1046-8234-4349-b785-1893dbed6bed'
tenant_id='e26eb051-74fd-4a24-aa59-5b2f448e5d1b'
document_id='528810bb-fe04-4bda-85da-4fac6875b3cc'
dataset_token="$(docker exec docker-db_postgres-1 psql -U postgres -d dify -Atc \
  "select token from api_tokens where type='dataset' and tenant_id='${tenant_id}' order by created_at desc limit 1")"

curl -sS -X PATCH \
  "http://127.0.0.1/v1/datasets/${dataset_id}/documents/status/disable" \
  -H "Authorization: Bearer ${dataset_token}" \
  -H 'Content-Type: application/json' \
  --data-binary "{\"document_ids\":[\"${document_id}\"]}"
