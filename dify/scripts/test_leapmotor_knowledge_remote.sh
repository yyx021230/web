#!/bin/sh
set -eu

dataset_id='745f1046-8234-4349-b785-1893dbed6bed'
tenant_id='e26eb051-74fd-4a24-aa59-5b2f448e5d1b'
dataset_token="$(docker exec docker-db_postgres-1 psql -U postgres -d dify -Atc \
  "select token from api_tokens where type='dataset' and tenant_id='${tenant_id}' order by created_at desc limit 1")"

for query in \
  'Lafa5 Ultra 500Ultra和600Ultra的续航、电池容量、快充时间分别是多少' \
  '零跑D99增程版有哪些版本，纯电续航和车身尺寸是多少' \
  '2027款零跑C16纯电与增程有哪些版本，不能混用配置' \
  '2027款B01有哪些当前版本和关键动力参数' \
  '零跑A10当前版本和续航分别是什么'
do
  body="$(python3 -c 'import json,sys; print(json.dumps({"query":sys.argv[1],"retrieval_model":{"search_method":"hybrid_search","reranking_enable":True,"reranking_mode":"reranking_model","reranking_model":{"reranking_provider_name":"langgenius/siliconflow/siliconflow","reranking_model_name":"Pro/BAAI/bge-reranker-v2-m3"},"weights":{"weight_type":"customized","vector_setting":{"vector_weight":0.7,"embedding_provider_name":"langgenius/siliconflow/siliconflow","embedding_model_name":"BAAI/bge-large-zh-v1.5"},"keyword_setting":{"keyword_weight":0.3}},"top_k":6,"score_threshold_enabled":False,"score_threshold":0}},ensure_ascii=False))' "$query")"
  response="$(curl -sS -X POST \
    "http://127.0.0.1/v1/datasets/${dataset_id}/retrieve" \
    -H "Authorization: Bearer ${dataset_token}" \
    -H 'Content-Type: application/json' \
    --data-binary "$body")"
  echo "QUERY: $query"
  printf '%s' "$response" | python3 -c 'import json,sys
data=json.load(sys.stdin)
records=data.get("records", [])
if not records:
    print("NO_RECORDS", data)
for i, record in enumerate(records[:3], 1):
    segment=record.get("segment", {})
    document=segment.get("document", {})
    text=" ".join((segment.get("content") or "").split())[:260]
    print(f"TOP{i} score={record.get(chr(115)+chr(99)+chr(111)+chr(114)+chr(101))} doc={document.get(chr(110)+chr(97)+chr(109)+chr(101))} text={text}")'
done
