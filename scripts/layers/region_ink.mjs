// Source-owned musical intervals, resolved independently of rendering or time.
export function createMaterialIndex(data) {
  const shift=data.x_shift??240;
  const source=new Map(),neutral=new Map(),byStaff=new Map();
  for(const r of data.regions||[]){
    const a=r.start_x-shift,b=r.end_x-shift;
    if(!Number.isFinite(a)||!Number.isFinite(b)||!(b>a))throw Error('Invalid material extent');
    if(!source.has(r.staff))source.set(r.staff,[]);
    source.get(r.staff).push({a,b,theme:r.theme});
  }
  for(const r of data.shared_staff_neutral_intervals||[]){
    if(!Number.isFinite(r.start_x)||!Number.isFinite(r.end_x))throw Error('Neutral interval needs native x bounds');
    if(!neutral.has(r.staff))neutral.set(r.staff,[]);
    neutral.get(r.staff).push({a:r.start_x-shift,b:r.end_x-shift});
  }
  for(const[staff,rows]of source){
    const blockers=neutral.get(staff)||[];
    const ends=[...new Set([...rows,...blockers].flatMap(r=>[r.a,r.b]))].sort((a,b)=>a-b);
    const resolved=[];
    for(let i=0;i<ends.length-1;i++){
      const a=ends[i],b=ends[i+1],x=(a+b)/2;
      if(blockers.some(r=>r.a<=x&&x<r.b))continue;
      const themes=new Set(rows.filter(r=>r.a<=x&&x<r.b).map(r=>r.theme));
      if(themes.size!==1)continue;
      const theme=[...themes][0],last=resolved.at(-1);
      if(last&&last.theme===theme&&Math.abs(last.b-a)<1e-7)last.b=b;
      else resolved.push({a,b,theme});
    }
    if(resolved.length)byStaff.set(staff,resolved);
  }
  const at=(staff,x)=>(byStaff.get(staff)||[]).find(r=>r.a<=x&&x<r.b)?.theme??null;
  const span=(staff,a,b)=>{
    if(b<a)[a,b]=[b,a];
    return(byStaff.get(staff)||[]).find(r=>r.a<=a+1e-7&&b<=r.b+1e-7)?.theme??null;
  };
  return{byStaff,at,span};
}

