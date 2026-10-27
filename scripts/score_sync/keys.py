"""Preserve written per-staff keys in temporary MEI after MusicXML import.

Verovio can promote the first part's mid-score key to a global scoreDef and
omit other parts whose keys did not change. Restore that scope from expanded
MusicXML. Canonical source, note attributes, and performance events are untouched.
"""
from fractions import Fraction as F
from copy import deepcopy
from xml.etree import ElementTree as E

N = '{http://www.music-encoding.org/ns/mei}'


def _source_keys(xml, score):
    root = E.fromstring(xml)
    staffmap = {s['id']: str(i + 1) for i, s in enumerate(score['staves'])}
    snapshots = [{} for _ in score['measures']]
    for part in root.findall('part'):
        pid = part.get('id')
        own = {k.split(':', 1)[1]: n for k, n in staffmap.items() if k.startswith(pid + ':')}
        state = {n: {'fifths': 0, 'visible': True} for n in own.values()}
        divisions = F(1)
        measures = part.findall('measure')
        if len(measures) != len(snapshots):
            raise ValueError('Expanded MusicXML key timeline differs from score route')
        for index, measure in enumerate(measures):
            # Cancellation is a mark on this change, not an instruction to
            # repeat on the next unrelated staff's modulation.
            state = {n: {k: v for k, v in value.items() if k != 'cancelaccid'}
                     for n, value in state.items()}
            cursor = F(0)
            changes = []
            for child in measure:
                if child.tag == 'attributes':
                    divisions = F(child.findtext('divisions', str(divisions)))
                    for key in child.findall('key'):
                        if cursor != 0:
                            raise ValueError(f'Mid-measure key in {pid}, occurrence {index + 1}, q={cursor}: native inline key projection requires review')
                        value = key.findtext('fifths')
                        fifths = int(value) if value is not None else None
                        targets = [own[key.get('number')]] if key.get('number') else list(own.values())
                        signature = {'fifths': fifths, 'visible': key.get('print-object') != 'no'}
                        cancel = key.find('cancel')
                        if cancel is not None:
                            signature['cancelaccid'] = 'after' if cancel.get('location') == 'right' else 'before'
                        if key.get('color') is not None:
                            signature['color'] = key.get('color')
                        changes.append((cursor, targets, signature))
                elif child.tag in ('backup', 'forward'):
                    cursor += (-1 if child.tag == 'backup' else 1) * F(child.findtext('duration')) / divisions
                elif child.tag == 'note' and child.find('chord') is None and child.find('grace') is None:
                    cursor += F(child.findtext('duration', '0')) / divisions
            # A scoreDef describes the bar entry. Unsupported inline changes
            # were rejected above rather than silently moved to that entry.
            changes.sort(key=lambda x: x[0])
            at_start = dict(state)
            for position, targets, value in changes:
                for target in targets:
                    state[target] = value
                    if position == 0:
                        at_start[target] = value
            snapshots[index].update(at_start)
    return snapshots


def restore_staff_keys(xml, mei, score):
    snapshots = _source_keys(xml, score)
    root = E.fromstring(mei)
    parents = {child: parent for parent in root.iter() for child in parent}
    pending = []
    index = 0
    report = []
    native_keys = {number: ('0', True) for number in snapshots[0]} if snapshots else {}
    for node in list(root.iter()):
        if node.tag == N + 'scoreDef':
            pending.append(node)
        elif node.tag == N + 'measure':
            if index >= len(snapshots):
                raise ValueError('MEI key timeline differs from score route')
            expected = snapshots[index]
            for definition in pending:
                global_keys = definition.findall(N + 'keySig')
                if not global_keys:
                    continue
                states = {tuple(sorted(value.items())) for value in expected.values()}
                # Unanimous source keys need no scoped repair. Keep the native
                # cancellation, style, and custom-key rendering intact.
                if len(states) <= 1:
                    continue
                if any(value['fifths'] is None or abs(value['fifths']) > 7 for value in expected.values()):
                    raise ValueError('Mixed nontraditional staff keys need an explicit native key projection')
                before = [k.get('sig') for k in global_keys]
                for key in global_keys:
                    definition.remove(key)
                group = definition.find(N + 'staffGrp')
                if group is None:
                    group = E.SubElement(definition, N + 'staffGrp')
                staffdefs = {s.get('n'): s for s in definition.iter(N + 'staffDef')}
                signatures = {}
                first_staff = min(expected, key=int)
                for number, source in expected.items():
                    fifths, visible = source['fifths'], source['visible']
                    staff = staffdefs.get(number)
                    if staff is None:
                        staff = E.SubElement(group, N + 'staffDef', {'n': number})
                    signature = '0' if fifths == 0 else str(abs(fifths)) + ('s' if fifths > 0 else 'f')
                    keys = staff.findall(N + 'keySig')
                    if len(keys) > 1:
                        raise ValueError('Ambiguous native staff key signatures')
                    if keys:
                        key = keys[0]
                    elif number == first_staff and global_keys[0].get('sig') == signature:
                        key = deepcopy(global_keys[0])
                        key.attrib.pop('{http://www.w3.org/XML/1998/namespace}id', None)
                        staff.append(key)
                    else:
                        key = E.SubElement(staff, N + 'keySig')
                    key.set('sig', signature)
                    if not visible:
                        key.set('visible', 'false')
                    elif key.get('visible') == 'false':
                        key.attrib.pop('visible')
                    for attr in ('cancelaccid', 'color'):
                        if attr in source:
                            key.set(attr, source[attr])
                    signatures[number] = signature
                report.append({'measure': index + 1, 'replaced_global': before, 'staff_keys': signatures})
            # Some local-only modulations produce no scoreDef at all (including
            # a whole-rest bar used to change instrument). Compare effective
            # native state, not merely the definitions the importer chose to emit.
            for definition in pending:
                for key in definition.findall(N + 'keySig'):
                    native_keys = {number: (key.get('sig'), key.get('visible') != 'false')
                                   for number in native_keys}
                for staff in definition.iter(N + 'staffDef'):
                    for key in staff.findall(N + 'keySig'):
                        native_keys[staff.get('n')] = (key.get('sig'), key.get('visible') != 'false')
            missing = {}
            for number, source in expected.items():
                fifths = source['fifths']
                if fifths is None or abs(fifths) > 7:
                    continue  # custom keys are left to the existing importer
                signature = '0' if fifths == 0 else str(abs(fifths)) + ('s' if fifths > 0 else 'f')
                if native_keys.get(number) != (signature, source['visible']):
                    missing[number] = signature
            if missing:
                definition = E.Element(N + 'scoreDef')
                group = E.SubElement(definition, N + 'staffGrp')
                for number, signature in missing.items():
                    source = expected[number]
                    staff = E.SubElement(group, N + 'staffDef', {'n': number})
                    key = E.SubElement(staff, N + 'keySig', {'sig': signature})
                    if not source['visible']:
                        key.set('visible', 'false')
                    for attr in ('cancelaccid', 'color'):
                        if attr in source:
                            key.set(attr, source[attr])
                    native_keys[number] = (signature, source['visible'])
                parent = parents[node]
                parent.insert(list(parent).index(node), definition)
                report.append({'measure': index + 1, 'restored_missing_staff_keys': missing})
            pending.clear()
            index += 1
    if index != len(snapshots):
        raise ValueError('MEI key timeline differs from score route')
    if not report:
        return mei, report
    E.register_namespace('', N[1:-1])
    return E.tostring(root, encoding='unicode'), report
