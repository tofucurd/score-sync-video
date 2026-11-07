/** Native SVG guide compositor. All helpers remain inside installGuide so the
 * renderer can inject installGuide.toString() into an owned browser context.
 * Source text, timing, material identities and comparison notation come only
 * from S.guide_payload; no musical work or scene ID selects behavior.
 */
export function installGuide(actor,S){
 if(!S?.guide_payload||typeof S.guide_payload!=='object'||Array.isArray(S.guide_payload))throw Error('guide_payload is required for the guide renderer');
 const payload=S.guide_payload;
 for(const key of ['blocks','spans','cues','label_representatives','label_bands','label_space_decisions','native_comparisons','tempo_labels']){
  if(payload[key]===undefined)payload[key]=[];
  if(!Array.isArray(payload[key]))throw Error('guide_payload.'+key+' must be an array');
 }
 for(const key of ['palette','labels']){
  if(payload[key]===undefined)payload[key]={};
  if(!payload[key]||typeof payload[key]!=='object'||Array.isArray(payload[key]))throw Error('guide_payload.'+key+' must be an object');
 }
 payload.id??='guide';payload.panel_in??=0;
 if(!Number.isFinite(payload.panel_in)||!Number.isFinite(payload.panel_out)||payload.panel_out<=payload.panel_in)throw Error('guide_payload requires finite panel_in < panel_out');
 const validLife=(entry,path)=>{if(!Number.isFinite(entry.from)||!Number.isFinite(entry.to)||entry.to<=entry.from)throw Error(path+' requires finite from < to');};
 const spanIds=new Set(payload.spans.map(s=>s.id));
 for(const [i,ref]of payload.label_representatives.entries()){
  const path='guide_payload.label_representatives['+i+']';
  if(!ref||typeof ref!=='object'||Array.isArray(ref))throw Error(path+' must be an object with target_id, from and to');
  validLife(ref,path);
  if(!spanIds.has(ref.target_id))throw Error(path+' has unknown target_id: '+ref.target_id);
  if(ref.display_from!==undefined||ref.display_to!==undefined)validLife({from:ref.display_from??ref.from,to:ref.display_to??ref.to},path+' display lifetime');
  if(ref.preferred_side!==undefined&&!['above','below'].includes(ref.preferred_side))throw Error(path+' preferred_side must be above or below');
 }
 for(const [i,stage]of (payload.reading_stages||[]).entries()){
  validLife(stage,'guide_payload.reading_stages['+i+']');
  if(!Array.isArray(stage.block_indices)||stage.block_indices.some(index=>!Number.isInteger(index)||!payload.blocks[index]))throw Error('reading_stages contains an unknown block index');
 }
 for(const [i,entry]of payload.tempo_labels.entries()){
  validLife(entry,'guide_payload.tempo_labels['+i+']');
  if(typeof entry.text!=='string')throw Error('tempo_labels text must be a string');
 }
 for(const c of payload.native_comparisons){
  validLife(c,'native_comparisons '+c.id);
  if(typeof c.svg!=='string'||!c.svg.trim())throw Error('native_comparisons '+c.id+' requires native SVG');
  if(c.native_controls)throw Error('native_comparisons.native_controls is not supported; supply already prepared native SVG');
 }
 if(!S.geometry||!['notes','staves','measures'].every(key=>Array.isArray(S.geometry[key])))throw Error('Guide renderer requires geometry notes, staves and measures arrays');
 if(!actor?.root||!actor.scoreClip?.firstElementChild||!actor.readingLine||!actor.labels||!Array.isArray(actor.verticalComponents))throw Error('Guide renderer requires native actor root, scoreClip, readingLine, labels and verticalComponents');
// Solve a single row inside the original source phrases. Positions are frozen
// before the first frame, never clamped/reflowed against the moving blue cursor.
function planPackedSourceRow(items,pairScale){
 const ordered=[...items].sort((a,b)=>a.anchor.native_x-b.anchor.native_x),edges=[];
 let floor=.22;
 for(let i=0;i<ordered.length;i++)for(let j=i+1;j<ordered.length;j++){
  const a=ordered[i],b=ordered[j],wa=a.displayWindow||a.window,wb=b.displayWindow||b.window,from=Math.max(wa[0],wb[0])-.2,to=Math.min(wa[1],wb[1])+.2;
  if(from>=to)continue;
  const scale=pairScale(from,to);floor=Math.min(floor,scale);
  edges.push({i,j,distance:((a.anchor.screen_dx||0)+a.width+a.paddingX-(b.anchor.screen_dx||0)+b.paddingX+Math.max(a.size,b.size)*.32)/scale});
 }
 const bounds=ordered.map(item=>{
  const x=item.anchor.native_x,d=item.bandFitDetail,s=d?.source;
  if(!s||item.bandNativeOffset||item.bandFit!=='fixed-source-barline-gap')return{lo:x,hi:x};
  // At most one em and one quarter of the exact phrase: nearby attribution
  // survives even for short motifs. Existing barline clearance is retained.
  const travel=Math.min(item.size/floor,(s.r-s.x)/4);let lo=Math.max(s.x,x-travel),hi=Math.min(s.r,x+travel);
  if(d.columns){
   const margin=(item.paddingX+item.size*d.clearanceEm+2)/floor,half=item.width/floor/2;
   const gap=d.gaps.find(([l,h])=>x>=l+margin+half-.001&&x<=h-margin-half+.001);
   if(!gap)return{lo:x,hi:x};
   lo=Math.max(lo,gap[0]+margin+half);hi=Math.min(hi,gap[1]-margin-half);
  }
  return{lo,hi};
 });
 for(let i=0;i<ordered.length;i++)for(const e of edges.filter(e=>e.i===i))bounds[e.j].lo=Math.max(bounds[e.j].lo,bounds[i].lo+e.distance);
 for(let j=ordered.length-1;j>=0;j--)for(const e of edges.filter(e=>e.j===j))bounds[e.i].hi=Math.min(bounds[e.i].hi,bounds[j].hi-e.distance);
 if(bounds.some(b=>b.lo>b.hi+.000001))return null;
 const positions=[];
 for(let i=0;i<ordered.length;i++){
  const lo=Math.max(bounds[i].lo,...edges.filter(e=>e.j===i).map(e=>positions[e.i]+e.distance));
  if(lo>bounds[i].hi+.000001)return null;
  positions[i]=Math.max(lo,Math.min(bounds[i].hi,ordered[i].anchor.native_x));
 }
 return ordered.map((item,i)=>({item,x:positions[i],previous_x:item.anchor.native_x,scale_floor:floor}));
}

// Final source anchors are compiled first; immutable production is not edited.
function installCompactLabelPolicy(actor,S,P,labels,layoutCache){
 const bands=P.label_bands||[],components=actor.verticalComponents;
 const life=i=>i.displayWindow||i.window;
 const members=b=>labels.filter(i=>i.bandStaff===b.staff&&(i.bandSide||'below')===(b.side||'below')&&i.window[0]<b.to+.001&&i.window[1]>b.from-.001);
 const linked=new Map();
 bands.forEach((b,index)=>{
  if(b.purpose)return;
  const items=members(b);if(!items.length)return;
  linked.set(index,items);b.legacy_height=b.height;b.legacy_row_height=b.row_height;
  const count=Math.max(...items.map(i=>i.bandSlot))+1;
  b.compact_rows=Array.from({length:count},(_,slot)=>{
   const row=items.filter(i=>i.bandSlot===slot);
   // Keep the previously verified glyph/barline clearance. Savings come from
   // real occupancy and corridor sharing, not shaving clearance off both edges.
   return{height:b.legacy_row_height,windows:row.map(i=>({from:life(i)[0],to:life(i)[1],source:i.representative_id}))};
  });
  b.row_height=Math.max(...b.compact_rows.map(r=>r.height));
  b.height=b.compact_rows.reduce((n,r)=>n+r.height,0)+(b.padding_before||0)+(b.padding_after||0);
 });
 const owners=new Map(components.flatMap((ids,n)=>ids.map(id=>[id,n]))),pairs=[],rejected=[];
 const extents=new Map(S.geometry.staves.map(s=>[s.id,{top:s.y-s.height/2-450,bottom:s.y+s.height/2+450}]));
 for(const n of S.geometry.notes){const e=extents.get(n.staff);if(e&&Number.isFinite(n.y)){e.top=Math.min(e.top,n.y-750);e.bottom=Math.max(e.bottom,n.y+750);}}
 // Bound all costs on monotone transition pieces, including final extensions.
 // Component maxima and padding maxima need not coincide: using both is a
 // conservative lower scale bound, without pretending all distant passages
 // happen simultaneously. Quarter-second subdivision only tightens the bound.
 const quint=u=>{u=Math.max(0,Math.min(1,u));return u*u*u*(10+u*(-15+6*u));},cubic=u=>{u=Math.max(0,Math.min(1,u));return u*u*(3-2*u);};
 const cohortByStaff=new Map(S.geometry.staves.map(st=>[st.id,(S.cohorts||[]).filter(c=>c.staves.includes(st.id))])),weightCache=new Map(),scaleCache=new Map();
 const weightAt=t=>{if(!weightCache.has(t))weightCache.set(t,new Map([...cohortByStaff].map(([id,cs])=>[id,Math.max(0,...cs.map(c=>quint(t<c.start?(t-c.start+4)/4:t>c.end?(c.end+4-t)/4:1)))])));return weightCache.get(t);};
 const comparisons=(P.native_comparisons||[]).filter(c=>c.placement!=='sidebar');
 // Rebuild the uncompressed reference from FINAL extended band lifetimes.
 // Earlier anchor-cache layouts precede extensions and are not authoritative
 // for free-label occupancy near a retained tail.
 const referenceCache=new Map();
 const referenceAt=t=>{
  if(referenceCache.has(t))return referenceCache.get(t);
  const weights=weightAt(t),reserved=components.map(ids=>Math.sqrt(Math.max(...ids.map(id=>weights.get(id)||0)))),ranges=components.map(ids=>({top:Math.min(...ids.map(id=>extents.get(id).top)),bottom:Math.max(...ids.map(id=>extents.get(id).bottom))}));
  const rows=bands.map((b,index)=>({...b,index,alpha:quint(Math.min((t-b.from+4)/4,(b.to+4-t)/4))*Math.sqrt(weights.get(b.staff)||0)}));
  const refs=comparisons.map(c=>({c,alpha:cubic((t-c.from)/.6)*(1-cubic((t-c.to)/.35))*(weights.get(c.anchor_staff)||0),height:c.native_height??c.height/.06}));
  const total=ranges.reduce((n,r,i)=>n+(r.bottom-r.top+240)*reserved[i],0),padding=rows.reduce((n,b)=>n+(b.legacy_height??b.height)*b.alpha,0)+refs.reduce((n,r)=>n+((r.c.row_padding_px??85)+(r.c.fixed_display_scale?r.height*r.c.fixed_display_scale:0))*r.alpha,0),native=refs.reduce((n,r)=>n+(r.c.fixed_display_scale?0:r.height)*r.alpha,0),scale=Math.min(.22,Math.max(800,1640-padding)/Math.max(1,total+native)),dy=new Map(),slots=new Map();let cursor=0;
  components.forEach((ids,i)=>{
   const insert=side=>{for(const b of rows.filter(b=>owners.get(b.staff)===i&&(b.side||'below')===side&&b.alpha>0)){const height=(b.legacy_height??b.height)*b.alpha;slots.set(b.index,{y:cursor*scale,height});cursor+=height/scale;}};
   insert('above');const r=ranges[i],h=r.bottom-r.top,center=cursor+h*reserved[i]/2;for(const id of ids)dy.set(id,center-(r.top+r.bottom)/2);cursor+=(h+240)*reserved[i];insert('below');
   for(const v of refs.filter(v=>owners.get(v.c.anchor_staff)===i))cursor+=(v.height*(v.c.fixed_display_scale||scale)+(v.c.row_padding_px??85))*v.alpha/scale;
  });
  const result={t,weights,scale,dy,slots};referenceCache.set(t,result);return result;
 };
 const guests=[];
 for(const item of labels.filter(i=>i.anchor&&!i.bandStaff)){
  const a=item.anchor,[from,to]=life(item),occupied=new Set(),times=[from-.2,from,to,to+.2];
  for(let t=Math.ceil((from-.2)*4)/4;t<to+.2;t+=.25)times.push(t);
  for(const t of times){
   const l=referenceAt(t);if((l.weights.get(item.row.s.staff)||0)<.01)continue;
   const y=(a.native_y+(l.dy.get(item.row.s.staff)||0))*l.scale+(a.screen_dy||0),top=y+item.top-item.size*.3,bottom=y+item.bottom+item.size*.3;
   for(const [index,slot] of l.slots){const b=bands[index];if(b.compact_rows&&top<slot.y+slot.height&&bottom>slot.y)occupied.add(index);}
  }
  for(const index of occupied){const entry={from,to,source:item.representative_id};(bands[index].compact_guests??=[]).push(entry);guests.push({band:index,...entry});}
 }
 const conservativeScale=(lo,hi)=>{
  const key=lo+'|'+hi;if(scaleCache.has(key))return scaleCache.get(key);
  const edges=[lo,hi,...(S.cohorts||[]).flatMap(c=>[c.start-4,c.start,c.end,c.end+4]),...bands.flatMap(b=>[b.from-4,b.from,b.to,b.to+4]),...comparisons.flatMap(c=>[c.from,c.from+.6,c.to,c.to+.35])].filter(t=>t>=lo&&t<=hi);
  for(let t=Math.ceil(lo*4)/4;t<hi;t+=.25)edges.push(t);
  const times=[...new Set(edges)].sort((a,b)=>a-b);let floor=.22;
  for(let j=1;j<times.length;j++){
   const l=times[j-1],h=times[j],wl=weightAt(l),wh=weightAt(h),upper=id=>Math.max(wl.get(id)||0,wh.get(id)||0);
   const total=components.reduce((sum,ids)=>sum+(Math.max(...ids.map(id=>extents.get(id).bottom))-Math.min(...ids.map(id=>extents.get(id).top))+240)*Math.sqrt(Math.max(...ids.map(upper))),0);
   let padding=bands.reduce((sum,b)=>{const fade=t=>quint(Math.min((t-b.from+4)/4,(b.to+4-t)/4));return sum+(b.legacy_height??b.height)*Math.max(fade(l),fade(h))*Math.sqrt(upper(b.staff));},0),native=0;
   for(const c of comparisons){const alpha=Math.max(cubic((l-c.from)/.6),cubic((h-c.from)/.6))*Math.max(1-cubic((l-c.to)/.35),1-cubic((h-c.to)/.35))*upper(c.anchor_staff),height=c.native_height??c.height/.06;padding+=((c.row_padding_px??85)+(c.fixed_display_scale?height*c.fixed_display_scale:0))*alpha;native+=(c.fixed_display_scale?0:height)*alpha;}
   floor=Math.min(floor,Math.max(800,1640-padding)/Math.max(1,total+native));
  }
  scaleCache.set(key,floor);return floor;
 };
 // The first allocator predates barline-safe x anchoring and display tails.
 // Recolour that overlap graph once, AFTER final anchors and lifetimes exist.
 // Keep one immutable slot per label; never reflow in response to the cursor.
 // Original-height reference layouts bound the smallest possible score scale:
 // removing rows only increases it, so separated anchor intervals stay apart.
 const rowPacking=[],rowPackingAttempts=[];
 for(const [index,items] of linked){
  const b=bands[index],oldCount=b.compact_rows.length;
  if(oldCount<2||b.compact_guests?.length||items.some(i=>!i.anchor))continue;
  // Root-space harmonic-analysis lanes live below the last active score staff.
  // They are not free motif labels and are therefore absent from `guests`.
  // Row assignment and vertical reservation are separate: footer labels may
  // move up, while their old lower-row budget remains available to harmony.
  const harmony=Array.isArray(P.harmony_anchors)?P.harmony_anchors:(P.harmony_anchors?.entries||[]),lower=new Set(components.slice(owners.get(b.staff)+1).flat());
  const hasLower=(S.cohorts||[]).some(c=>c.start-4<b.to+4&&c.end+4>b.from-4&&c.staves.some(id=>lower.has(id)));
  const protectedFooter=(b.side||'below')==='below'&&!hasLower&&harmony.some(h=>h.kind==='printed_harmony');
  const conflicts=new Map(items.map(i=>[i,new Set()])),collisions=[];let scaleFloor=Infinity;
  for(let a=0;a<items.length;a++)for(let c=a+1;c<items.length;c++){
   const x=items[a],y=items[c],lo=Math.max(life(x)[0],life(y)[0])-.2,hi=Math.min(life(x)[1],life(y)[1])+.2;
   if(lo>=hi)continue;
   const scale=conservativeScale(lo,hi)*.998;scaleFloor=Math.min(scaleFloor,scale);
   const box=i=>({x:i.anchor.native_x*scale+(i.anchor.screen_dx||0)-i.paddingX,r:i.anchor.native_x*scale+(i.anchor.screen_dx||0)+i.width+i.paddingX});
   const xx=box(x),yy=box(y),gap=Math.max(x.size,y.size)*.32;
   if(xx.r+gap>yy.x&&yy.r+gap>xx.x){conflicts.get(x).add(y);conflicts.get(y).add(x);collisions.push({labels:[x.label.textContent,y.label.textContent],from:lo,to:hi,scale,clearance:Math.max(yy.x-xx.r,xx.x-yy.r),required:gap});}
  }
  const slots=new Map();
  for(const item of [...items].sort((a,z)=>a.bandSlot-z.bandSlot||a.anchor.native_x-z.anchor.native_x||life(a)[0]-life(z)[0])){
   const used=new Set([...conflicts.get(item)].map(i=>slots.get(i)));let slot=0;while(used.has(slot))slot++;slots.set(item,slot);
  }
  let count=Math.max(...slots.values())+1,shifts=[];
  if(count>=oldCount){
   const packed=planPackedSourceRow(items,(lo,hi)=>conservativeScale(lo,hi)*.998);
   if(packed){
    for(const {item,x,previous_x,scale_floor} of packed){
     if(Math.abs(x-previous_x)>.000001){
      const a=item.anchor;
      if(a.node){const world=actor.scoreClip.firstElementChild,local=new DOMPoint(x,a.native_y).matrixTransform(a.node.getCTM().inverse().multiply(world.getCTM()));a.x=local.x;a.y=local.y;}
      a.native_x=x;shifts.push({source:item.representative_id,from:previous_x,to:x,source_bounds:item.bandFitDetail.source,shift_at_scale_floor_px:Math.abs(x-previous_x)*scale_floor});
     }
     slots.set(item,0);
    }
    count=1;
   }
  }
  rowPackingAttempts.push({band:index,rows_before:oldCount,rows_after:count,collisions});if(count>=oldCount)continue;
  rowPacking.push({band:index,staff:b.staff,side:b.side,from:b.from,to:b.to,rows_before:oldCount,rows_after:count,maximum_saved_px:protectedFooter?0:(oldCount-count)*b.legacy_row_height,footer_reservation_preserved:protectedFooter,scale_floor:Number.isFinite(scaleFloor)?scaleFloor:null,source_local_adjustments:shifts,labels:items.map(i=>({source:i.representative_id,text:i.label.textContent,slot_before:i.bandSlot,slot_after:slots.get(i)}))});
  for(const item of items)item.bandSlot=slots.get(item);
  if(protectedFooter)b.compact_reserved_rows=b.compact_rows;
  b.compact_rows=Array.from({length:count},(_,slot)=>({height:b.legacy_row_height,windows:items.filter(i=>i.bandSlot===slot).map(i=>({from:life(i)[0],to:life(i)[1],source:i.representative_id}))}));
  b.slots=count;b.height=(protectedFooter?oldCount:count)*b.legacy_row_height+(b.padding_before||0)+(b.padding_after||0);
 }
 const eligible=[...linked.keys()];
 const clearPair=(ia,ib)=>{
  const a=bands[ia],b=bands[ib],ca=owners.get(a.staff),cb=owners.get(b.staff);
  if(a.compact_guests?.length||b.compact_guests?.length||a.compact_reserved_rows||b.compact_reserved_rows)return null;
  if(!(ca<cb)||Math.max(a.from,b.from)>Math.min(a.to,b.to)+8)return null;
  const from=Math.max(a.from,b.from)-4,to=Math.min(a.to,b.to)+4;if(from>=to)return null;
  const intervening=components.slice(ca+1,cb).flat();
  if((S.cohorts||[]).some(c=>c.start-4<to&&c.end+4>from&&c.staves.some(id=>intervening.includes(id))))return null;
  for(const other of bands)if(other!==a&&other!==b&&other.from-4<to&&other.to+4>from&&((owners.get(other.staff)>ca&&owners.get(other.staff)<cb)||(owners.get(other.staff)===ca&&(other.side||'below')==='below')||(owners.get(other.staff)===cb&&other.side==='above')))return null;
  if((P.native_comparisons||[]).some(c=>c.placement!=='sidebar'&&c.from<to&&c.to+.35>from&&owners.get(c.anchor_staff)>=ca&&owners.get(c.anchor_staff)<cb))return null;
  let scaleFloor=Infinity;
  for(const x of linked.get(ia))for(const y of linked.get(ib)){
   const lo=Math.max(life(x)[0],life(y)[0])-.2,hi=Math.min(life(x)[1],life(y)[1])+.2;if(lo>=hi)continue;
   if(!x.anchor||!y.anchor)return null;
   const scale=conservativeScale(lo,hi)*.998;scaleFloor=Math.min(scaleFloor,scale);
   const bx=i=>({x:i.anchor.native_x*scale+(i.anchor.screen_dx||0)-i.paddingX,r:i.anchor.native_x*scale+(i.anchor.screen_dx||0)+i.width+i.paddingX});
   const xx=bx(x),yy=bx(y),gap=Math.max(x.size,y.size)*.32;
   if(xx.r+gap>yy.x&&yy.r+gap>xx.x){rejected.push({upper:ia,lower:ib,reason:'horizontal-overlap',labels:[x.label.textContent,y.label.textContent]});return null;}
  }
  return{upper:ia,lower:ib,from,to,intervening,scale_floor:Number.isFinite(scaleFloor)?scaleFloor:null,maximum_saved_px:Math.min(a.height,b.height)};
 };
 for(const ia of eligible.filter(i=>(bands[i].side||'below')==='below'))for(const ib of eligible.filter(i=>bands[i].side==='above')){const pair=clearPair(ia,ib);if(pair)pairs.push(pair);}
 const used=new Set(),selected=[];
 for(const pair of pairs.sort((a,b)=>b.maximum_saved_px-a.maximum_saved_px||a.upper-b.upper)){
  if(used.has(pair.upper)||used.has(pair.lower))continue;
  bands[pair.upper].compact_peer=pair.lower;bands[pair.lower].compact_host=pair.upper;
  used.add(pair.upper);used.add(pair.lower);selected.push(pair);
 }
 P.compact_vertical_audit={policy:'source-constrained-rows-with-independent-footer-reserve-v4',font_sizes_preserved:true,source_identity_preserved:true,anchors_fixed_during_playback:true,native_anchors_preserved:!rowPacking.some(r=>r.source_local_adjustments.length),band_count:bands.length,extensions_preserved:(P.band_display_extensions||[]).length,free_label_dependencies:guests,row_packing:rowPacking,row_packing_attempts:rowPackingAttempts,pairs:selected,rejected};
}



// Preview-only, absolute-time sidebar compositor. Original nodes remain geometry
// anchors. Visible runs retain source characters across adjacent reading stages.
function incrementalReading({E,ease,text,pages,groups,P,X,W}){
 const layer=E('g',{'data-incremental-reading':'true'},text),tracks=new Map(),decor=[];
 const semanticWindows=P.semantic_text_windows||P.connection_windows||[],semanticCache=new Map();
 function semanticFor(item,key,occurrence){
  if(!key)return null;
  const cacheKey=JSON.stringify([item.index,key,occurrence]);if(semanticCache.has(cacheKey))return semanticCache.get(cacheKey);
  const b=item.b,theme=Object.hasOwn(b.keyword_themes||{},key)?b.keyword_themes[key]:b.theme;
  const matching=semanticWindows.filter(w=>w.block===item.index&&w.keyword===key&&(w.keyword_occurrence||0)===occurrence&&(!theme||w.theme===theme));
  const overrides=[...new Set(matching.map(w=>w.connection_color).filter(Boolean))];
  if(overrides.length>1)throw Error('Ambiguous persistent text colour: '+cacheKey);
  const colour=overrides[0]||b.keyword_colors?.[key]||P.palette?.[theme]||null;
  semanticCache.set(cacheKey,colour);return colour;
 }
 const add=(key,record)=>{let runs=tracks.get(key);if(!runs){runs=[];tracks.set(key,runs)}let run=runs.at(-1);if(!run||Math.abs(run.records.at(-1).to-record.from)>1e-6){run={key,records:[]};runs.push(run)}run.records.push(record)};
 for(const item of groups){
  if(item.b.kind==='native_score')continue;
  if(['native_table','image'].includes(item.b.kind)){
   const node=item.g.cloneNode(true);layer.append(node);decor.push({node,item});continue;
  }
  const b=item.b,identity=b.unit_id||('block-'+item.index),base=b.display_ranges?.[0]?.[0]||0;
  let offset=0;
  for(const node of [...item.g.children].filter(n=>n.localName==='text')){
   let char=0;
   for(const span of node.children){
    const style=getComputedStyle(span),chars=Array.from(span.textContent);
    for(const c of chars){
     const pos=node.getStartPositionOfChar(char++),off=base+offset++;
     add(identity+'|'+off+'|'+c,{c,identity,offset:off,x:pos.x,y:pos.y,size:Number(node.getAttribute('font-size')),weight:style.fontWeight,fill:style.fill,
      keyword:span.dataset.key||null,occurrence:Number(span.dataset.occurrence||0),semantic_fill:semanticFor(item,span.dataset.key||null,Number(span.dataset.occurrence||0)),block:item.index,ordinal:item.page.ordinal,
      from:Math.max(item.page.from,b.reveal_from??-Infinity),to:item.page.to});
    }
   }
  }
  if(offset!==Array.from(b.text||'').length)throw Error('Incremental source text mismatch at block '+item.index);
  for(const node of [...item.g.children].filter(n=>n.localName!=='text')){const copy=node.cloneNode(true);layer.append(copy);decor.push({node:copy,item});}
 }
 for(const page of pages){
  const title=[...page.g.children].find(n=>n.localName==='text');if(!title)continue;
  const style=getComputedStyle(title);Array.from(title.textContent).forEach((c,i)=>{const pos=title.getStartPositionOfChar(i);add('title|'+page.section_text+'|'+i,{c,identity:'title|'+page.section_text,offset:i,x:pos.x,y:pos.y,size:Number(title.getAttribute('font-size')),weight:style.fontWeight,fill:style.fill,keyword:null,block:-1,ordinal:page.ordinal,from:page.from,to:page.to});});
 }
 const duration=.24,retreat=.14,characters=[...tracks.values()].flat(),outgoingAt=new Map(),enterDelays=new Map(),moveDelays=new Map();
 // Source identity + character offset is authoritative. Carry meaning across
 // retained pages even when their new block no longer declares this keyword.
 // This is absolute-time data, never a memory of which frame rendered first.
 let semanticCharacters=0,inheritedRecords=0;
 for(const track of characters){
  let colour=track.records.find(r=>r.semantic_fill)?.semantic_fill;if(!colour)continue;
  semanticCharacters++;
  const refs=track.records.filter(r=>r.keyword&&r.semantic_fill).map(r=>({block:r.block,keyword:r.keyword,occurrence:r.occurrence}));
  for(const r of track.records){if(r.semantic_fill)colour=r.semantic_fill;else inheritedRecords++;r.semantic_fill=colour;r.semantic_refs=refs;}
 }
 const positionKey=r=>r.ordinal+'|'+r.block,rect=r=>({x:r.x,r:r.x+r.size,y:r.y-r.size,b:r.y+r.size*.18}),intersects=(a,b)=>a.x<b.r&&a.r>b.x&&a.y<b.b&&a.b>b.y;
 for(const track of characters){const r=track.records.at(-1);let list=outgoingAt.get(r.to);if(!list){list=[];outgoingAt.set(r.to,list)}list.push(rect(r));}
 for(const track of characters){const first=track.records[0];if((outgoingAt.get(first.from)||[]).some(b=>intersects(rect(first),b)))enterDelays.set(positionKey(first),retreat);
  for(let i=1;i<track.records.length;i++){const a=track.records[i-1],b=track.records[i];if(Math.abs(a.x-b.x)<.01&&Math.abs(a.y-b.y)<.01)continue;const ar=rect(a),br=rect(b),sweep={x:Math.min(ar.x,br.x),r:Math.max(ar.r,br.r),y:Math.min(ar.y,br.y),b:Math.max(ar.b,br.b)};if((outgoingAt.get(b.from)||[]).some(r=>intersects(sweep,r)))moveDelays.set(positionKey(b),retreat);}
 }
 for(const track of characters)for(const r of track.records){r.enter_delay=enterDelays.get(positionKey(r))||0;r.move_delay=moveDelays.get(positionKey(r))||0;}
 const ordered=characters.sort((a,b)=>a.records[0].ordinal-b.records[0].ordinal||a.records[0].y-b.records[0].y||a.records[0].x-b.records[0].x);
 const signature=run=>{const x=run.records[0].x;return JSON.stringify(run.records.map(r=>[r.ordinal,r.from,r.to,Math.round((r.x-x)*100)/100,r.y,r.size,r.weight,r.fill,r.keyword,r.occurrence,r.block,r.enter_delay,r.move_delay,r.semantic_fill]));};
 const runs=[];
 for(const track of ordered){const r=track.records[0],sig=signature(track),last=runs.at(-1);
  if(last&&last.signature===sig&&last.identity===r.identity&&last.lastOffset+1===r.offset&&Math.abs(last.y-r.y)<.01){last.value+=r.c;last.lastOffset=r.offset;last.characters.push(track)}
  else runs.push({records:track.records,signature:sig,identity:r.identity,lastOffset:r.offset,y:r.y,value:r.c,characters:[track]});
 }
 for(const run of runs){run.node=E('text',{'font-family':'Han','data-source-unit':run.identity},layer);run.node.textContent=run.value;}
 for(const d of decor)d.signature=d.node.localName+'|'+(d.node.localName==='g'?d.node.innerHTML:d.node.outerHTML);
 for(const d of decor){const same=c=>c!==d&&c.signature===d.signature&&c.item.top===d.item.top;d.previous=decor.find(c=>same(c)&&c.item.page.ordinal===d.item.page.ordinal-1);d.next=decor.find(c=>same(c)&&c.item.page.ordinal===d.item.page.ordinal+1);}
 const lifetime=(a,z,t)=>({alpha:(a<=0?1:ease((t-a)/duration))*(z>=P.panel_out?1:1-ease((t-z)/retreat)),dy:(a<=0?0:8*(1-ease((t-a)/duration)))-(z>=P.panel_out?0:4*ease((t-z)/retreat))});
 const sourceTracks=new Map();
 for(const track of characters)for(const index of new Set(track.records.map(r=>r.block))){let list=sourceTracks.get(index);if(!list){list=[];sourceTracks.set(index,list)}list.push(track);}
 const overlap=(a,b)=>(a.display_ranges||[]).reduce((sum,[x,y])=>sum+(b.display_ranges||[]).reduce((n,[v,w])=>n+Math.max(0,Math.min(y,w)-Math.max(x,v)),0),0);
 const anchorGroups=groups.map(item=>{const previous=[...(pages[item.page.ordinal-1]?.blocks.values()||[])].map(candidate=>({candidate,shared:item.index===candidate.index?Infinity:item.b.unit_id&&item.b.unit_id===candidate.b.unit_id?overlap(item.b,candidate.b):0})).filter(v=>v.shared>0).sort((a,b)=>b.shared-a.shared)[0]?.candidate;return{item,previous,original:item.g.getAttribute('transform')||''};});
 let currentTime=0;
 function applyAnchorGeometry(t){
  currentTime=t;
  for(const{item,previous,original}of anchorGroups){const delay=moveDelays.get(item.page.ordinal+'|'+item.index)||0,dy=previous?(previous.top-item.top)*(1-ease((t-item.page.from-delay)/duration)):0;item.g.setAttribute('transform',`translate(0 ${dy}) ${original}`.trim());}
 }
 function blockAlpha(index,t=currentTime,keyword=null,occurrence=0){
  const matches=(sourceTracks.get(index)||[]).filter(track=>!keyword||track.records.some(r=>r.block===index&&r.keyword===keyword&&(r.occurrence||0)===occurrence));
  return Math.max(0,...matches.map(track=>lifetime(track.records[0].from+track.records[0].enter_delay,track.records.at(-1).to,t).alpha));
 }
 const paperInkNodes=[...layer.querySelectorAll('tspan,text:not(:has(tspan))')];
 function paperTextNodes(){
  return paperInkNodes.filter(node=>{let alpha=1;for(let n=node;n&&n!==layer;n=n.parentElement){if(n.style.visibility==='hidden'||n.style.display==='none')return false;alpha*=Number(n.style.opacity||1);}return alpha>.01;});
 }
 const rgb=c=>/^#[0-9a-f]{6}$/i.test(c)?[1,3,5].map(i=>parseInt(c.slice(i,i+2),16)):c.match(/[\d.]+/g)?.slice(0,3).map(Number);
 const mix=(a,b,u)=>{const ca=rgb(a),cb=rgb(b);return ca?.length===3&&cb?.length===3?'rgb('+ca.map((v,i)=>Math.round(v+(cb[i]-v)*u)).join(',')+')':b;};
 let last={};
 function draw(t,activeWindows=[]){
  applyAnchorGeometry(t);
  let visibleCharacters=0,stationaryCharacters=0,movingCharacters=0;const colouredRuns=[];
  for(const run of runs){
   const rs=run.records,first=rs[0],end=rs.at(-1),life=lifetime(first.from+first.enter_delay,end.to,t),node=run.node;
   node.style.visibility=life.alpha>0?'visible':'hidden';node.style.opacity=life.alpha;if(life.alpha<=0)continue;
   let at=rs.findIndex(r=>t>=r.from&&t<r.to);if(at<0)at=t<first.from?0:rs.length-1;
   const r=rs[at],old=rs[Math.max(0,at-1)],u=at?ease((t-r.from-r.move_delay)/duration):1;
   const x=old.x+(r.x-old.x)*u,y=old.y+(r.y-old.y)*u+life.dy;
   node.setAttribute('x',x);node.setAttribute('y',y);node.setAttribute('font-size',r.size);node.setAttribute('font-weight',r.weight);
   const hit=activeWindows.filter(w=>w.block===r.block&&w.keyword===r.keyword&&(w.keyword_occurrence||0)===(r.occurrence||0)&&w.progress>0).sort((a,b)=>b.progress-a.progress||a.from-b.from)[0];
   if(r.semantic_fill){
    const activity=Math.max(0,...activeWindows.filter(w=>(r.semantic_refs||[]).some(ref=>w.block===ref.block&&w.keyword===ref.keyword&&(w.keyword_occurrence||0)===(ref.occurrence||0))).map(w=>w.progress));
    const base=mix(old.semantic_fill||r.semantic_fill,r.semantic_fill,u),fill=mix(base,'#FAF8F1',.10*(1-Math.min(1,activity)));
    node.setAttribute('fill',fill);colouredRuns.push({text:run.value,unit:run.identity,source_offset:run.characters[0].records[0].offset,block:r.block,keyword:r.keyword,base,fill,active_progress:activity,opacity:life.alpha,x,y,size:r.size});
   }else node.setAttribute('fill',hit?(hit.connection_color||P.palette?.[hit.theme]||mix(old.fill,r.fill,u)):mix(old.fill,r.fill,u));
   visibleCharacters+=run.value.length;
   if(rs.length>1&&life.alpha>.999){if(Math.abs(old.x-r.x)<.01&&Math.abs(old.y-r.y)<.01)stationaryCharacters+=run.value.length;else if(u<1)movingCharacters+=run.value.length;}
  }
  for(const d of decor){const p=d.item.page,life=lifetime(d.previous?d.previous.item.page.from:p.from,d.next?d.next.item.page.to:p.to,t);d.node.style.opacity=life.alpha;d.node.style.visibility=t>=p.from&&t<p.to+(d.next?0:retreat)&&life.alpha>0?'visible':'hidden';d.node.setAttribute('transform',`translate(0 ${life.dy})`);}
  last={seconds:t,visible_characters:visibleCharacters,unchanged_characters_retained:stationaryCharacters,moving_characters:movingCharacters,visible_runs:runs.filter(r=>r.node.style.visibility==='visible').length,total_runs:runs.length,source_character_tracks:characters.length,enter_seconds:duration,exit_seconds:retreat,persistent_colour:{policy:'source-character-semantic-colour-v1',inactive_paper_mix:.10,semantic_characters:semanticCharacters,inherited_records:inheritedRecords,visible_runs:colouredRuns}};
 }
 function figureSlots(slots,t){
  const visible=[];
  for(const slot of slots){const previous=slots.find(v=>v!==slot&&v.id===slot.id&&Math.abs(v.to-slot.from)<1e-6),next=slots.find(v=>v!==slot&&v.id===slot.id&&Math.abs(slot.to-v.from)<1e-6);
   const life=lifetime(previous?previous.from:slot.from,next?next.to:slot.to,t);let top=slot.top;
   if(previous)top=previous.top+(slot.top-previous.top)*ease((t-slot.from)/duration);
   if(t>=slot.from&&t<slot.to+(!next?retreat:0))visible.push({...slot,top,alpha:life.alpha});
  }return visible.sort((a,b)=>b.alpha-a.alpha);
 }
 return{draw,figureSlots,applyAnchorGeometry,blockAlpha,paperTextNodes,audit:()=>last};
}

/** Independent score-only layer. Serialize this function alongside installGuide.
 * Input: S.guide_payload.harmony_anchors (compiled source entries), with
 * note_ids[], native_x, native_end_x. Optional harmony_layout overrides only
 * the layer's safe bounds/font sizes, never the native score or reading panel.
 * Call draw(F) AFTER the native actor and guide draw. No native DOM is mutated.
 */
function installHarmony(actor, S) {
  const NS = 'http://www.w3.org/2000/svg';
  const P = S.guide_payload || {}, root = actor.root;
  const world = actor.scoreClip.firstElementChild;
  if (!world || !S.geometry) throw Error('Harmony layer requires native world and geometry');
  const C = Object.assign({left: 395, right: 2618, top: 62, bottom: 1798,
    size: 30, tempo_size: 28, pad: 6, locator_pad: 12, lane_gap: 10, label_gap: 4,
    ink: P.analysis_color || '#00815C', direction_ink: '#56645D'}, P.harmony_layout || {});
  const prefix = (world.id.match(/^(scene\d+-)/) || ['','scene1-'])[1];
  const uid = prefix + 'harmony-' + String(P.id || 'score').replace(/[^a-zA-Z0-9_-]/g, '');
  const E = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v);
    if (parent) parent.append(n);
    return n;
  };
  const defs = E('defs', {id: uid + '-defs'}, root);
  const clip = E('clipPath', {id: uid + '-clip'}, defs);
  E('rect', {x:C.left, y:C.top, width:C.right-C.left, height:C.bottom-C.top}, clip);
  const layer = E('g', {id:uid, 'data-layer':'score-harmony', 'clip-path':`url(#${uid}-clip)`,
    'font-family':'Han, serif', 'font-weight':400, 'pointer-events':'none', fill:C.ink}, root);
  // Keep this layer below the cursor from installation onward; draw never reorders it.
  if(actor.readingLine?.parentNode===root)root.insertBefore(layer,actor.readingLine);
  // The clip ends before the existing reading-column fade. No new paper or panel.
  const strip = id => String(id || '').replace(/^scene\d+-/, '');
  const nativeNodes = new Map([...world.querySelectorAll('[id]')].map(n => [strip(n.id),n]));
  const geos = new Map(S.geometry.notes.map(n => [n.id,n]));
  const mapped = id => nativeNodes.get(geos.get(strip(id))?.svg_id || strip(id));
  const qnum = q => Array.isArray(q) ? q[0]/q[1] : Number(q);
  const norm = s => String(s || '').normalize('NFC').replace(/\s/g,'').toLowerCase();
  const finite = b => b && [b.x,b.r,b.y,b.b].every(Number.isFinite) && b.r >= b.x && b.b >= b.y;
  const intersects = (a,b,p=0) => a.x < b.r+p && a.r > b.x-p && a.y < b.b+p && a.b > b.y-p;
  const screen = b => finite(b) && b.r>C.left && b.x<C.right && b.b>C.top && b.y<C.bottom;
  function bounds(n, relative=root) {
    if (!n?.isConnected || !n.getCTM() || !relative.getCTM()) return null;
    try {
      const b=n.getBBox(), m=relative.getCTM().inverse().multiply(n.getCTM());
      const ps=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]]
        .map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));
      const r={x:Math.min(...ps.map(p=>p.x)), r:Math.max(...ps.map(p=>p.x)),
        y:Math.min(...ps.map(p=>p.y)), b:Math.max(...ps.map(p=>p.y))};
      return finite(r)?r:null;
    } catch (_) { return null; }
  }
  function mounted(n) {
    for (let p=n; p && p!==world.parentNode; p=p.parentNode)
      if (p.style?.display==='none' || p.getAttribute?.('display')==='none') return false;
    return true;
  }
  function visiblyStyled(n) {
    for (let p=n; p && p!==root; p=p.parentNode) {
      if (p.style?.display==='none' || p.style?.visibility==='hidden' ||
          p.getAttribute?.('visibility')==='hidden') return false;
      const o=p.style?.opacity || p.getAttribute?.('opacity');
      if (o!==null && o!==undefined && o!=='' && Number(o)<.025) return false;
    }
    return true;
  }
  const union = bs => ({x:Math.min(...bs.map(b=>b.x)),r:Math.max(...bs.map(b=>b.r)),
    y:Math.min(...bs.map(b=>b.y)),b:Math.max(...bs.map(b=>b.b))});
  const staffForNode = new Map();
  const staffRows = S.geometry.staves.map(st => ({id:st.id, groups:st.svg_ids.map(id=>nativeNodes.get(id))
    .filter(Boolean).map(n=>{
      staffForNode.set(n,st.id);
      const paths=[...n.children].filter(c=>c.tagName.toLowerCase()==='path');
      const b=paths.length?bounds(paths[0],world):null;
      return {node:n,paths,nativeX:b?[b.x,b.r]:null};
    })}));
  const weight = (staves,F) => staves.length ? Math.max(...staves.map(s=>Number(F.weights?.[s] || 0))) : 1;
  const ownerOf = n => {const id=staffForNode.get(n.closest('g.staff'));return id?[id]:[];};
  // Native-x bounds are used only to cull work. Every final box/anchor uses DOM CTM.
  const records = [], seen=new Set();
  function addObstacle(node, staves, type) {
    if (!node || seen.has(node)) return;
    seen.add(node); const b=bounds(node,world);
    if (b) records.push({node,staves,type,nativeX:[b.x,b.r]});
  }
  for (const g of S.geometry.notes) addObstacle(mapped(g.id),[g.staff],'note');
  const controls=(S.geometry.controls || []).map(c=>({...c,node:nativeNodes.get(strip(c.svg_id))})).filter(c=>c.node);
  for (const c of controls) addObstacle(c.node,c.staves || [],c.class || 'control');
  // Beam and tuplet geometry is not always a child of one note or a control.
  for (const n of world.querySelectorAll('g.beam,g.tuplet,g.clef,g.keySig,g.meterSig'))
    addObstacle(n,ownerOf(n),'native-symbol');
  const tempoControls=controls.filter(c=>/(^|\s)(tempo|dir)(\s|$)/.test(c.class || ''));
  const keyName = token => {
    const m=String(token).match(/^([#b]?)([A-G])([Mm])$/);
    return m ? (m[1]==='#'?'♯':m[1]==='b'?'♭':'')+m[2]+m[3] : null;
  };
  // Display typography only: printed_text, its analysis, and its native q stay intact.
  function writeHarmony(text, printed, size, sourceLines) {
    const lines=Array.isArray(sourceLines)&&sourceLines.length?sourceLines.map(String):[String(printed || '')];
    const lineRuns=[],displayLines=[],anchors=[];
    function layoutLine(raw,index){
      const runs=[],equal=raw.startsWith('=')?'=':'',value=equal?raw.slice(1):raw;
      // Keep the relation sign with its left-hand chord. The source lines are
      // untouched; only the rendered wrap moves '=' to the preceding line.
      const carriedEqual=!!equal&&index>0;
      const colon=value.indexOf(':'),key=colon>=0?keyName(value.slice(0,colon)):null,wholeKey=keyName(value);
      const prefix=(carriedEqual?'':equal)+(key?key+(equal?'':':'):''),body=(key?value.slice(colon+1):value)
        .replace(/#/g,'♯').replace(/(^|\/|add)b(?=[A-GivIV0-9])/g,'$1♭');
      const run=(value,x,y=0,fontSize=size)=>{
        const n=E('tspan',{x,y:y+index*size*1.37,'font-size':fontSize},text);
        n.textContent=value;runs.push({node:n,x,y,line:index});return n;
      };
      if(wholeKey){const name=equal+wholeKey,n=run(name,0);lineRuns.push(...runs);return{display:name,anchor:n.getComputedTextLength()/2};}
      let advance=prefix?run(prefix,0).getComputedTextLength():0;
      if(equal&&key)advance+=size*.04;
      const prefixWidth=advance,add=body.match(/^(.*?)(?:add([♭♯]?\d+))?(\/.*)?$/);
      const main=add?.[1]??body,added=add?.[2]||'',suffix=add?.[3]||'';
      const figureMatch=main.match(/^(.*?)(64|65|43|42|6|7|9|2)$/);
      const base=figureMatch?.[1]||main,figure=figureMatch?.[1]?figureMatch[2]:'',small=size*.62;
      advance+=run(base,advance).getComputedTextLength();
      let displayBody=base;
      if(/^(64|65|43|42)$/.test(figure)){
        const upper=run(figure[0],advance,-size*.48,small),lower=run(figure[1],advance,size*.22,small);
        advance+=Math.max(upper.getComputedTextLength(),lower.getComputedTextLength());displayBody+=figure[0]+'/'+figure[1];
      }else if(figure){advance+=run(figure,advance,-size*.32,small).getComputedTextLength();displayBody+=figure;}
      if(added){advance+=run('add'+added,advance+size*.04,-size*.32,small).getComputedTextLength()+size*.04;displayBody+='add'+added;}
      if(suffix){advance+=run(suffix,advance+size*.06).getComputedTextLength()+size*.06;displayBody+=suffix;}
      const anchor=equal?advance/2:prefixWidth+(advance-prefixWidth)/2;
      if(lines[index+1]?.startsWith('=')){run('=',advance+size*.12);displayBody+=' =';}
      lineRuns.push(...runs);return{display:prefix+(equal&&key?' ':'')+displayBody,anchor};
    }
    lines.forEach((raw,index)=>{const result=layoutLine(raw,index);displayLines.push(result.display);anchors.push(result.anchor);});
    // Both lines share the verified chord column. A complete equivalence line
    // centers on it; an initial key declaration still aligns its Roman numeral.
    for(const r of lineRuns){r.x+=anchors[0]-anchors[r.line];r.node.setAttribute('x',r.x);}
    return{displayText:displayLines.join('\n'),displayLines,anchorOffset:anchors[0],lineRuns};
  }
  const input=Array.isArray(P.harmony_anchors)?P.harmony_anchors:(P.harmony_anchors?.entries || []);
  // The compiler supplies the current source entries and display lifetimes.
  const entries=input.map((a,index)=>{
    const local=a.kind==='native_local_timing_word', tempo=a.kind==='native_global_tempo';
    const g=E('g', {id:uid+'-item-'+index, 'data-harmony-id':a.id || index}, layer);
    const ink=a.source_color || ((tempo||local)?C.direction_ink:C.ink);
    const labelDx=Number(a.label_dx ?? 0);
    const text=E('text', {x:0,y:0,fill:ink,'font-size':tempo?C.tempo_size:C.size,
      'font-style':tempo?'italic':'normal','xml:space':'preserve'},g);
    let typography=null;
    if(tempo || local)text.textContent=a.printed_text || '';
    else typography=writeHarmony(text,a.printed_text,C.size,a.source_printed_lines);
    const metric=text.getBBox();
    // Align the Roman numeral to its actual note column; key prefixes extend left.
    const anchorOffset=typography?.anchorOffset ?? (metric.x+metric.width/2);
    g.style.display='none';
    const ids=a.note_ids || (a.notes || a.representative_notes || []).map(n=>n.event_id);
    const first=ids[0] ? mapped(ids[0]) : null;
    const aliases=[a.printed_text,a.musicxml_direction?.words_joined_whitespace_normalized].map(norm).filter(Boolean);
    const nativeMatches=tempoControls.filter(c=>aliases.includes(norm(c.node.textContent)));
    return {a,g,text,metric,anchorOffset,ids,first,tempo,local,nativeMatches,index,ink,labelDx,
      displayText:typography?.displayText || a.printed_text || '',
      displayLines:typography?.displayLines || [a.printed_text || ''],lineRuns:typography?.lineRuns || []};
  });
  const harmonicEntries=entries.filter(e=>!e.tempo&&!e.local);
  const singleLineEntries=harmonicEntries.filter(e=>e.displayLines.length===1);
  const harmonyAscent=Math.max(0,...singleLineEntries.map(e=>-e.metric.y));
  const harmonyDescent=Math.max(0,...singleLineEntries.map(e=>e.metric.y+e.metric.height));
  const harmonyLineHeight=harmonyAscent+harmonyDescent+C.lane_gap;
  const equationLineHeight=C.size*1.1;
  // A source equation keeps its lower line on the bottom lane with ordinary
  // fixed 1.1-em leading. It must not enlarge single-line lanes or consume the
  // unused em-box padding that previously pushed its upper line into a hairpin.
  for(const e of harmonicEntries.filter(e=>e.displayLines.length>1)){
    for(const r of e.lineRuns)r.node.setAttribute('y',r.y+r.line*equationLineHeight);
    e.metric=e.text.getBBox();
  }
  for(const e of entries){
    e.lineMetrics=e.lineRuns.length?e.displayLines.map((_,line)=>union(e.lineRuns
      .filter(r=>r.line===line).map(r=>{const b=r.node.getBBox();return{x:b.x,r:b.x+b.width,y:b.y,b:b.y+b.height};}))):
      [{x:e.metric.x,r:e.metric.x+e.metric.width,y:e.metric.y,b:e.metric.y+e.metric.height}];
  }
  let last={scene:P.id,drawn:false,entries:[],new_alignment_verified:false};
  function draw(F) {
    const wm=root.getCTM().inverse().multiply(world.getCTM());
    const toRoot=(x,y=0)=>new DOMPoint(x,y).matrixTransform(wm);
    const cached=new Map(), box=n=>{if(!cached.has(n))cached.set(n,bounds(n));return cached.get(n);};
    const obstacles=[];
    for (const r of records) {
      if (weight(r.staves,F)<.025) continue;
      const xa=toRoot(r.nativeX[0]).x, xb=toRoot(r.nativeX[1]).x;
      if (Math.max(xa,xb)<C.left-120 || Math.min(xa,xb)>C.right+120 || !mounted(r.node)) continue;
      const b=box(r.node);if(screen(b))obstacles.push({...b,type:r.type});
    }
    const bands=[];
    for (const st of staffRows) {
      if (weight([st.id],F)<.025) continue;
      // The five real native staff paths define a protected band; label y is not used.
      for (const record of st.groups) {
        if (!record.nativeX || !record.paths.length) continue;
        const xa=toRoot(record.nativeX[0]).x,xb=toRoot(record.nativeX[1]).x;
        if(Math.max(xa,xb)<C.left || Math.min(xa,xb)>C.right || !mounted(record.node))continue;
        const first=box(record.paths[0]),end=box(record.paths.at(-1));
        if (!first || first.r<C.left || first.x>C.right) continue;
        const b=union([first,end]);
        bands.push({x:C.left,r:C.right,y:b.y-3,b:b.b+3,staff:st.id});break;
      }
    }
    bands.sort((a,b)=>a.y-b.y);
    obstacles.push(...bands);
    // Locators are inside scoreClip, which the root-level scan below deliberately skips.
    // Read their actual root-space boxes; do not translate or restyle the native numbers.
    const protectedLocators=[];
    for(const n of actor.scoreClip.querySelectorAll('g.score-locators text')){
      if(!visiblyStyled(n))continue;
      const b=box(n);if(!screen(b))continue;
      const p=C.locator_pad;
      const protectedBox={x:b.x-p,r:b.r+p,y:b.y-p,b:b.b+p,type:'native-locator'};
      obstacles.push(protectedBox);
      protectedLocators.push({text:n.textContent,bbox:b,protected_bbox:protectedBox});
    }
    // Respect guide's existing labels/markers and native locator text without touching them.
    for (const child of root.children) {
      if ([world,actor.scoreClip,actor.labels,actor.nav,defs,layer].includes(child) ||
          child.tagName.toLowerCase()==='defs' || child.hasAttribute('data-reading-panel')) continue;
      const texts=child.tagName.toLowerCase()==='text'?[child]:[...child.querySelectorAll('text')];
      for (const t of texts) if (visiblyStyled(t)) {const b=box(t);if(screen(b))obstacles.push({...b,type:'existing-label'});}
    }
    // Semantic lanes cannot migrate through the score to escape an obstacle.
    const topGap=bands.length?{y:C.top,b:Math.min(...bands.map(b=>b.y))}:null;
    const bottomGap=bands.length?{y:Math.max(...bands.map(b=>b.b)),b:C.bottom}:null;
    const harmonyBaselines=bottomGap?[bottomGap.b-C.pad-harmonyDescent,
      bottomGap.b-C.pad-harmonyDescent-harmonyLineHeight]:[];
    const occupied=[],out=[];
    const active=entries.slice().sort((a,b)=>(b.tempo-a.tempo) || qnum(a.a.q)-qnum(b.a.q) || a.index-b.index);
    for (const e of active) {
      const a=e.a; e.g.style.display='none';
      const row={id:a.id,kind:a.kind,printed_text:a.printed_text,display_text:e.displayText,display_lines:e.displayLines,
        q:a.q,measure:a.measure,symbol_color:e.ink,label_dx:e.labelDx,status:null};
      out.push(row);
      if (e.local) {row.status='native-local-preserved';row.note_ids=e.ids;continue;}
      if (a.status && !a.status.startsWith('verified')) {row.status='unverified-skipped';continue;}
      if (!a.printed_text || !Number.isFinite(qnum(a.q ?? a.quarter))) {row.status='invalid-entry';continue;}
      let ax=null,ay=null,staff=null,anchorMode=null;
      // The first compiled note is the verified exact-onset anchor; do not fall through
      // to later supporting notes (some source evidence intentionally starts later).
      if (!e.tempo && e.first && mounted(e.first)) {
        const h=box(e.first.querySelector('.notehead') || e.first);
        if(h && h.r>h.x){ax=(h.x+h.r)/2;ay=(h.y+h.b)/2;staff=geos.get(strip(e.ids[0]))?.staff;anchorMode='native-notehead';}
      }
      if ((e.tempo || (!e.first && a.verified_quarter_anchor)) && Number.isFinite(a.native_x)) {ax=toRoot(a.native_x).x;anchorMode='native-quarter-world-ctm';}
      // A compiled point without its true note DOM is an actionable audit failure,
      // not permission to substitute an approximate quarter-axis location.
      if (!Number.isFinite(ax)) {row.status='missing-native-anchor';row.note_ids=e.ids;continue;}
      row.anchor={x:ax,y:ay,staff,mode:anchorMode,event_id:e.ids[0] || null};
      const x=e.tempo?ax:ax-e.anchorOffset+e.labelDx;
      const width=e.metric.width;
      if (x+e.metric.x+width<C.left || x+e.metric.x>C.right || (!e.tempo && (ax<C.left || ax>C.right))) {
        row.status='offscreen';continue;
      }
      if (e.tempo) {
        const visibleNative=e.nativeMatches.map(c=>({c,b:box(c.node)})).filter(({c,b})=>
          weight(c.staves || [],F)>.025 && mounted(c.node) && screen(b) &&
          Math.abs(b.x-ax)<Math.max(90,C.tempo_size*3));
        if(visibleNative.length){
          row.status=a.source_discrepancy?'native-visible-source-spelling-diff':'native-visible';
          row.native_control_ids=visibleNative.map(v=>v.c.node.id);
          row.source_discrepancy=a.source_discrepancy || null;continue;
        }
      }
      // Harmony: exactly two shared baselines in the bottom gap, lower lane first.
      // Tempo: fixed candidates above the first staff. The second top lane clears
      // locator baseline 80 without searching per-frame obstacle edges.
      const gap=e.tempo?topGap:bottomGap;
      let choice=null;
      const candidates=!gap?[]:e.tempo?[
        gap.y+C.pad-e.metric.y,
        gap.y+C.pad+e.metric.height-e.metric.y,
        (gap.y+gap.b-e.metric.height)/2-e.metric.y,
        gap.b-C.pad-e.metric.height-e.metric.y
      ]:e.displayLines.length>1?[harmonyBaselines[0]-(e.displayLines.length-1)*equationLineHeight]:harmonyBaselines;
      const rejected=[];
      for(let lane=0;gap && lane<candidates.length;lane++){
        const baseline=candidates[lane],ty=baseline+e.metric.y;
        const bb={x:x+e.metric.x,r:x+e.metric.x+width,y:ty,b:ty+e.metric.height};
        const lineBoxes=e.lineMetrics.map(b=>({x:x+b.x,r:x+b.r,y:baseline+b.y,b:baseline+b.b}));
        if(bb.y<gap.y+C.pad || bb.b>gap.b-C.pad)continue;
        if(bb.x<C.left+2 || bb.r>C.right-2)continue;
        // The blank upper-left corner of a two-line label is not ink. Test
        // each line independently, while retaining the full envelope for clips.
        const nativeHit=obstacles.find(b=>lineBoxes.some(l=>intersects(l,b,C.pad)));
        // lane_gap is vertical baseline spacing, not extra horizontal glyph padding.
        // The former 10px test hid B's iii despite a real 6.36px gap after flat-VI.
        const labelHit=occupied.find(b=>lineBoxes.some(l=>intersects(l,b,C.label_gap)));
        if(nativeHit || labelHit){
          const hit=nativeHit || labelHit;
          rejected.push({lane,bbox:bb,line_boxes:lineBoxes,reason:nativeHit?'native-obstacle':'harmony-label',
            obstacle:{x:hit.x,r:hit.r,y:hit.y,b:hit.b,type:hit.type || 'placed-label'}});
          continue;
        }
        choice={box:bb,lineBoxes,baseline,lane,gap:{top:gap.y,bottom:gap.b}};break;
      }
      if(!choice){row.status='no-safe-gap';row.required_gap=e.tempo?'above-first-staff':'below-last-staff';row.rejected_candidates=rejected;continue;}
      // Tspan figure positions remain local; translate the whole label as one unit.
      e.g.setAttribute('transform',`translate(${x} ${choice.baseline})`);
      e.g.style.display='';e.g.style.opacity=e.tempo?'0.92':'0.94';
      occupied.push(...choice.lineBoxes);
      Object.assign(row,{status:'displayed',bbox:choice.box,line_boxes:choice.lineBoxes,baseline:choice.baseline,lane:choice.lane,gap:choice.gap});
      if(a.kind==='printed_tonal_region'){
        row.extent={start_q:a.q,end_q:a.end_q || null,end_x:Number.isFinite(a.native_end_x)?toRoot(a.native_end_x).x:null};
        row.region_note='Label denotes the verified local region, not a new global chord or key.';
      }
    }
    last={scene:P.id,drawn:true,seconds:F.seconds,q:F.q,counts:out.reduce((o,e)=>(o[e.status]=(o[e.status]||0)+1,o),{}),
      entries:out,protected_native_boxes:obstacles.length,protected_locators:protectedLocators,staff_bands:bands.length,
      bounds:{left:C.left,right:C.right,top:C.top,bottom:C.bottom},semantic_lanes:{harmony_baselines:harmonyBaselines,top_gap:topGap,bottom_gap:bottomGap},new_alignment_verified:false};
    return last;
  }
  return {draw,audit:()=>last};
}

const harmonyLayer=installHarmony(actor,S);function installNativeComparisons(actor,S){
 const NS='http://www.w3.org/2000/svg',root=actor.root,P=S.guide_payload,world=actor.scoreClip.firstElementChild;
 const E=(tag,a={},p)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(a))n.setAttribute(k,v);p?.append(n);return n};
 const uid='native-comparisons-'+P.id,defs=E('defs',{},root),clip=E('clipPath',{id:uid+'-clip'},defs);E('rect',{x:390,y:65,width:2250,height:1745},clip);
 const layer=E('g',{'data-layer':'native-source-comparisons','clip-path':`url(#${uid}-clip)`},root);root.insertBefore(layer,actor.readingLine);
 const sidebarLayer=E('g',{'data-layer':'sidebar-native-comparisons'},root),sidebarAnchors=new Map();
 const pairBack=E('g',{'data-layer':'native-comparison-target-ranges','clip-path':`url(#${uid}-clip)`},root);root.insertBefore(pairBack,actor.scoreClip);
 const pairLinks=E('g',{'data-layer':'native-comparison-short-links','clip-path':`url(#${uid}-clip)`},root);root.insertBefore(pairLinks,actor.readingLine);
 const mainNodes=new Map([...world.querySelectorAll('[id]')].map(n=>[n.id.replace(/^scene\d+-/,''),n])),geometry=new Map(S.geometry.notes.map(n=>[n.id,n]));
 const ease=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
 function box(n,base){const b=n.getBBox(),m=base.getCTM().inverse().multiply(n.getCTM()),pts=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));return{x:Math.min(...pts.map(p=>p.x)),r:Math.max(...pts.map(p=>p.x)),y:Math.min(...pts.map(p=>p.y)),b:Math.max(...pts.map(p=>p.y))}};
 function visibleBounds(music){
  // A container bbox can include non-painted glyph definitions. Only painted
  // instances and real text determine the quotation's occupied vertical range.
  const boxes=[...music.querySelectorAll('path,polygon,polyline,line,rect,circle,ellipse,use,text')].filter(n=>{const cs=getComputedStyle(n);return !n.closest('defs')&&cs.display!=='none'&&!['hidden','collapse'].includes(cs.visibility)}).map(n=>box(n,music)).filter(b=>b.r>b.x||b.b>b.y);
  if(!boxes.length)throw Error('Empty native comparison');
  const x=Math.min(...boxes.map(b=>b.x)),y=Math.min(...boxes.map(b=>b.y));
  return{x,y,width:Math.max(...boxes.map(b=>b.r))-x,height:Math.max(...boxes.map(b=>b.b))-y};
 }
 const union=boxes=>({x:Math.min(...boxes.map(b=>b.x)),r:Math.max(...boxes.map(b=>b.r)),y:Math.min(...boxes.map(b=>b.y)),b:Math.max(...boxes.map(b=>b.b))});
 const expand=(b,p=7)=>({x:b.x-p,r:b.r+p,y:b.y-p,b:b.b+p});
 function paintRect(n,b,style){for(const[k,v]of Object.entries({x:b.x,y:b.y,width:b.r-b.x,height:b.b-b.y,rx:8,fill:style.fill,'fill-opacity':.65,stroke:style.stroke,'stroke-opacity':.55,'stroke-width':2}))n.setAttribute(k,v)}
 const inkSelector='g.note,g.chord,g.beam,g.rest,g.mRest,g.clef,g.keySig,g.meterSig,g.dir,g.tempo,g.dynam,g.hairpin,g.slur,g.tie,g.syl,g.breath,g.artic',measures=new Map(S.geometry.measures.map(m=>[m.svg_id,m]));
 const nativeStaffInk=S.geometry.staves.map(s=>({id:s.id,groups:s.svg_ids.map(id=>mainNodes.get(id)).filter(Boolean).map(node=>({node,measure:measures.get(node.closest('g.measure')?.id.replace(/^scene\d+-/,''))}))}));
 const nativeControls=(S.geometry.controls||[]).map(c=>({c,node:mainNodes.get(c.svg_id)})).filter(v=>v.node).map(v=>({...v,native:box(v.node,world)}));
 const staffLabels=new Map([...actor.labels.querySelectorAll('[data-staff]')].map(n=>[n.dataset.staff,n]));
 function shortInk(F,a,b,music,captionLines){
  const margin=64,roi={x:Math.min(a.x,b.x)-margin,r:Math.max(a.r,b.r)+margin,y:Math.min(a.y,b.y)-8,b:Math.max(a.b,b.b)+8},wm=root.getCTM().inverse().multiply(world.getCTM()),left=(roi.x-wm.e)/wm.a,right=(roi.r-wm.e)/wm.a,out=[],seen=new Set();
  const intersects=v=>v.r>=roi.x&&v.x<=roi.r&&v.b>=roi.y&&v.y<=roi.b;
  function add(node){if(seen.has(node)||node.closest('defs'))return;seen.add(node);const v=box(node,root);if(!intersects(v)||!(v.r>v.x||v.b>v.y))return;for(let n=node;n&&n!==root;n=n.parentElement){const cs=getComputedStyle(n);if(cs.display==='none'||cs.visibility==='hidden'||Number(cs.opacity)<.01)return;}out.push({...v,id:node.id||node.textContent.trim().slice(0,40)});}
  const near=new Set(nativeStaffInk.filter(s=>{const n=staffLabels.get(s.id),y=n?Number(n.getAttribute('y'))-10:-1e6;return(F.weights[s.id]||0)>.01&&y>roi.y-180&&y<roi.b+180}).map(s=>s.id));
  for(const s of nativeStaffInk)if(near.has(s.id))for(const entry of s.groups){const m=entry.measure;if(m&&(m.x+m.width<left||m.x>right))continue;for(const n of entry.node.querySelectorAll(inkSelector))add(n);}
  for(const{c,node,native}of nativeControls)if(c.staves.some(s=>near.has(s))&&native.r>=left&&native.x<=right)add(node);
  for(const n of music.querySelectorAll(inkSelector+',text'))add(n);for(const n of captionLines)add(n);
  // This layer draws before the outer guide's labels. Project their immutable
  // source anchors now; reading their previous-frame DOM would be incorrect.
  if(typeof motifLabels!=='undefined')for(const item of motifLabels){const anchor=item.anchor;if(!anchor)continue;const alpha=(F.weights[item.row.s.staff]||0)*(typeof labelVisibility==='function'?labelVisibility(item,F.seconds):1);if(alpha<.01)continue;const p=new DOMPoint(anchor.x,anchor.y).matrixTransform(root.getCTM().inverse().multiply(anchor.node.getCTM()));p.x+=anchor.screen_dx||0;p.y+=anchor.screen_dy||0;if(item.bandStaff){const slot=actor.labelSlots?.get(item.bandStaff+':'+(item.bandSide||'below'));if(slot)p.y=slot.y+(slot.slot_offsets?.[item.bandSlot]??(slot.row_height||64)*slot.alpha*(item.bandSlot+.5))-(item.top+item.bottom)/2;}const v={x:p.x-(item.paddingX??12),r:p.x+item.width+(item.paddingX??12),y:p.y+item.top,b:p.y+item.bottom,id:item.row.s.id};if(intersects(v))out.push(v);}
  return out;
 }
 function shortRoute(a,b,ink,scale){
  const padding=6,upper=a.b<=b.y,sy=upper?a.b:a.y,ey=upper?b.y:b.b,lo=Math.max(a.x,b.x)+padding,hi=Math.min(a.r,b.r)-padding;
  const hits=(p,q,o)=>Math.max(p.x,q.x)>=o.x-padding&&Math.min(p.x,q.x)<=o.r+padding&&Math.max(p.y,q.y)>=o.y-padding&&Math.min(p.y,q.y)<=o.b+padding;
  const clear=points=>points.slice(1).every((p,i)=>ink.every(o=>!hits(points[i],p,o)));
  const result=(points,kind,anchor)=>({points,kind,anchor,clearance:padding,path:points.map((p,i)=>(i?'L':'M')+' '+p.x+' '+p.y).join(' ')});
  // Fixed source fractions have stable identities, independent of render
  // history or viewport position. E's .15 column clears both ersterbend and
  // the motif label; it remains attached to this same source range as it moves.
  const fractions=[.15,.5,.85,...Array.from({length:19},(_,i)=>(i+1)/20)];
  for(const f of [...new Set(fractions)]){const x=a.x+(a.r-a.x)*f,p=[{x,y:sy},{x,y:ey}];if(x>=lo&&x<=hi&&clear(p))return result(p,'vertical',{source_fraction:f});}
  // A narrower clear interval can fall between the fixed fractions. Its
  // edges come from current real ink, not from the old label DOM or a cache.
  if(hi>=lo){let gaps=[[lo,hi]];for(const o of ink){if(o.b+padding<Math.min(sy,ey)||o.y-padding>Math.max(sy,ey))continue;const x=o.x-padding,r=o.r+padding;gaps=gaps.flatMap(([l,h])=>r<=l||x>=h?[[l,h]]:[[l,Math.min(h,x)],[Math.max(l,r),h]].filter(([l,h])=>h-l>2));}for(const[l,h]of gaps){const x=(l+h)/2,p=[{x,y:sy},{x,y:ey}];if(clear(p))return result(p,'vertical-gap',{source_fraction:(x-a.x)/(a.r-a.x)});}}
  // Dynamics can cover the whole facing edge while a short side exit is
  // clear. Use fixed fractions of the same real range, never an invented
  // target or a previous-frame point. All segments retain the same clearance.
  for(const side of ['left','right'])for(const f of [1,.85,.7,.5,.3,.15,0])for(const native of [0,200,300,500,700,900,1300]){
   const ax=side==='left'?a.x:a.r,bx=side==='left'?b.x:b.r,d=Math.min(56,native*scale),x=side==='left'?Math.min(ax,bx)-d:Math.max(ax,bx)+d,py=upper?a.y+(a.b-a.y)*f:a.b-(a.b-a.y)*f;
   const p=[{x:ax,y:py},{x,y:py},{x,y:ey},{x:bx,y:ey}].filter((p,i,all)=>!i||p.x!==all[i-1].x||p.y!==all[i-1].y);
   if(clear(p))return result(p,'side-port',{side,source_fraction:f,native_offset:native});
  }
  // Local side detours also undergo the full test. Never reuse the old
  // unconditional left dogleg, cut through notation, or lift the pen.
  for(const side of ['left','right'])for(const native of [360,600,900,1300]){const d=Math.min(56,Math.max(12,native*scale)),x=side==='left'?Math.min(a.x,b.x)-d:Math.max(a.r,b.r)+d,p=[{x:side==='left'?a.x:a.r,y:sy},{x,y:sy},{x,y:ey},{x:side==='left'?b.x:b.r,y:ey}];if(clear(p))return result(p,'side',{side,native_offset:native});}
  return{path:'',points:[],kind:'no-clear-local-route',clearance:padding};
 }
 const items=(P.native_comparisons||[]).map(c=>{
  const sidebar=c.placement==='sidebar',rowClip=E('clipPath',{id:uid+'-'+c.id+'-row'},defs),rowRect=E('rect',{x:sidebar?2740:390,width:sidebar?1100:2250},rowClip),row=E('g',{'clip-path':`url(#${uid}-${c.id}-row)`},sidebar?sidebarLayer:layer);
  const mask=E('rect',{x:sidebar?2740:390,width:sidebar?1100:2250,fill:'#FAF8F1'},row),group=E('g',{'data-source-figure':c.id,'font-family':'Han',fill:c.color,color:c.color},row);
  const caption=E('g',{'font-size':c.caption_size||30,'font-weight':400,'data-caption-layout':'beside-notation'},group);
  const captionLines=(c.caption_lines||[c.caption]).filter(text=>typeof text==='string'&&text.trim()).map(text=>{const n=E('text',{},caption);n.textContent=text;return n});
  const referenceRanges=E('g',{'data-reference-paired-ranges':c.id},group);
  const parsed=new DOMParser().parseFromString(c.svg,'image/svg+xml').documentElement;
  if(parsed.querySelector('parsererror,image'))throw Error('Expected native vector notation: '+c.id);
  const music=E('g',{id:parsed.id,'data-comparison-score':c.id,color:c.color,fill:c.color},group);
  // No nested SVG viewport: actual browser bounds include full labels/lyrics.
  for(const node of [...parsed.children])music.append(document.importNode(node,true));
  // Pair fills are behind notation and its title, including side captions
  // whose real bounds overlap the highlighted reference range.
  group.append(caption);
  for(const n of music.querySelectorAll('g.mNum'))if(!(c.preserved_measure_numbers||[]).includes(n.textContent.trim()))n.remove();
  if(c.reference_staff_ids){for(const st of music.querySelectorAll('g.staff'))if(!c.reference_staff_ids.includes(st.id))st.remove();for(const n of music.querySelectorAll('g.grpSym,g.barLine,g.system>path'))n.remove();}
  const quoteNodes=new Map([...music.querySelectorAll('[id]')].map(n=>[n.id,n])),findRef=id=>quoteNodes.get(id)||[...quoteNodes.values()].find(n=>n.id.endsWith('-'+id)),points=[];
  for(const binding of c.correspondences||[]){
   const ref=findRef(binding.ref_id),main=mainNodes.get(geometry.get(binding.score_id)?.svg_id);
   if(!ref||!main)throw Error('Missing comparison note '+c.id+' '+JSON.stringify(binding));
   const rb=box(ref.querySelector('.notehead')||ref,music),mb=box(main.querySelector('.notehead')||main,world);
   points.push({source:(rb.x+rb.r)/2,target:(mb.x+mb.r)/2,ref,main,staff:geometry.get(binding.score_id)?.staff||c.anchor_staff,...binding});
  }
  points.sort((a,b)=>a.source-b.source);
  for(let i=1;i<points.length;i++)if(!sidebar&&points[i].target<points[i-1].target)throw Error('Non-monotone comparison '+c.id);
  const originalBox=visibleBounds(music),fallback=c.native_x-originalBox.x;
  function warp(x){if(sidebar)return x;if(!points.length)return x+fallback;if(x<=points[0].source)return points[0].target+x-points[0].source;if(x>=points.at(-1).source)return points.at(-1).target+x-points.at(-1).source;const i=points.findIndex(p=>p.source>=x),a=points[i-1],b=points[i];return a.target+(b.target-a.target)*(x-a.source)/(b.source-a.source)}
  const candidates=[...music.querySelectorAll('g.note,g.clef,g.keySig,g.meterSig,g.label,g.labelAbbr,g.dir,g.tempo,g.dynam,g.syl,g.breath,g.artic')].filter(n=>!n.closest('defs'));
  const fixed=candidates.filter(n=>!candidates.some(p=>p!==n&&p.contains(n))),owned=n=>fixed.some(p=>p===n||p.contains(n)),records=[];
  function record(node,rigid){
   const matrix=m=>m?new DOMMatrix([m.a,m.b,m.c,m.d,m.e,m.f]):new DOMMatrix();
   const b=box(node,music),parent=matrix(music.getCTM()).inverse().multiply(matrix(node.parentNode.getCTM())),own=matrix(node.transform?.baseVal?.consolidate()?.matrix),head=node.querySelector?.('.notehead'),hb=head?box(head,music):null,anchor=hb?(hb.x+hb.r)/2:(b.x+b.r)/2;
   const sx=rigid||b.r-b.x<1?1:(warp(b.r)-warp(b.x))/(b.r-b.x),dx=rigid?warp(anchor)-anchor:warp(b.x)-sx*b.x;
   records.push({node,m:parent.inverse().multiply(new DOMMatrix([sx,0,0,1,dx,0])).multiply(parent).multiply(own)});
  }
  // Notes are rigid units; only spacing and connecting notation are stretched.
  for(const n of fixed)record(n,true);
  for(const n of music.querySelectorAll('path,polygon,polyline,line,rect,circle,ellipse,use,text'))if(!n.closest('defs')&&!owned(n))record(n,['use','text'].includes(n.localName));
  for(const{node,m}of records)node.setAttribute('transform',`matrix(${m.a} ${m.b} ${m.c} ${m.d} ${m.e} ${m.f})`);
  function translateNative(n,dx,dy=0){
   const matrix=m=>new DOMMatrix([m.a,m.b,m.c,m.d,m.e,m.f]),p=matrix(music.getCTM().inverse().multiply(n.parentNode.getCTM())),own=n.transform.baseVal.consolidate()?.matrix;
   const m=p.inverse().multiply(new DOMMatrix([1,0,0,1,dx,dy])).multiply(p).multiply(own?matrix(own):new DOMMatrix());
   n.setAttribute('transform',`matrix(${m.a} ${m.b} ${m.c} ${m.d} ${m.e} ${m.f})`);
  }
  const lyricLayout=[];
  const sourceColorAudit=[];
  for(const h of c.source_note_colors||[]){
   const selected=new Set(h.ids.map(findRef));if(selected.has(undefined))throw Error('Missing source color note '+c.id);
   for(const n of selected){n.style.color=n.style.fill=h.color;}
   // Preserve the neutral beam underneath; overlay only the verified run,
   // including complete stems. A mixed beam is not recolored wholesale.
   for(const beam of music.querySelectorAll('g.beam')){
    const notes=[...beam.querySelectorAll('g.note')],colored=notes.filter(n=>selected.has(n));if(!colored.length)continue;
    const columns=colored.map(n=>box(n.querySelector('g.stem')||n.querySelector('.notehead')||n,music)),lo=Math.min(...columns.map(b=>b.x)),hi=Math.max(...columns.map(b=>b.r));
    for(const shape of [...beam.children].filter(n=>['polygon','path','polyline'].includes(n.localName))){
     if(colored.length===notes.length){shape.style.color=shape.style.fill=h.color;continue;}
     const clipId=uid+'-'+c.id+'-color-'+sourceColorAudit.length+'-'+shape.parentNode.id,cp=E('clipPath',{id:clipId,clipPathUnits:'userSpaceOnUse'},defs),parent=music.getCTM().inverse().multiply(beam.getCTM()),inv=parent.inverse(),a=new DOMPoint(lo,-10000).matrixTransform(inv),b=new DOMPoint(hi,10000).matrixTransform(inv);
     E('rect',{x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(b.x-a.x),height:Math.abs(b.y-a.y)},cp);
     const overlay=shape.cloneNode(true);overlay.removeAttribute('id');overlay.setAttribute('clip-path',`url(#${clipId})`);overlay.style.color=overlay.style.fill=h.color;beam.append(overlay);
    }
   }
   sourceColorAudit.push({color:h.color,note_ids:h.ids,notes:selected.size});
  }
  const referenceHighlights=(c.reference_highlights||[]).map(h=>{
   const ns=h.ids.map(findRef);if(ns.some(n=>!n))throw Error('Missing source highlight '+c.id);
   const b=union(ns.map(n=>box(n,music))),rect=E('rect',{x:b.x-70,y:b.y-70,width:b.r-b.x+140,height:b.b-b.y+140,fill:h.color,'fill-opacity':.14,stroke:'none','data-source-highlight':c.id},music);music.insertBefore(rect,music.firstChild);return{...h,rect,nodes:ns};
  });
  const bounds=visibleBounds(music),pad=50;c.native_height=bounds.height+pad*2;
  if(sidebar){c.sidebar_scale=Math.min((c.sidebar_staff_height||72)/720,((c.sidebar_width||865)-32)/bounds.width);c.sidebar_height=bounds.height*c.sidebar_scale;const staffHeight=720*c.sidebar_scale;if(staffHeight<(c.sidebar_minimum_staff_height||48)-.01)throw Error('Unreadable sidebar staff size '+c.id+': '+staffHeight);P.blocks[c.host_block].height=c.sidebar_height+32;}
  const targetRanges=E('g',{'data-comparison-target':c.id},pairBack),links=E('g',{'data-comparison-links':c.id},pairLinks);
  const pairGroups=(c.pair_groups||[{id:'confirmed',ref_ids:points.map(p=>p.ref_id)}]).map(g=>{
   const pp=g.score_ids?g.score_ids.map(id=>({score_id:id,staff:geometry.get(id)?.staff,main:mainNodes.get(geometry.get(id)?.svg_id)})):points.filter(p=>g.ref_ids.includes(p.ref_id)),byStaff=new Map();
   const refNodes=g.score_ids?g.ref_ids.map(findRef):null;if(refNodes?.some(n=>!n)||pp.some(p=>!p.main))throw Error('Missing exact comparison range '+c.id);
   for(const p of pp){const k=g.target_scope==='individual-original-notes'?p.score_id:p.staff;if(!byStaff.has(k))byStaff.set(k,[]);byStaff.get(k).push(p)}
   return{g,points:pp,refNodes,refRect:E('rect',{},referenceRanges),targets:[...byStaff.values()].map(ps=>({points:ps,rect:E('rect',{},targetRanges)})),path:E('path',{fill:'none',stroke:g.pair_style?.stroke||c.color,'stroke-width':2,'stroke-opacity':.9,'stroke-linecap':'round','stroke-linejoin':'round'},links)};
  });
  return{c,row,rowRect,mask,group,caption,captionLines,music,bounds,pad,points,lyricLayout,targetRanges,links,pairGroups,referenceHighlights,sourceColorAudit};
 });
 function sidebarApproach(rb,music,full){
  const obstacles=[...music.querySelectorAll('use,path,polygon,polyline,line,rect,circle,ellipse,text')].filter(n=>!n.closest('defs')&&!n.hasAttribute('data-source-highlight')).map(n=>box(n,root));
  const padding=3,hit=(a,b,o)=>Math.max(a.x,b.x)>=o.x-padding&&Math.min(a.x,b.x)<=o.r+padding&&Math.max(a.y,b.y)>=o.y-padding&&Math.min(a.y,b.y)<=o.b+padding;
  const clear=ps=>ps.slice(1).every((b,i)=>obstacles.every(o=>!hit(ps[i],b,o))),left=full.x-16,candidates=[];
  for(const f of [.5,.2,.8]){const y=rb.y+(rb.b-rb.y)*f;candidates.push([{x:rb.x,y},{x:left,y}]);}
  for(const side of ['top','bottom'])for(const f of [.5,.2,.8,.05,.95]){const x=rb.x+(rb.r-rb.x)*f,y=side==='top'?rb.y:rb.b,outer=side==='top'?full.y-12:full.b+12;candidates.push([{x,y},{x,y:outer},{x:left,y:outer}]);}
  const chosen=candidates.filter(clear).sort((a,b)=>a.slice(1).reduce((v,p,i)=>v+Math.hypot(p.x-a[i].x,p.y-a[i].y),0)-b.slice(1).reduce((v,p,i)=>v+Math.hypot(p.x-b[i].x,p.y-b[i].y),0))[0];
  return chosen?{points:chosen,port:chosen.at(-1),source_range:rb,clearance:padding}:{points:[],port:null,source_range:rb,error:'no-clear-quote-exit'};
 }
 let last=[];
 function draw(F){
  const wm=root.getCTM().inverse().multiply(world.getCTM());last=[];sidebarAnchors.clear();if(actor.guidePaperLayers)actor.guidePaperLayers.panel.insertBefore(sidebarLayer,actor.guidePaperLayers.links);else root.insertBefore(sidebarLayer,actor.readingLine);
  for(const{c,row,rowRect,mask,group,caption,captionLines,music,bounds,pad,points,lyricLayout,targetRanges,links,pairGroups,referenceHighlights,sourceColorAudit}of items){
   const sidebar=c.placement==='sidebar',paperSlots=actor.incrementalReading?actor.incrementalReading.figureSlots((actor.sidebarFigureSlots||[]).filter(v=>v.id===c.id),F.seconds):(actor.sidebarFigureSlots||[]).filter(v=>v.id===c.id).map(v=>({...v,alpha:ease((F.seconds-v.from-.35)/.35)*(1-ease((F.seconds-v.to)/.35))})).sort((a,b)=>b.alpha-a.alpha),paperSlot=paperSlots[0];
   const scale=sidebar?c.sidebar_scale:c.fixed_display_scale||Math.abs(wm.a),musicX=sidebar?(paperSlot?.x||2810)+16-bounds.x*scale:wm.e+(Math.abs(wm.a)-scale)*(c.native_x||0);
   const slot=sidebar?(paperSlot?{y:paperSlot.top,height:c.sidebar_height+32}:null):actor.referenceSlots?.get(c.id),alpha=sidebar?(paperSlot?.alpha||0):ease((F.seconds-c.from)/.6)*(1-ease((F.seconds-c.to)/.35))*(F.weights[c.anchor_staff]||0);
   for(const n of [targetRanges,links]){n.style.visibility=alpha>0&&slot?'visible':'hidden';n.style.opacity=alpha}
   if(alpha<=0||!slot){row.style.visibility='hidden';group.style.visibility='hidden';continue}
   for(const n of [rowRect,mask]){n.setAttribute('y',slot.y-(sidebar?16:(c.row_inset_px??30)));n.setAttribute('height',slot.height)}
   row.style.visibility='visible';group.style.visibility='visible';group.style.opacity=alpha;
   const x=scale*bounds.x+musicX,y=slot.y;
   music.setAttribute('transform',`translate(${musicX} ${y+((sidebar?0:pad)-bounds.y)*scale}) scale(${scale})`);
   const lineHeight=(c.caption_size||30)*1.25,captionWidth=Math.max(0,...captionLines.map(n=>n.getComputedTextLength())),rightCaption=c.caption_side==='right',upperClearance=c.caption_vertical==='source-upper-clearance',captionX=rightCaption?x+bounds.width*scale:x-captionWidth-24,captionY=upperClearance?y-(c.row_inset_px??30)+(c.caption_size||30)*7/6:y+(pad+bounds.height/2)*scale-(Math.max(1,captionLines.length)-1)*lineHeight/2+10;
   captionLines.forEach((n,i)=>{n.setAttribute('x',captionX);n.setAttribute('y',captionY+i*lineHeight);n.setAttribute('text-anchor',rightCaption?'end':'start')});
   for(const h of referenceHighlights||[]){const active=F.seconds>=h.from&&F.seconds<h.to;h.rect.style.display=active?'':'none';for(const n of h.nodes)n.style.color=n.style.fill=active?h.color:'';}
   const pairing=[];
   for(const pg of pairGroups){
    const refNodes=pg.refNodes|| (pg.g.reference_scope==='complete-hypothesis'?[...music.querySelectorAll('g.note')]:pg.points.map(p=>p.ref)),rb=expand(pg.g.reference_scope==='complete-quote'?box(music,root):union(refNodes.map(n=>box(n,root))));
    // A phrase slur can sit above the individual note groups. Include its
    // real upper extent so a short approach never cuts through that slur.
    if(!sidebar)rb.y=Math.min(rb.y,y+pad*scale-7);
    const pairStyle=pg.g.pair_style||{fill:c.color,stroke:c.color};paintRect(pg.refRect,rb,pairStyle);
    const targets=pg.targets.map(t=>{const b=expand(union(t.points.map(p=>box(p.main,root))));paintRect(t.rect,b,pairStyle);t.rect.style.visibility=(F.weights[t.points[0].staff]||0)>.6?'visible':'hidden';return{...t,b}});
    // The hypothetical inner line also quotes originals from a distant cello
    // staff. Keep all four real-note boxes, but connect the adjacent violin
    // representative rather than drawing through the intervening live staves.
    const connected=targets.filter(t=>!pg.g.connect_staff||t.points[0].staff===pg.g.connect_staff),t=connected[0];
    const approach=sidebar?sidebarApproach(rb,music,{x:x,r:x+bounds.width*scale,y,b:y+c.sidebar_height}):null;
    if(sidebar){const a={...approach,figure_id:c.id,group:pg.g.id};sidebarAnchors.set(c.id,a);sidebarAnchors.set(c.id+'::'+pg.g.id,a);}
    const route=sidebar?{path:'',kind:'shared-budget-sidebar-relation',approach}:t?shortRoute(t.b,rb,shortInk(F,t.b,rb,music,captionLines),scale):{path:'',kind:'no-target'},path=route.path;
    pg.path.setAttribute('d',path);pg.path.setAttribute('stroke',pairStyle.stroke);
    pairing.push({id:pg.g.id,color:c.color,pair_style:pairStyle,route,reference_scope:pg.g.reference_scope||'confirmed-notes',reference_bounds:rb,target_bounds:targets.map(t=>({bounds:t.b,score_ids:t.points.map(p=>p.score_id)})),connected_score_ids:t?.points.map(p=>p.score_id)||[],path,unconfirmed_reference_notes_bound_to_score:false});
   }
   last.push({id:c.id,placement:c.placement||'score',staff_height_px:720*scale,main_staff_height_px:(S.geometry.staves.find(s=>s.id===c.anchor_staff)?.height||720)*Math.abs(wm.d),sidebar_anchor:sidebarAnchors.get(c.id)||null,source_note_colors:sourceColorAudit,preserved_measure_numbers:[...music.querySelectorAll('g.mNum')].map(n=>({text:n.textContent.trim(),bounds:box(n,root)})),caption:c.caption,caption_lines:captionLines.map(n=>n.textContent),caption_layout:rightCaption?'source-right-aligned-upper-clearance':'left-beside-notation',caption_bounds:captionLines.length?box(caption,root):null,caption_lines_bounds:captionLines.map(n=>box(n,root)),caption_nearby_controls:upperClearance?[...music.querySelectorAll('g.dir,g.tempo,g.hairpin,g.dynam,g.slur')].map(n=>({id:n.id,kind:n.getAttribute('class'),text:n.textContent.trim(),bounds:box(n,root)})):[],x,y,width:bounds.width*scale,height:c.native_height*scale,row_reserved_height:slot.height,row_padding_px:c.row_padding_px??85,opacity:alpha,source_pages:c.source_pages,anchor_staff:c.anchor_staff,fixed_native_anchor:true,raster_images:0,staff_scale:scale,reference_note_count:music.querySelectorAll('g.note').length,reference_lyrics:[...music.querySelectorAll('g.syl')].map(n=>n.textContent.trim()),lyric_layout:lyricLayout,pairing,matched_note_columns:points.map(p=>{const rb=box(p.ref.querySelector('.notehead')||p.ref,root),mb=box(p.main.querySelector('.notehead')||p.main,root),rx=(rb.x+rb.r)/2,mx=(mb.x+mb.r)/2;return{reference:p.ref_id,score:p.score_id,x:wm.a*p.target+wm.e,reference_x:rx,score_x:mx,alignment_error_px:rx-mx}}),actual_browser_bounds:{x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height}});
  }
 }
 return{draw,audit:()=>last,anchor:id=>sidebarAnchors.get(id)};
}

