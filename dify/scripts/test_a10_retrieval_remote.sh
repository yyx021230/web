#!/bin/sh
set -eu

dataset_id='745f1046-8234-4349-b785-1893dbed6bed'
tenant_id='e26eb051-74fd-4a24-aa59-5b2f448e5d1b'
dataset_token="$(docker exec docker-db_postgres-1 psql -U postgres -d dify -Atc \
  "select token from api_tokens where type='dataset' and tenant_id='${tenant_id}' order by created_at desc limit 1")"

for query in \
  '零跑汽车 零跑A10 A10 当前在售 官网 当前年款 具体版本 续航 电池 动力 尺寸 快充 底盘 智驾 标配 选配'
do
  body="$(python3 -c 'import json,sys; print(json.dumps({"query":sys.argv[1],"retrieval_model":{"search_method":"hybrid_search","reranking_enable":True,"reranking_mode":"reranking_model","reranking_model":{"reranking_provider_name":"langgenius/siliconflow/siliconflow","reranking_model_name":"Pro/BAAI/bge-reranker-v2-m3"},"weights":{"weight_type":"customized","vector_setting":{"vector_weight":0.7,"embedding_provider_name":"langgenius/siliconflow/siliconflow","embedding_model_name":"BAAI/bge-large-zh-v1.5"},"keyword_setting":{"keyword_weight":0.3}},"top_k":6,"score_threshold_enabled":False,"score_threshold":0}},ensure_ascii=False))' "$query")"
  response="$(curl -sS -X POST \
    "http://127.0.0.1/v1/datasets/${dataset_id}/retrieve" \
    -H "Authorization: Bearer ${dataset_token}" \
    -H 'Content-Type: application/json' --data-binary "$body")"
  echo "QUERY: $query"
  printf '%s' "$response" | python3 -c 'import json,sys
data=json.load(sys.stdin); rows=data.get("records",[])
print("COUNT",len(rows))
for row in rows[:3]:
 s=row.get("segment",{}); d=s.get("document",{})
 print(row.get("score"),d.get("name")," ".join((s.get("content") or "").split())[:180])'
done
