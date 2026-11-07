"""Guide compilation exercises source fidelity, semantic color and global routing."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)
        self.geometry = {
            'staves': [{'id': 'strings', 'y': 100, 'svg_ids': ['staff-one']}],
            'notes': [{'id': 'n1', 'staff': 'strings', 'svg_id': 'note-one', 'x': 100},
                      {'id': 'n2', 'staff': 'strings', 'svg_id': 'note-two', 'x': 200}],
            'measures': [{'index': 1, 'q': 0, 'end': 20, 'x': 0, 'width': 400}],
        }
        sources = {
            'score': {'events': [{'id': 'n1', 'staff': 'strings', 'q': 4, 'duration': 2},
                                 {'id': 'n2', 'staff': 'strings', 'q': 6, 'duration': 2}]},
            'geometry': self.geometry,
            'alignment': {'sample_rate': 100, 'samples': 2000, 'points': [[0, 0], [2000, 20]], 'notes': []},
        }
        bindings = {}
        for name, value in sources.items():
            path = self.d / (name + '.json')
            path.write_text(json.dumps(value))
            bindings[name] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        self.source = {
            'id': 'new-orchestral-work', 'source_hashes': bindings,
            'units': [{'id': 'u1', 'text': '主题甲持续发展。', 'provenance': {'document': 'guide.pdf', 'page': 1}}],
            'palette': {'subject': '#345678'}, 'labels': {'subject': '主题甲'},
            'blocks': [{'id': 'paragraph', 'unit_id': 'u1', 'display_ranges': [[0, 8]],
                        'theme': 'subject', 'keywords': ['主题甲']}],
            'stages': [{'id': 'opening', 'from': 0, 'to': 20, 'blocks': ['paragraph']}],
            'spans': [{'id': 'phrase', 'staff': 'strings', 'ids': ['n1', 'n2'], 'theme': 'subject',
                       'q0': 4, 'q1': 8, 'label': '主题甲'}],
            'cues': [{'at': 1, 'block': 'paragraph', 'keyword': '主题甲', 'target_id': 'phrase'}],
        }

    def api(self):
        try:
            return importlib.import_module('score_sync.guide')
        except ImportError:
            self.fail('The public source-bound guide compiler and loader are missing')

    def compile(self, source=None):
        return self.api().compile_guide(source or self.source, self.d)

    def test_cli_compiles_source_ranges_and_real_connector_windows(self):
        path = self.d / 'input.json'
        path.write_text(json.dumps(self.source, ensure_ascii=False))
        run = subprocess.run([sys.executable, str(ROOT / 'scripts/compile_guide.py'),
                              '--movement-dir', str(self.d), '--input', str(path)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads((self.d / 'guide.json').read_text())
        self.assertEqual(data['blocks'][0]['text'], '主题甲持续发展。')
        self.assertEqual(data['blocks'][0]['index'], 0)
        self.assertEqual(data['coverage']['uncovered'], [])
        w = data['connection_windows'][0]
        self.assertEqual((w['target_id'], w['block'], w['page_id']), ('phrase', 0, 'opening'))
        self.assertLess(w['full_at'], 4)
        self.assertGreaterEqual(w['hold_until'], 4)

    def test_uncovered_or_rewritten_source_fails_without_touching_output(self):
        for change in ['missing', 'rewritten']:
            src = copy.deepcopy(self.source)
            if change == 'missing':
                src['blocks'][0]['display_ranges'] = [[0, 3]]
            else:
                src['blocks'][0]['text'] = '凭空编写的摘要'
            with self.assertRaisesRegex(ValueError, 'coverage|source text|display'):
                self.compile(src)
            self.assertFalse((self.d / 'guide.json').exists())

    def test_errata_preserve_original_ranges_and_repeat_provenance(self):
        src = copy.deepcopy(self.source)
        src['units'][0]['errata'] = [{'start': 3, 'end': 5, 'original': '持续',
                                      'replacement': '继续', 'reason': 'PDF 勘误表第 1 项'}]
        src['blocks'].append({**copy.deepcopy(src['blocks'][0]), 'id': 'repeat'})
        src['stages'][0]['blocks'].append('repeat')
        payload = self.compile(src)
        self.assertEqual(payload['blocks'][0]['text'], '主题甲继续发展。')
        self.assertEqual(payload['coverage']['units']['u1']['display_occurrences'], 2)
        self.assertEqual(payload['blocks'][1]['provenance']['page'], 1)

    def test_keyword_coloring_applies_to_every_occurrence_and_rejects_conflicts(self):
        src = copy.deepcopy(self.source)
        src['blocks'][0].pop('keywords')
        src['blocks'][0].pop('theme')
        payload = self.compile(src)
        self.assertEqual(payload['blocks'][0]['keyword_themes']['主题甲'], 'subject')
        self.assertIn('主题甲', payload['blocks'][0]['keywords'])
        src['blocks'][0]['keyword_colors'] = {'主题甲': '#000000'}
        with self.assertRaisesRegex(ValueError, 'color|colour'):
            self.compile(src)

    def test_stale_bindings_missing_targets_and_wrong_indices_fail(self):
        mutations = [lambda s: s['source_hashes']['score'].update(sha256='0' * 64),
                     lambda s: s['spans'][0].update(ids=['missing']),
                     lambda s: s['blocks'][0].update(index=3),
                     lambda s: s['cues'][0].update(at=21)]
        for mutate in mutations:
            src = copy.deepcopy(self.source)
            mutate(src)
            with self.assertRaises(ValueError):
                self.compile(src)

    def test_load_returns_font_text_material_assignments_and_empty_optional_layers(self):
        payload = self.compile()
        (self.d / 'guide.json').write_text(json.dumps(payload))
        fields, text = self.api().load_guide(self.d, self.geometry)
        self.assertIn('主题甲持续发展。', text)
        self.assertEqual(fields['material_regions']['assignments'], {'n1': 'subject', 'n2': 'subject'})
        self.assertEqual(fields['guide_payload']['native_comparisons'], [])
        src = copy.deepcopy(self.source)
        src['cues'] = []
        src['label_representatives'] = []
        empty = self.compile(src)
        self.assertEqual(empty['connection_windows'], [])
        self.assertEqual(empty['connection_capacity']['maximum_points'], 0)

    def test_native_comparison_checks_svg_binding_and_preserves_paired_notes(self):
        src = copy.deepcopy(self.source)
        comparison = {'id': 'quotation', 'source_unit_id': 'u1', 'from': 2, 'to': 10,
                      'anchor_staff': 'strings', 'theme': 'subject', 'height': 100,
                      'source_hashes': src['source_hashes'],
                      'source_note_ids': ['n1'],
                      'svg': '<svg xmlns="http://www.w3.org/2000/svg"><g id="ref-one"><path d="M0 0L5 5"/></g></svg>',
                      'pairs': [{'ref_id': 'ref-one', 'score_id': 'n1'}]}
        src['native_comparisons'] = [comparison]
        payload = self.compile(src)
        self.assertEqual(payload['native_comparisons'][0]['pairs'][0]['score_id'], 'n1')
        self.assertEqual(payload['native_comparisons'][0]['correspondences'][0]['ref_id'], 'ref-one')
        for bad in ['<script>alert(1)</script>', '<image href="https://example.org/x"/>',
                    '<use href="file:///tmp/source.svg#x"/>', '<path onload="x()"/>',
                    '<style>path{fill:url(https://example.org/a)}</style>']:
            changed = copy.deepcopy(src)
            changed['native_comparisons'][0]['svg'] = '<svg xmlns="http://www.w3.org/2000/svg">' + bad + '</svg>'
            with self.assertRaisesRegex(ValueError, 'SVG|native|external'):
                self.compile(changed)

    def test_reading_cue_without_target_needs_no_fake_connector(self):
        src = copy.deepcopy(self.source)
        src['cues'] = [{'at': 0, 'block': 'paragraph'}]
        self.assertEqual(self.compile(src)['connection_windows'], [])

    def test_display_probe_extends_label_and_line_together_and_stops_at_missing_frame(self):
        src = copy.deepcopy(self.source)
        src['label_representatives'] = [{'target_id': 'phrase', 'from': 3, 'to': 8.55}]
        src['display_lifetimes'] = {
            'fps': 20, 'source_hashes': src['source_hashes'],
            'requests': [{'target_id': 'phrase', 'from': 2, 'to': 11}],
            'samples': [{'seconds': i/20, 'target_id': 'phrase', 'label_safe': True,
                         'route_safe': True, 'source_visible': True}
                        for i in range(36, 220)],
        }
        payload = self.compile(src)
        ref, w = payload['label_representatives'][0], payload['connection_windows'][0]
        self.assertEqual(ref['display_from'], 2)
        self.assertEqual(w['from'], 2)
        self.assertEqual(ref['display_to'], 11)
        self.assertEqual(w['to'], 11)
        self.assertEqual(w['routing_layout_from'], 2.55)
        self.assertEqual(w['routing_layout_to'], 8.55)
        # The first absent sample is a stopping boundary, never proof of safety.
        src['display_lifetimes']['samples'] = [s for s in src['display_lifetimes']['samples'] if s['seconds'] < 10]
        limited = self.compile(src)
        self.assertEqual(limited['connection_windows'][0]['to'], 10)
        self.assertEqual(limited['label_representatives'][0]['display_to'], 10)
        # An unsafe early prefix retains both original entrances.
        src['display_lifetimes']['samples'][5]['route_safe'] = False
        rejected = self.compile(src)
        self.assertEqual(rejected['connection_windows'][0]['from'], 2.55)
        self.assertEqual(rejected['label_representatives'][0].get('display_from', 3), 3)

    def test_global_reference_samples_and_components_survive_chunk_selection(self):
        connections = importlib.import_module('score_sync.guide_connections')
        windows = [dict(index=0, **{'from': 2}, full_at=2.5, hold_until=8, to=8.5),
                   dict(index=1, **{'from': 8}, full_at=8.2, hold_until=12, to=12.5),
                   dict(index=2, **{'from': 12}, full_at=12.2, hold_until=16, to=16.5)]
        payload = {'connection_windows': windows}
        connections.attach_routing_references(payload, lambda t: {'seconds': t})
        self.assertTrue(any(8 <= r['seconds'] < 8.5 and r['window_indices'] == [0, 1]
                            for r in payload['routing_reference_frames']))
        selected = connections.retain_routing_components(copy.deepcopy(payload), 3, 4)
        self.assertEqual([w['index'] for w in selected['connection_windows']], [0, 1, 2])
        self.assertEqual(selected['routing_reference_frames'], payload['routing_reference_frames'])

    def test_capacity_is_configurable_counts_ramps_and_handles_empty_windows(self):
        connections = importlib.import_module('score_sync.guide_connections')
        bounded, report = connections.bound_connections([], policy={'maximum_points': 1, 'maximum_branches': 1})
        self.assertEqual((bounded, report['maximum_points']), ([], 0))
        def window(i, onset):
            return dict(index=i, page_id='page', block=i, keyword='word', theme='arbitrary-name',
                        target_id=str(i), continuation=False, **{'from': onset-1.45},
                        full_at=onset-.8, hold_until=onset+5, to=onset+5.35,
                        source_start=onset, source_end=onset+5)
        bounded, report = connections.bound_connections([window(0, 4), window(1, 8)],
                                                         policy={'maximum_points': 1, 'maximum_branches': 1})
        self.assertLessEqual(bounded[0]['to'], bounded[1]['from'])
        self.assertEqual(report['maximum_branches'], 1)


if __name__ == '__main__':
    unittest.main()
