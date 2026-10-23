import hashlib

import pytest


def digest(text): return hashlib.sha256(text.encode()).hexdigest()


def data():
    before = '<svg xmlns="http://www.w3.org/2000/svg"><g id="direction" class="dir"><text x="100" y="300"><tspan>zu 2</tspan></text></g><g id="note"/></svg>'
    after = before.replace('x="100"', 'x="850"')
    manifest = {'schema': 1, 'source_score_sha256': 'score-sha',
                'input_svg_sha256': digest(before), 'output_svg_sha256': digest(after),
                'operations': [{'id': 'direction', 'kind': 'text_x', 'before': 100,
                                'after': 850, 'text': 'zu 2', 'reason': 'Separate overlapping directions'}]}
    return before, after, manifest


def test_layout_override_changes_only_exact_attribute_and_is_idempotent():
    from score_sync.layout_overrides import apply_layout_overrides
    before, after, manifest = data()
    actual, report = apply_layout_overrides(before, manifest, 'score-sha')
    assert actual == after and report['applied'] == 1
    actual, report = apply_layout_overrides(after, manifest, 'score-sha')
    assert actual == after and report['already_applied'] is True


def test_layout_override_rejects_changed_source_svg_or_wording():
    from score_sync.layout_overrides import apply_layout_overrides
    before, _, manifest = data()
    with pytest.raises(ValueError, match='source'): apply_layout_overrides(before, manifest, 'other-score')
    with pytest.raises(ValueError, match='SVG'): apply_layout_overrides(before + ' ', manifest, 'score-sha')
    manifest['operations'][0]['text'] = 'wrong word'
    with pytest.raises(ValueError, match='text'): apply_layout_overrides(before, manifest, 'score-sha')


def test_layout_override_rejects_non_text_and_wrong_output_digest():
    from score_sync.layout_overrides import apply_layout_overrides
    before, _, manifest = data()
    manifest['operations'][0]['kind'] = 'note_x'
    with pytest.raises(ValueError, match='kind'): apply_layout_overrides(before, manifest, 'score-sha')
    before, _, manifest = data(); manifest['output_svg_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='output'): apply_layout_overrides(before, manifest, 'score-sha')
