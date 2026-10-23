import pytest


def sample():
    note = '<note><rest><display-step>B</display-step><display-octave>2</display-octave></rest><duration>24</duration><voice>1</voice><type>quarter</type></note>'
    xml = '<score-partwise><part id="P2">' + ''.join('<measure>' + note.replace('<note>', f'<note id="s-p2-m5-n1-o{i}">') + '</measure>' for i in (5, 11)) + '</part></score-partwise>'
    return xml, {'schema': 1, 'source_score_sha256': 'source', 'operations': [
        {'source_id': 's-p2-m5-n1', 'before_note_xml': note,
         'changes': {'rest/display-step': ['B', 'F'], 'rest/display-octave': ['2', '3']}}]}


def test_rest_display_override_expands_occurrences_without_changing_music():
    from score_sync.engraving_overrides import apply_engraving_overrides
    from xml.etree import ElementTree as ET
    xml, manifest = sample(); actual, report = apply_engraving_overrides(xml, manifest, 'source')
    assert report['applied'] == 2
    root = ET.fromstring(actual)
    for n in root.findall('.//note'):
        assert n.findtext('rest/display-step') == 'F'
        assert n.findtext('rest/display-octave') == '3'
        assert n.findtext('duration') == '24' and n.findtext('voice') == '1'
    assert '<display-step>B</display-step>' in xml


def test_changed_source_note_or_musical_field_cannot_be_overridden():
    from score_sync.engraving_overrides import apply_engraving_overrides
    xml, manifest = sample()
    with pytest.raises(ValueError, match='source'): apply_engraving_overrides(xml, manifest, 'other')
    with pytest.raises(ValueError, match='identity'): apply_engraving_overrides(xml.replace('<duration>24', '<duration>12'), manifest, 'source')
    manifest['operations'][0]['changes']['duration'] = ['24', '12']
    with pytest.raises(ValueError, match='display'): apply_engraving_overrides(xml, manifest, 'source')
