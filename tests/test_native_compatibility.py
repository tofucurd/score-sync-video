"""Native output must preserve source notation through the importer boundary."""
from xml.etree import ElementTree as ET

import pytest

from score_sync.score import engraving_musicxml

MEI = '{http://www.music-encoding.org/ns/mei}'


def _dynamic_fixture(parentheses='yes', content='<pp/>'):
    return f'''<score-partwise version="4.0">
      <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
      <part id="P1"><measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time>
      <clef><sign>G</sign><line>2</line></clef></attributes>
      <direction placement="below"><direction-type>
      <dynamics parentheses="{parentheses}">{content}</dynamics></direction-type><offset>2</offset></direction>
      <note id="original-note"><pitch><step>C</step><octave>4</octave></pitch>
      <duration>4</duration><voice>1</voice><type>whole</type></note>
      </measure></part></score-partwise>'''


def _native(xml):
    verovio = pytest.importorskip('verovio')
    tk = verovio.toolkit()
    tk.setOptions({'inputFrom': 'musicxml', 'breaks': 'none', 'header': 'none', 'footer': 'none'})
    assert tk.loadData(xml)
    return ET.fromstring(tk.getMEI()), tk.renderToSVG(1)


def test_parenthetical_dynamic_reaches_native_output_without_losing_music_glyph():
    # Break caught: importer silently drops source parentheses=yes.
    source = _dynamic_fixture()
    projected = engraving_musicxml(source)
    mei, svg = _native(projected)
    dynamic = mei.find('.//' + MEI + 'dynam')
    assert ' '.join(''.join(dynamic.itertext()).split()) == '( pp )'
    assert '\ue52b' in svg  # actual SMuFL pianissimo glyph, not ordinary letters pp
    assert ET.fromstring(projected).find('.//dynamics/pp') is not None
    assert ET.fromstring(projected).findtext('.//direction/offset') == '2'
    assert ET.tostring(ET.fromstring(projected).find('.//note')) == ET.tostring(ET.fromstring(source).find('.//note'))
    assert ET.fromstring(source).find('.//dynamics').attrib == {'parentheses': 'yes'}


def test_parenthetical_projection_is_idempotent():
    source = _dynamic_fixture(content='<other-dynamics>(</other-dynamics><pp/><other-dynamics>)</other-dynamics>')
    projected = engraving_musicxml(source)
    assert engraving_musicxml(projected) == projected
    mei, _ = _native(projected)
    assert ' '.join(''.join(mei.find('.//' + MEI + 'dynam').itertext()).split()) == '( pp )'


def test_unparenthesized_dynamic_is_not_wrapped():
    source = _dynamic_fixture(parentheses='no', content='<other-dynamics>sempre</other-dynamics><p/>')
    projected = engraving_musicxml(source)
    assert ET.tostring(ET.fromstring(projected).find('.//dynamics')) == ET.tostring(ET.fromstring(source).find('.//dynamics'))
    mei, _ = _native(projected)
    assert ' '.join(''.join(mei.find('.//' + MEI + 'dynam').itertext()).split()) == 'sempre p'


def _key_fixture():
    root = ET.Element('score-partwise', {'version': '4.0'})
    listing = ET.SubElement(root, 'part-list')
    for part_id in ['P1', 'P2', 'P3']:
        item = ET.SubElement(listing, 'score-part', {'id': part_id})
        ET.SubElement(item, 'part-name').text = part_id
    for part_id, keys in [('P1', [-5, 3, -5]), ('P2', [0, 0, 0]), ('P3', [-3, 5, -3])]:
        part = ET.SubElement(root, 'part', {'id': part_id})
        for index, fifths in enumerate(keys, 1):
            measure = ET.SubElement(part, 'measure', {'number': str(index)})
            attributes = ET.SubElement(measure, 'attributes')
            ET.SubElement(attributes, 'divisions').text = '1'
            ET.SubElement(ET.SubElement(attributes, 'key'), 'fifths').text = str(fifths)
            if index == 1:
                time = ET.SubElement(attributes, 'time')
                ET.SubElement(time, 'beats').text = '4'
                ET.SubElement(time, 'beat-type').text = '4'
                clef = ET.SubElement(attributes, 'clef')
                ET.SubElement(clef, 'sign').text = 'G'
                ET.SubElement(clef, 'line').text = '2'
            measure.append(ET.fromstring('<note><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>'))
    return ET.tostring(root, encoding='unicode')


