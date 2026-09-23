"""The local full-pair report must not turn partial image results into success."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))
from complete_editorial_samples import render_samples, TEMPLATES


def test_fixed_acceptance_matrix_has_nine_distinct_visual_sources():
    assert len(TEMPLATES) == len(set(TEMPLATES.values())) == 9
    assert set(TEMPLATES) == {
        (case, mother) for case in ('a10-current', 'b10-current', 'c10-current')
        for mother in (49, 75, 1158)
    }
    for case, mother in TEMPLATES:
        key = f'pair-{case}-m{mother}'
        assert len(f'hermes-2026-09-21-{key}-a2-0123456789ab') <= 64


def test_report_preserves_full_copy_escapes_sources_and_marks_partial_results(tmp_path):
    draft = 'Short copy\n<script>alert(1)</script>'
    row = {
        'case_id': 'a10-current', 'mother': {'id': 49},
        'prompt_template': {'id': 2197, 'image_url': 'https://example.com/source.png'},
        'copy': {'ok': True, 'title': 'A10 <test>', 'content': draft},
        'image_plan': {'ok': True}, 'image': {'ok': False, 'status': 'submitted'},
        'status': 'image_plan_ready', 'quality_note': 'Needs review <again>',
    }
    delivery = {'completed': 0, 'expected': 1}
    run = SimpleNamespace(run_dir=tmp_path, state={'posts': {'sample': row}},
                          cases={'a10-current': {'vehicle_model': 'A10'}},
                          delivery_manifest=lambda: delivery)
    render_samples(run)
    page = (tmp_path / 'comparison.html').read_text()
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert '<script>alert(1)</script>' not in page
    assert '配图尚未通过完整校验' in page
    assert '图文自动校验通过，待审核' not in page
    assert row['copy']['content'] == draft
    assert json.loads((tmp_path / 'sample-results.json').read_text()) == delivery
    row['image'] = {'ok': True, 'local_image': 'images/901/post-01-a1.png'}
    render_samples(run)
    page = (tmp_path / 'comparison.html').read_text()
    assert '图文自动校验通过，待审核' in page
    assert 'href="images/901/post-01-a1.png"' in page
    assert 'Needs review &lt;again&gt;' in page
