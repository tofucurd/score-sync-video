// Native glyph outlines beside fixed labels; no change to score geometry.
export function installStaffSignatures(actor, scene) {
 const data=scene.staff_signatures;
 if(!data)return {draw(){},audit(){return {enabled:false}}};
 const NS='http://www.w3.org/2000/svg',options={clef:true,key:true,transposition:true,...data.options};
 const el=(tag,attrs,parent)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.append(n);return n;};
 const labels=new Map([...actor.labels.querySelectorAll('text')].map(n=>[n.getAttribute('data-staff'),n]));
 const rows=Object.entries(data.staves).map(([id,st])=>{
  const label=labels.get(id);if(!label)throw Error('Signature staff has no native label: '+id);
  label.setAttribute('x',245);label.setAttribute('font-size',25);
  return {id,label,name:label.textContent,events:st.events,index:-2,node:el('g',{'data-signature-staff':id},actor.labels)};
 });
 const glyph=(parent,code,x,y,size)=>{
  if(!data.glyphs[code]?.length)throw Error('Missing native signature glyph: '+code);
  const g=el('g',{transform:`translate(${x} ${y}) scale(${size})`},parent);
  for(const attrs of data.glyphs[code])el('path',{...attrs,fill:'#59645F',stroke:'none'},g);
 };
 let last=[];
 function draw(F){
  last=[];
  for(const row of rows){
   const es=row.events;let lo=0,hi=es.length;
   while(lo<hi){const m=(lo+hi)>>1;if(es[m].q<=F.q+1e-8)lo=m+1;else hi=m;}
   const idx=lo-1,s=es[idx],node=row.node;
   node.setAttribute('transform',`translate(0 ${Number(row.label.getAttribute('y'))-10})`);
   node.style.opacity=row.label.style.opacity;
   if(idx!==row.index){
    row.index=idx;node.replaceChildren();
    row.label.textContent=row.name+(s&&options.transposition&&s.pitch_label?`（${s.pitch_label}）`:'');
    row.label.setAttribute('font-size',25);const width=row.label.getComputedTextLength();if(width>205)row.label.setAttribute('font-size',25*205/width);
    if(s){
     const pitched=['G','F','C'].includes(s.sign),code={G:'E050',F:'E062',C:'E05C',percussion:'E069'}[s.sign];
     if(options.clef){
      if(pitched)for(let k=-2;k<=2;k++)el('line',{x1:260,x2:312,y1:k*5,y2:k*5,stroke:'#A6AAA2','stroke-width':.8},node);
      if(code)glyph(node,code,266,pitched?10-(s.line-1)*5:0,.020);
      if(s.octave)el('text',{x:273,y:s.octave<0?27:-20,'font-size':11,'text-anchor':'middle'},node).textContent=Math.abs(s.octave)===1?'8':'15';
     }
     if(options.key&&pitched&&s.fifths){el('text',{x:326,y:7,'font-size':19},node).textContent=Math.abs(s.fifths);glyph(node,s.fifths>0?'E262':'E260',343,4,.025);}
    }
   }
   last.push({staff:row.id,q:F.q,state:s||null,label:row.label.textContent});
  }
 }
 return {draw,audit:()=>({enabled:true,layout_mutations:false,staves:last})};
}