def _effective_keys(mei, staff_count):
    # Interpret the public MEI scope rules, rather than a repair helper's report.
    keys = {str(i): '0' for i in range(1, staff_count + 1)}
    result = []
    for node in ET.fromstring(mei).iter():
        if node.tag == MEI + 'scoreDef':
            global_key = node.find(MEI + 'keySig')
            if global_key is not None:
                keys = {n: global_key.get('sig') for n in keys}
            for staff in node.iter(MEI + 'staffDef'):
                key = staff.find(MEI + 'keySig')
                if key is not None:
                    keys[staff.get('n')] = key.get('sig')
        elif node.tag == MEI + 'measure':
            result.append([keys[str(i)] for i in range(1, staff_count + 1)])
    return result


@pytest.mark.parametrize('route,want', [
    (None, [['5f', '0', '3f'], ['3s', '0', '5s'], ['5f', '0', '3f']]),
    ([2, 3, 2], [['3s', '0', '5s'], ['5f', '0', '3f'], ['3s', '0', '5s']]),
])
def test_native_global_modulation_preserves_each_parts_written_key(tmp_path, route, want):
    # Break caught: a flute modulation must not add sharps/flats to an unkeyed
    # horn or overwrite another part's independently changing written key.
    import json
    from score_sync.score import prepare_score, parse_musicxml
    pypdf = pytest.importorskip('pypdf')
    pytest.importorskip('verovio')
    source = tmp_path / 'keys.musicxml'
    source.write_text(_key_fixture())
    pdf = tmp_path / 'source.pdf'
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open('wb') as output:
        writer.write(output)
    movement = {'score': str(source), 'pdf': str(pdf)}
    if route is not None:
        movement['source_route'] = route
    before = parse_musicxml(source, route)[0]['events']
    out = tmp_path / 'prepared'
    prepare_score(movement, out)
    assert _effective_keys((out / 'score.mei').read_text(), 3) == want
    actual = json.loads((out / 'score.json').read_text())['events']
    assert [{k: v for k, v in event.items() if k != 'storage_staff'} for event in actual] == before
    assert [event['storage_staff'] for event in actual] == [event['staff'] for event in before]
    assert source.read_text() == _key_fixture()


def _write_and_prepare(tmp_path, xml):
    from score_sync.score import prepare_score
    pypdf = pytest.importorskip('pypdf')
    source = tmp_path / 'source.musicxml'
    source.write_text(xml)
    pdf = tmp_path / 'reference.pdf'
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open('wb') as output:
        writer.write(output)
    out = tmp_path / 'prepared'
    prepare_score({'score': str(source), 'pdf': str(pdf)}, out)
    return out


def test_native_scoped_key_retains_source_cancellation_style(tmp_path):
    # Break caught: restoring sig alone drops the printed natural-sign policy.
    root = ET.fromstring(_key_fixture())
    key = root.find("part[@id='P1']").findall('measure')[1].find('attributes/key')
    cancel = ET.Element('cancel', {'location': 'before-barline'})
    cancel.text = '-5'
    key.insert(0, cancel)
    out = _write_and_prepare(tmp_path, ET.tostring(root, encoding='unicode'))
    mei = ET.parse(out / 'score.mei').getroot()
    own = mei.find(f".//{MEI}staffDef[@n='1']/{MEI}keySig[@sig='3s']")
    assert own is not None
    assert own.get('cancelaccid') == 'before'
    # The unchanged horn must not inherit a different part's cancellation.
    assert all(k.get('cancelaccid') is None for k in mei.findall(f".//{MEI}staffDef[@n='2']/{MEI}keySig"))


def test_correct_native_scoped_key_metadata_survives_repair(tmp_path):
    from score_sync.score import parse_musicxml
    from score_sync.keys import restore_staff_keys
    source = tmp_path / 'source.musicxml'
    source.write_text(_key_fixture())
    score, xml = parse_musicxml(source)
    mei, _ = _native(xml)
    definition = next(d for d in mei.iter(MEI + 'scoreDef')
                      if d.find(MEI + 'keySig') is not None and d.find(MEI + 'keySig').get('sig') == '3s')
    group = ET.SubElement(definition, MEI + 'staffGrp')
    staff = ET.SubElement(group, MEI + 'staffDef', {'n': '1'})
    expected = {'sig': '3s', 'cancelaccid': 'before', 'color': '#112233'}
    ET.SubElement(staff, MEI + 'keySig', expected)
    fixed, _ = restore_staff_keys(xml, ET.tostring(mei, encoding='unicode'), score)
    keys = ET.fromstring(fixed).findall(f".//{MEI}staffDef[@n='1']/{MEI}keySig[@sig='3s']")
    assert len(keys) == 1
    assert keys[0].attrib == expected


