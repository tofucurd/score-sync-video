"""Cover preparation is testable without starting Chromium or an encoder."""
import copy

import pytest

from score_sync import visual


def cover_bundle():
    measures = [dict(index=i, source_index=i, occurrence=1, svg_id=f'm{i}',
                     q=[i - 1, 1], end=[i, 1], x=i * 100, width=100)
                for i in range(1, 7)]
    return {'geometry': {'measures': measures,
                         'staves': [{'id': 'P1:1', 'label': '长笛'},
                                    {'id': 'P2:1', 'label': '中提琴'},
                                    {'id': 'P3:1', 'label': '大提琴'}]},
            'svg': '<svg/>', 'fonts': 'old-fonts', 'sections': [],
            'time_at': lambda q: q, 'curve': lambda t: t,
            'alignment': {}, 'score': {}, 'audio': {}, 'notes': [],
            'work': {'title': '测试组曲'}}


def config():
    return {'work': {'title': '测试组曲', 'number': 12}, 'cover': {
        'layout': 'paper', 'first_measure': 2, 'last_measure': 5,
        'aspect_ranges': {'16x9': [2, 5], '4x3': [2, 4]},
        'staves': ['P1:1', 'P2:1', 'P3:1'], 'sample_q': 1.1,
        'words': {'composer_en': 'TEST COMPOSER', 'composer_zh': '测试作曲家',
                  'performer_zh': '测试指挥', 'ensemble_zh': '测试乐团',
                  'performer_en': 'TEST CONDUCTOR', 'ensemble_en': 'TEST ENSEMBLE'}}}


def test_both_aspects_use_final_template_and_exact_separate_native_ranges(monkeypatch):
    from score_sync.covers import build_cover_specs
    seen = []
    monkeypatch.setattr(visual, 'font_css', lambda corpus: seen.append(corpus) or 'full-fonts')
    monkeypatch.setattr(visual, 'frame_state', lambda b, t: {'seconds': t, 'highlights': {'real-note': {'color': '#C94732', 'weight': 1}}})
    b = cover_bundle(); before = copy.deepcopy({k: v for k, v in b.items() if not callable(v)})
    specs = build_cover_specs(config(), b)
    assert set(specs) == {'16x9', '4x3'}
    assert specs['16x9']['cover_selection']['measures'] == ['m2', 'm3', 'm4', 'm5']
    assert specs['4x3']['cover_selection']['measures'] == ['m2', 'm3', 'm4']
    assert specs['16x9']['width'] == 3840 and specs['4x3']['width'] == 2880
    for spec in specs.values():
        assert spec['cover_layout'] == 'paper'
        assert spec['number'] == 'XII'
        assert spec['fonts'] == 'full-fonts'
        assert spec['frames'][0]['highlights']['real-note']['color'] == '#C94732'
        assert spec['cover_words']['performer_zh'] == '测试指挥'
        assert spec['cover_words']['work_type_en'] == ''
    assert '测试指挥' in seen[0] and 'SYMPHONY' not in seen[0]
    assert before == {k: v for k, v in b.items() if not callable(v)}


def test_bad_cover_staff_or_sample_fails_before_browser(monkeypatch):
    from score_sync.covers import build_cover_specs
    monkeypatch.setattr(visual, 'font_css', lambda _: pytest.fail('invalid input must fail before font work'))
    c = config(); c['cover']['staves'] = ['unknown']
    with pytest.raises(ValueError, match='staff'): build_cover_specs(c, cover_bundle())
    c = config(); c['cover']['sample_q'] = 5.8
    with pytest.raises(ValueError, match='sample_q'): build_cover_specs(c, cover_bundle())


def test_missing_final_cover_words_are_actionable(monkeypatch):
    from score_sync.covers import build_cover_specs
    c = config(); del c['cover']['words']
    with pytest.raises(ValueError, match='cover.words'): build_cover_specs(c, cover_bundle())


def test_build_covers_calls_final_specs_without_project_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, 'bundle', lambda *_: cover_bundle())
    monkeypatch.setattr(visual, 'font_css', lambda _: '')
    monkeypatch.setattr(visual, 'frame_state', lambda b, t: {'seconds': t})
    calls = []
    monkeypatch.setattr(visual, 'run_browser', lambda spec, path, mode: calls.append((spec, path, mode)))
    files = visual.build_covers(config(), tmp_path, tmp_path / 'covers')
    assert len(calls) == 2 and len(files) == 6
    assert all(spec['cover_layout'] == 'paper' and mode == 'cover' for spec, _, mode in calls)


@pytest.mark.parametrize('work_type', ['', 'SUITE'])
def test_optional_work_type_is_passed_and_included_in_font_subset(monkeypatch, work_type):
    from score_sync.covers import build_cover_specs
    seen = []
    monkeypatch.setattr(visual, 'font_css', lambda corpus: seen.append(corpus) or '')
    monkeypatch.setattr(visual, 'frame_state', lambda b, t: {'seconds': t})
    c = config(); c['cover']['words']['work_type_en'] = work_type
    before = copy.deepcopy(c)
    specs = build_cover_specs(c, cover_bundle())
    assert all(spec['cover_words']['work_type_en'] == work_type for spec in specs.values())
    assert work_type in seen[0]
    assert c == before


@pytest.mark.parametrize('work_type', [None, 12, False, []])
def test_optional_work_type_rejects_non_text_before_browser(monkeypatch, work_type):
    from score_sync.covers import build_cover_specs
    monkeypatch.setattr(visual, 'font_css', lambda _: pytest.fail('invalid input must fail before font work'))
    c = config(); c['cover']['words']['work_type_en'] = work_type
    with pytest.raises(ValueError, match='work_type_en'):
        build_cover_specs(c, cover_bundle())


def test_paper_layout_is_default_and_unknown_layout_is_rejected(monkeypatch):
    from score_sync.covers import build_cover_specs
    monkeypatch.setattr(visual, 'font_css', lambda _: '')
    monkeypatch.setattr(visual, 'frame_state', lambda b, t: {'seconds': t})
    c = config(); del c['cover']['layout']
    assert all(s['cover_layout'] == 'paper' for s in build_cover_specs(c, cover_bundle()).values())
    c['cover']['layout'] = 'unknown'
    with pytest.raises(ValueError, match='cover.layout'):
        build_cover_specs(c, cover_bundle())
