import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';

const runtimeURL = process.env.GUIDE_RUNTIME_CANDIDATE
  ? pathToFileURL(process.env.GUIDE_RUNTIME_CANDIDATE)
  : new URL('../scripts/layers/guide_runtime.mjs', import.meta.url);
const installGuide = runtimeURL.pathname.endsWith('.js')
  ? vm.runInNewContext(`(${await fs.readFile(runtimeURL, 'utf8')})`)
  : (await import(runtimeURL.href)).installGuide;
const inkURL = process.env.GUIDE_INK_CANDIDATE
  ? pathToFileURL(process.env.GUIDE_INK_CANDIDATE)
  : new URL('../scripts/layers/guide_ink.mjs', import.meta.url);
const {createMaterialIndex, installMaterialRegions} = await import(inkURL.href);

test('missing guide payload is rejected before accessing native browser geometry', () => {
  assert.throws(() => installGuide({}, {}), /guide_payload.*required/i);
});

test('serialized guide function preserves its payload validation without module closure', () => {
  const injected = vm.runInNewContext(`(${installGuide.toString()})`);
  assert.throws(() => injected({}, {}), /guide_payload.*required/i);
});

test('material regions use native coordinates when no x shift is supplied', () => {
  const index = createMaterialIndex({regions:[{staff:'viola',start_x:100,end_x:200,theme:'answer'}]});
  assert.equal(index.at('viola',150), 'answer');
  assert.equal(index.at('viola',-90), null);
});

test('explicit x shifts, conflicting ownership, and neutral spans are respected', () => {
  const index = createMaterialIndex({x_shift:20,regions:[
    {staff:'viola',start_x:100,end_x:200,theme:'answer'},
    {staff:'viola',start_x:180,end_x:250,theme:'question'},
  ],shared_staff_neutral_intervals:[{staff:'viola',start_x:120,end_x:130}]});
  assert.equal(index.at('viola',90),'answer');
  assert.equal(index.at('viola',105),null);
  assert.equal(index.at('viola',170),null);
  assert.equal(index.at('viola',200),'question');
  assert.equal(index.span('viola',135,155),'answer');
  assert.equal(index.span('viola',90,150),null);
  assert.equal(index.at('missing',90),null);
});

test('omitted material data is an explicit empty index', () => {
  assert.equal(createMaterialIndex().byStaff.size,0);
});

test('material renderer does no browser work when material regions are omitted', () => {
  const injected = vm.runInNewContext(`(${installMaterialRegions.toString()})`);
  const layer = injected({}, {});
  layer.draw({seconds:0, highlights:{}});
  assert.equal(layer.audit().enabled,false);
});


test('label representatives cannot inherit an unspecified project lifetime', () => {
  const payload = {id:'custom',panel_out:20,blocks:[],spans:[{id:'phrase',staff:'viola',ids:[]}],cues:[],palette:{},label_representatives:[{target_id:'phrase'}]};
  assert.throws(() => installGuide({}, {guide_payload:payload}), /label_representatives.*from.*to/i);
});

test('legacy positional label triples are rejected instead of selecting source themes', () => {
  const payload = {id:'custom',panel_out:20,blocks:[],spans:[],cues:[],palette:{},label_representatives:[['answer','viola',8]]};
  assert.throws(() => installGuide({}, {guide_payload:payload}), /label_representatives.*object/i);
});

const {packCompactLabelRows} = await import('../scripts/layers/guide_layout.mjs');

test('compact rows release unused space while preserving immutable slot anchors', () => {
  const rows=[{from:0,to:30,alpha:1,height:104,row_height:40,legacy_row_height:40,padding_before:2,padding_after:2,
    compact_rows:[{height:40,windows:[{from:0,to:10}]},{height:60,windows:[{from:20,to:30}]}]}];
  const before=structuredClone(rows);
  const atStart=packCompactLabelRows(rows,5)[0],atEnd=packCompactLabelRows(rows,25)[0];
  assert.equal(atStart.effective_height,44);
  assert.deepEqual(atStart.slot_offsets,[20,40]);
  assert.equal(atEnd.effective_height,64);
  assert.deepEqual(atEnd.slot_offsets,[0,30]);
  assert.deepEqual(rows,before);
});

test('harmonic footer reservation survives compaction of a visible motif row', () => {
  const row={from:0,to:10,alpha:1,height:84,legacy_row_height:40,padding_before:2,padding_after:2,
    compact_rows:[{height:40,windows:[{from:0,to:10}]}],
    compact_reserved_rows:[{height:40,windows:[{from:0,to:10}]},{height:40,windows:[{from:0,to:10}]}]};
  const result=packCompactLabelRows([row],5)[0];
  assert.equal(result.effective_height,84);
  assert.deepEqual(result.slot_offsets,[20]);
});

test('independent bands share a corridor only while both are present', () => {
  const rows=[{height:60,alpha:1,padding_before:4,compact_peer:1},
    {height:40,alpha:1,padding_before:2,compact_host:0}];
  const shared=packCompactLabelRows(rows,5);
  assert.equal(shared.length,1);
  assert.equal(shared[0].effective_height,60);
  assert.deepEqual(shared[0].aliases.map(a=>({index:a.band.index,offset:a.offset})),[{index:0,offset:4},{index:1,offset:22}]);
  const alone=packCompactLabelRows([{...rows[0],alpha:0},rows[1]],5);
  assert.equal(alone.find(b=>b.index===1).effective_height,40);
  assert.equal(alone.find(b=>b.index===1).aliases.length,1);
});

test('a free-label guest retains the reserved clearance throughout its own lifetime', () => {
  const rows=[{from:0,to:30,alpha:1,height:80,legacy_row_height:40,
    compact_guests:[{from:12,to:18}],
    compact_rows:[{height:30,windows:[{from:0,to:5}]},{height:30,windows:[{from:25,to:30}]}]}];
  assert.equal(packCompactLabelRows(rows,15)[0].effective_height,80);
});

test('serialized compact allocator is cold-frame deterministic', () => {
  const injected=vm.runInNewContext(`(${packCompactLabelRows.toString()})`);
  const rows=[{from:0,to:10,alpha:.5,height:40,legacy_row_height:40,
    compact_rows:[{height:40,windows:[{from:0,to:10}]}]}];
  const first=JSON.stringify(injected(rows,6));
  injected(rows,100);injected(rows,-100);
  assert.equal(JSON.stringify(injected(rows,6)),first);
  assert.equal(injected(rows,6)[0].effective_height,20);
});
