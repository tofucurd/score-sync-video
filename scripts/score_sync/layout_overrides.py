"""Apply reviewed text-placement repairs without modifying musical notation.

All changes are bound to an exact source and SVG input/output pair. This avoids
reusing a native ID or a numeric offset after another score or engraver changes
the geometry. Only direct direction text x coordinates are supported.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET


def _digest(svg):
    return hashlib.sha256(svg.encode('utf-8')).hexdigest()


def apply_layout_overrides(svg, manifest, source_sha256):
    """Return (svg, report); retain all unmodified SVG bytes exactly."""
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text())
    if manifest.get('schema') != 1:
        raise ValueError('Unsupported layout override schema')
    if manifest.get('source_score_sha256') != source_sha256:
        raise ValueError('Layout override source score hash mismatch')
    before_hash, after_hash = manifest.get('input_svg_sha256'), manifest.get('output_svg_sha256')
    if not before_hash or not after_hash:
        raise ValueError('Layout override requires input and output SVG hashes')
    actual = _digest(svg)
    if actual == after_hash:
        return svg, {'applied': 0, 'already_applied': True, 'svg_sha256': actual}
    if actual != before_hash:
        raise ValueError('Layout override input SVG hash mismatch; inspect the new engraving instead of reusing old coordinates')
    report = []
    for op in manifest.get('operations', []):
        if op.get('kind') != 'text_x':
            raise ValueError('Unsupported layout override kind; only text_x may change')
        ident = op['id']
        nodes = [n for n in ET.fromstring(svg).iter() if n.get('id') == ident]
        if len(nodes) != 1 or nodes[0].get('class') != 'dir':
            raise ValueError(f'Layout override requires one native direction: {ident}')
        texts = [n for n in nodes[0] if n.tag.split('}')[-1] == 'text']
        if len(texts) != 1 or ' '.join(''.join(texts[0].itertext()).split()) != op.get('text'):
            raise ValueError(f'Layout override text mismatch: {ident}')
        before, after = float(op['before']), float(op['after'])
        if not math.isfinite(before) or not math.isfinite(after) or float(texts[0].get('x', 'nan')) != before:
            raise ValueError(f'Layout override old x coordinate mismatch: {ident}')
        # The exact guarded SVG structure places <text> directly inside <g>.
        pattern = re.compile(r'(<(?:[\w.-]+:)?g\b(?=[^>]*\bid="' + re.escape(ident)
                             + r'")[^>]*>\s*<(?:[\w.-]+:)?text\b[^>]*\bx=")([^\"]+)(")')
        matches = list(pattern.finditer(svg))
        if len(matches) != 1 or float(matches[0][2]) != before:
            raise ValueError(f'Layout override cannot locate exact text attribute: {ident}')
        match = matches[0]
        replacement = str(int(after)) if after.is_integer() else str(after)
        svg = svg[:match.start(2)] + replacement + svg[match.end(2):]
        report.append({**op})
    if _digest(svg) != after_hash:
        raise ValueError('Layout override output SVG hash mismatch')
    return svg, {'applied': len(report), 'already_applied': False,
                 'operations': report, 'svg_sha256': after_hash}
