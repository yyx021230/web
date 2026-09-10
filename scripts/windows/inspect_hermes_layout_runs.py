"""Read-only, credential-free checkpoint summary for two acceptance runs."""
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--content', action='store_true')
parser.add_argument('--image-status', action='store_true')
args = parser.parse_args()
results = []
for run_id in (2, 3):
    checkpoint = Path(f'/app/web/outputs/xhs_hermes_web/run-{run_id}/2026-09-08/checkpoint.json')
    if not checkpoint.exists():
        continue
    state = json.loads(checkpoint.read_text())
    posts = []
    for post in state.get('posts', {}).values():
        plan, copy, image = (post.get(key) or {} for key in ('image_plan', 'copy', 'image'))
        row = {'key': post['key'], 'status': post.get('status'), 'timings': post.get('timings'),
               'mother_id': post['mother']['id'], 'template_id': post['prompt_template']['id'],
               'reserve_template_id': (post.get('reserve_prompt_template') or {}).get('id'),
               'copy_ok': copy.get('ok'), 'plan_ok': plan.get('ok'), 'image_ok': image.get('ok'),
               'task_id': image.get('task_id'), 'image_url': image.get('image_url'),
               'plan_errors': plan.get('errors'), 'image_errors': image.get('error'),
               'plan_model_attempts': plan.get('model_attempts'),
               'previous_image_failures': image.get('previous_failures', image.get('failures'))}
        if args.content:
            row.update(title=copy.get('title'), content=copy.get('content'),
                       image_text_blocks=plan.get('text_blocks'), adapted_prompt=plan.get('adapted_prompt'),
                       ocr_lines=image.get('ocr_lines'), copy_validation=copy.get('validation'))
        if args.image_status and image.get('task_id'):
            sys.path.insert(0, '/app/web/ops/xhs_hermes')
            from run_daily_8x5 import OnlineData, request_json
            online = OnlineData()
            response = request_json(f"{online.backend}/ai-image/tasks/{image['task_id']}", headers=online.auth)
            status = response.get('data', response)
            row['backend_image'] = {key: status.get(key) for key in ('task_id', 'status', 'error', 'created_at', 'updated_at', 'image_url')}
        posts.append(row)
    results.append({'run_id': run_id, 'updated_at': state.get('updated_at'), 'posts': posts})
print(json.dumps(results))
