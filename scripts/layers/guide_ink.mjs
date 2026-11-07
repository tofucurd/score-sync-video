// Source-owned musical intervals, resolved independently of rendering or time.
export function createMaterialIndex(data = {}) {
  const shift=data.x_shift??0;
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

// Native paint servers use the target element's local user space, while
// material extents are in world space. Keep these distinct.
// Colour the original staff ink; no panels, boxes or geometry edits.
export function installMaterialRegions(actor, scene, makeIndex) {
  const data=scene.material_regions;
  if(!data)return{draw(){},audit(){return{enabled:false}}};
  if(typeof makeIndex!=='function')throw Error('Material renderer requires createMaterialIndex');
  if(!data.palette||typeof data.palette!=='object')throw Error('Material regions require a palette');
  if(!actor?.root||!actor.scoreClip?.firstElementChild||!scene.geometry)throw Error('Material renderer requires native actor and geometry');
  const NS='http://www.w3.org/2000/svg';
  const el=(name,attrs,parent)=>{const n=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.append(n);return n;};
  const world=actor.scoreClip.firstElementChild;
  const native=new Map([...world.querySelectorAll('[id]')].map(n=>[n.id.replace(/^scene\d+-/,''),n]));
  const notes=new Map(scene.geometry.notes.map(n=>[n.id,{...n,node:native.get(n.svg_id)}]).filter(([,n])=>n.node));
  const index=makeIndex(data),regionsByStaff=index.byStaff;
  for(const rows of regionsByStaff.values())for(const r of rows)if(!data.palette[r.theme])throw Error('Unknown material palette identity: '+r.theme);
  const assignments=data.assignments||Object.fromEntries((data.regions||[]).flatMap(r=>(r.event_ids||[]).map(id=>[id,r.theme])));
  const byEvent=new Map(Object.entries(assignments).map(([id,theme])=>[id,{theme}]));
  for(const theme of Object.values(assignments))if(!data.palette[theme])throw Error('Unknown material palette identity: '+theme);
  const colorAt=(staff,x)=>data.palette[index.at(staff,x)]||'#000000';
  const spanColor=(staff,a,z)=>data.palette[index.span(staff,a,z)]||'#000000';
  const intersects=(staff,a,z)=>(regionsByStaff.get(staff)||[]).some(r=>r.a<z&&a<r.b);
  const paint=(n,color)=>{n.style.color=color;if(n.getAttribute('fill')!=='none')n.style.fill=color;};
  const mix=(base,active,weight)=>{const w=Math.max(0,Math.min(1,weight));return'rgb('+[1,3,5].map(i=>Math.round(parseInt(base.slice(i,i+2),16)*(1-w)+parseInt(active.slice(i,i+2),16)*w)).join(',')+')';};
  const xBox=n=>{const b=n.getBBox(),m=world.getCTM().inverse().multiply(n.getCTM());return[b.x*m.a+m.e,(b.x+b.width)*m.a+m.e];};
  // A time-axis endpoint minus a fixed inset may cut through the last glyph:
  // Widen only to complete owned glyphs, bounded by the next different owner's
  // actual ink. Source neutral intervals remain hard barriers.
  const footprintAudit=[];
  const glyphsByStaff=new Map();
  for(const [staff,rows] of regionsByStaff){
    const lo=rows[0].a-1200,hi=rows.at(-1).b+1200;
    const glyphs=[...notes.values()].filter(n=>n.staff===staff&&n.x>=lo&&n.x<=hi)
      .map(n=>{const head=xBox(n.node.querySelector('g.notehead')||n.node),ink=xBox(n.node);
        return{id:n.id,head:head[0],a:ink[0],b:ink[1],theme:byEvent.get(n.id)?.theme||null};});
    glyphsByStaff.set(staff,glyphs);
    const originals=rows.map(r=>({...r}));
    const neutral=(data.shared_staff_neutral_intervals||[]).filter(r=>r.staff===staff)
      .map(r=>({a:r.start_x-(data.x_shift??0),b:r.end_x-(data.x_shift??0)}));
    const owned=originals.map(r=>glyphs.filter(g=>g.theme===r.theme&&g.head>=r.a&&g.head<r.b));
    for(let i=0;i<rows.length;i++){
      const r=rows[i],o=originals[i],gs=owned[i];if(!gs.length)continue;
      const pad=12;
      let a=Math.min(o.a,...gs.map(g=>g.a-pad)),b=Math.max(o.b,...gs.map(g=>g.b+pad));
      const prior=glyphs.filter(g=>g.head<o.a&&g.theme!==o.theme);
      const next=glyphs.filter(g=>g.head>=o.b&&g.theme!==o.theme);
      if(prior.length)a=Math.min(o.a,Math.max(a,Math.max(...prior.map(g=>g.b))+pad));
      if(next.length)b=Math.max(o.b,Math.min(b,Math.min(...next.map(g=>g.a))-pad));
      for(const n of neutral){if(n.b<=o.a)a=Math.max(a,n.b);if(n.a>=o.b)b=Math.min(b,n.a);}
      // Adjacent material rows share one ownership boundary; settle it below.
      if(i&&originals[i-1].b===o.a)a=o.a;
      if(originals[i+1]?.a===o.b)b=o.b;
      r.a=a;r.b=b;
    }
    for(let i=1;i<rows.length;i++){
      const adjacent=originals[i-1].b===originals[i].a,overlap=rows[i-1].b>rows[i].a;
      if((!adjacent&&!overlap)||!owned[i-1].length||!owned[i].length)continue;
      const leftInk=Math.max(...owned[i-1].map(g=>g.b)),rightInk=Math.min(...owned[i].map(g=>g.a));
      if(leftInk<=rightInk){
        const pad=Math.min(12,(rightInk-leftInk)/3),left=leftInk+pad,right=rightInk-pad;
        const at=Math.max(left,Math.min(right,adjacent?originals[i].a:(left+right)/2));
        rows[i-1].b=at;rows[i].a=at;
      }else if(overlap){rows[i-1].b=originals[i-1].b;rows[i].a=originals[i].a;}
    }
    rows.forEach((r,i)=>{if(r.a!==originals[i].a||r.b!==originals[i].b)
      footprintAudit.push({staff,theme:r.theme,source:[originals[i].a,originals[i].b],paint:[r.a,r.b],
        owned_events:owned[i].map(g=>g.id)});});
  }
  const defs=el('defs',{},actor.root),gradients=new Map(),paintServers=new Map();
  const coordinateAudit=[];
  const rgb=data.palette;
  const uid='region-'+actor.root.querySelector('.movement-corner')?.textContent+'-'+document.querySelectorAll('[data-material-region-defs]').length;
  defs.setAttribute('data-material-region-defs','true');
  for(const[staff,rows]of regionsByStaff){
    const left=rows[0].a-1,right=Math.max(...rows.map(r=>r.b))+1;
    const id=uid+'-'+staff.replace(':','-'),g=el('linearGradient',{id,gradientUnits:'userSpaceOnUse',x1:left,x2:right,y1:0,y2:0},defs);
    const stops=[[left,'#000000']];
    for(let i=0;i<rows.length;i++){
      const r=rows[i],a=r.a,z=r.b,c=data.palette[r.theme];
      // Hard ownership changes: no manufactured fade-to-black inside a material.
      stops.push([a,i&&rows[i-1].b===a?data.palette[rows[i-1].theme]:'#000000'],[a,c],[z,c]);
      if(!rows[i+1]||rows[i+1].a!==z)stops.push([z,'#000000']);
    }
    stops.push([right,'#000000']);stops.sort((a,b)=>a[0]-b[0]);
    for(const[x,c]of stops)el('stop',{offset:(x-left)/(right-left),'stop-color':c},g);
    gradients.set(staff,g);
  }
  // Derive a paint-server transform from each real target's CTM. In this native
  // engraving targets may have a local translation; using world x directly
  // in their local paint server would shift their visible material colors.
  // Staff animation changes y only, so the horizontal transform is stable.
  function serverFor(template,node){
    const m=world.getCTM().inverse().multiply(node.getCTM());
    if(Math.abs(m.b)>1e-8||Math.abs(m.c)>1e-8)throw Error('Unexpected rotated material target');
    const key=template.id+'|'+m.a+'|'+m.e;
    if(!paintServers.has(key)){
      const g=template.cloneNode(true);g.id=template.id+'-local-'+paintServers.size;
      g.setAttribute('gradientTransform',`matrix(${1/m.a} 0 0 1 ${-m.e/m.a} 0)`);
      defs.append(g);paintServers.set(key,'url(#'+g.id+')');
      coordinateAudit.push({gradient:g.id,target:node.id||node.parentNode?.id,
        local_to_world_x:{scale:m.a,translation:m.e},world_to_local_x:{scale:1/m.a,translation:-m.e/m.a}});
    }
    return paintServers.get(key);
  }
  const inkStats={staff_line_paths:0,ledger_line_paths:0,groups:0,controls:0,preserved_none:0,
    homogeneous_beams:0,mixed_beams:0,beam_polygons:0,black_boundary_fades:0};
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
        line.style.stroke=serverFor(gradient,line);inkStats.staff_line_paths++;
      }
      for(const g of group.querySelectorAll('g.rest,g.mRest,g.multiRest,g.chord,g.beam,g.tuplet,g.clef,g.keySig,g.meterSig,g.ledgerLines')){
        const[a,z]=xBox(g);if(!intersects(staff.id,a,z))continue;
        const color=spanColor(staff.id,a,z);if(color!=='#000000')remember(g,color);inkStats.groups++;
        if(g.classList.contains('ledgerLines'))for(const n of g.querySelectorAll('path')){if(intersects(staff.id,...xBox(n))){n.style.stroke=serverFor(gradient,n);inkStats.ledger_line_paths++;}}
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
  // Beam polygons are shared musical ink, not children of individual note owners.
  // A homogeneous beam is fully solid, including its left edge and secondary beams.
  // Mixed beams split only between actual member stem attachment columns. Never
  // paint the enclosing beam group to solve a polygon defect: that leaks into notes.
  const eventForNode=new Map([...notes].map(([id,n])=>[n.node,id]));
  const beamAudit=[];
  for(const beam of world.querySelectorAll('g.beam')){
    const members=[...beam.querySelectorAll('g.note')].filter(n=>n.closest('g.beam')===beam)
      .map(node=>({node,id:eventForNode.get(node)})).filter(v=>v.id);
    if(!members.some(v=>byEvent.has(v.id)))continue;
    const polygons=[...beam.children].filter(n=>n.localName==='polygon');if(!polygons.length)continue;
    const owners=members.map(v=>{
      const stem=v.node.querySelector('g.stem path'),head=v.node.querySelector('g.notehead')||v.node;
      const box=xBox(stem||head);return{...v,x:(box[0]+box[1])/2,theme:byEvent.get(v.id)?.theme||null};
    }).sort((a,b)=>a.x-b.x);
    const identities=new Set(owners.map(v=>v.theme));
    let template=null,solid=null;
    if(identities.size===1){solid=rgb[owners[0].theme]||'#000000';inkStats.homogeneous_beams++;}
    else{
      inkStats.mixed_beams++;
      const [left,right]=xBox(beam),id=uid+'-beam-'+beamAudit.length;
      template=el('linearGradient',{id,gradientUnits:'userSpaceOnUse',x1:left,x2:right,y1:0,y2:0},defs);
      const stops=[[left,rgb[owners[0].theme]||'#000000']];
      for(let i=1;i<owners.length;i++)if(owners[i].theme!==owners[i-1].theme){
        const at=(owners[i-1].x+owners[i].x)/2;
        stops.push([at,rgb[owners[i-1].theme]||'#000000'],[at,rgb[owners[i].theme]||'#000000']);
      }
      stops.push([right,rgb[owners.at(-1).theme]||'#000000']);
      for(const[x,c]of stops)el('stop',{offset:(x-left)/Math.max(1,right-left),'stop-color':c},template);
    }
    for(const polygon of polygons){
      const c=solid||serverFor(template,polygon);polygon.style.fill=c;polygon.style.stroke=c;
      if(solid)polygon.style.color=solid;inkStats.beam_polygons++;
    }
    beamAudit.push({id:beam.id,members:owners.map(v=>({id:v.id,theme:v.theme,x:v.x})),
      mode:solid?'homogeneous-solid':'member-boundary-split',color:solid,polygons:polygons.length});
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

  // Optional vocal themes use the current programme and explicit phrase identities.
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
    const highlights=Object.fromEntries(Object.entries(F.highlights||{}).map(([id,h])=>[id,scene.vocal_note_staves?.[id]?{...h,color:colors[scene.vocal_note_staves[id]]||h.color}:h]));
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
        const b=badge.role.getBBox();badge.node.textContent=data.short_names?.[theme]||theme;
        badge.node.setAttribute('fill',data.palette[theme]);badge.node.setAttribute('x',b.x+b.width+24);
        badge.node.setAttribute('y',badge.role.getAttribute('y'));
        const box=badge.node.getBBox();if(box.x+box.width>3830)throw Error('Theme badge overflows fixed margin');
        if(opacity>0)shown.push({staff:badge.staff,theme,label:badge.node.textContent,opacity,role_color:badge.role.getAttribute('fill'),x:box.x,right:box.x+box.width});
      }
    }
    last={seconds:F.seconds,staff_ink:inkStats,guide_ink_revision:'local-paint-space-hard-boundaries-v1',paint_servers:coordinateAudit,glyph_extent_repairs:footprintAudit,beam_ownership:beamAudit,badges:shown,
      active: [...now].filter(id=>byEvent.has(id)).slice(0,12).map(id=>({id,theme:byEvent.get(id).theme,color:notes.get(id)?.node.style.color,production_active_color:highlights[id].color,weight:highlights[id].weight,base:data.palette[byEvent.get(id).theme]}))};
  }
  return{draw,audit:()=>last};
}
