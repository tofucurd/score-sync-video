// Deterministic compact bands and shared corridors, in absolute recording time.
export function packCompactLabelRows(rows,t){
 const envelope=(from,to)=>{let u=Math.max(0,Math.min(1,(t-from+4)/4,(to+4-t)/4));return u*u*u*(10+u*(-15+6*u));};
 const shaped=rows.map((b,index)=>{
  if(!b.compact_rows)return{...b,index,effective_height:b.height*b.alpha,offset:(b.padding_before||0)*b.alpha,slot_offsets:null,slot_alpha:b.alpha};
  const outer=envelope(b.from,b.to),guest=Math.min(outer,Math.max(0,...(b.compact_guests||[]).map(w=>envelope(w.from,w.to))));
  const measure=source=>{let cursor=0,maxAlpha=0;const offsets=source.map(row=>{const own=Math.max(guest,...row.windows.map(w=>envelope(w.from,w.to)));const alpha=b.alpha*Math.min(1,own/Math.max(outer,1e-9)),height=row.height+Math.max(0,b.legacy_row_height-row.height)*guest/Math.max(outer,1e-9);maxAlpha=Math.max(maxAlpha,alpha);const mid=cursor+height*alpha/2;cursor+=height*alpha;return mid;});return{cursor,maxAlpha,offsets};};
  const packed=measure(b.compact_rows),reserved=b.compact_reserved_rows?measure(b.compact_reserved_rows):packed;
  return{...b,index,effective_height:Math.max(packed.cursor,reserved.cursor)+((b.padding_before||0)+(b.padding_after||0))*reserved.maxAlpha,offset:(b.padding_before||0)*reserved.maxAlpha,slot_offsets:packed.offsets,slot_alpha:packed.maxAlpha};
 });
 return shaped.filter(b=>b.compact_host===undefined||b.effective_height<=0||shaped[b.compact_host].effective_height<=0).map(b=>{
  const candidate=b.compact_peer===undefined?null:shaped[b.compact_peer],peer=b.effective_height>0&&candidate?.effective_height>0?candidate:null,height=peer?Math.max(b.effective_height,peer.effective_height):b.effective_height;
  return{...b,effective_height:height,aliases:[{band:b,offset:b.offset},...(peer?[{band:peer,offset:height-peer.effective_height+peer.offset}]:[])]};
 });
}