const nativeComparisons=installNativeComparisons(actor,S);
 const NS='http://www.w3.org/2000/svg',P=S.guide_payload,root=actor.root,paper='#FAF8F1';
 const E=(tag,a={},parent)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(a))n.setAttribute(k,v);parent?.append(n);return n};
 const ease=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
 const box=n=>{if(!n?.getCTM())return null;const b=n.getBBox(),m=root.getCTM().inverse().multiply(n.getCTM()),pts=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));return{x:Math.min(...pts.map(p=>p.x)),r:Math.max(...pts.map(p=>p.x)),y:Math.min(...pts.map(p=>p.y)),b:Math.max(...pts.map(p=>p.y))}};
 const union=bs=>({x:Math.min(...bs.map(v=>v.x)),r:Math.max(...bs.map(v=>v.r)),y:Math.min(...bs.map(v=>v.y)),b:Math.max(...bs.map(v=>v.b))});
 const defs=E('defs',{},root),uid='connection-'+P.id;
 const cl=E('clipPath',{id:uid+'-clip'},defs);E('rect',{x:390,y:65,width:2250,height:1748},cl);
 const backdrop=E('g',{'clip-path':'url(#'+uid+'-clip)'},null);root.insertBefore(backdrop,actor.readingLine);
 const scoreLink=E('g',{},null);root.insertBefore(scoreLink,actor.readingLine);
 const markers=E('g',{'clip-path':'url(#'+uid+'-clip)'},root);
 const fade=E('linearGradient',{id:uid+'-fade',gradientUnits:'userSpaceOnUse',x1:2620,x2:2740},defs);
 E('stop',{offset:0,'stop-color':paper,'stop-opacity':0},fade);E('stop',{offset:1,'stop-color':paper,'stop-opacity':1},fade);
 const panel=E('g',{'data-reading-panel':P.id},root);
 E('rect',{x:2620,y:0,width:120,height:1830,fill:'url(#'+uid+'-fade)'},panel);E('rect',{x:2740,y:0,width:1100,height:1830,fill:paper},panel);
 const text=E('g',{'font-family':'Han'},panel),links=E('g',{},panel),measure=E('text',{visibility:'hidden',x:-9999,y:-9999},text);
 actor.guidePaperLayers={panel,links};
 const X=2810,W=P.typography?.column_width||945,groups=[],pages=[];actor.sidebarFigureSlots=[];
 const stageSpecs=P.reading_stages?.length?P.reading_stages:[{id:'single',from:P.panel_in,to:P.panel_out,block_indices:P.blocks.map((b,i)=>b.kind==='score_figure_reference'?null:i).filter(i=>i!==null)}];
 const pageAt=t=>pages.find(p=>t>=p.from&&t<p.to)||pages.at(-1);
 function width(t,size,weight=400){measure.setAttribute('font-size',size);measure.setAttribute('font-weight',weight);measure.textContent=t;return measure.getComputedTextLength()}
 function wrap(str,size,keys){
  const chars=Array.from(str),style=chars.map(()=>null);
  for(const key of keys){if(!key)continue;let at=0,occurrence=0;while((at=str.indexOf(key,at))>=0){const n=Array.from(str.slice(0,at)).length;for(let j=n;j<n+Array.from(key).length;j++)style[j]={key,occurrence};at+=key.length;occurrence++}}
  const lines=[];let line=[],len=0;
  chars.forEach((c,i)=>{if(c==='\n'){lines.push(line);line=[];len=0;return}const w=width(c,size,style[i]?500:400);if(line.length&&len+w>W){lines.push(line);line=[];len=0}line.push({c,key:style[i]?.key||null,occurrence:style[i]?.occurrence??null});len+=w});if(line.length)lines.push(line);
  for(let i=1;i<lines.length;i++)if(/^[，。；：！？）》、…);,!?]/.test(lines[i][0]?.c||'')&&lines[i-1].length>2)lines[i].unshift(lines[i-1].pop());
  if(lines.length>1&&lines.at(-1).length<4)while(lines.at(-1).length<4&&lines.at(-2).length>10)lines.at(-1).unshift(lines.at(-2).pop());
  if(lines.flat().map(c=>c.c).join('')!==str.replace(/\n/g,''))throw Error('Lost source text');return lines;
 }
 let yy=146,maxBottom=146;const fixedBlockTops=new Map();
 for(const stage of stageSpecs){
 const page={...stage,ordinal:pages.length,g:E('g',{'data-reading-stage':stage.id},text),blocks:new Map(),alpha:0};pages.push(page);yy=146;
 if(stage.section_text){E('text',{x:X,y:101,'font-size':32,fill:'#59645F'},page.g).textContent=stage.section_text;}
 for(const index of stage.block_indices){
  const b=P.blocks[index];if(b.fixed_top_from_stage){if(fixedBlockTops.has(index))yy=Math.max(yy,fixedBlockTops.get(index));else fixedBlockTops.set(index,yy)}const top=yy,g=E('g',{'data-block':index},page.g),hot=[];
  const base=P.palette[b.theme]||'#38443E';
  if(b.kind==='native_score'){actor.sidebarFigureSlots.push({id:b.figure_id,block:index,x:X,top:yy+16,height:b.height-32,from:stage.from,to:stage.to,ordinal:page.ordinal});yy+=b.height+(b.gap_after??28);
  }else if(b.kind==='native_table'){
   E('text',{x:X,y:yy+32,'font-size':32,fill:'#59645F'},g).textContent=b.text;yy+=58;
   const svg=new DOMParser().parseFromString(b.svg,'image/svg+xml').documentElement;if(svg.querySelector('parsererror,image'))throw Error('Invalid inline native figure');svg.setAttribute('x',X);svg.setAttribute('y',yy);svg.setAttribute('width',b.width||865);svg.setAttribute('height',b.height);const figure=document.importNode(svg,true);g.append(figure);
   for(const row of figure.querySelectorAll('[data-table-row]')){const cells=[...row.children],widths=cells.map(c=>c.querySelector('text').getComputedTextLength()),gap=(206-widths.reduce((a,b)=>a+b,0))/Math.max(1,cells.length-1);if(gap<3)throw Error('Inline table cell overflow: '+widths);let xx=Number(row.dataset.columnX)+5;cells.forEach((c,i)=>{const t=c.querySelector('text'),r=c.querySelector('rect');t.setAttribute('x',xx);if(r){r.setAttribute('x',xx-2);r.setAttribute('width',widths[i]+4)}xx+=widths[i]+gap});}yy+=b.height+(b.gap_after??28);
  }else if(b.kind==='image'){
   if(b.text){E('text',{x:X,y:yy+27,'font-size':P.typography?.caption||32,fill:'#647168'},g).textContent=b.text;yy+=48;}
   for(const im of b.images){E('image',{x:X,y:yy,width:W,height:im.height,href:im.uri,preserveAspectRatio:'xMidYMid meet'},g);yy+=im.height+6}yy+=22;
  }else{
   const compact=P.compact??false,size=P.typography?.[b.kind]??(b.kind==='footnote'?(compact?30:34):b.kind==='harmony'?34:b.kind==='quote'?46:b.kind==='context'?40:(compact?42:46)),leading=size*(P.typography?.leading||1.37);
   if(['footnote','harmony'].includes(b.kind)){E('line',{x1:X,x2:X+W,y1:yy-8,y2:yy-8,stroke:'#D9D6CD','stroke-width':1.5},g);yy+=14}
   for(const line of wrap(b.text,size,b.keywords||[])){
    const n=E('text',{x:X,y:yy+size,'font-size':size,fill:b.kind==='footnote'?'#667068':b.kind==='quote'?base:'#303B36'},g);let run='',key=null,occurrence=null;
    const flush=()=>{if(!run)return;const identity=Object.hasOwn(b.keyword_themes||{},key)?b.keyword_themes[key]:b.theme,t=E('tspan',{fill:key?(b.keyword_colors?.[key]||P.palette[identity]||'#38443E'):'inherit','font-weight':key?500:400},n);t.textContent=run;if(key){t.dataset.key=key;t.dataset.occurrence=occurrence;t.dataset.baseColor=b.keyword_colors?.[key]||P.palette[identity]||'#38443E';hot.push(t)}run=''};
    for(const c of line){if(c.key!==key||c.occurrence!==occurrence){flush();key=c.key;occurrence=c.occurrence}run+=c.c}flush();yy+=leading;
   }
   yy+=b.kind==='footnote'?(P.typography?.footnote_gap??18):(P.typography?.paragraph_gap??28);
  }
  const item={b,g,index,page,top,bottom:yy,hot};groups.push(item);page.blocks.set(index,item);
 }
 if(yy>1798)throw Error('Reading column overflow '+P.id+'/'+stage.id+': '+yy);
 page.bottom=yy;maxBottom=Math.max(maxBottom,yy);
 }
 const persistentBlocks=[];
 if(P.stable_reading_blocks&&!P.incremental_sidebar){
  const tracks=new Map();for(const item of groups){const key=item.index+'|'+item.top;let runs=tracks.get(key);if(!runs){runs=[];tracks.set(key,runs)}let run=runs.at(-1);if(!run||run.items.at(-1).page.to!==item.page.from){run={items:[]};runs.push(run)}run.items.push(item)}
  for(const runs of tracks.values())for(const run of runs)if(run.items.length>1){const first=run.items[0],last=run.items.at(-1),node=first.g.cloneNode(true);text.append(node);for(const item of run.items)item.g.style.visibility='hidden';persistentBlocks.push({node,from:Math.max(first.page.from,first.b.reveal_from??-Infinity),to:last.page.to,index:first.index,first:first.page.ordinal===0,last:last.page.ordinal===pages.length-1,originalNodes:run.items.map(item=>item.g)})}
 }
 for(const slot of P.incremental_sidebar?[]:actor.sidebarFigureSlots){let prior=actor.sidebarFigureSlots.find(s=>s!==slot&&s.id===slot.id&&s.top===slot.top&&s.to===slot.from);if(prior){slot.from=prior.from;prior.to=slot.to;}}
 const incrementalSidebar=P.incremental_sidebar?incrementalReading({E,ease,text,pages,groups,P,X,W}):null;actor.incrementalReading=incrementalSidebar;
 const windowMode=Array.isArray(P.connection_windows),jointMode=windowMode&&!!P.routing_reference_frames?.length,pageById=new Map(pages.map(p=>[p.id,p]));
 const connectionWindows=(P.connection_windows||[]).map((w,i)=>{
  const inherited=P.cues[w.cue_index]||{};let page=pageById.get(w.page_id);const persistent=persistentBlocks.find(p=>p.index===w.block);if(P.incremental_sidebar&&P.blocks[w.block]?.bridge_id){const sourcePage=page;page=Object.create(sourcePage);Object.defineProperty(page,'alpha',{get:()=>incrementalSidebar.blockAlpha(w.block)});}else if(P.blocks[w.block]?.bridge_id&&persistent){page=Object.create(page);Object.defineProperty(page,'alpha',{get:()=>Number(persistent.node.style.opacity)})}const full_at=w.full_at??w.from+.65,to=w.to??w.hold_until+.35;
  if(!page)throw Error('Unknown connection page '+w.page_id);
  if(![w.from,full_at,w.hold_until,to].every(Number.isFinite)||full_at<w.from||w.hold_until<full_at||to<w.hold_until)throw Error('Invalid connection window '+w.index);
  const c={...inherited,...w,index:w.index??i,full_at,to,page};
  if(w.target_id)c.link_targets=null;
  c.semanticGroup=String(w.semantic_group??JSON.stringify([page.id,c.block,c.keyword,c.keyword_occurrence||0,c.theme]));
  c.semanticKey=JSON.stringify([page.id,c.block,c.keyword,c.keyword_occurrence||0,c.theme,c.target_id]);return c;
 });
 if(new Set(connectionWindows.map(w=>w.index)).size!==connectionWindows.length)throw Error('Duplicate connection window index');
 const windowProgress=(w,t)=>{const grow=Math.min(.65,w.full_at-w.from),retreat=Math.min(.35,w.to-w.hold_until);return(grow?ease((t-w.from)/grow):+(t>=w.from))*(retreat?1-ease((t-w.hold_until)/retreat):+(t<w.to))};
 // Colour the complete overlap graph once. Slots belong to the source track,
 // never to the current frame's active subset; appearing links cannot push
 // an already visible line to another corridor.
 for(const kind of jointMode?[]:['paper','score']){
  const nodes=new Map();
  for(const w of connectionWindows){const staff=kind==='score'?P.spans.find(s=>s.id===w.target_id)?.staff:'all',colour=P.palette[w.theme]||w.theme,key=JSON.stringify([w.page.id,staff,colour]);let n=nodes.get(key);if(!n){n={page:w.page.id,staff,windows:[],slot:0};nodes.set(key,n)}n.windows.push(w);}
  const placed=[];
  for(const n of [...nodes.values()].sort((a,b)=>Math.min(...a.windows.map(w=>w.from))-Math.min(...b.windows.map(w=>w.from)))){
   const used=new Set(placed.filter(p=>p.page===n.page&&p.staff===n.staff&&p.windows.some(a=>n.windows.some(b=>a.from<b.to&&b.from<a.to))).map(p=>p.slot));while(used.has(n.slot))n.slot++;
   for(const w of n.windows)w[kind+'Slot']=n.slot;placed.push(n);
  }
 }
 const byid=new Map(S.geometry.notes.map(n=>[n.id,n]));
 const nodes=new Map([...actor.scoreClip.querySelectorAll('[id]')].map(n=>[n.id.replace(/^scene\d+-/,''),n]));
 const mapped=id=>nodes.get(byid.get(id)?.svg_id);
 const staffLabels=new Map([...actor.labels.querySelectorAll('[data-staff]')].map(n=>[n.dataset.staff,n]));
 const rows=P.spans.map(s=>({s,nodes:s.ids.map(mapped).filter(Boolean),band:E('rect',{rx:9,'data-material-range':s.id,fill:'#A7A194',stroke:'none'},backdrop)}));
 const controlEntries=(S.geometry.controls||[]).filter(c=>c.staves.length===1).map(c=>({staff:c.staves[0],node:nodes.get(c.svg_id)})).filter(c=>c.node);
 const staffGeometry=new Map(S.geometry.staves.map(s=>[s.id,s]));
 // Pick the source-facing side once in native coordinates, before the first
 // animated draw. This priority is identical for a full render and a chunk.
 // It never changes merely because the opposite route becomes shorter.
 for(const r of rows){const bs=r.nodes.map(box).filter(Boolean),st=staffGeometry.get(r.s.staff);if(bs.length&&st){const b=union(bs);r.nativeBounds=b;r.nativeRight=b.r;r.routeSide=st.y-b.y<=b.b-st.y?'upper':'lower';}}
 const measureGeometry=new Map(S.geometry.measures.map(m=>[m.svg_id,m]));
 const staffGroups=new Map(S.geometry.staves.map(s=>[s.id,s.svg_ids.map(id=>nodes.get(id)).filter(Boolean).map(node=>({node,measure:measureGeometry.get(node.closest('g.measure')?.id.replace(/^scene\d+-/,''))}))]));
 // Bar lines live alongside staff groups, so staff-only obstacle walks miss
 // them. They are hard obstacles for source names, not walls for gap routing.
 const barlineGroups=[...actor.scoreClip.querySelectorAll('g.barLine,g.grpSym')].map(node=>({node,measure:measureGeometry.get(node.closest('g.measure')?.id.replace(/^scene\d+-/,''))}));
 const onScreen=(b)=>b&&b.r>395&&b.x<2640&&b.b>65&&b.y<1810;
 const line=E('path',{fill:'none','stroke-width':3.6,'stroke-linecap':'round','stroke-linejoin':'round'},scoreLink);
 const rightLine=E('path',{fill:'none','stroke-width':3.6,'stroke-linecap':'round','stroke-linejoin':'round'},links);
 const underline=E('path',{fill:'none','stroke-width':5,'stroke-linecap':'round'},links);
 const badge=E('text',{'font-family':'Han','font-size':32,'font-weight':500,stroke:paper,'stroke-width':8,'paint-order':'stroke fill'},markers);
 const endpoint=E('circle',{r:5,stroke:paper,'stroke-width':2},markers);
 const terminalStub=E('path',{fill:'none','stroke-width':3.2,'stroke-linecap':'round'},markers);
 const connectorLayers=[{line,rightLine,underline,badge,endpoint,terminalStub}];
 const connectorCount=windowMode?Math.max(1,...connectionWindows.map(w=>connectionWindows.filter(v=>v.from<=w.from&&v.to>w.from).length)):Math.max(1,...P.cues.map(c=>c.link_targets?.length||1));
 for(let i=1;i<connectorCount;i++)connectorLayers.push({
  line:E('path',{fill:'none','stroke-width':3.6,'stroke-linecap':'round','stroke-linejoin':'round'},scoreLink),
  rightLine:E('path',{fill:'none','stroke-width':3.6,'stroke-linecap':'round','stroke-linejoin':'round'},links),
  underline:E('path',{fill:'none',stroke:'none','stroke-width':5,'stroke-linecap':'round'},links),
  badge:E('text',{},markers),endpoint:E('circle',{r:5,stroke:paper,'stroke-width':2},markers),
  terminalStub:E('path',{fill:'none','stroke-width':3.2,'stroke-linecap':'round'},markers)});
 const connectorPaintGroups=new Map();
 function connectorPaint(layer,colour,page,alpha){
  const key=colour+'|'+page.id;let paint=connectorPaintGroups.get(key);
  if(!paint){paint={score:E('g',{'data-connector-colour':colour,'data-page':page.id},scoreLink),paper:E('g',{'data-connector-colour':colour,'data-page':page.id},links),marks:E('g',{},markers),alpha:0};connectorPaintGroups.set(key,paint)}
  paint.alpha=Math.max(paint.alpha,alpha);for(const n of [paint.score,paint.paper,paint.marks])n.style.opacity=paint.alpha;
  for(const [name,n]of Object.entries(layer)){const parent=name==='line'?paint.score:['rightLine','underline'].includes(name)?paint.paper:paint.marks;if(n.parentNode!==parent)parent.append(n)}
  return paint;
 }
 // Sparse, source-bound representatives cover the material identities in
 // each excerpt. A later section owns a new fixed instance; no label is
 // reassigned or moved in response to the cursor or viewport.
 const representatives=P.label_representatives;
 const labelRows=representatives.map(ref=>({ref,row:rows.find(r=>r.s.id===ref.target_id)})).filter(({row:r})=>r&&r.s.label!==null&&r.s.label!=='');
 let displayClockReady=false,lifetimeProbeState=null;
 const labelVisibility=(item,t)=>{if(lifetimeProbeState?.labels?.includes(item.labelIndex))return 1;const w=displayClockReady?item.displayWindow:item.window;return ease((t-w[0]+.2)/.4)*(1-ease((t-w[1]+.2)/.4));};
 const labelMeasure=document.createElement('canvas').getContext('2d');
 const motifLabels=labelRows.map(({row,ref},labelIndex)=>{
  const theme=row.s.theme,size=P.label_typography?.sizes?.[ref.target_id||row.s.id]??42,weight=400,paddingX=P.label_typography?size*.24:12,paddingY=P.label_typography?size*.16:5,group=E('g',{'data-source-motif':theme,'data-source-span':row.s.id},markers),back=E('rect',{fill:P.palette[theme]||'#58645B',rx:P.label_typography?3:4,stroke:'none'},group),label=E('text',{'font-family':'Han','font-size':size,'font-weight':weight,fill:paper},group);label.textContent=row.s.label||P.labels[theme]||theme;
  labelMeasure.font=`${weight} ${size}px Han`;const ink=labelMeasure.measureText(label.textContent),ascent=ink.actualBoundingBoxAscent||size,descent=ink.actualBoundingBoxDescent||0;
  const reservedBand=P.label_space_decisions?.find(d=>d.target_id===(ref.target_id||row.s.id)&&d.from===ref.from),preferredRow=rows.find(r=>r.s.id===(reservedBand?.preferred_source_id||ref.preferred_source_id))||row;
  return{labelIndex,preferredSide:ref.preferred_side,placementRole:ref.placement_role,labelLines:ref.lines,displayWindow:[ref.display_from??ref.from,ref.display_to??ref.to],theme,row:preferredRow,singleLine:!!reservedBand?.single_line,representative_id:ref.target_id||row.s.id,bandStaff:reservedBand?.staff,bandSlot:reservedBand?.slot||0,candidateRows:(ref.candidate_ids||[]).map(id=>rows.find(r=>r.s.id===id)).filter(Boolean),group,back,label,size,width:width(label.textContent,size,weight),paddingX,paddingY,top:-ascent-paddingY,bottom:descent+paddingY,window:[ref.from,ref.to],anchor:null};
 }).filter(Boolean);
 const tempo=E('text',{x:410,y:48,'font-family':'Han','font-size':28,fill:'#5B645D'},root);
 // The blue time cursor must remain above the score, frames, markers and paper.
 root.append(actor.readingLine);
 const shapeCache=new WeakMap(),routeCache=new Map();
 // A cue must not start in a gap that is about to collapse. Resolve its side
 // from the complete absolute-time cohort track, not the chunk's first frame.
 // The .1 neighbour gate can change the current lane, but never this priority.
 const routeSides=new Map(),staffOrder=S.geometry.staves.map(s=>s.id);
 const cohortWeight=(id,t)=>Math.max(0,...(S.cohorts||[]).filter(c=>c.staves.includes(id)).map(c=>{const z=Math.max(0,Math.min(1,t<c.start?(t-c.start+4)/4:t>c.end?(c.end+4-t)/4:1));return z*z*z*(10+z*(-15+6*z))}));
 (windowMode?connectionWindows:P.cues).forEach((cue,i)=>{
  const start=windowMode?(cue.routing_layout_from??cue.from):cue.at,end=windowMode?(cue.routing_layout_to??cue.to):Math.min(P.panel_out,P.cues[i+1]?.at??P.panel_out)+.35,key=windowMode?'window-'+cue.index:i,edges=[start,end,...(S.cohorts||[]).flatMap(c=>[c.start-4,c.start,c.end,c.end+4]).filter(t=>t>start&&t<end)].sort((a,b)=>a-b),times=[...edges,...edges.slice(1).map((t,j)=>(t+edges[j])/2)];
  for(const ref of cue.link_targets||[cue]){
   const r=rows.find(r=>r.s.id===ref.target_id);if(!r)continue;const at=staffOrder.indexOf(r.s.staff);
   const volatility=side=>{const ids=new Set(),moving=new Set(),order=side==='upper'?staffOrder.slice(0,at).reverse():staffOrder.slice(at+1);for(const t of times){const id=order.find(id=>cohortWeight(id,t)>.1);ids.add(id||'edge');if(id&&cohortWeight(id,t)<.999)moving.add(id)}return Math.max(0,ids.size-1)+moving.size};
   const upper=volatility('upper'),lower=volatility('lower');routeSides.set(key+':'+ref.target_id,upper<lower?'upper':lower<upper?'lower':r.routeSide);
  }
 });
 const primitives='use,path,polygon,polyline,line,rect,circle,ellipse,text';
 function inkShape(node){
  let local=shapeCache.get(node);
  if(!local){
   const b=node.getBBox();if(!(b.width||b.height))return null;
   local={b:{x:b.x,y:b.y,width:b.width,height:b.height}};
   // Curved slurs, ties, hairpins and stems are sampled as thin actual ink;
   // their large bounding rectangles are NOT solid obstacles.
   if(node.localName==='path'&&node.getTotalLength){try{const length=node.getTotalLength(),count=Math.min(480,Math.max(2,Math.ceil(length/55)));local.points=[];for(let i=0;i<=count;i++){const p=node.getPointAtLength(length*i/count);local.points.push([p.x,p.y])}}catch{}}
   shapeCache.set(node,local);
  }
  // SVG text metrics can be recomputed at a new effective raster scale.
  // Paths are invariant; text bounds must reflect this actual frame rather
  // than whichever routing reference happened to populate the cache first.
  if(node.localName==='text'){const b=node.getBBox();local.b={x:b.x,y:b.y,width:b.width,height:b.height};}
  const ctm=node.getCTM();if(!ctm)return null;const m=root.getCTM().inverse().multiply(ctm),b=local.b;
  const transform=([x,y])=>({x:m.a*x+m.c*y+m.e,y:m.b*x+m.d*y+m.f});
  const corners=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(transform);
  const out={x:Math.min(...corners.map(p=>p.x)),r:Math.max(...corners.map(p=>p.x)),y:Math.min(...corners.map(p=>p.y)),b:Math.max(...corners.map(p=>p.y)),kind:'rect'};
  if(local.points){const pts=local.points.map(transform);out.kind='segments';out.segments=pts.slice(1).map((p,i)=>[pts[i],p]);out.pad=2+Math.min(2,Math.abs(m.a)*(parseFloat(node.getAttribute('stroke-width'))||13)/2)}
  return out;
 }
 function collectInk(F,target,left,right,includeBarlines=false){
  const wm=root.getCTM().inverse().multiply(actor.scoreClip.firstElementChild.getCTM()),nativeLeft=(left-wm.e)/wm.a,nativeRight=(right-wm.e)/wm.a,out=[],seen=new Set();
  const low=target.safeTop-90,high=target.safeBottom+90;
  function add(node,staff){if(seen.has(node))return;seen.add(node);let opacity=1;for(let n=node;n&&n!==root;n=n.parentElement){if(n.style?.display==='none'||['hidden','collapse'].includes(n.style?.visibility||n.getAttribute?.('visibility')))return;const a=n.style?.opacity||n.getAttribute?.('opacity');if(a!==null&&a!==undefined&&a!=='')opacity*=Number(a);}if(opacity<.03)return;const cs=getComputedStyle(node);if(cs.visibility==='hidden'||cs.display==='none'||(cs.fill==='none'&&cs.stroke==='none'))return;const v=inkShape(node);if(v&&v.r>left-8&&v.x<right+8&&v.b>low&&v.y<high)out.push({...v,staff,svg_id:node.id||node.closest('[id]')?.id})}
  for(const[staff,label]of staffLabels){
   const center=+label.getAttribute('y')-10;if((F.weights[staff]||0)<.1||Math.abs(center-target.center)>330)continue;
   for(const entry of staffGroups.get(staff)||[]){const m=entry.measure;if(m&&(m.x+m.width<nativeLeft-700||m.x>nativeRight+700))continue;
    // Five staff lines are existing notation, not filled barriers. Long links
    // are confined to inter-staff lanes below, rather than drawn along them.
    for(const node of entry.node.querySelectorAll(primitives)){if(node.parentNode===entry.node&&node.localName==='path')continue;add(node,staff)}
   }
  }
  for(const c of controlEntries){if((F.weights[c.staff]||0)<.1)continue;const v=box(c.node);if(!v||v.r<left-8||v.x>right+8||v.b<low||v.y>high)continue;for(const node of c.node.querySelectorAll(primitives))add(node,c.staff)}
  if(includeBarlines)for(const entry of barlineGroups){const m=entry.measure;if(m&&(m.x+m.width<nativeLeft-700||m.x>nativeRight+700))continue;for(const node of entry.node.querySelectorAll(primitives))add(node)}
  for(const node of actor.scoreClip.querySelectorAll('.score-locators text')){
   if(node.style.display==='none'||Number(node.getAttribute('opacity')||1)<.03)continue;
   const v=inkShape(node);if(v&&v.r>left-8&&v.x<right+8&&v.b>low&&v.y<high)out.push({...v,svg_id:'generated-locator:'+node.getAttribute('data-source-measure')+':'+node.getAttribute('data-occurrence'),obstacle_type:'generated-score-locator'});
  }
  // Labels are anchored in native coordinates and updated later in draw().
  // Calculate their current boxes from those anchors, never the previous
  // frame's DOM, so a connector cannot cross a label or depend on warm-up.
  for(const item of motifLabels){const a=item.anchor;if(!a||(F.weights[item.row.s.staff]||0)*labelVisibility(item,F.seconds)<.03)continue;
   const p=new DOMPoint(a.x,a.y).matrixTransform(root.getCTM().inverse().multiply(a.node.getCTM()));p.x+=a.screen_dx||0;p.y+=a.screen_dy||0;if(item.bandStaff){const slot=actor.labelSlots?.get(item.bandStaff+':'+(item.bandSide||'below'));if(!slot)continue;p.y=slot.y+(slot.slot_offsets?.[item.bandSlot]??(slot.row_height||64)*slot.alpha*(item.bandSlot+.5))-(item.top+item.bottom)/2;}
   const v={x:p.x-item.paddingX,r:p.x+item.width+item.paddingX,y:p.y+item.top,b:p.y+item.bottom,kind:'rect',staff:item.row.s.staff};
   if(v.r>left-8&&v.x<right+8&&v.b>low&&v.y<high)out.push(v);
  }
  for(const node of root.querySelectorAll('[data-source-figure]')){
   if(node.style.visibility==='hidden'||Number(node.style.opacity||1)<.02)continue;
   // A split-staff SVG still contains the other staff outside its viewBox.
   // getBBox() includes that invisible ink: use the actual viewport and the
   // animated row crop, otherwise the hidden staff blocks the source lane.
   const parts=[];
   for(const child of node.children){
    if(child.hasAttribute('data-reference-paired-ranges'))continue;
    if(child.localName==='svg'){
     const m=root.getCTM().inverse().multiply(node.getCTM()),x=child.x.baseVal.value,y=child.y.baseVal.value,w=child.width.baseVal.value,h=child.height.baseVal.value;
     const ps=[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));
     parts.push({x:Math.min(...ps.map(p=>p.x)),r:Math.max(...ps.map(p=>p.x)),y:Math.min(...ps.map(p=>p.y)),b:Math.max(...ps.map(p=>p.y))});
    }else{const b=box(child);if(b)parts.push(b)}
   }
   const crop=box([...node.parentNode.children].find(n=>n.localName==='rect'));
   for(const [partIndex,b]of parts.entries()){const v=crop?{x:Math.max(b.x,crop.x),r:Math.min(b.r,crop.r),y:Math.max(b.y,crop.y),b:Math.min(b.b,crop.b)}:b;
    if(v.r>v.x&&v.b>v.y&&v.r>left-8&&v.x<right+8&&v.b>low&&v.y<high)out.push({...v,kind:'rect',svg_id:'reference:'+node.getAttribute('data-source-figure')+':'+partIndex,obstacle_type:'native-reference-content'});
   }
  }
  return out;
 }
 let routeAttemptDiagnostics=[];
 function chooseConnectorRoute(lane,ink,cached,template=null){
  const scale=Math.max(.001,lane.scale),padding=3.2;
  const pointDistance=(p,a,b)=>{const dx=b.x-a.x,dy=b.y-a.y,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy||1)));return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy)};
  const cross=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);
  const nearSegments=(a,b,c,d,pad)=>{const ab1=cross(a,b,c),ab2=cross(a,b,d),cd1=cross(c,d,a),cd2=cross(c,d,b);if(ab1*ab2<=0&&cd1*cd2<=0&&Math.max(Math.min(a.x,b.x),Math.min(c.x,d.x))<=Math.min(Math.max(a.x,b.x),Math.max(c.x,d.x))+pad&&Math.max(Math.min(a.y,b.y),Math.min(c.y,d.y))<=Math.min(Math.max(a.y,b.y),Math.max(c.y,d.y))+pad)return true;return Math.min(pointDistance(a,c,d),pointDistance(b,c,d),pointDistance(c,a,b),pointDistance(d,a,b))<pad};
  const hitsSegment=(a,b,o)=>{const pad=padding+(o.pad||0);if(Math.max(a.x,b.x)<o.x-pad||Math.min(a.x,b.x)>o.r+pad||Math.max(a.y,b.y)<o.y-pad||Math.min(a.y,b.y)>o.b+pad)return false;if(o.kind==='segments')return o.segments.some(([c,d])=>nearSegments(a,b,c,d,pad));return true};
  const hitCount=points=>{let n=0;for(let i=1;i<points.length;i++)for(const o of ink)if(hitsSegment(points[i-1],points[i],o))n++;return n};
  const pointsFor=d=>{const y0=lane.center+d.y0*scale,y1=lane.center+(d.y1??d.y0)*scale,endY=d.side==='upper'?lane.upper:lane.lower,turn=Math.min(lane.right-6,lane.x+d.turn*scale),p=[{x:lane.right,y:y0}];if(d.pivot!==undefined){const x=Math.min(lane.right-8,lane.x+d.pivot*scale);p.push({x,y:y0},{x,y:y1})}p.push({x:turn,y:y1},{x:turn,y:endY},{x:lane.x,y:endY});return p.filter((v,i)=>!i||Math.abs(v.x-p[i-1].x)+Math.abs(v.y-p[i-1].y)>.05)};
  const valid=points=>points.every(p=>p.x>=lane.x-.1&&p.x<=lane.right+.1&&p.y>=lane.top&&p.y<=lane.bottom);
  const asPath=points=>points.map((p,i)=>(i?'L':'M')+' '+p.x.toFixed(2)+' '+p.y.toFixed(2)).join(' ');
  if(template?.kind==='gap'){
   const side=template.side,top=side==='upper'?lane.top:Math.max(lane.lower,lane.center+lane.staffHalf+6),bottom=side==='upper'?Math.min(lane.upper,lane.center-lane.staffHalf-6):lane.bottom;
   if(bottom-top<4)return null;
   const y=top+1+(bottom-top-2)*template.fraction,descriptor={side,y0:(y-lane.center)/scale,turn:0},points=pointsFor(descriptor);
   return valid(points)&&!hitCount(points)?{points,descriptor,hits:0,cached:false,continuous:true,d:asPath(points),gaps:0}:null;
  }
  const channelize=route=>{
   if(!route||!lane.channelOffset)return route;
   const delta=(route.descriptor.side==='upper'?-1:1)*lane.channelOffset,d={...route.descriptor,y0:route.descriptor.y0+delta/scale};if(d.y1!==undefined)d.y1+=delta/scale;
   const points=pointsFor(d);return valid(points)&&!hitCount(points)?{...route,points,descriptor:d,d:asPath(points),channel_offset_px:delta}:null;
  };
  // Follow a continuous, source-owned ink envelope before trying the general
  // router. Incoming notation is considered before it reaches the paper seam;
  // its influence grows continuously over 120px, rather than invalidating a
  // cached horizontal line in one frame. This is a function of native geometry
  // at this absolute time, with no previous-frame smoothing or hidden segment.
  const envelopes=[],lookahead=120,own=ink.filter(o=>o.staff===lane.staff&&o.r>=lane.x-padding);
  for(const side of lane.onlySide?[lane.onlySide]:['upper','lower']){
   const base=side==='upper'?lane.upper-7:lane.lower+7;let y=base;
   for(const o of own){const z=Math.max(0,Math.min(1,(lane.right+lookahead-o.x)/lookahead)),a=z*z*(3-2*z),edge=side==='upper'?o.y-padding-(o.pad||0)-1:o.b+padding+(o.pad||0)+1,candidate=base+(edge-base)*a;y=side==='upper'?Math.min(y,candidate):Math.max(y,candidate)}
   const descriptor={side,y0:(y-lane.center)/scale,turn:0},points=pointsFor(descriptor);
   if(valid(points)&&!hitCount(points)){const length=points.slice(1).reduce((v,p,i)=>v+Math.hypot(p.x-points[i].x,p.y-points[i].y),0);envelopes.push({points,descriptor,hits:0,cost:length,cached:false,continuous:true,d:asPath(points),gaps:0})}
  }
  const envelope=envelopes.find(r=>r.descriptor.side===(lane.onlySide||lane.sourceSide));if(envelope)return channelize(envelope);
  // General fallback is also frame-time deterministic. A remembered route
  // may be useful for diagnostics, but may not choose a different path when a
  // render chunk starts later in the same cue.
  cached=null;
  if(cached&&(!lane.onlySide||cached.side===lane.onlySide)){const points=pointsFor(cached);if(valid(points)&&!hitCount(points))return{points,descriptor:cached,hits:0,cached:true,d:asPath(points),gaps:0}}
  const candidates=[],sides=lane.onlySide?[lane.onlySide]:lane.sourceSide?[lane.sourceSide,lane.sourceSide==='upper'?'lower':'upper']:['upper','lower'];
  function add(side,y0,turn,y1,pivot){const d={side,y0:(y0-lane.center)/scale,turn:turn/scale};if(y1!==undefined)d.y1=(y1-lane.center)/scale;if(pivot!==undefined)d.pivot=pivot/scale;const points=pointsFor(d);if(!valid(points))return;const length=points.slice(1).reduce((v,p,i)=>v+Math.hypot(p.x-points[i].x,p.y-points[i].y),0),hits=hitCount(points);candidates.push({points,descriptor:d,hits,cost:length+hits*220+(lane.sourceSide&&side!==lane.sourceSide?10000:0)})}
  const laneSets=[];
  // Retain the full legal gap: dense glyph-edge candidates near its centre
  // must not evict the outer, clear lanes in a dense source passage.
  for(const side of sides){const top=side==='upper'?lane.top:Math.max(lane.lower,lane.center+lane.staffHalf+6),bottom=side==='upper'?Math.min(lane.upper,lane.center-lane.staffHalf-6):lane.bottom;if(bottom<top)continue;const mid=(top+bottom)/2,ys=[mid,top+1,bottom-1];for(let y=top+5;y<bottom;y+=7)ys.push(y);for(const o of ink)for(const y of[o.y-padding-3,o.b+padding+3])if(y>=top&&y<=bottom)ys.push(y);const unique=[...new Set(ys.map(y=>Math.round(y*2)/2))].sort((a,b)=>Math.abs(a-mid)-Math.abs(b-mid));laneSets.push({side,ys:unique});for(const y of unique)for(const turn of[0,14,30,54])add(side,y,turn)}
  let clear=candidates.filter(c=>c.hits===0).sort((a,b)=>a.cost-b.cost)[0];
  if(!clear){
   // One local dogleg, not a global maze: route through two legal lanes and
   // choose a turn at a real ink edge. This handles dense controls in C/D.
   const pivots=[36,72,120,...ink.flatMap(o=>[o.x-lane.x-9,o.r-lane.x+9])].filter(x=>x>24&&x<lane.right-lane.x-16).sort((a,b)=>a-b);const step=Math.max(1,Math.ceil(pivots.length/18)),px=[...new Set([...pivots.slice(0,12),...pivots.filter((_,i)=>i%step===0),...pivots.slice(-4)])];
   const spread=ys=>P.source_ports?[...new Set([...ys.slice(0,7),...ys.slice().sort((a,b)=>a-b).filter((_,i,a)=>i<8||i>=a.length-4)])]:ys.slice(0,7);
   for(const{side,ys}of laneSets)for(const y0 of spread(ys))for(const y1 of spread(ys)){if(Math.abs(y0-y1)<5)continue;for(const x of px)add(side,y0,0,y1,x)}
   clear=candidates.filter(c=>c.hits===0).sort((a,b)=>a.cost-b.cost)[0];
  }
  // Never fabricate a connection by lifting the pen over native symbols.
  // A successful route is one continuous, collision-free polyline.
  if(!clear&&P.route_diagnostic_mode)routeAttemptDiagnostics.push({lane,template,candidate_count:candidates.length,best:candidates.slice().sort((a,b)=>a.hits-b.hits||a.cost-b.cost).slice(0,3).map(c=>({points:c.points,hits:c.hits,blocked_segments:c.points.slice(1).map((b,i)=>({a:c.points[i],b,obstacles:ink.flatMap((o,j)=>hitsSegment(c.points[i],b,o)?[j]:[])}))}))});
  return channelize(clear?{...clear,cached:false,d:asPath(clear.points),gaps:0}:null);
 }
 // END CONNECTOR ROUTER
 const routeDiagnostics={failures:[],samples:[]};if(P.route_diagnostic_mode)window.guideRouteDiagnostics=routeDiagnostics;
 let jointCollect=false,jointReference=null,jointSnapshots=[],jointSelection=new Map(),jointPlanAudit=null;
 const polyLength=p=>p.slice(1).reduce((n,b,i)=>n+Math.hypot(b.x-p[i].x,b.y-p[i].y),0);
 function jointCandidates(lane,ink,selectedId=null){
  const side=lane.onlySide||lane.sourceSide||'upper',other=side==='upper'?'lower':'upper',templates=[{kind:'base',side},...[.18,.5,.76,.82].map(fraction=>({kind:'gap',side,fraction})),...(!lane.onlySide?[{kind:'base',side:other},{kind:'gap',side:other,fraction:.5}]:[])];
  return templates.flatMap(template=>(P.source_ports||['right']).map(port=>({...template,port,id:(P.source_ports?port+'-':'')+template.side+'-'+template.kind+(template.fraction??'')}))).filter(t=>!selectedId||t.id===selectedId).map(template=>{const id=template.id,route=chooseConnectorRoute({...lane,x:({left:lane.leftX,quarter:lane.leftX+(lane.x-lane.leftX)*.25,threetenths:lane.leftX+(lane.x-lane.leftX)*.3,twofifths:lane.leftX+(lane.x-lane.leftX)*.4,middle:(lane.leftX+lane.x)/2,threefifths:lane.leftX+(lane.x-lane.leftX)*.6,threequarter:lane.leftX+(lane.x-lane.leftX)*.75})[template.port]??lane.x,onlySide:template.side,channelOffset:0},ink,null,template);return route?{id,template,route}:null}).filter(Boolean);
 }
 function jointPair(a,b){
  const same=a.semantic===b.semantic&&a.wordKey===b.wordKey,segments=p=>p.slice(1).map((q,i)=>[p[i],q]).filter(([p,q])=>Math.hypot(p.x-q.x,p.y-q.y)>.1);
  let crossings=0,overlap=0,close=0;
  for(const [p,q]of (a.visible_segments||segments(a.points)))for(const [u,v]of (b.visible_segments||segments(b.points))){
   const horizontal=Math.abs(p.y-q.y)<.01,otherHorizontal=Math.abs(u.y-v.y)<.01;
   if(horizontal===otherHorizontal){
    const distance=Math.abs(horizontal?p.y-u.y:p.x-u.x),shared=Math.min(horizontal?Math.max(p.x,q.x):Math.max(p.y,q.y),horizontal?Math.max(u.x,v.x):Math.max(u.y,v.y))-Math.max(horizontal?Math.min(p.x,q.x):Math.min(p.y,q.y),horizontal?Math.min(u.x,v.x):Math.min(u.y,v.y));
    if(shared>3&&!same){if(distance<3.8)overlap+=shared;else if(distance<12)close+=shared*(12-distance)/12;}
   }else{
    const h=horizontal?[p,q]:[u,v],z=horizontal?[u,v]:[p,q],x=z[0].x,y=h[0].y;
    if(x>Math.min(h[0].x,h[1].x)+.1&&x<Math.max(h[0].x,h[1].x)-.1&&y>Math.min(z[0].y,z[1].y)+.1&&y<Math.max(z[0].y,z[1].y)-.1&&!same)crossings++;
   }
  }
  const forkConflict=a.semantic===b.semantic&&a.slot!==b.slot;
  return{crossings,overlap_px:overlap,close_px:close,cost:(overlap>3||forkConflict?1e12:0)+crossings*20000+close*20};
 }
 const paperMeasure=document.createElement('canvas').getContext('2d'),paperMetricCache=new Map();
 function paperTextInk(node){
  if(!node.textContent||!node.getNumberOfChars())return null;
  const cs=getComputedStyle(node),font=cs.fontWeight+' '+cs.fontSize+' '+cs.fontFamily,key=font+'|'+node.textContent;
  let metric=paperMetricCache.get(key);if(!metric){paperMeasure.font=font;const m=paperMeasure.measureText(node.textContent);metric={ascent:m.actualBoundingBoxAscent,descent:m.actualBoundingBoxDescent};paperMetricCache.set(key,metric);}
  const baseline=node.getStartPositionOfChar(0),m=root.getCTM().inverse().multiply(node.getCTM()),b=box(node);
  return{x:b.x,r:b.r,y:(baseline.y-metric.ascent)*m.d+m.f,b:(baseline.y+metric.descent)*m.d+m.f,ink:true};
 }
 function paperWordBounds(node){const b=paperTextInk(node),line=node.closest('text'),segments=line?.querySelectorAll('tspan'),ink=segments?.length?[...segments].map(paperTextInk):[b];return{...b,keyword_ink_bottom:b.b,b:Math.max(...ink.filter(Boolean).map(v=>v.b))};}
 function paperObstacles(wb){const nodes=incrementalSidebar?incrementalSidebar.paperTextNodes():pages.filter(p=>p.alpha>.01).flatMap(p=>[...p.g.querySelectorAll('tspan,text:not(:has(tspan))')]);return nodes.map(paperTextInk).filter(b=>b&&b.r>=X&&b.b>=wb.b-4&&b.y<=wb.b+22);}
 function jointOption(job,candidate,slot){
  const entry=candidate.route.points[0],corridor=2766+slot*14,wordY=job.wb.b+(job.wb.ink?5:7),exitY=wordY+(job.wb.ink?slot*4:0),paperPoints=[...(job.paperPrefix?.length?job.paperPrefix:[{x:job.wb.x,y:wordY},...(slot?[{x:job.wb.x,y:exitY}]:[])]),{x:corridor,y:exitY},{x:corridor,y:entry.y},entry],points=[...paperPoints,...candidate.route.points.slice(1)],w=job.connectionWindow;
  // Same-line source words need distinct fixed horizontal exits as well as
  // distinct margin corridors. Check the actual text, not a guessed line gap.
  if(paperPoints.slice(1).some((b,i)=>(job.paperInk||[]).some(o=>Math.max(paperPoints[i].x,b.x)>=o.x-3.2&&Math.min(paperPoints[i].x,b.x)<=o.r+3.2&&Math.max(paperPoints[i].y,b.y)>=o.y-3.2&&Math.min(paperPoints[i].y,b.y)<=o.b+3.2)))return null;
  return{...candidate,key:candidate.id+'@'+slot,slot,paperPoints,points,semantic:w.semanticGroup,wordKey:JSON.stringify([w.page.id,w.block,w.keyword,w.keyword_occurrence||0]),cost:polyLength(points)*.02+(points.length-2)*8+(candidate.template?.kind==='gap'?1:0)+slot*.1};
 }
 function solveJointPlan(){
  const options=new Map(),unary=new Map(),pairs=new Map(),windowById=new Map(connectionWindows.map(w=>[w.index,w]));
  for(const snap of jointSnapshots)for(const job of snap.jobs){
   const keys=new Set(job.options.map(o=>o.key)),prior=options.get(job.index);options.set(job.index,prior?new Set([...prior].filter(k=>keys.has(k))):keys);
   for(const o of job.options){const key=job.index+'|'+o.key;unary.set(key,(unary.get(key)||0)+o.cost);}
  }
  for(const [index,keys]of options)if(!keys.size)throw Error('No stable joint route candidate for window '+index);
  for(const snap of jointSnapshots)for(let i=0;i<snap.jobs.length;i++)for(let j=i+1;j<snap.jobs.length;j++){
   const a=snap.jobs[i],b=snap.jobs[j];for(const x of a.options)for(const y of b.options){const key=a.index<b.index?a.index+'|'+x.key+'|'+b.index+'|'+y.key:b.index+'|'+y.key+'|'+a.index+'|'+x.key;pairs.set(key,(pairs.get(key)||0)+jointPair(x,y).cost);}
  }
  const order=[...options.keys()].sort((a,b)=>windowById.get(a).from-windowById.get(b).from||a-b),components=[];let componentEnd=-Infinity;
  for(const index of order){const w=windowById.get(index);if(!components.length||w.from>=componentEnd-1e-9){components.push([]);componentEnd=w.to;}components.at(-1).push(index);componentEnd=Math.max(componentEnd,w.to);}
  jointSelection=new Map();let totalCost=0;
  for(const component of components){let beam=[{cost:0,chosen:new Map()}];
   for(const index of component){const next=[];for(const state of beam)for(const key of options.get(index)){
    let cost=state.cost+(unary.get(index+'|'+key)||0);for(const [other,k]of state.chosen){const pair=index<other?index+'|'+key+'|'+other+'|'+k:other+'|'+k+'|'+index+'|'+key;cost+=pairs.get(pair)||0;}
    if(cost<1e12)next.push({cost,chosen:new Map([...state.chosen,[index,key]])});
   }next.sort((a,b)=>a.cost-b.cost||JSON.stringify([...a.chosen]).localeCompare(JSON.stringify([...b.chosen])));beam=next.slice(0,192);if(!beam.length){if(P.route_diagnostic_mode)routeDiagnostics.assignment_details={window:index,component,snapshots:jointSnapshots.filter(s=>s.jobs.some(j=>component.includes(j.index))).map(s=>({seconds:s.seconds,jobs:s.jobs.map(j=>({index:j.index,options:j.options.map(o=>({key:o.key,semantic:o.semantic,wordKey:o.wordKey,points:o.points}))}))}))};throw Error('No non-overlapping joint routing assignment at window '+index);}}
   totalCost+=beam[0]?.cost||0;for(const [index,key]of beam[0]?.chosen||[])jointSelection.set(index,key);
  }
  jointPlanAudit={reference_count:jointSnapshots.length,cost:totalCost,components,assignments:[...jointSelection].map(([index,candidate])=>({index,candidate})),references:jointSnapshots.map(s=>{
   const pairs=[];for(let i=0;i<s.jobs.length;i++)for(let j=i+1;j<s.jobs.length;j++){const a=s.jobs[i],b=s.jobs[j],x=a.options.find(o=>o.key===jointSelection.get(a.index)),y=b.options.find(o=>o.key===jointSelection.get(b.index)),allowed=a.options.flatMap(x=>b.options.map(y=>jointPair(x,y))).filter(m=>m.cost<1e12);pairs.push({windows:[a.index,b.index],selected:jointPair(x,y),minimum_crossings:allowed.length?Math.min(...allowed.map(m=>m.crossings)):null});}
   return{seconds:s.seconds,window_indices:s.jobs.map(j=>j.index),pairs};})};
 }
 function revealConnector(paperPoints,route,progress){
  const length=points=>points.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p.x-points[i].x,p.y-points[i].y),0);
  function prefix(points,budget){if(budget<=0||points.length<2)return '';let d=`M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;for(let i=1;i<points.length&&budget>0;i++){const a=points[i-1],b=points[i],n=Math.hypot(b.x-a.x,b.y-a.y);if(n<1e-8)continue;const t=Math.min(1,budget/n);d+=` L ${(a.x+(b.x-a.x)*t).toFixed(2)} ${(a.y+(b.y-a.y)*t).toFixed(2)}`;budget-=n}return d}
  const paperLength=length(paperPoints),scoreLength=length(route.points),p=Math.max(0,Math.min(1,progress)),shown=(paperLength+scoreLength)*p,scoreBudget=shown-paperLength;
  // Collision geometry must be the same finite prefixes that are painted.
  const visibleSegments=(points,budget)=>{const result=[];for(let i=1;i<points.length&&budget>0;i++){const a=points[i-1],b=points[i],n=Math.hypot(b.x-a.x,b.y-a.y);if(n<1e-8)continue;const t=Math.min(1,budget/n);if(n*t>.1)result.push([a,{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t}]);budget-=n;}return result;};
  const visible_segments=[...visibleSegments(paperPoints,Math.min(shown,paperLength)),...(route.fragments||[{start:0,points:route.points}]).flatMap(f=>visibleSegments(f.points,scoreBudget-f.start))];
  return{visible_segments,paper_path:prefix(paperPoints,Math.min(shown,paperLength)),score_path:(route.fragments||[{start:0,points:route.points}]).map(f=>prefix(f.points,scoreBudget-f.start)).filter(Boolean).join(' '),paper_length:paperLength,score_length:scoreLength,shown_length:shown,progress:p,arrived:p>=1};
 }
 // END CONNECTOR REVEAL
 function wrapLabel(item){
  if(item.singleLine||item.lines?.length===2)return;
  const text=item.label.textContent,chars=Array.from(text);
  let lines=item.labelLines;if(!lines&&chars.length>=4){const n=Math.ceil(chars.length/2);lines=[chars.slice(0,n).join(''),chars.slice(n).join('')];}if(!lines)return;
  if(!Array.isArray(lines)||lines.length!==2||lines.join('')!==text)throw Error('Label lines must preserve all source characters in exactly two lines');
  item.lines=lines;item.label.textContent='';for(let i=0;i<lines.length;i++){const t=E('tspan',{x:0,y:i*item.size*1.2},item.label);t.textContent=lines[i];}
  item.width=Math.max(...lines.map(t=>width(t,item.size,400)));item.bottom+=item.size*1.2;
 }
 function sourceCandidates(item){
  const choices=[item.row,...item.candidateRows.filter(r=>r!==item.row)];
  const score=r=>{let n=0;for(let t=item.window[0]+.5;t<item.window[1];t+=.5)n+=cohortWeight(r.s.staff,t);return n;};
  const scores=new Map(choices.map(r=>[r,score(r)]));
  return choices.sort((a,b)=>scores.get(b)-scores.get(a));
 }
 function prepareReservedBands(){
  if(!P.label_space_decisions?.length)return;
  const world=actor.scoreClip.firstElementChild,staves=S.geometry.staves,nativeBox=n=>{const b=n.getBBox(),m=world.getCTM().inverse().multiply(n.getCTM());return{x:b.x*m.a+m.e,r:(b.x+b.width)*m.a+m.e,y:b.y*m.d+m.f,b:(b.y+b.height)*m.d+m.f};};
  const bars=barlineGroups.filter(e=>e.node.classList.contains('barLine')).flatMap(e=>[...e.node.querySelectorAll(primitives)].map(nativeBox));
  for(const item of motifLabels.filter(i=>i.bandStaff)){
   item.bandStaff=item.row.s.staff;
   const possible=new Set((S.cohorts||[]).filter(c=>c.start<item.window[1]+4&&c.end>item.window[0]-4).flatMap(c=>c.staves));
   const crossing=(row,side)=>{const st=staffGeometry.get(row.s.staff),b=union(row.nodes.map(nativeBox));return bars.filter(v=>v.x>b.x-1500&&v.x<b.r+1500&&v.y<=st.y+st.height/2&&v.b>=st.y-st.height/2&&staves.some(o=>possible.has(o.id)&&o.y>=v.y-400&&o.y<=v.b+400&&(side==='above'?o.y<st.y-1:o.y>st.y+1)));};
   const decision=(P.label_space_decisions||[]).find(d=>d.target_id===item.representative_id&&Math.abs(d.from-item.window[0])<.001);
   let chosen=null;
   // A reviewed ownership side belongs to this exact source for its entire
   // lifetime. Real crossing strokes still enter the fixed-x gap guard below.
   if(decision?.band_side){if(!['above','below'].includes(decision.band_side))throw Error('Invalid fixed source-band side');chosen={row:item.row,side:decision.band_side};}
   else for(const row of sourceCandidates(item)){for(const side of ['below','above'])if(!crossing(row,side).length){chosen={row,side};break;}if(chosen)break;}
   if(chosen){item.row=chosen.row;item.bandStaff=chosen.row.s.staff;item.bandSide=chosen.side;item.crossingBarlines=crossing(chosen.row,chosen.side);}else{item.bandSide='below';item.crossingBarlines=crossing(item.row,'below');}
   item.bandSlot=0;item.bandBefore=decision?.padding_before||0;item.bandAfter=decision?.padding_after||0;item.bandNativeOffset=decision?.native_x_offset||0;
  }
  // Allocate only overlapping source-label lifetimes; fixed columns remain
  // attached to their verified source phrase. Long labels may share one row
  // after meaningful wrapping, instead of adding another vertical band.
  const extents=new Map(staves.map(st=>[st.id,{top:st.y-st.height/2-450,bottom:st.y+st.height/2+450}]));for(const n of S.geometry.notes){const e=extents.get(n.staff);if(e&&Number.isFinite(n.y)){e.top=Math.min(e.top,n.y-750);e.bottom=Math.max(e.bottom,n.y+750);}}
  const scaleAt=t=>{const weights=new Map(staves.map(st=>[st.id,cohortWeight(st.id,t)])),total=staves.reduce((n,st)=>{const e=extents.get(st.id);return n+(e.bottom-e.top+240)*Math.sqrt(weights.get(st.id)||0);},0);let padding=0,native=0;
   for(const band of P.label_bands||[]){const u=Math.max(0,Math.min(1,(t-band.from+4)/4,(band.to+4-t)/4));padding+=band.height*u*u*u*(10+u*(-15+6*u))*Math.sqrt(weights.get(band.staff)||0);}
   for(const c of P.native_comparisons||[])if(c.placement!=='sidebar'){const a=ease((t-c.from)/.6)*(1-ease((t-c.to)/.35))*(weights.get(c.anchor_staff)||0),h=c.native_height??c.height/.06;padding+=((c.row_padding_px??85)+(c.fixed_display_scale?h*c.fixed_display_scale:0))*a;native+=(c.fixed_display_scale?0:h)*a;}
   return Math.min(.22,Math.max(800,1640-padding)/Math.max(1,total+native));};
  const allocated=[];
  for(const item of motifLabels.filter(i=>i.bandStaff).sort((a,b)=>a.window[0]-b.window[0])){
   const scales=[];for(let t=item.window[0];t<=item.window[1];t+=.25)scales.push(scaleAt(t));const minScale=Math.min(...scales)*.998,b=union(item.row.nodes.map(nativeBox)),center=(b.x+b.r)/2,interval=()=>[center-(item.width+2*item.paddingX)/minScale/2,center+(item.width+2*item.paddingX)/minScale/2];
   const neighbours=allocated.filter(a=>a.bandStaff===item.bandStaff&&a.bandSide===item.bandSide&&a.window[0]<item.window[1]&&item.window[0]<a.window[1]);
   let own=interval(),overlap=a=>own[0]<a.bandInterval[1]&&a.bandInterval[0]<own[1];
   if(neighbours.some(overlap)&&item.label.textContent.length>=4){const original={text:item.label.textContent,width:item.width,bottom:item.bottom},before=new Set(neighbours.filter(overlap).map(a=>a.bandSlot));let beforeSlot=0;while(before.has(beforeSlot))beforeSlot++;wrapLabel(item);own=interval();const after=new Set(neighbours.filter(overlap).map(a=>a.bandSlot));let afterSlot=0;while(after.has(afterSlot))afterSlot++;if(afterSlot>=beforeSlot){item.label.textContent=original.text;item.width=original.width;item.bottom=original.bottom;delete item.lines;own=interval();}}
   const used=new Set(neighbours.filter(overlap).map(a=>a.bandSlot));while(used.has(item.bandSlot))item.bandSlot++;
   item.bandInterval=own;allocated.push(item);
  }
  const bands=[];
  for(const item of allocated.sort((a,b)=>a.bandStaff.localeCompare(b.bandStaff)||a.bandSide.localeCompare(b.bandSide)||a.window[0]-b.window[0])){
   const height=Math.max(64,Math.ceil(item.bottom-item.top+item.size*.32)),last=bands.at(-1);
   if(last&&last.staff===item.bandStaff&&last.side===item.bandSide&&last.to+8>=item.window[0]){last.to=Math.max(last.to,item.window[1]);last.slots=Math.max(last.slots,item.bandSlot+1);last.row_height=Math.max(last.row_height,height);last.padding_before=Math.max(last.padding_before||0,item.bandBefore);last.padding_after=Math.max(last.padding_after||0,item.bandAfter);last.height=last.slots*last.row_height+last.padding_before+last.padding_after;}
   else bands.push({staff:item.bandStaff,side:item.bandSide,from:item.window[0],to:item.window[1],row_height:height,slots:item.bandSlot+1,padding_before:item.bandBefore,padding_after:item.bandAfter,height:height*(item.bandSlot+1)+item.bandBefore+item.bandAfter});
  }
  P.label_bands=[...bands,...(P.label_bands||[]).filter(b=>b.purpose)];
 }
 prepareReservedBands();
 const motifLayoutCache=new Map(),motifNativeBoxes=new WeakMap(),motifScrollClock=new Map(P.label_layout_clock||[]);
 function compileMotifAnchors(referenceOverride,items=motifLabels){
  if(!motifLabels.length)return;
  const world=actor.scoreClip.firstElementChild,staves=S.geometry.staves,indices=new Map(staves.map((s,i)=>[s.id,i])),parents=staves.map((_,i)=>i),find=i=>parents[i]===i?i:(parents[i]=find(parents[i]));
  for(const dep of[...(S.geometry.staff_dependencies||staves.map(s=>({staves:s.dependencies||[s.id]}))),...(S.geometry.controls||[]).filter(c=>c.staves.length>1)]){const ii=dep.staves.map(id=>indices.get(id)).filter(i=>i!==undefined);if(ii.length)for(let i=Math.min(...ii);i<Math.max(...ii);i++)parents[find(i+1)]=find(i)}
  const extents=new Map(staves.map(s=>[s.id,{top:s.y-s.height/2-450,bottom:s.y+s.height/2+450}]));for(const n of S.geometry.notes){const e=extents.get(n.staff);if(e&&Number.isFinite(n.y)){e.top=Math.min(e.top,n.y-750);e.bottom=Math.max(e.bottom,n.y+750)}}
  const components=new Map();staves.forEach((s,i)=>{const k=find(i);if(!components.has(k))components.set(k,[]);components.get(k).push(s.id)});
  // Use one deterministic native layout for this content track, rather than
  // the first rendered frame; independent render chunks use identical anchors.
  const referenceTime=Math.max(0,referenceOverride??P.reading_stages?.[0]?.from??P.panel_in??0);
  const componentRows=[...components.values()].map(ids=>({ids,top:Math.min(...ids.map(id=>extents.get(id).top)),bottom:Math.max(...ids.map(id=>extents.get(id).bottom))}));
  const comparisons=(P.native_comparisons||[]).filter(c=>c.placement!=='sidebar');
  function layoutAt(t){
   if(motifLayoutCache.has(t))return motifLayoutCache.get(t);
   const weights=new Map(staves.map(s=>[s.id,cohortWeight(s.id,t)])),reserved=componentRows.map(c=>Math.sqrt(Math.max(...c.ids.map(id=>weights.get(id)||0))));
   const labelBands=(P.label_bands||[]).map(v=>{const u=Math.max(0,Math.min(1,(t-v.from+4)/4,(v.to+4-t)/4));return {...v,alpha:u*u*u*(10+u*(-15+6*u))*Math.sqrt(weights.get(v.staff)||0)};});
   const references=comparisons.map(c=>({c,alpha:ease((t-c.from)/.6)*(1-ease((t-c.to)/.35))*(weights.get(c.anchor_staff)||0),height:c.native_height??c.height/.06}));
   const total=componentRows.reduce((n,c,i)=>n+(c.bottom-c.top+240)*reserved[i],0),padding=labelBands.reduce((n,v)=>n+v.height*v.alpha,0)+references.reduce((n,v)=>n+((v.c.row_padding_px??85)+(v.c.fixed_display_scale?v.height*v.c.fixed_display_scale:0))*v.alpha,0),native=references.reduce((n,v)=>n+(v.c.fixed_display_scale?0:v.height)*v.alpha,0),scale=Math.min(.22,Math.max(800,1640-padding)/Math.max(1,total+native)),dy=new Map(),bandSlots=new Map();let cursor=0;
   componentRows.forEach((c,i)=>{const insert=side=>{for(const band of labelBands.filter(v=>c.ids.includes(v.staff)&&v.alpha>0&&(v.side||'below')===side)){bandSlots.set(band.staff+':'+side,{y:cursor*scale+(band.padding_before||0)*band.alpha,row_height:band.row_height||64,alpha:band.alpha});cursor+=band.height*band.alpha/scale;}};insert('above');const h=c.bottom-c.top,w=reserved[i],center=cursor+h*w/2;for(const id of c.ids)dy.set(id,center-(c.top+c.bottom)/2);cursor+=(h+240)*w;insert('below');for(const v of references.filter(v=>c.ids.includes(v.c.anchor_staff)))cursor+=(v.height*(v.c.fixed_display_scale||scale)+(v.c.row_padding_px??85))*v.alpha/scale;});
   const result={t,scale,dy,weights,bandSlots,scrollX:motifScrollClock.get(t)};motifLayoutCache.set(t,result);return result;
  }
  const end=Math.max(referenceTime,...items.map(i=>Number.isFinite(i.window[1])?i.window[1]:(P.reading_stages?.at(-1)?.to??referenceTime))),times=[referenceTime,end];for(let t=Math.ceil(referenceTime*4)/4;t<end;t+=.25)times.push(t);
  const allLayouts=times.map(layoutAt),layouts=allLayouts.filter(v=>items.some(i=>(v.weights.get(i.row.s.staff)||0)>.4)),chosen=(layouts.length?layouts:[layoutAt(referenceTime)]).reduce((a,z)=>z.scale<a.scale?z:a),scale=chosen.scale,dy=chosen.dy,active=new Set(staves.filter(s=>(chosen.weights.get(s.id)||0)>.03).map(s=>s.id));
  const centers=staves.filter(s=>active.has(s.id)).map(s=>({id:s.id,y:(s.y+dy.get(s.id))*scale})).sort((a,b)=>a.y-b.y);
  const nativeBox=node=>{if(motifNativeBoxes.has(node))return motifNativeBoxes.get(node);const b=node.getBBox(),m=world.getCTM().inverse().multiply(node.getCTM()),pts=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m)),v={x:Math.min(...pts.map(p=>p.x)),r:Math.max(...pts.map(p=>p.x)),y:Math.min(...pts.map(p=>p.y)),b:Math.max(...pts.map(p=>p.y))};motifNativeBoxes.set(node,v);return v;};
  const projected=(b,staff)=>({x:b.x*scale,r:b.r*scale,y:(b.y+(dy.get(staff)||0))*scale,b:(b.b+(dy.get(staff)||0))*scale});
  const placed=motifLabels.filter(i=>i.anchor&&!items.includes(i)&&items.some(j=>i.window[0]<j.window[1]&&j.window[0]<i.window[1])).map(i=>{const a=i.anchor,x=a.native_x*scale+(a.screen_dx||0);let y=(a.native_y+(dy.get(i.row.s.staff)||0))*scale+(a.screen_dy||0);if(i.bandStaff){const slot=chosen.bandSlots.get(i.bandStaff+':'+(i.bandSide||'below'));if(slot)y=slot.y+(slot.slot_offsets?.[i.bandSlot]??slot.row_height*slot.alpha*(i.bandSlot+.5))-(i.top+i.bottom)/2;}return{x:x-i.paddingX,r:x+i.width+i.paddingX,y:y+i.top,b:y+i.bottom};}),order=[...items].sort((a,b)=>(indices.get(a.row.s.staff)-indices.get(b.row.s.staff))||(a.row.s.q0-b.row.s.q0)||(b.row.s.q1-a.row.s.q1));
  for(const item of order){
   for(const candidate of (item.bandStaff?[item.row]:sourceCandidates(item))){item.row=candidate;
   const r=item.row,staff=r.s.staff,anchorNode=r.nodes[0]?.closest('g.staff');if(!anchorNode){item.placement='missing-source-node';continue;}
   if(item.bandStaff){
    const b=union(r.nodes.map(nativeBox)),st=staffGeometry.get(staff),scales=[];
    for(let t=item.window[0];t<=item.window[1]+.001;t+=.25){
     const weights=new Map(staves.map(s=>[s.id,cohortWeight(s.id,t)])),denseTotal=componentRows.reduce((n,c)=>n+(c.bottom-c.top+240)*Math.sqrt(Math.max(...c.ids.map(id=>weights.get(id)||0))),0);
     const labelPadding=(P.label_bands||[]).reduce((n,v)=>{const u=Math.max(0,Math.min(1,(t-v.from+4)/4,(v.to+4-t)/4));return n+v.height*u*u*u*(10+u*(-15+6*u))*Math.sqrt(weights.get(v.staff)||0);},0);
     let referencePadding=0,referenceNative=0;for(const c of comparisons){const alpha=ease((t-c.from)/.6)*(1-ease((t-c.to)/.35))*(weights.get(c.anchor_staff)||0),height=c.native_height??c.height/.06;referencePadding+=((c.row_padding_px??85)+(c.fixed_display_scale?height*c.fixed_display_scale:0))*alpha;referenceNative+=(c.fixed_display_scale?0:height)*alpha;}
     scales.push(Math.min(.22,Math.max(800,1640-labelPadding-referencePadding)/Math.max(1,denseTotal+referenceNative)));
    }
    const minimumScale=Math.min(...scales)*.998;
    const columns=(item.crossingBarlines||[]).map(v=>(v.x+v.r)/2);
    const xs=[...new Set(columns)].sort((a,b)=>a-b),gaps=xs.slice(1).map((x,i)=>[xs[i],x]).filter(([l,h])=>h>b.x&&l<b.r),center=(b.x+b.r)/2;let clearanceEm=.30,margin=(item.paddingX+item.size*clearanceEm+2)/minimumScale;
    const fit=()=>gaps.map(([l,h])=>({l:l+margin,h:h-margin-item.width/minimumScale})).filter(g=>g.h>=g.l).map(g=>Math.max(g.l,Math.min(g.h,center-item.width/minimumScale/2))).sort((a,z)=>Math.abs(a+item.width/minimumScale/2-center)-Math.abs(z+item.width/minimumScale/2-center))[0];
    let x=columns.length?fit():center-item.width/minimumScale/2;if(x===undefined){wrapLabel(item);x=fit();}if(x===undefined){clearanceEm=.16;margin=(item.paddingX+item.size*clearanceEm+2)/minimumScale;x=fit();}
    // Keep a visible diagnostic on an impossible source interval. Never hide
    // the representative or relocate it into a different phrase.
    item.bandFit=x===undefined?'no-two-line-source-gap':'fixed-source-barline-gap';item.bandFitDetail={source:b,columns:columns.length,gaps,minimumScale,referenceScale:scale,width:item.width,margin,clearanceEm};
    const point={x:(x??center-item.width/minimumScale/2)+item.width/minimumScale/2+(item.bandNativeOffset||0),y:st.y};if(item.bandNativeOffset&&(point.x<b.x||point.x>b.r))throw Error('Fixed label offset left its exact source phrase');const local=new DOMPoint(point.x,point.y).matrixTransform(anchorNode.getCTM().inverse().multiply(world.getCTM()));item.anchor={node:anchorNode,x:local.x,y:local.y,screen_dx:-item.width/2,native_x:point.x,native_y:point.y,reference_scale:minimumScale};item.placement='reserved-source-band';break;
   }
   const native=union(r.nodes.map(nativeBox)),b=projected(native,staff),w=item.width,h=item.size,pad=7,labelGap=P.label_typography?item.size*.30:5,ink=[],center=(staffGeometry.get(staff).y+dy.get(staff))*scale,at=centers.findIndex(c=>c.id===staff),previous=centers[at-1]?.y??center-200,next=centers[at+1]?.y??center+200;
   const priorHalf=(staffGeometry.get(centers[at-1]?.id)?.height||720)*scale/2,nextHalf=(staffGeometry.get(centers[at+1]?.id)?.height||720)*scale/2;
   const safeTop=Math.max(-35,previous+priorHalf+5),safeBottom=Math.min(1636,next-nextHalf-5),left=b.x-w-150,right=b.r+w+150;
   const add=(node,owner)=>{const o=projected(nativeBox(node),owner);if(o.r>left&&o.x<right&&o.b>safeTop-5&&o.y<safeBottom+5)ink.push({...o,source:node.id||node.parentNode?.getAttribute('class'),owner})};
   for(const near of centers.filter(c=>Math.abs(c.y-center)<240))for(const entry of staffGroups.get(near.id)||[]){const m=entry.measure;if(m&&(m.x+m.width<left/scale||m.x>right/scale))continue;for(const node of entry.node.querySelectorAll(primitives)){if(node.parentNode===entry.node&&node.localName==='path')continue;add(node,near.id)}}
   for(const c of controlEntries)if(active.has(c.staff))for(const node of c.node.querySelectorAll(primitives))add(node,c.staff);
   // Protect actual staff-level barline ink; source names may use a clear gap
   // above/below it, but never cover the corresponding measure stroke.
   const st=staffGeometry.get(staff),half=st.height*scale/2;
   for(const entry of barlineGroups){const m=entry.measure;if(m&&(m.x+m.width<left/scale||m.x>right/scale))continue;for(const node of entry.node.querySelectorAll(primitives)){
    const o=nativeBox(node),owners=staves.filter(v=>v.y>=o.y-400&&v.y<=o.b+400),presence=1-owners.reduce((n,v)=>n*(1-(chosen.weights.get(v.id)||0)),1);if(presence<.03)continue;
    // Match renderer.generated's weighted whole-stroke transform. A real
    // multi-staff barline crosses the inter-staff gap as well as both staves.
    const edge=(vv,sign)=>{let remaining=1,sum=0;for(const v of vv){const weight=chosen.weights.get(v.id)||0,p=remaining*weight;sum+=p*(v.y+(dy.get(v.id)||0)+sign*v.height/2);remaining*=1-weight;}return sum/presence*scale;};
    ink.push({x:o.x*scale,r:o.r*scale,y:edge(owners,-1),b:edge([...owners].reverse(),1),source:node.id||'generated-barline'});
   }}
   ink.push(...placed);
   // Validate a fixed source anchor against every real local layout in its
   // lifetime. The globally smallest scale is not necessarily the smallest
   // gap between this source and a neighbour entering or leaving the score.
   const lifeLayouts=allLayouts.filter(v=>(v.weights.get(staff)||0)*labelVisibility(item,v.t)>.4),possible=staves.filter(v=>lifeLayouts.some(l=>(l.weights.get(v.id)||0)>.1)),rawInk=[],rawBars=[];
   const nativeLeft=left/scale-1000,nativeRight=right/scale+1000;
   for(const owner of possible)for(const entry of staffGroups.get(owner.id)||[]){const m=entry.measure;if(m&&(m.x+m.width<nativeLeft||m.x>nativeRight))continue;for(const node of entry.node.querySelectorAll(primitives)){if(node.parentNode===entry.node&&node.localName==='path')continue;const o=nativeBox(node);if(o.r>=nativeLeft&&o.x<=nativeRight)rawInk.push({...o,staff:owner.id});}}
   for(const c of controlEntries)for(const node of c.node.querySelectorAll(primitives)){const o=nativeBox(node);if(o.r>=nativeLeft&&o.x<=nativeRight)rawInk.push({...o,staff:c.staff});}
   for(const entry of barlineGroups)for(const node of entry.node.querySelectorAll(primitives)){const o=nativeBox(node);if(o.r>=nativeLeft&&o.x<=nativeRight)rawBars.push({...o,owners:staves.filter(v=>v.y>=o.y-400&&v.y<=o.b+400)});}
   let lifeProjected=null;
   const lifecycleClear=(x,y)=>{
    const nativeX=(x+item.width/2)/scale,edge=y+(item.top+item.bottom)/2<center?sourceTop:sourceBottom,nativeY=edge/scale-dy.get(staff),offset=y-edge;
    if(!lifeProjected)lifeProjected=lifeLayouts.map(l=>{
     const obstacles=rawInk.filter(o=>(l.weights.get(o.staff)||0)>.1).map(o=>({x:o.x*l.scale,r:o.r*l.scale,y:(o.y+l.dy.get(o.staff))*l.scale,b:(o.b+l.dy.get(o.staff))*l.scale}));
     // Empty neighbouring staves are ownership boundaries too: a badge must
     // not appear to annotate another instrument's silent measure.
     for(const st of possible)if((l.weights.get(st.id)||0)>.1)obstacles.push({x:-Infinity,r:Infinity,y:(st.y+l.dy.get(st.id)-st.height/2)*l.scale-3,b:(st.y+l.dy.get(st.id)+st.height/2)*l.scale+3});
     for(const o of rawBars){const presence=1-o.owners.reduce((n,v)=>n*(1-(l.weights.get(v.id)||0)),1);if(presence<.03)continue;const edge=(vv,sign)=>{let remaining=1,sum=0;for(const v of vv){const w=l.weights.get(v.id)||0;sum+=remaining*w*(v.y+l.dy.get(v.id)+sign*v.height/2);remaining*=1-w;}return sum/presence*l.scale;};obstacles.push({x:o.x*l.scale,r:o.r*l.scale,y:edge(o.owners,-1),b:edge([...o.owners].reverse(),1)});}
     const locators=S.score_locators;if(locators&&Number.isFinite(l.scrollX)){
      labelMeasure.font=`400 ${locators.font_size}px Han`;
      for(const loc of locators.items){const sx=1344+(loc.native_x-l.scrollX)*l.scale;if(sx<locators.left||sx>locators.right)continue;const m=labelMeasure.measureText(loc.text),half=m.width/2;obstacles.push({x:loc.native_x*l.scale-half,r:loc.native_x*l.scale+half,y:locators.baseline_y-(m.actualBoundingBoxAscent||locators.font_size)-100,b:locators.baseline_y+(m.actualBoundingBoxDescent||0)-100});}
     }
     for(const other of motifLabels){if(other===item||!other.anchor||(l.weights.get(other.row.s.staff)||0)*labelVisibility(other,l.t)<=.4)continue;const a=other.anchor,xx=a.native_x*l.scale+(a.screen_dx||0);let yy=(a.native_y+l.dy.get(other.row.s.staff))*l.scale+(a.screen_dy||0);if(other.bandStaff){const slot=l.bandSlots.get(other.bandStaff+':'+(other.bandSide||'below'));if(!slot)continue;yy=slot.y+slot.row_height*slot.alpha*(other.bandSlot+.5)-(other.top+other.bottom)/2;}obstacles.push({x:xx-other.paddingX,r:xx+other.width+other.paddingX,y:yy+other.top,b:yy+other.bottom});}
     return{l,obstacles};
    });
    for(const {l,obstacles} of lifeProjected){const xx=nativeX*l.scale-item.width/2,yy=(nativeY+l.dy.get(staff))*l.scale+offset,a={x:xx-item.paddingX,r:xx+item.width+item.paddingX,y:yy+item.top,b:yy+item.bottom};if(Number.isFinite(l.scrollX)){const shift=1344-l.scrollX*l.scale;if(a.r+shift<390||a.x+shift>2640)continue;}if(obstacles.some(o=>a.r>o.x-labelGap&&a.x<o.r+labelGap&&a.b>o.y-labelGap&&a.y<o.b+labelGap))return false;}
    return true;
   };
   const preferred=item.preferredSide||'above',above=Math.min(b.y-item.bottom-labelGap,center-half-item.bottom-labelGap),below=Math.max(b.b-item.top+labelGap,center+half-item.top+labelGap),ys=[...(preferred==='above'?[above,below]:[below,above]),safeTop-item.top,safeBottom-item.bottom];
   for(let y=safeTop-item.top;y<=safeBottom-item.bottom;y+=3)ys.push(y);
   // Explanatory labels must not occupy their own range-edge connector
   // endpoint. Fix them before the source range, leaving its right edge and
   // the real inter-staff corridor open as the score scrolls.
   const relation=item.placementRole==='relation',foreign=item.placementRole==='leading'||relation,middle=foreign?b.x-w-24:(b.x+b.r-w)/2,xmin=b.x-w-(foreign?180:75),xmax=relation?b.r-w-36:foreign?b.x-w-24:b.r+75,xs=foreign?[middle,...(relation?[xmax]:[])]:[middle,b.x,b.r-w,b.r+16,b.x-w-16];for(let d=6;d<Math.max(middle-xmin,xmax-middle);d+=6)for(const x of[middle-d,middle+d])if(x>=xmin&&x<=xmax)xs.push(x);
   let point=null,best=null;
   const sourceTop=Math.min(b.y,center-half),sourceBottom=Math.max(b.b,center+half);
   const distanceToSource=y=>Math.max(0,sourceTop-(y+item.bottom),(y+item.top)-sourceBottom);
   const clearYs=[...new Set(ys)].filter(y=>y+item.top>=safeTop&&y+item.bottom<=safeBottom).sort((a,z)=>distanceToSource(a)-distanceToSource(z));
   // Harmonic roles must remain beside their actual phrase. Prefer the
   // nearest legal source x before choosing vertical position; y-first
   // packing can silently place a role over the preceding measure.
   const sourceXs=[...new Set([(b.x+b.r-w)/2,b.x,b.r-w,...xs.filter(x=>x+w/2>=b.x&&x+w/2<=b.r)])];
   const candidates=relation?sourceXs.sort((a,b)=>Math.abs(a-xmax)-Math.abs(b-xmax)).flatMap(x=>clearYs.map(y=>({x,y}))):clearYs.flatMap(y=>sourceXs.map(x=>({x,y})));
   for(const {x,y} of candidates){const a={x:x-item.paddingX,r:x+w+item.paddingX,y:y+item.top,b:y+item.bottom},hits=ink.filter(o=>a.r>o.x+0.01-(P.label_typography?labelGap:0)&&a.x<o.r-0.01+(P.label_typography?labelGap:0)&&a.b>o.y+0.01-(P.label_typography?labelGap:0)&&a.y<o.b-0.01+(P.label_typography?labelGap:0));if(!best||hits.length<best.hits.length)best={x,y,hits};if(!hits.length&&lifecycleClear(x,y)){point={x,y};break}}
   item.layout={scale,b,center,safeTop,safeBottom,best};
   if(point){const edge=point.y+(item.top+item.bottom)/2<center?sourceTop:sourceBottom,screenDy=point.y-edge,nativePoint={x:(point.x+item.width/2)/scale,y:edge/scale-dy.get(staff)},local=new DOMPoint(nativePoint.x,nativePoint.y).matrixTransform(anchorNode.getCTM().inverse().multiply(world.getCTM()));item.anchor={node:anchorNode,x:local.x,y:local.y,screen_dx:-item.width/2,screen_dy:screenDy,native_x:nativePoint.x,native_y:nativePoint.y,reference_scale:scale};item.placement='fixed';placed.push({x:point.x-item.paddingX,r:point.x+w+item.paddingX,y:point.y+item.top,b:point.y+item.bottom});item.group.dataset.sourceSpan=r.s.id;break;}else item.placement='no-local-gap';
   }
  }
 }
 // Compile every reserved-band anchor before free-gap labels, including
 // bands whose reading context starts later but overlaps this label's life.
 // Otherwise a future fixed badge can collide with an already-placed label.
 for(const item of [...motifLabels].sort((a,b)=>Number(!!b.bandStaff)-Number(!!a.bandStaff)||a.window[0]-b.window[0]))compileMotifAnchors(item.window[0],[item]);
 // Conservative full-lifetime screening of reserved rows, in the same
 // local layouts used by the renderer. Potential path-bbox conflicts are
 // subsequently checked against actual thin ink at their precise timestamps.
 const bandLifetimeRisks=[];
 function auditReservedBandLifetimes(){
  const world=actor.scoreClip.firstElementChild,staves=S.geometry.staves;
  const nativeBox=node=>{if(motifNativeBoxes.has(node))return motifNativeBoxes.get(node);const b=node.getBBox(),m=world.getCTM().inverse().multiply(node.getCTM()),pts=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>new DOMPoint(x,y).matrixTransform(m)),v={x:Math.min(...pts.map(p=>p.x)),r:Math.max(...pts.map(p=>p.x)),y:Math.min(...pts.map(p=>p.y)),b:Math.max(...pts.map(p=>p.y))};motifNativeBoxes.set(node,v);return v;};
  for(const item of motifLabels.filter(i=>i.bandStaff&&i.anchor)){
   const times=[...motifLayoutCache.values()].filter(l=>l.t>=item.window[0]&&l.t<=item.window[1]&&(l.weights.get(item.bandStaff)||0)*labelVisibility(item,l.t)>.4),minScale=Math.min(...times.map(l=>l.scale)),half=(item.width/2+item.paddingX+item.size*.3)/minScale,near=[],x=item.anchor.native_x;
   for(const st of staves)for(const entry of staffGroups.get(st.id)||[]){const m=entry.measure;if(m&&(m.x+m.width<x-half-600||m.x>x+half+600))continue;for(const node of entry.node.querySelectorAll(primitives)){if(node.parentNode===entry.node&&node.localName==='path')continue;const b=nativeBox(node);if(b.r>x-half&&b.x<x+half)near.push({...b,staff:st.id,id:node.id||node.closest('[id]')?.id});}}
   for(const c of controlEntries)for(const node of c.node.querySelectorAll(primitives)){const b=nativeBox(node);if(b.r>x-half&&b.x<x+half)near.push({...b,staff:c.staff,id:node.id||node.closest('[id]')?.id});}
   const seen=new Set();
   for(const l of times){const slot=l.bandSlots.get(item.bandStaff+':'+(item.bandSide||'below'));if(!slot)continue;const xx=x*l.scale-item.width/2,yy=slot.y+(slot.slot_offsets?.[item.bandSlot]??slot.row_height*slot.alpha*(item.bandSlot+.5))-(item.top+item.bottom)/2,a={x:xx-item.paddingX,r:xx+item.width+item.paddingX,y:yy+item.top,b:yy+item.bottom},shift=1344-(l.scrollX||0)*l.scale;if(Number.isFinite(l.scrollX)&&(a.r+shift<390||a.x+shift>2640))continue;
    for(const o of near){if((l.weights.get(o.staff)||0)<.1)continue;const v={x:o.x*l.scale,r:o.r*l.scale,y:(o.y+l.dy.get(o.staff))*l.scale,b:(o.b+l.dy.get(o.staff))*l.scale},gap=item.size*.16;if(a.r<=v.x-gap||a.x>=v.r+gap||a.b<=v.y-gap||a.y>=v.b+gap)continue;const key=o.id+'|'+Math.floor(l.t);if(seen.has(key))continue;seen.add(key);bandLifetimeRisks.push({seconds:l.t,representative_id:item.representative_id,label:item.label.textContent,staff:item.bandStaff,obstacle_staff:o.staff,svg_id:o.id,bounds:a,obstacle:v,kind:'conservative-native-bbox-needs-actual-ink-check'});}
   }
  }
 }
 if(P.coverage_diagnostic_mode)auditReservedBandLifetimes();
 for(const cue of P.cues.filter(c=>c.require_links))for(const ref of cue.link_targets||[cue]){
  const label=motifLabels.find(x=>x.row.s.id===ref.target_id);
  if(!label||label.placement!=='fixed')throw Error('Required source label cannot be placed: '+ref.target_id);
 }
 // Late retention changes only the lifetime of an already allocated row.
 // Apply after all original anchor/size/slot compilation, never before it.
 for(const extension of P.band_display_extensions||[]){
  const band=P.label_bands?.[extension.index];
  if(!band||band.staff!==extension.staff||(band.side||'below')!==extension.side||Math.abs(band.from-extension.from)>1e-7||Math.abs(band.to-extension.original_to)>1e-7||!(extension.to>=band.to))throw Error('Band retention does not match original allocated row');
  band.to=extension.to;
 }
 displayClockReady=true;
 if(P.compact_vertical)installCompactLabelPolicy(actor,S,P,motifLabels,motifLayoutCache);
 let last={};
 function draw(F){
  const shown=ease((F.seconds-P.panel_in)/.85)*(1-ease((F.seconds-P.panel_out)/.85))*(jointCollect?0:1)+(jointCollect?1:0);panel.setAttribute('transform',`translate(${(1-shown)*1220} 0)`);panel.style.opacity=shown;
  // All preview windows use the same absolute reading track. Text withdraws
  // as the old connector retracts, then the next text rises softly into place.
  // The paper and score continue uninterrupted through this internal change.
  for(const page of pages){
   const incoming=page.ordinal===0?1:ease((F.seconds-page.from-(incrementalSidebar?0:.35))/(incrementalSidebar?.24:.35));
   const outgoing=page.ordinal===pages.length-1?1:1-ease((F.seconds-page.to)/(incrementalSidebar?.14:.35));
   page.alpha=incoming*outgoing;page.g.style.opacity=incrementalSidebar?0:page.alpha;page.g.style.visibility=page.alpha>0?'visible':'hidden';
   page.g.setAttribute('transform',incrementalSidebar?'translate(0 0)':`translate(0 ${16*(1-incoming)-12*(1-outgoing)})`);
  }
  for(const item of groups)if(item.b.reveal_from!==undefined&&!persistentBlocks.some(p=>p.index===item.index)){item.g.style.opacity=ease((F.seconds-item.b.reveal_from)/.7);}
  for(const item of persistentBlocks){const incoming=item.first?1:ease((F.seconds-item.from-.35)/.35),outgoing=item.last?1:1-ease((F.seconds-item.to)/.35);item.node.style.opacity=incoming*outgoing;item.node.style.visibility=incoming*outgoing>0?'visible':'hidden';item.node.setAttribute('transform',`translate(0 ${16*(1-incoming)-12*(1-outgoing)})`);}
  incrementalSidebar?.applyAnchorGeometry(F.seconds);nativeComparisons.draw(F);
  let ci=0;for(let i=0;i<P.cues.length;i++)if(F.seconds>=P.cues[i].at)ci=i;
  const cue=P.cues[ci]||{at:P.panel_in,no_link:true,focus_blocks:[]},old=P.cues[Math.max(0,ci-1)]||cue,u=ease((F.seconds-cue.at)/.35),weights={};
  if(!old.no_link)weights[old.theme]=1-u;if(!cue.no_link)weights[cue.theme]=(weights[cue.theme]||0)+u;
  const activeWindows=connectionWindows.filter(w=>lifetimeProbeState?lifetimeProbeState.routes.includes(w.index):F.seconds>=w.from&&F.seconds<w.to).map(w=>lifetimeProbeState?{...w,hold_until:Math.max(w.hold_until,F.seconds+1),to:Math.max(w.to,F.seconds+1.35)}:w).map(w=>({...w,progress:windowProgress(w,F.seconds),phase:F.seconds>=w.hold_until?'retracting':F.seconds<w.full_at?'extending':'held'}));
  const uniqueWindows=new Map();
  for(const w of activeWindows){const prior=uniqueWindows.get(w.semanticKey);if(!prior||w.progress>prior.progress)uniqueWindows.set(w.semanticKey,w);if(!w.no_link)weights[w.theme]=Math.max(weights[w.theme]||0,w.progress*w.page.alpha);}
  const visible=[],probeSourceIds=new Set([...motifLabels.map(i=>i.row.s.id),...activeWindows.map(w=>w.target_id)]);
  const viewportMatrix=P.display_lifetime_diagnostic?root.getCTM().inverse().multiply(actor.scoreClip.firstElementChild.getCTM()):null;
  for(const r of rows){
   const w=F.weights[r.s.staff]||0;
   if(viewportMatrix&&w<.03){r.band.style.opacity=0;continue;}
   if(viewportMatrix&&r.nativeBounds&&!probeSourceIds.has(r.s.id)){
    const x=r.nativeBounds.x*viewportMatrix.a+viewportMatrix.e,right=r.nativeBounds.r*viewportMatrix.a+viewportMatrix.e;
    if(right<380||x>2655){r.frame={x:x-9,r:right+9,y:0,b:0};r.band.style.opacity=0;continue;}
   }
   const bs=r.nodes.map(box).filter(v=>v&&v.r>v.x);if(!bs.length||w<.03){r.band.style.opacity=0;continue}
   const b=union(bs),label=staffLabels.get(r.s.staff),center=+label.getAttribute('y')-10;r.box=b;r.center=center;
   const other=[...staffLabels].filter(([s])=>(F.weights[s]||0)>.1).map(([,n])=>+n.getAttribute('y')-10).sort((a,b)=>a-b),at=other.indexOf(center),prev=other[at-1]??center-200,next=other[at+1]??center+200;
   r.safeTop=(prev+center)/2+7;r.safeBottom=(next+center)/2-7;
   const a=weights[r.s.theme]||0,parent=r.s.role==='parent';
   const top=Math.max(r.safeTop,Math.min(center-24,b.y-6)),bottom=Math.min(r.safeBottom,Math.max(center+24,b.b+6));
   r.frame={x:b.x-9,r:b.r+9,y:top,b:bottom};
   for(const[k,v]of Object.entries({x:b.x-9,y:top,width:Math.max(1,b.r-b.x+18),height:Math.max(12,bottom-top),fill:'#A7A194','fill-opacity':parent?0:.05+.05*a,stroke:'none','stroke-opacity':0,'stroke-width':0,opacity:w}))r.band.setAttribute(k,v);
   if(r.s.paint===false)r.band.style.opacity=0;if(r.s.annotation_only){r.band.style.opacity=w;for(const[k,v]of Object.entries({x:b.x-4,y:b.y-4,width:b.r-b.x+8,height:b.b-b.y+8,fill:'none',stroke:r.s.annotation_color||'#B15B50','stroke-width':1.3,'stroke-opacity':.55}))r.band.setAttribute(k,v);}
   if(onScreen(b)&&w>.6)visible.push(r);
  }
  for(const g of groups){
   if(P.stable_reading_blocks&&!P.incremental_sidebar){const before=pages[g.page.ordinal-1]?.blocks.get(g.index),after=pages[g.page.ordinal+1]?.blocks.get(g.index);if((before&&before.top===g.top&&F.seconds<g.page.from+.7)||(after&&after.top===g.top&&F.seconds>g.page.to)){g.g.setAttribute('transform',`translate(0 ${-16*(1-(g.page.ordinal===0?1:ease((F.seconds-g.page.from-.35)/.35)))+12*(1-(g.page.ordinal===pages.length-1?1:1-ease((F.seconds-g.page.to)/.35)))})`);}else g.g.removeAttribute('transform');}
   const reading=((old.focus_blocks||[old.block]).includes(g.index)?1-u:0)+((cue.focus_blocks||[cue.block]).includes(g.index)?u:0),current=Math.max(reading,...activeWindows.filter(w=>w.page===g.page&&(w.focus_blocks||[w.block]).includes(g.index)).map(w=>w.progress));g.g.style.opacity=incrementalSidebar?1:g.b.kind==='footnote'?1:.78+.22*Math.min(1,current);
   for(const t of g.hot){const matches=c=>g.index===c.block&&t.dataset.key===c.keyword&&Number(t.dataset.occurrence||0)===(c.keyword_occurrence||0),window=activeWindows.filter(w=>w.page===g.page&&w.progress>0&&matches(w)).sort((a,b)=>b.progress-a.progress||a.from-b.from)[0],hit=window||(matches(cue)?cue:null);t.style.fill=hit?(hit.connection_color||P.palette[hit.theme]||t.dataset.baseColor):t.dataset.baseColor}
  }
  // Each window owns one absolute-time length budget. A new connection can
  // extend while an earlier one is held or retracting; reading cues do not
  // serialize the independent musical events.
  incrementalSidebar?.draw(F.seconds,activeWindows);
  const retreat=.35,extend=.65,elapsed=F.seconds-cue.at,legacyRetiring=ci>0&&!old.no_link&&elapsed<retreat,legacyIndex=legacyRetiring?ci-1:ci,legacyCue=P.cues[legacyIndex]||cue,delay=ci>0&&!old.no_link?retreat:0;
  const legacyPage=pageAt(legacyCue.at),arrival=Math.max(legacyCue.at+delay,P.panel_in+.85,legacyPage.ordinal?legacyPage.from+.70:-Infinity),legacyProgress=(legacyRetiring?1-ease(elapsed/retreat):ease((F.seconds-arrival)/extend))*(1-ease((F.seconds-(P.panel_out-retreat))/retreat));
  const jobs=windowMode?[...uniqueWindows.values()].map(w=>({connectionCue:w,linePage:w.page,progress:w.progress,retiring:w.phase==='retracting',lineIndex:w.cue_index,routeKey:'window-'+w.index,window:w,lineMix:w.page.alpha})):(legacyCue.link_targets?.length?legacyCue.link_targets.map(ref=>({...legacyCue,...ref})):[legacyCue]).map(c=>({connectionCue:c,linePage:legacyPage,progress:legacyProgress,retiring:legacyRetiring,lineIndex:legacyIndex,routeKey:legacyIndex,window:null,lineMix:(legacyRetiring?1-ease(elapsed/retreat):1)*legacyPage.alpha}));
  const multiple=jobs.length>1,connectionAudits=[],jointPrepared=[];
  // Opaque same-colour children share one translucent group. Overlapping
  // common stems are composited once, including separate simultaneous words.
  const linkOpacity=(theme,at)=>P.connection_opacities?.[theme]??(.70+.13*(1-ease((F.seconds-at)/1.2)));
  scoreLink.style.opacity=links.style.opacity=!windowMode&&multiple?linkOpacity(legacyCue.theme,legacyCue.at)*shown*legacyPage.alpha:1;
  for(const paint of connectorPaintGroups.values()){paint.alpha=0;for(const n of [paint.score,paint.paper,paint.marks])n.style.opacity=0;}
  for(const layer of connectorLayers)for(const n of Object.values(layer))n.style.opacity=0;
  for(let connectionIndex=0;connectionIndex<jobs.length;connectionIndex++){
  const {connectionCue,linePage,progress,retiring,lineIndex,routeKey,window:connectionWindow,lineMix}=jobs[connectionIndex],layer=connectorLayers[connectionIndex],{line,rightLine,underline,badge,endpoint,terminalStub}=layer;
  const active=visible.filter(r=>r.s.theme===connectionCue.theme&&r.s.role!=='parent');
  const target=active.find(r=>r.s.id===connectionCue.target_id);
  // An explicitly enabled source exit follows immutable native geometry.
  const source=connectionCue.source_lifecycle?rows.find(r=>r.s.id===connectionCue.target_id):null;
  let sourceLifecycle=null;
  if(source&&Number.isFinite(source.nativeRight)){const m=root.getCTM().inverse().multiply(actor.scoreClip.firstElementChild.getCTM()),edge=source.nativeRight*m.a+m.e+9,start=connectionCue.source_lifecycle?.start_x??650,finish=connectionCue.source_lifecycle?.finish_x??500,remaining=ease((edge-finish)/(start-finish));sourceLifecycle={edge,start,finish,remaining,phase:edge<=finish?'source-exited':edge<start?'source-leaving':'visible'};}
  line.style.opacity=rightLine.style.opacity=underline.style.opacity=badge.style.opacity=endpoint.style.opacity=terminalStub.style.opacity=0;
  const block=(incrementalSidebar?pages.find(p=>F.seconds>=p.from&&F.seconds<p.to)?.blocks.get(connectionCue.block):null)||linePage.blocks.get(connectionCue.block),keyword=connectionCue.keyword,occurrence=connectionCue.keyword_occurrence||0;
  const earlyPrefix=connectionWindow?.routing_layout_from!==undefined&&F.seconds<connectionWindow.routing_layout_from;
  // Only new optional prefixes resolve their actual visible text node. The
  // parent interval keeps its already-checked geometry byte for byte.
  const persistentWordBlock=earlyPrefix?persistentBlocks.find(p=>p.index===connectionCue.block&&p.originalNodes.includes(block?.g)&&Number(p.node.style.opacity)>.99):null;
  const wordNodes=persistentWordBlock?[...persistentWordBlock.node.querySelectorAll('tspan[data-key]')]:(block?.hot||[]);
  const words=keyword?wordNodes.filter(n=>n.dataset.key===keyword&&Number(n.dataset.occurrence||0)===occurrence):[];
  const textNode=persistentWordBlock?.node||block?.g;
  const actualTextVisible=(()=>{if(incrementalSidebar)return incrementalSidebar.blockAlpha(block?.index,F.seconds,keyword,occurrence)>.03;if(!earlyPrefix)return true;if(!textNode||F.seconds<(block.b.reveal_from??-Infinity)+.7)return false;let opacity=1;for(let n=textNode;n&&n!==root;n=n.parentElement){if(n.style?.visibility==='hidden'||n.style?.display==='none')return false;opacity*=Number(n.style?.opacity||1);}return opacity>.03&&(persistentWordBlock?Number(persistentWordBlock.node.style.opacity)>.99:linePage.alpha>.99);})();
  // A wrapped keyword retains separate local underlines. Exit through its
  // leftmost segment, rather than a one-character fragment at the line end.
  const wordSegments=words.map((node,index)=>({node,index,b:box(node)})).filter(s=>s.b).sort((a,b)=>a.b.x-b.b.x||(b.b.r-b.b.x)-(a.b.r-a.b.x)||a.index-b.index);
  const anchor=wordSegments[0],figureAnchor=connectionCue.figure_id?nativeComparisons.anchor(connectionCue.figure_id):null,paperPrefix=figureAnchor?.points||[],wb=connectionCue.figure_id?(figureAnchor?.port?{x:figureAnchor.port.x,r:figureAnchor.port.x,y:figureAnchor.port.y-7,b:figureAnchor.port.y-7}:null):(anchor?paperWordBounds(anchor.node):null),colour=connectionCue.connection_color||P.palette[connectionCue.theme]||P.connection_color||'#58645B';
  const jointJob={index:connectionWindow?.index,options:[],selected:null};if(jointMode)jointPrepared.push(jointJob);
  let linkState=connectionCue.no_link?'semantic-no-link':!keyword||!wb?'no-exact-keyword':!actualTextVisible?'exact-block-not-visible':linePage.alpha<=.01?'page-hidden':'no-visible-source',routeAudit=null;
  if(windowMode)connectorPaint(layer,colour,linePage,linkOpacity(connectionCue.theme,connectionWindow.from)*shown*linePage.alpha);
  if(!connectionCue.no_link&&keyword&&wb&&sourceLifecycle?.phase==='source-exited')linkState='source-exited';
  if(wb&&actualTextVisible&&shown>.98&&linePage.alpha>.01){
   underline.setAttribute('d',words.map(n=>{const b=paperWordBounds(n);return `M ${b.x} ${b.b+(b.ink?5:7)} H ${b.r}`}).join(' '));underline.setAttribute('stroke',colour);underline.style.opacity=windowMode?1:shown*lineMix;
  }
  if(!connectionCue.no_link&&target&&wb&&actualTextVisible&&shown>.98&&linePage.alpha>.01&&sourceLifecycle?.phase!=='source-exited'){
   const b=target.frame,wm=root.getCTM().inverse().multiply(actor.scoreClip.firstElementChild.getCTM()),scale=Math.abs(wm.a),half=(staffGeometry.get(target.s.staff)?.height||720)*Math.abs(wm.d)/2;
   const sourcePort=connectionCue.source_port||{},tx=sourcePort.edge==='left'?b.x+(sourcePort.native_inset||0)*scale:b.r-(sourcePort.native_inset||0)*scale;
   // Do not clamp an offscreen endpoint into a false source position.
   if(tx>=400&&tx<2612){
    const terminalMark=!!sourcePort.terminal_mark;
    // Range fills stop at the mid-gap; connector lanes may use the whole
    // actual inter-staff gap. In particular, the first staff has no hidden
    // neighbour above it. Native ink remains the collision authority.
    const neighbours=[...staffLabels].filter(([id])=>(F.weights[id]||0)>.1).map(([id,n])=>({center:+n.getAttribute('y')-10,half:(staffGeometry.get(id)?.height||720)*Math.abs(wm.d)/2}));
    const above=neighbours.filter(n=>n.center<target.center-.1).sort((a,b)=>b.center-a.center)[0],below=neighbours.filter(n=>n.center>target.center+.1).sort((a,b)=>a.center-b.center)[0];
    const lane={staff:target.s.staff,channelOffset:connectionWindow?(connectionWindow.scoreSlot||0)*8:0,sourceSide:routeSides.get(routeKey+':'+connectionCue.target_id)||target.routeSide,leftX:b.x,x:tx,right:2630,center:target.center,top:Math.max(74,above?above.center+above.half+8:74),bottom:Math.min(1800,below?below.center-below.half-8:1800),upper:Math.max(target.safeTop+4,b.y),lower:Math.min(target.safeBottom-4,b.b),staffHalf:half,scale,...(sourcePort.side?{onlySide:sourcePort.side}:{})};
    const ink=collectInk(F,target,(P.source_ports?Math.min(tx,b.x):tx)-10,2755),key=routeKey+':'+connectionCue.target_id,prior=routeCache.get(key);
    if(jointMode){routeAttemptDiagnostics=[];const paperInk=paperPrefix.length?[]:paperObstacles(wb);const job={wb,connectionWindow,paperPrefix,paperInk};if(P.route_diagnostic_mode)jointJob.diagnostic={lane,obstacle_count:ink.length,obstacles:ink.map(({segments,...b})=>({...b,segment_count:segments?.length})),word_bounds:wb,paper_text_obstacles:paperInk,target_id:connectionCue.target_id,keyword,source_text:block.b.text,source_ids:target.s.ids};jointJob.options=jointCandidates(lane,ink,lifetimeProbeState?.fixedCandidates?jointSelection.get(connectionWindow.index)?.split('@')[0]:jointCollect?null:jointSelection.get(connectionWindow.index)?.split('@')[0]).flatMap(c=>[0,1].map(slot=>jointOption(job,c,slot)).filter(Boolean));jointJob.selected=jointCollect&&!lifetimeProbeState?.fixedCandidates?jointJob.options[0]:jointJob.options.find(o=>o.key===jointSelection.get(connectionWindow.index));if(jointJob.diagnostic)jointJob.diagnostic.route_attempts=routeAttemptDiagnostics;}
    const selected=jointJob.selected,route=jointMode?selected?.route:chooseConnectorRoute(lane,ink,prior?.descriptor);
    if(route){
     const topologyChanged=prior&&(prior.descriptor.side!==route.descriptor.side||(prior.descriptor.pivot!==undefined)!==(route.descriptor.pivot!==undefined)),changes=(prior?.changes||0)+(topologyChanged?1:0);routeCache.set(key,{descriptor:route.descriptor,changes});
     const entry=route.points[0],end=route.points.at(-1),corridor=jointMode?2766+(selected?.slot||0)*14:2766+(connectionWindow?.paperSlot||0)*10,wordY=wb.b+(wb.ink?5:7),alpha=linkOpacity(connectionCue.theme,connectionWindow?.from??legacyCue.at)*shown*linePage.alpha,paperPoints=selected?.paperPoints||[{x:wb.x,y:wordY},{x:corridor,y:wordY},{x:corridor,y:entry.y},entry],reveal=revealConnector(paperPoints,route,progress*(sourceLifecycle?.remaining??1));
     if(jointMode)jointJob.visible={...selected,visible_segments:reveal.visible_segments};
     line.setAttribute('d',reveal.score_path);line.setAttribute('stroke',colour);line.style.opacity=windowMode||multiple?1:alpha;
     // Paper-side segment is above the paper, score-side segment below native
     // ink. The 2630 seam is continuous; the vertical corridor is real margin.
     rightLine.setAttribute('d',reveal.paper_path);rightLine.setAttribute('stroke',colour);rightLine.style.opacity=windowMode||multiple?1:alpha;
     endpoint.setAttribute('cx',end.x);endpoint.setAttribute('cy',end.y);endpoint.setAttribute('r',sourcePort.endpoint_radius??5);endpoint.setAttribute('fill',colour);endpoint.style.opacity=reveal.arrived?(windowMode?1:shown):0;
     if(terminalMark){terminalStub.setAttribute('d',`M ${end.x} ${end.y} V ${end.y-10}`);terminalStub.setAttribute('stroke',colour);terminalStub.style.opacity=reveal.arrived?(windowMode?1:shown):0}
     linkState=sourceLifecycle?.phase==='source-leaving'?'source-leaving':route.gaps?'connected-ink-gaps':'connected';routeAudit={joint_candidate:selected?.key||null,semantic_group:connectionWindow?.semanticGroup||null,paper_slot:selected?.slot??connectionWindow?.paperSlot??0,score_slot:connectionWindow?.scoreSlot??0,channel_offset_px:route.channel_offset_px||0,continuous:!!route.continuous,side:route.descriptor.side,cached:route.cached,reroutes:changes,ink_obstacles:ink.length,ink_gaps:route.gaps,source_endpoint:end,entry,points:route.points,figure_anchor:figureAnchor,word_anchor:{x:wb.x,y:wordY,segment:anchor?.index??null,segment_count:words.length,underline_y:wordY},paper_path:rightLine.getAttribute('d'),animation:{phase:sourceLifecycle?.phase==='source-leaving'?'source-leaving':retiring||(!windowMode&&F.seconds>P.panel_out-retreat)?'retracting':reveal.arrived?'held':'extending',...reveal,extend_seconds:extend,retract_seconds:retreat}};
    }else linkState='no-interstaff-lane';
   }else linkState='source-endpoint-offscreen';
  }
  const audit={target:target||source,linkState,routeAudit,keyword,occurrence,sourceLifecycle,role:connectionCue.role||null,window:connectionWindow?{index:connectionWindow.index,from:connectionWindow.from,full_at:connectionWindow.full_at,hold_until:connectionWindow.hold_until,to:connectionWindow.to,cue_index:lineIndex,page_id:linePage.id,target_id:connectionCue.target_id,source_start:connectionWindow.source_start??null,source_end:connectionWindow.source_end??null,continuation:!!connectionWindow.continuation,source_q:target||source?[ (target||source).s.q0,(target||source).s.q1 ]:null,progress,effective_progress:progress*(sourceLifecycle?.remaining??1),phase:connectionWindow.phase,page_opacity:linePage.alpha}:null};connectionAudits.push(audit);
  const required=windowMode?connectionCue.require_link:(legacyCue.require_links&&!retiring);
  if(!jointCollect&&required&&progress>.999&&shown>.98&&linePage.alpha>.99&&linkState!=='connected'&&!(connectionCue.source_lifecycle&&((linkState==='source-leaving'&&routeAudit?.ink_gaps===0)||(linkState==='source-exited'&&sourceLifecycle?.remaining===0))))throw Error('Required guide connection missing at '+F.seconds+': '+(connectionWindow?.index??connectionCue.role)+'='+linkState);
  }
  let jointAudit=null;
  if(jointMode){
   if(jointCollect){const referenceJobs=jointPrepared.filter(j=>!jointReference?.window_indices||jointReference.window_indices.includes(j.index));for(const j of referenceJobs){const context=connectionAudits.filter(a=>a.window?.index===j.index).map(a=>({state:a.linkState,keyword:a.keyword,box:a.target?.frame,staff:a.target?.s.staff,page:a.window.page_opacity,window:a.window}));if(P.route_diagnostic_mode)routeDiagnostics.samples.push({seconds:F.seconds,window:j.index,candidates:j.options.map(o=>o.key)});if(!j.options.length){if(P.route_diagnostic_mode)routeDiagnostics.failures.push({seconds:F.seconds,window:j.index,context,...j.diagnostic});else throw Error('No joint reference candidates at '+F.seconds+' window '+j.index+' '+JSON.stringify(context));}}jointSnapshots.push({seconds:F.seconds,jobs:referenceJobs});}
   const metrics={crossings:0,overlap_px:0,close_px:0,cost:0};for(let i=0;i<jointPrepared.length;i++)for(let j=i+1;j<jointPrepared.length;j++){const a=jointCollect?jointPrepared[i].selected:jointPrepared[i].visible,b=jointCollect?jointPrepared[j].selected:jointPrepared[j].visible;if(a&&b){const m=jointPair(a,b);for(const k of Object.keys(metrics))metrics[k]+=m[k]||0;}}
   jointAudit={...metrics,planned:!jointCollect,reference_count:jointPlanAudit?.reference_count||0,assignments:jointPrepared.map(j=>({window:j.index,candidate:j.selected?.key||null})),hard_conflict:metrics.overlap_px>3};
   if(!jointCollect&&jointAudit.hard_conflict)throw Error('Joint connector false shared stem at '+F.seconds);
  }
  const {target=null,linkState=windowMode?'no-active-window':'no-connection',routeAudit=null,keyword=null,occurrence=0}=connectionAudits[0]||{},lineIndex=windowMode?(jobs[0]?.lineIndex??null):legacyIndex;
  const named=[],labelInkCollisions=[];
  for(const item of motifLabels){
   item.group.style.opacity=0;const r=item.row,a=item.anchor,opacity=(F.weights[r.s.staff]||0)*labelVisibility(item,F.seconds);if(!a||opacity<.03)continue;
   const p=new DOMPoint(a.x,a.y).matrixTransform(root.getCTM().inverse().multiply(a.node.getCTM()));p.x+=a.screen_dx||0;p.y+=a.screen_dy||0;if(item.bandStaff){const slot=actor.labelSlots?.get(item.bandStaff+':'+(item.bandSide||'below'));if(!slot)continue;p.y=slot.y+(slot.slot_offsets?.[item.bandSlot]??(slot.row_height||64)*slot.alpha*(item.bandSlot+.5))-(item.top+item.bottom)/2;}
   item.group.setAttribute('transform',`translate(${p.x} ${p.y})`);item.group.style.opacity=opacity;item.label.setAttribute('x',0);item.label.setAttribute('y',0);
   for(const[k,v]of Object.entries({x:-item.paddingX,y:item.top,width:item.width+2*item.paddingX,height:item.bottom-item.top}))item.back.setAttribute(k,v);
   if(P.label_typography&&onScreen({x:p.x-item.paddingX,r:p.x+item.width+item.paddingX,y:p.y+item.top,b:p.y+item.bottom})&&(opacity>.4||lifetimeProbeState?.labels?.includes(item.labelIndex))){
    const raw={x:Math.max(390,p.x-item.paddingX),r:Math.min(2640,p.x+item.width+item.paddingX),y:Math.max(65,p.y+item.top),b:Math.min(1810,p.y+item.bottom)},gap=item.size*.30;
    const intersects=(o,margin)=>{const b={x:raw.x-margin,r:raw.r+margin,y:raw.y-margin,b:raw.b+margin};if(o.r<=390||o.x>=2640||o.b<=65||o.y>=1810||o.x>=b.r||o.r<=b.x||o.y>=b.b||o.b<=b.y)return false;if(o.kind!=='segments')return true;
     const extra=Math.max(0,(o.pad||0)-2);return o.segments.some(([a,z])=>{let lo=0,hi=1;for(const[key,min,max]of[['x',b.x-extra,b.r+extra],['y',b.y-extra,b.b+extra]]){const d=z[key]-a[key];if(Math.abs(d)<1e-9){if(a[key]<min||a[key]>max)return false;}else{let x=(min-a[key])/d,y=(max-a[key])/d;if(x>y)[x,y]=[y,x];lo=Math.max(lo,x);hi=Math.min(hi,y);if(lo>hi)return false;}}return true;});};
    const hits=collectInk(F,r,raw.x-gap,raw.r+gap,true).filter(o=>o.svg_id&&intersects(o,gap));
    if(hits.length){const obstacles=hits.map(o=>({svg_id:o.svg_id,obstacle_type:o.obstacle_type||'score-ink',staff:o.staff,kind:o.kind,x:o.x,r:o.r,y:o.y,b:o.b,actual_overlap:intersects(o,0),below_minimum_clearance:intersects(o,item.size*.16)}));labelInkCollisions.push({representative_id:item.representative_id,window:item.window,source_id:r.s.id,staff:r.s.staff,label:item.label.textContent,status:obstacles.some(o=>o.actual_overlap&&o.obstacle_type!=='native-reference-content')?'ink-overlap':obstacles.some(o=>o.actual_overlap)?'reference-content-overlap':obstacles.some(o=>o.below_minimum_clearance)?'clearance-below-0.16em':'compact-clearance-0.16-to-0.30em',bounds:raw,obstacles});}
   }
   named.push({label_index:item.labelIndex,id:r.s.id,representative_id:item.representative_id,label:item.label.textContent,theme:item.theme,staff:r.s.staff,x:p.x,y:p.y,size:item.size,bounds:{x:p.x-item.paddingX,r:p.x+item.width+item.paddingX,y:p.y+item.top,b:p.y+item.bottom},reserved_band:item.bandStaff||null,band_fit:item.bandFit||null,band_fit_detail:item.bandFitDetail||null,lines:item.lines||[item.label.textContent],band_slot:item.bandSlot,band_side:item.bandSide||null,padding:[item.paddingX,item.paddingY],opacity,barlines_checked:true,native_anchor:{x:a.native_x,y:a.native_y},fixed:true,reference_scale:a.reference_scale});
  }
  const activeIdentities=new Set(motifLabels.filter(i=>labelVisibility(i,F.seconds)>.4).map(i=>i.theme)),visibleNames=new Set(named.filter(i=>i.opacity>.4&&onScreen(i.bounds)).map(i=>i.theme)),unexplained=rows.filter(r=>r.s.paint!==false&&activeIdentities.has(r.s.theme)&&!visibleNames.has(r.s.theme)&&(F.weights[r.s.staff]||0)>.4&&onScreen(r.frame)).map(r=>({theme:r.s.theme,id:r.s.id,staff:r.s.staff,bounds:r.frame})),unplaced=motifLabels.filter(i=>!i.anchor&&labelVisibility(i,F.seconds)>.4&&(F.weights[i.row.s.staff]||0)>.4&&onScreen(i.row.frame)).map(i=>({representative_id:i.representative_id,source_id:i.row.s.id,label:i.label.textContent,staff:i.row.s.staff,status:i.placement}));
  tempo.textContent=P.tempo_labels.find(entry=>F.seconds>=entry.from&&F.seconds<entry.to)?.text||'';
  last={vertical_layout:actor.verticalLayoutAudit?.(),compact_vertical_policy:P.compact_vertical_audit,sidebar_incremental:incrementalSidebar?.audit(),scene:P.id,seconds:F.seconds,joint_routing:jointAudit,joint_plan:jointPlanAudit,reading_track_id:P.reading_track_id||null,reading_stage:pageAt(F.seconds).id,visible_reading_stages:pages.filter(p=>p.alpha>0).map(p=>({id:p.id,opacity:p.alpha,block_indices:p.block_indices})),cursor_topmost:root.lastElementChild===actor.readingLine,legacy_tick_count:rows.filter(r=>r.ticks).length,motif_labels:named,visible_materials:P.coverage_diagnostic_mode?visible.filter(r=>r.s.paint!==false).map(r=>({id:r.s.id,theme:r.s.theme,staff:r.s.staff,bounds:r.frame})):undefined,unexplained_visible_materials:unexplained,unplaced_visible_labels:unplaced,motif_label_ink_collisions:labelInkCollisions,motif_label_collisions:named.flatMap((a,i)=>named.slice(i+1).filter(b=>onScreen(a.bounds)&&onScreen(b.bounds)&&a.opacity>.4&&b.opacity>.4&&a.bounds.x<b.bounds.r&&b.bounds.x<a.bounds.r&&a.bounds.y<b.bounds.b&&b.bounds.y<a.bounds.b).map(b=>({a:a.id,b:b.id,labels:[a.label,b.label]}))),band_lifetime_risks:P.coverage_diagnostic_mode?bandLifetimeRisks:undefined,motif_label_placements:motifLabels.map(item=>({id:item.row.s.id,representative_id:item.representative_id,window:item.window,label:item.label.textContent,staff:item.row.s.staff,status:item.placement,layout:item.placement==='fixed'?undefined:item.layout})),range_border:{stroke:'none',width:0,opacity:0,focus_invariant:true},range_fill:{color:'#A7A194',rest:.05,active:.10},text_bottom:maxBottom,reading_page_heights:pages.map(p=>({id:p.id,bottom:p.bottom})),reading_blocks:groups.map(g=>({stage:g.page.id,index:g.index,unit_id:g.b.unit_id,ranges:g.b.display_ranges,top:g.top,bottom:g.bottom,bridge:g.b.bridge_id||null,reveal_from:g.b.reveal_from??null,persistent:persistentBlocks.some(p=>p.index===g.index),text:g.b.text})),active_theme:cue.theme,active_block:cue.block,source_relation:target?{id:target.s.id,staff:target.s.staff,measures:[target.s.measure0,target.s.measure1]}:null,connection_windows:activeWindows.map(w=>({index:w.index,from:w.from,full_at:w.full_at,hold_until:w.hold_until,to:w.to,cue_index:w.cue_index,page_id:w.page.id,target_id:w.target_id,source_start:w.source_start??null,source_end:w.source_end??null,source_q:w.source_q??null,continuation:!!w.continuation,progress:w.progress,phase:w.phase,page_opacity:w.page.alpha,rendered_as:uniqueWindows.get(w.semanticKey).index})),connections:connectionAudits.map(c=>({window:c.window,role:c.role,keyword:c.keyword,state:c.linkState,source_lifecycle:c.sourceLifecycle,target:c.target?{id:c.target.s.id,staff:c.target.s.staff,measures:[c.target.s.measure0,c.target.s.measure1]}:null,route:c.routeAudit})),link_state:linkState,route:routeAudit,link_keyword:keyword||null,keyword_occurrence:occurrence,line_cue_index:lineIndex,span_count:rows.length,blocks:P.blocks.filter(b=>b.kind!=='image').map(b=>b.text),new_alignment_verified:false};if(jointCollect&&P.route_diagnostic_mode&&labelInkCollisions.length){(routeDiagnostics.label_failures??=[]).push({seconds:F.seconds,labels:labelInkCollisions});}window.guideLinkageAudit=last;harmonyLayer.draw(F);
 }
 if(jointMode&&P.frozen_joint_plan){
  jointPlanAudit=P.frozen_joint_plan;jointSelection=new Map(jointPlanAudit.assignments.map(a=>[a.index,a.candidate]));
  for(const w of connectionWindows)if(!jointSelection.has(w.index))throw Error('Frozen plan missing window '+w.index);
 }else if(jointMode){
  jointCollect=true;
  const nativeDraw=actor.draw;
  let referenceOrdinal=0;for(const reference of P.routing_reference_frames){jointReference=reference;nativeDraw(reference.frame);draw(reference.frame);if(P.route_diagnostic_mode&&++referenceOrdinal%25===0)console.info('__GUIDE_PREFLIGHT__',JSON.stringify({references:referenceOrdinal,total:P.routing_reference_frames.length,failed_candidates:routeDiagnostics.failures.length,seconds:reference.seconds}));}
  if(routeDiagnostics.failures.length)throw Error('Global route preflight failed: '+routeDiagnostics.failures.length+' samples; diagnostic artifact required');
  try{solveJointPlan();}catch(error){if(P.route_diagnostic_mode)routeDiagnostics.assignment_failure=String(error);throw error;}jointCollect=false;jointReference=null;routeCache.clear();
 }
 function paperExitProbe(indices){return(P.paper_exit_probe_windows||[]).filter(w=>indices.includes(w.index)).map(raw=>{const w={...P.cues[raw.cue_index],...raw},page=pageById.get(w.page_id),block=page.blocks.get(w.block);if(w.figure_id)return{window:w.index,kind:'native-figure'};const segments=block.hot.filter(n=>n.dataset.key===w.keyword&&Number(n.dataset.occurrence||0)===(w.keyword_occurrence||0)).map(node=>({node,b:box(node)})).sort((a,b)=>a.b.x-b.b.x||(b.b.r-b.b.x)-(a.b.r-a.b.x));if(!segments.length)return{window:w.index,keyword:w.keyword,valid_slots:[],error:'missing-source-word'};const wb=paperWordBounds(segments[0].node),paperInk=paperObstacles(wb),job={wb,paperInk,connectionWindow:{...w,page,semanticGroup:w.semantic_group}},candidate={id:'paper-probe',route:{points:[{x:2630,y:wb.b+5}]}},options=[0,1].map(slot=>jointOption(job,candidate,slot)).filter(Boolean);return{window:w.index,keyword:w.keyword,word_bounds:wb,valid_slots:options.map(o=>o.slot),obstacles:options.length?undefined:paperInk};});}
 function lifetimeProbe(F,request){
  if(!P.display_lifetime_diagnostic)throw Error('Lifetime probe requires explicit diagnostic spec');
  const prior=jointCollect,ns=jointSnapshots.length,nf=routeDiagnostics.failures.length,nr=routeDiagnostics.samples.length,nl=routeDiagnostics.label_failures?.length||0;
  const labels=request.labels||[],routeResults=[];lifetimeProbeState={labels,routes:[]};jointCollect=true;
  try{
   // Existing collection mode reports impossible geometry; strict rendering
   // still retains every original guard. Probe routes separately so a broad
   // search horizon never impersonates an over-capacity final schedule.
   if(labels.length)draw(F);
   const seen=labels.length?last.motif_labels:[],ink=labels.length?last.motif_label_ink_collisions:[];
   const labelResults=labels.map(index=>{const v=seen.find(v=>v.label_index===index),item=motifLabels[index];let reason=null;
    if(!item.anchor)reason='unplaced-original-anchor';
    else if((F.weights[item.row.s.staff]||0)<.99)reason='natural-staff-transition';
    else if(!v)reason=item.bandStaff?'original-band-unavailable':'source-not-visible';
    else if(v.bounds.x<390||v.bounds.r>2640||v.bounds.y<65||v.bounds.b>1810)reason='label-clipped';
    else if(!item.row.frame||item.row.frame.r<=390||item.row.frame.x>=2640)reason='source-not-visible';
    else if(F.seconds<item.window[0]-.2&&seen.some(o=>o.label_index!==index&&o.theme===item.theme&&onScreen(o.bounds)&&F.seconds>=motifLabels[o.label_index].window[0]-.2&&F.seconds<=motifLabels[o.label_index].window[1]+.2))reason='same-semantic-representative-visible';
    else if(ink.some(c=>c.representative_id===item.representative_id&&c.window[0]===item.window[0]&&c.status!=='compact-clearance-0.16-to-0.30em'))reason='native-ink-or-reference-conflict';
    return{index,safe:!reason,reason,bounds:v?.bounds,source_bounds:item.row.frame,source_id:item.row.s.id,band:item.bandStaff||null,natural_weight:F.weights[item.row.s.staff]||0,ink_conflict:ink.some(c=>c.representative_id===item.representative_id&&c.window[0]===item.window[0]&&c.status!=='compact-clearance-0.16-to-0.30em')};});
   const pairs=seen.flatMap((a,i)=>seen.slice(i+1).filter(b=>a.bounds.x<b.bounds.r&&b.bounds.x<a.bounds.r&&a.bounds.y<b.bounds.b&&b.bounds.y<a.bounds.b&&a.opacity>.03&&b.opacity>.03).map(b=>[a.label_index,b.label_index]));
   const routePairs=[];
   if(request.fixed_candidates&&(request.routes||[]).length){
    lifetimeProbeState={labels:[],routes:request.routes||[],fixedCandidates:true};draw(F);
    const jobs=jointSnapshots.at(-1)?.jobs||[];
    for(const index of request.routes||[]){const job=jobs.find(j=>j.index===index),c=last.connections.find(c=>c.window?.index===index);routeResults.push({index,candidates:job?.options.map(o=>o.key)||[],state:c?.state,endpoint:c?.route?.source_endpoint});}
    for(let i=0;i<jobs.length;i++)for(let j=i+1;j<jobs.length;j++){const a=jobs[i],b=jobs[j];if(a.selected&&b.selected){const m=jointPair(a.selected,b.selected);if(m.overlap_px>3||m.cost>=1e12)routePairs.push({indices:[a.index,b.index],...m});}}
   }else for(const index of request.routes||[]){lifetimeProbeState={labels:[],routes:[index]};draw(F);const snap=jointSnapshots.at(-1),job=snap?.jobs.find(j=>j.index===index),c=last.connections.find(c=>c.window?.index===index);routeResults.push({index,candidates:job?.options.map(o=>o.key)||[],state:c?.state,endpoint:c?.route?.source_endpoint});}
   // Compare an existing label only when its changed-band result can have
   // lost visibility. Complete clear boxes already have maximal visibility.
   // This is an actual same-clock baseline draw, not an inference from timers.
   const baselineNeed=(request.baseline_labels||[]).filter(index=>{
    const v=labelResults.find(v=>v.index===index);if(!v||v.natural_weight<=.03)return false;
    const b=v.bounds,z=v.source_bounds;
    return !b||b.x<390||b.r>2640||b.y<65||b.b>1810||!z||z.r<=390||z.x>=2640||z.b<=65||z.y>=1810||v.ink_conflict;
   });
   let baselineLabels=[];
   if(baselineNeed.length&&!request.baseline_only){
    const bands=(P.label_bands||[]).map(b=>b.to),windows=motifLabels.map(i=>i.displayWindow),savedState=lifetimeProbeState;
    try{
     for(const e of P.band_display_extensions||[])P.label_bands[e.index].to=e.original_to;
     for(const item of motifLabels)item.displayWindow=item.window;
     actor.drawScoreForLifetimeProbe(F);
     baselineLabels=lifetimeProbe(F,{labels:baselineNeed,routes:[],baseline_only:true}).labels;
    }finally{
     (P.label_bands||[]).forEach((b,i)=>b.to=bands[i]);motifLabels.forEach((item,i)=>item.displayWindow=windows[i]);
     lifetimeProbeState=savedState;actor.drawScoreForLifetimeProbe(F);draw(F);
    }
   }
   const wm=root.getCTM().inverse().multiply(actor.scoreClip.firstElementChild.getCTM());
   const geometry=request.certificate?{matrix:[wm.a,wm.b,wm.c,wm.d,wm.e,wm.f],mounted:S.geometry.measures.flatMap((m,i)=>{const n=nodes.get(m.svg_id);return n&&n.style.display!=='none'?[i]:[];}),locators:[...actor.scoreClip.querySelectorAll('.score-locators text')].flatMap((n,i)=>n.style.display!=='none'&&Number(n.getAttribute('opacity')||1)>=.03?[i]:[]),fixed_obstacles:[...actor.labels.children,tempo,actor.nav,actor.movementCorner,...root.querySelectorAll('[data-source-figure]')].filter(n=>n&&n.style.visibility!=='hidden'&&Number(n.style.opacity||1)>.02).map(n=>({id:n.id||n.getAttribute('data-source-figure')||n.textContent,bounds:box(n)})),all_labels:seen.map(v=>({index:v.label_index,theme:v.theme,bounds:v.bounds,opacity:v.opacity}))}:undefined;
   return{seconds:F.seconds,labels:labelResults,label_pairs:pairs,routes:routeResults,route_pairs:routePairs,geometry,baseline_checked_labels:baselineNeed,baseline_labels:baselineLabels};
  }finally{jointCollect=prior;lifetimeProbeState=null;jointSnapshots.length=ns;routeDiagnostics.failures.length=nf;routeDiagnostics.samples.length=nr;if(routeDiagnostics.label_failures)routeDiagnostics.label_failures.length=nl;routeCache.clear();}
 }
 return{draw,lifetimeProbe,routePlan:()=>jointPlanAudit,paperExitProbe,layoutPlan:()=>({bands:P.label_bands,labels:motifLabels.map(i=>({representative_id:i.representative_id,source_id:i.row.s.id,staff:i.row.s.staff,window:i.window,status:i.placement,size:i.size,width:i.width,top:i.top,bottom:i.bottom,lines:i.lines||[i.label.textContent],band:i.bandStaff?{staff:i.bandStaff,side:i.bandSide,slot:i.bandSlot}:null,anchor:i.anchor?{native_x:i.anchor.native_x,native_y:i.anchor.native_y,screen_dx:i.anchor.screen_dx||0,screen_dy:i.anchor.screen_dy||0}:null}))}),audit:()=>({...last,harmony:harmonyLayer.audit(),native_comparisons:nativeComparisons.audit()})};
}
