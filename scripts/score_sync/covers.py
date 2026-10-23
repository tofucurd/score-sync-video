"""Prepare both approved cover layouts from the current native score.

This module does not launch a browser. The final cover uses the same whole-score
SVG, geometry, note identities and highlight state as the video; no independent
re-engraving or project-specific helper is involved.
"""
from __future__ import annotations

import json
import math

ASPECTS = {'16x9': (3840, 2160), '4x3': (2880, 2160)}
WORD_KEYS = ('composer_en', 'composer_zh', 'performer_zh', 'ensemble_zh',
             'performer_en', 'ensemble_en')


def build_cover_specs(project_cfg, bundle):
    """Return {aspect: browser_spec} without drawing or modifying the bundle."""
    from . import visual

    selection = project_cfg.get('cover', {})
    layout = selection.get('layout', 'paper')
    if layout != 'paper':
        raise ValueError('cover.layout must be paper (flowing-score cover)')
    words = selection.get('words')
    if not isinstance(words, dict) or any(not isinstance(words.get(k), str) for k in WORD_KEYS):
        raise ValueError('Set cover.words: ' + ', '.join(WORD_KEYS) + '; use an empty string only when the credit is unavailable')
    if not isinstance(words.get('work_type_en', ''), str):
        raise ValueError('cover.words.work_type_en must be a string; omit it or use an empty string to hide the work type')
    words = {**words, 'work_type_en': words.get('work_type_en', '')}
    staves = selection.get('staves')
    known = {s['id'] for s in bundle['geometry']['staves']}
    if not isinstance(staves, list) or not staves or len(set(staves)) != len(staves) or any(s not in known for s in staves):
        raise ValueError('cover.staves must contain distinct native staff IDs from geometry.json')
    occurrence = selection.get('occurrence', 1)
    if not isinstance(occurrence, int) or occurrence < 1:
        raise ValueError('cover.occurrence must be a positive performance-route occurrence')
    phrases = {}
    for tag in ASPECTS:
        limits = selection.get('aspect_ranges', {}).get(tag,
                    [selection.get('first_measure', 1), selection.get('last_measure', 4)])
        if len(limits) != 2 or any(not isinstance(n, int) for n in limits) or limits[0] < 1 or limits[1] < limits[0]:
            raise ValueError(f'cover.aspect_ranges.{tag} must be [first_source_measure, last_source_measure]')
        first, last = limits
        phrase = [m for m in bundle['geometry']['measures']
                  if first <= m['source_index'] <= last and m.get('occurrence', 1) == occurrence]
        if [m['source_index'] for m in phrase] != list(range(first, last + 1)):
            raise ValueError(f'Cover excerpt {tag} is missing source measures in occurrence {occurrence}')
        if any(b['index'] != a['index'] + 1 for a, b in zip(phrase, phrase[1:])):
            raise ValueError(f'Cover excerpt {tag} must be contiguous in the reviewed performance route')
        phrases[tag] = phrase
    sample_q = visual.q(selection.get('sample_q', visual.q(phrases['16x9'][0]['q']) + .5))
    if not math.isfinite(sample_q) or any(not visual.q(p[0]['q']) <= sample_q < visual.q(p[-1]['end']) for p in phrases.values()):
        raise ValueError('cover.sample_q must lie inside both aspect excerpts')
    state = visual.frame_state(bundle, bundle['time_at'](sample_q))
    # Include the actual Chinese/Latin credits before subsetting; otherwise the
    # browser can silently draw missing credits with an unrelated system font.
    corpus = (json.dumps(project_cfg, ensure_ascii=False)
              + json.dumps(bundle['geometry']['staves'], ensure_ascii=False)
              + json.dumps(bundle['sections'], ensure_ascii=False) + bundle['svg']
              + json.dumps(words, ensure_ascii=False) + '曲谱同步'
              + visual.roman(project_cfg.get('work', {}).get('number')))
    fonts = visual.font_css(corpus)
    base = {k: v for k, v in bundle.items()
            if k not in ('curve', 'time_at', 'score', 'alignment', 'audio', 'notes')}
    specs = {}
    for tag, (width, height) in ASPECTS.items():
        specs[tag] = {**base, 'fonts': fonts, 'frames': [state], 'width': width,
                      'height': height, 'number': visual.roman(project_cfg.get('work', {}).get('number')),
                      'cover_layout': 'paper', 'cover_words': dict(words),
                      'cover_selection': {'measures': [m['svg_id'] for m in phrases[tag]],
                                          'staves': list(staves)}}
    return specs
