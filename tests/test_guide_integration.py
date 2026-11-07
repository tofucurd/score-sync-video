"""Optional guide selection must not change ordinary or cover rendering."""
from score_sync import visual


def test_ordinary_and_cover_keep_existing_renderer():
    assert visual.renderer_for_spec({'frames': []}, 'frame').name == 'browser_render.mjs'
    assert visual.renderer_for_spec({'guide_payload': {'id': 'chapter'}}, 'cover').name == 'browser_render.mjs'


def test_any_movement_with_guide_selects_guide_backend():
    assert visual.renderer_for_spec({'guide_payload': {'id': 'other-work'}}, 'frame').name == 'browser_guide.mjs'
    assert visual.renderer_for_spec({'scenes': [{}, {'guide_payload': {'id': 'finale'}}]}, 'video').name == 'browser_guide.mjs'


def test_input_code_never_selects_or_injects_a_renderer():
    assert visual.renderer_for_spec({'guide_overlay_code': 'throw Error(1)'}, 'frame').name == 'browser_render.mjs'
