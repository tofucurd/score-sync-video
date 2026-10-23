"""Guarded rest placement in a temporary engraving copy of MusicXML.

Canonical score timing, pitch, voices and note IDs remain untouched. Operations
identify source notes and are expanded to their actual performance occurrences.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET


def _identity(node):
    return (node.tag, sorted((k, v) for k, v in node.attrib.items() if k != 'id'),
            (node.text or '').strip(), [_identity(c) for c in node])


def apply_engraving_overrides(xml, manifest, source_sha256):
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text())
    if manifest.get('schema') != 1 or manifest.get('source_score_sha256') != source_sha256:
        raise ValueError('Engraving override schema or source score hash mismatch')
    root = ET.fromstring(xml); notes = root.findall('.//note'); applied = []
    for op in manifest.get('operations', []):
        changes = op['changes']
        if not changes or set(changes) - {'rest/display-step', 'rest/display-octave'}:
            raise ValueError('Only rest display-step/display-octave hints may be overridden')
        pattern = re.compile(re.escape(op['source_id']) + r'-o\d+$')
        matches = [n for n in notes if pattern.fullmatch(n.get('id', ''))]
        if not matches:
            raise ValueError('Engraving source note absent from performance route: ' + op['source_id'])
        expected = ET.fromstring(op['before_note_xml'])
        for n in matches:
            if n.find('rest') is None or n.find('pitch') is not None or _identity(n) != _identity(expected):
                raise ValueError('Engraving rest identity changed: ' + n.get('id', ''))
            for path, values in changes.items():
                field = n.find(path)
                if len(values) != 2 or field is None or field.text != values[0]:
                    raise ValueError('Engraving rest display before-value changed: ' + path)
                if path.endswith('display-step') and values[1] not in tuple('ABCDEFG'):
                    raise ValueError('Invalid rest display-step')
                if path.endswith('display-octave') and not re.fullmatch(r'[0-9]', values[1]):
                    raise ValueError('Invalid rest display-octave')
                field.text = values[1]
            applied.append(n.get('id'))
    return ET.tostring(root, encoding='unicode'), {'source_score_sha256': source_sha256,
            'applied': len(applied), 'rest_display_overrides': applied,
            'scope': 'temporary engraving copy; canonical notes and event timing unchanged'}
