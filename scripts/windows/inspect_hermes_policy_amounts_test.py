"""Read only the three approved runs' checkpoints and stage logs."""
import json
from pathlib import Path
root=Path('/app/web/outputs/xhs_hermes_web')
results=[]
for run_id in (9,10,11):
    folder=root/f'run-{run_id}'
    checkpoint=folder/'2026-09-09/checkpoint.json'
    result={'run_id':run_id,'checkpoint':checkpoint.exists()}
    if checkpoint.exists():
        data=json.loads(checkpoint.read_text())
        result['updated_at']=data.get('updated_at')
        result['last_error']=data.get('last_error')
        result['posts']=[]
        for p in data.get('posts',{}).values():
            result['posts'].append({'key':p['key'],'mother_id':(p.get('mother') or {}).get('id'),
                'copy':{k:(p.get('copy') or {}).get(k) for k in ('ok','title','errors')},
                'image_plan':{k:(p.get('image_plan') or {}).get(k) for k in ('ok','selected_prompt_id','errors')},
                'image':{k:(p.get('image') or {}).get(k) for k in ('ok','status','attempt','task_id','image_url','failures')},
                'timings':p.get('timings')})
    log=folder/'worker.log'
    if log.exists():
        events=[]
        for line in log.read_text(errors='replace').splitlines():
            try: event=json.loads(line)
            except ValueError: continue
            events.append({k:event[k] for k in ('stage','event','time','key','task_id','elapsed_seconds','error') if k in event})
        result['events']=events[-6:]
    results.append(result)
print(json.dumps(results,ensure_ascii=False))