// Colour the original staff ink; no panels, boxes or geometry edits.
export function installMaterialRegions(actor, scene, makeIndex) {
  const data=scene.material_regions;
  if(!data)return{draw(){},audit(){return{enabled:false}}};
  const NS='http://www.w3.org/2000/svg';
  const el=(name,attrs,parent)=>{const n=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.append(n);return n;};
  const world=actor.scoreClip.firstElementChild;
  const native=new Map([...world.querySelectorAll('[id]')].map(n=>[n.id.replace(/^scene\d+-/,''),n]));
  const notes=new Map(scene.geometry.notes.map(n=>[n.id,{...n,node:native.get(n.svg_id)}]).filter(([,n])=>n.node));
  const index=makeIndex(data),regionsByStaff=index.byStaff;
  const assignments=data.assignments||Object.fromEntries(data.regions.flatMap(r=>r.event_ids.map(id=>[id,r.theme])));
  const byEvent=new Map(Object.entries(assignments).map(([id,theme])=>[id,{theme}]));
  for(const theme of Object.values(assignments))if(!data.palette[theme])throw Error('Unknown material palette identity: '+theme);
  const colorAt=(staff,x)=>data.palette[index.at(staff,x)]||'#000000';
  const spanColor=(staff,a,z)=>data.palette[index.span(staff,a,z)]||'#000000';
  const intersects=(staff,a,z)=>(regionsByStaff.get(staff)||[]).some(r=>r.a<z&&a<r.b);
  const paint=(n,color)=>{n.style.color=color;if(n.getAttribute('fill')!=='none')n.style.fill=color;};
  const mix=(base,active,weight)=>{const w=Math.max(0,Math.min(1,weight));return'rgb('+[1,3,5].map(i=>Math.round(parseInt(base.slice(i,i+2),16)*(1-w)+parseInt(active.slice(i,i+2),16)*w)).join(',')+')';};
  const xBox=n=>{const b=n.getBBox(),m=world.getCTM().inverse().multiply(n.getCTM());return[b.x*m.a+m.e,(b.x+b.width)*m.a+m.e];};
  const defs=el('defs',{},actor.root),gradients=new Map();
  const uid='region-'+actor.root.querySelector('.movement-corner')?.textContent+'-'+document.querySelectorAll('[data-material-region-defs]').length;
  defs.setAttribute('data-material-region-defs','true');
  for(const[staff,rows]of regionsByStaff){
    const left=rows[0].a-1,right=Math.max(...rows.map(r=>r.b))+1;
    const id=uid+'-'+staff.replace(':','-'),g=el('linearGradient',{id,gradientUnits:'userSpaceOnUse',x1:left,x2:right,y1:0,y2:0},defs);
    const stops=[[left,'#000000']];
    for(const r of rows){const a=r.a,z=r.b,c=data.palette[r.theme];stops.push([a,'#000000'],[Math.min(a+35,z),c],[Math.max(a,z-35),c],[z,'#000000']);}
    stops.push([right,'#000000']);stops.sort((a,b)=>a[0]-b[0]);
    for(const[x,c]of stops)el('stop',{offset:(x-left)/(right-left),'stop-color':c},g);
    gradients.set(staff,'url(#'+id+')');
  }
  const inkStats={staff_line_paths:0,ledger_line_paths:0,groups:0,controls:0,preserved_none:0};
  const baseByNode=new Map();
  const remember=(n,c)=>{paint(n,c);baseByNode.set(n,c);};
  for(const staff of scene.geometry.staves){
    if(!regionsByStaff.has(staff.id))continue;
    const gradient=gradients.get(staff.id);
    for(const id of staff.svg_ids){
      const group=native.get(id);if(!group)continue;
      // Native five-line paths retain d, stroke-width and transform exactly.
      for(const line of [...group.children].filter(n=>n.localName==='path')){
        if(!/^M[-\d.]+ [-\d.]+ L[-\d.]+ [-\d.]+$/.test(line.getAttribute('d')||''))continue;
        if(!intersects(staff.id,...xBox(line)))continue;
        line.style.stroke=gradient;inkStats.staff_line_paths++;
      }
      for(const g of group.querySelectorAll('g.rest,g.mRest,g.multiRest,g.chord,g.beam,g.tuplet,g.clef,g.keySig,g.meterSig,g.ledgerLines')){
        const[a,z]=xBox(g);if(!intersects(staff.id,a,z))continue;
        const color=spanColor(staff.id,a,z);if(color!=='#000000')remember(g,color);inkStats.groups++;
        if(g.classList.contains('beam'))for(const n of g.children){if(n.localName==='polygon'){n.style.fill=gradient;n.style.stroke=gradient;}}
        if(g.classList.contains('ledgerLines'))for(const n of g.querySelectorAll('path')){if(intersects(staff.id,...xBox(n))){n.style.stroke=gradient;inkStats.ledger_line_paths++;}}
      }
    }
  }
  // A normal scene or a pruned viewport may legitimately contain no mapped staves.
  // A note is indivisible: accidental, head, stem, dot and printed syllable share its material.
  for(const[id,g]of notes){
    const r=byEvent.get(id);
    if(r){remember(g.node,data.palette[r.theme]);continue;}
    // Neutral notes inside an owned beam/chord must not inherit its material.
    // Everywhere else, leave the ordinary native ink completely untouched.
    for(let n=g.node.parentNode;n&&n!==world;n=n.parentNode){
      if(baseByNode.has(n)){remember(g.node,'#000000');break;}
    }
  }
  // Single-owner directions outside staff groups need their own colour inheritance.
  for(const c of scene.geometry.controls||[]){
    if(c.staves.length!==1||!regionsByStaff.has(c.staves[0]))continue;
    const n=native.get(c.svg_id);if(!n||n.closest('g.staff'))continue;
    const[a,z]=xBox(n);
    // The WHOLE indication must belong to one continuous material span.
    const color=spanColor(c.staves[0],a,z);if(color==='#000000')continue;remember(n,color);inkStats.controls++;
    inkStats.preserved_none+=n.querySelectorAll('[fill="none"]').length;
  }
  const nodeIds=new Map([...notes].map(([id,n])=>[n.node,id]));
  const shared=[];
  for(const g of world.querySelectorAll('g.chord')){
    const members=[...g.querySelectorAll('g.note')].map(n=>nodeIds.get(n)).filter(Boolean);
    if(!members.some(id=>baseByNode.has(notes.get(id).node)))continue;
    const pieces=[...g.children].filter(n=>['stem','flag','dots'].some(c=>n.classList.contains(c)));
    if(!pieces.length)continue;
    const colors=new Set(members.map(id=>baseByNode.get(notes.get(id).node)||'#000000'));
    shared.push({members,pieces,base:colors.size===1?[...colors][0]:'#000000'});
  }

  // Restore the production vocal UI verbatim; only add a small thematic text beside each role.
  const phraseThemes=new Map((data.vocal_phrase_themes||[]).filter(p=>!p.theme_conflict).map(p=>[p.phrase_id,p.theme]));
  const timeline=scene.vocalProgramme?.timeline;
  const timelines=new Map((timeline?.lanes||[]).map(l=>[l.id,l]));
  const phrases=new Map((timeline?.lanes||[]).flatMap(l=>l.phrases.map(p=>[p.id,p])));
  const episodes=new Map();
  for(const[staff,lane]of timelines){
    const rows=[];
    lane.phrases.forEach((p,i)=>{const theme=phraseThemes.get(p.id);if(!theme)return;const last=rows.at(-1);
      if(last&&last.theme===theme&&last.last_index===i-1&&p.continuity_from_previous&&p.start-last.end<=1.2&&p.start_q-last.end_q<=3){last.end=p.end;last.end_q=p.end_q;last.last_index=i;}
      else rows.push({theme,start:p.start,end:p.end,end_q:p.end_q,last_index:i});});
    episodes.set(staff,rows);
  }
  const badges=[...actor.root.querySelectorAll('[data-voice-label]')].map(role=>{
    const cohort=role.closest('[data-vocal-cohort]')?.getAttribute('data-vocal-cohort');
    const node=el('text',{'font-family':'Han','font-size':28,'font-weight':400,opacity:0,'data-material-badge':role.getAttribute('data-voice-label')},role.parentNode);
    return{role,node,cohort,staff:role.getAttribute('data-voice-label')};
  });
  const smooth=v=>{const t=Math.max(0,Math.min(1,v));return t*t*(3-2*t);};
  let previous=new Set(),last={};
  function draw(F){
    const colors=actor.programme?.colorForStaff(F.seconds)||{};
    const highlights=Object.fromEntries(Object.entries(F.highlights).map(([id,h])=>[id,scene.vocal_note_staves?.[id]?{...h,color:colors[scene.vocal_note_staves[id]]||h.color}:h]));
    const now=new Set(Object.keys(highlights));
    for(const id of new Set([...previous,...now])){const n=notes.get(id);if(!n||!baseByNode.has(n.node))continue;const base=baseByNode.get(n.node),h=highlights[id];paint(n.node,h?mix(base,h.color,h.weight):base);}
    for(const group of shared){const h=group.members.map(id=>highlights[id]).filter(Boolean).sort((a,b)=>b.weight-a.weight)[0];for(const n of group.pieces)paint(n,h?mix(group.base,h.color,h.weight):group.base);}
    previous=now;
    const programme=actor.programme?.audit(),shown=[];
    for(const badge of badges){
      const lane=programme?.lanes.find(l=>l.cohort_id===badge.cohort&&l.id===badge.staff);
      const episode=lane&&(episodes.get(badge.staff)||[]).find(e=>e.start<=F.seconds&&F.seconds<e.end);
      let theme=episode?.theme,opacity=0;
      if(theme){
        for(const member of lane.members||[badge.staff]){
          const match=(episodes.get(member)||[]).find(e=>e.start<=F.seconds&&F.seconds<e.end);
          if(!match||match.theme!==theme){theme=null;break;}
        }
        if(theme)opacity=smooth((F.seconds-episode.start)/.12)*(1-smooth((F.seconds-(episode.end-.12))/.12))*Number(badge.role.getAttribute('opacity')||1);
      }
      badge.node.setAttribute('opacity',opacity);
      if(theme){
        const b=badge.role.getBBox();badge.node.textContent=data.short_names[theme];
        badge.node.setAttribute('fill',data.palette[theme]);badge.node.setAttribute('x',b.x+b.width+24);
        badge.node.setAttribute('y',badge.role.getAttribute('y'));
        const box=badge.node.getBBox();if(box.x+box.width>3830)throw Error('Theme badge overflows fixed margin');
        if(opacity>0)shown.push({staff:badge.staff,theme,label:badge.node.textContent,opacity,role_color:badge.role.getAttribute('fill'),x:box.x,right:box.x+box.width});
      }
    }
    last={seconds:F.seconds,staff_ink:inkStats,badges:shown,
      active: [...now].filter(id=>byEvent.has(id)).slice(0,12).map(id=>({id,theme:byEvent.get(id).theme,color:notes.get(id)?.node.style.color,production_active_color:highlights[id].color,weight:highlights[id].weight,base:data.palette[byEvent.get(id).theme]}))};
  }
  return{draw,audit:()=>last};
}