def test_mid_measure_key_change_is_not_silently_moved_to_bar_start(tmp_path):
    # This importer cannot yet keep an inline key at its source cursor. Refuse
    # a false score instead of exporting a modulation two beats too early.
    root = ET.fromstring(_key_fixture())
    for part in root.findall('part'):
        for measure in list(part.findall('measure'))[1:]:
            part.remove(measure)
        part.find('measure/attributes/key/fifths').text = '0'
    first = root.find('part/measure')
    first.find('note/duration').text = '2'
    first.find('note/type').text = 'half'
    first.append(ET.fromstring('<attributes><key><fifths>3</fifths></key></attributes>'))
    first.append(ET.fromstring('<note><pitch><step>D</step><octave>5</octave></pitch><duration>2</duration><type>half</type></note>'))
    with pytest.raises(ValueError, match='[Mm]id.measure key'):
        _write_and_prepare(tmp_path, ET.tostring(root, encoding='unicode'))


def test_route_entry_unnumbered_key_replaces_older_numbered_staff_keys(tmp_path):
    from score_sync.score import parse_musicxml
    source = tmp_path / 'grand-staff.musicxml'
    note_pair = '<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type><staff>1</staff></note><backup><duration>4</duration></backup><note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type><staff>2</staff></note>'
    source.write_text('<score-partwise><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list><part id="P1">'
        '<measure number="1"><attributes><divisions>1</divisions><key number="1"><fifths>0</fifths></key><key number="2"><fifths>-1</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>'+note_pair+'</measure>'
        '<measure number="2"><attributes><key><fifths>3</fifths></key></attributes>'+note_pair+'</measure>'
        '<measure number="3">'+note_pair+'</measure></part></score-partwise>')
    model, xml = parse_musicxml(source, [3])
    state = {'1': None, '2': None}
    for key in ET.fromstring(xml).findall('part/measure/attributes/key'):
        for staff in [key.get('number')] if key.get('number') else state:
            state[staff] = int(key.findtext('fifths'))
    assert state == {'1': 3, '2': 3}
    assert [e['pitch'] for e in model['events']] == [72, 48]


@pytest.mark.parametrize('rest_on_change', [False, True])
def test_local_only_key_change_survives_when_first_part_does_not_modulate(tmp_path, rest_on_change):
    # Break caught in the real English-horn entry: a local key on a resting
    # staff disappears completely when the first part supplies no scoreDef.
    from copy import deepcopy
    from score_sync.score import parse_musicxml
    root = ET.fromstring(_key_fixture())
    for part in root.findall('part'):
        measures = part.findall('measure')
        fourth = deepcopy(measures[-1])
        fourth.set('number', '4')
        part.append(fourth)
        for i, measure in enumerate(part.findall('measure')):
            attributes = measure.find('attributes')
            if i == 0:
                attributes.find('key/fifths').text = '0'
            else:
                measure.remove(attributes)
                if part.get('id') == 'P2' and i in (1, 3):
                    measure.insert(0, ET.fromstring('<attributes><key><fifths>' + ('1' if i == 1 else '0') + '</fifths></key></attributes>'))
            if rest_on_change and part.get('id') == 'P2' and i == 1:
                measure.remove(measure.find('note'))
                measure.append(ET.fromstring('<note><rest measure="yes"/><duration>4</duration></note>'))
    xml = ET.tostring(root, encoding='unicode')
    out = _write_and_prepare(tmp_path, xml)
    assert _effective_keys((out / 'score.mei').read_text(), 3) == [
        ['0', '0', '0'], ['0', '1s', '0'], ['0', '1s', '0'], ['0', '0', '0']]
    assert (tmp_path / 'source.musicxml').read_text() == xml
    import json
    before = parse_musicxml(tmp_path / 'source.musicxml')[0]['events']
    actual = json.loads((out / 'score.json').read_text())['events']
    assert [{k: v for k, v in event.items() if k != 'storage_staff'} for event in actual] == before
