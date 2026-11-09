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
  const cover=(staff,a,b)=>{
    if(b<a)[a,b]=[b,a];
    const pieces=[];let cursor=a;
    for(const r of byStaff.get(staff)||[]){
      if(r.b<=cursor||r.a>=b)continue;
      if(r.a>cursor+1e-7)return null;
      const z=Math.min(b,r.b);pieces.push({a:cursor,b:z,theme:r.theme});cursor=z;
      if(cursor>=b-1e-7)return pieces;
    }
    return null; // Never bridge a neutral or conflicting interval.
  };
  return{byStaff,at,span,cover};
}

// Colour the original staff ink; no panels, boxes or geometry edits.
export function installMaterialRegions(actor, scene, makeIndex) {
  const data=scene.material_regions;
  if(!data)return{draw(){},audit(){return{enabled:false}}};
  const NS='http://www.w3.org/2000/svg';
  const el=(name,attrs,parent)=>{const n=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.append(n);return n;};
  const world=actor.scoreClip.firstElementChild;
  const native=new Map([...world.querySelectorAll('[id]')].map(n=>[n.id.replace(/^scene\d+-/,''),n]));
  // Engraving used a different font metric. Fit genuine expression frames to
  // the loaded italic ink, retaining their original padding and stroke weight.
  // Tiny rectangles in dashed extensions are not text frames.
  for(const g of world.querySelectorAll('g.dir')){
    const rect=g.querySelector(':scope > rect'),text=g.querySelector(':scope > text');
    if(!rect||!text||rect.getAttribute('fill-opacity')!=='0')continue;
    const r=rect.getBBox(),t=text.getBBox();
    if(r.height<100||r.width<100)continue;
    const padding=Math.max(20,t.x-r.x);
    if(t.x+t.width+padding>r.x+r.width)
      rect.setAttribute('width',t.x+t.width+padding-r.x);
  }
  const notes=new Map(scene.geometry.notes.map(n=>[n.id,{...n,node:native.get(n.svg_id)}]).filter(([,n])=>n.node));
  const index=makeIndex(data.display_regions?{...data,regions:data.display_regions}:data),regionsByStaff=index.byStaff;
  const sourceAssignments=data.assignments||Object.fromEntries(data.regions.flatMap(r=>r.event_ids.map(id=>[id,r.theme])));
  // A directly observed reference shade need not assert a new musical identity.
  const assignments={...sourceAssignments,...(data.display_assignments||{})};
  const byEvent=new Map(Object.entries(assignments).map(([id,theme])=>[id,{theme}]));
  for(const theme of Object.values(assignments))if(!data.palette[theme])throw Error('Unknown material palette identity: '+theme);
  const colorAt=(staff,x)=>data.palette[index.at(staff,x)]||'#000000';
  const spanColor=(staff,a,z)=>data.palette[index.span(staff,a,z)]||'#000000';
  const intersects=(staff,a,z)=>(regionsByStaff.get(staff)||[]).some(r=>r.a<z&&a<r.b);
  const paint=(n,color)=>{n.style.color=color;if(n.getAttribute('fill')!=='none')n.style.fill=color;};
  const mix=(base,active,weight)=>{const w=Math.max(0,Math.min(1,weight));return'rgb('+[1,3,5].map(i=>Math.round(parseInt(base.slice(i,i+2),16)*(1-w)+parseInt(active.slice(i,i+2),16)*w)).join(',')+')';};
  const xBox=n=>{const b=n.getBBox(),m=world.getCTM().inverse().multiply(n.getCTM());return[b.x*m.a+m.e,(b.x+b.width)*m.a+m.e];};
  const defs=el('defs',{},actor.root),gradients=new Map(),paintServers=new Map(),coordinateAudit=[];
  // Labels can contain spaces/punctuation; use a document-unique CSS-safe ID.
  const uid='region-'+document.querySelectorAll('[data-material-region-defs]').length;
  defs.setAttribute('data-material-region-defs','true');
  for(const[staff,rows]of regionsByStaff){
    const left=rows[0].a-1,right=Math.max(...rows.map(r=>r.b))+1;
    const id=uid+'-'+staff.replace(':','-'),g=el('linearGradient',{id,gradientUnits:'userSpaceOnUse',x1:left,x2:right,y1:0,y2:0},defs);
    const stops=[[left,'#000000']];
    for(let i=0;i<rows.length;i++){
      const r=rows[i],a=r.a,z=r.b,c=data.palette[r.theme];
      const joinedLeft=i>0&&Math.abs(rows[i-1].b-a)<1e-7,joinedRight=i+1<rows.length&&Math.abs(z-rows[i+1].a)<1e-7;
      // An owned colour-to-colour boundary has no neutral gap. Do not insert
      // a black dip into the staff or a shared beam at that boundary.
      if(joinedLeft)stops.push([a,c]);else stops.push([a,'#000000'],[Math.min(a+35,z),c]);
      if(joinedRight)stops.push([z,c]);else stops.push([Math.max(a,z-35),c],[z,'#000000']);
    }
    stops.push([right,'#000000']);stops.sort((a,b)=>a[0]-b[0]);
    for(const[x,c]of stops)el('stop',{offset:(x-left)/(right-left),'stop-color':c},g);
    gradients.set(staff,g);
  }
  // Region x belongs to world; SVG userSpaceOnUse belongs to each painted node.
  // Preserve the native geometry and convert only the paint-server coordinates.
  function serverFor(template,node){
    const m=world.getCTM().inverse().multiply(node.getCTM());
    if(Math.abs(m.b)>1e-8||Math.abs(m.c)>1e-8||Math.abs(m.a)<1e-8)throw Error('Unexpected material target transform');
    const key=template.id+'|'+m.a+'|'+m.e;
    if(!paintServers.has(key)){
      const g=template.cloneNode(true);g.id=template.id+'-local-'+paintServers.size;
      g.setAttribute('gradientTransform',`matrix(${1/m.a} 0 0 1 ${-m.e/m.a} 0)`);
      defs.append(g);
      const audit={gradient:g.id,first_target:node.id||node.parentNode?.id,
        local_to_world_x:{scale:m.a,translation:m.e},world_to_local_x:{scale:1/m.a,translation:-m.e/m.a},targets:0};
      coordinateAudit.push(audit);paintServers.set(key,{url:'url(#'+g.id+')',audit});
    }
    const server=paintServers.get(key);server.audit.targets++;return server.url;
  }
  const inkStats={staff_line_paths:0,ledger_line_paths:0,beam_polygons:0,homogeneous_beams:0,gradient_beams:0,rest_bridged_beams:0,groups:0,controls:0,family_spanners:0,preserved_none:0};
  const beamAudit=[];
  const familyOf=new Map(Object.entries(data.semantic_families||{}).flatMap(([id,f])=>(f.members||[]).map(t=>[t,id]))),spannerAudit=[];
  const reviewedSpanners=new Map((data.spanner_ink_overrides||[]).map(r=>[r.svg_id,r]));
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
      // Clefs, key and meter describe the staff, not the preceding material.
      // Phrase padding can reach those structural glyphs at a section boundary.
      for(const g of group.querySelectorAll('g.rest,g.mRest,g.multiRest,g.chord,g.beam,g.tuplet,g.ledgerLines')){
        const[a,z]=xBox(g);if(!intersects(staff.id,a,z))continue;
        const color=spanColor(staff.id,a,z);if(color!=='#000000')remember(g,color);inkStats.groups++;
        if(g.classList.contains('beam')){
          // A wholly owned beam includes the full engraved stem/beam footprint,
          // which can extend beyond the notehead-based interval padding.
          // A rest has no stem in this shared beam. Its neutral glyph must not
          // punch a black hole through the beam connecting owned pitched notes.
          // Any genuinely neutral pitched member still uses the original mask.
          const members=[...g.querySelectorAll('g.note')].map(n=>{
            const id=n.id.replace(/^scene\d+-/,'');return{id,theme:byEvent.get(id)?.theme,x:notes.get(id)?.x};
          }).sort((a,b)=>a.x-b.x);
          const themes=new Set(members.map(n=>n.theme));
          const owned=members.length&&members.every(n=>n.theme&&Number.isFinite(n.x))&&members.every((n,i)=>!i||n.x!==members[i-1].x||n.theme===members[i-1].theme);
          const theme=owned&&themes.size===1?[...themes][0]:null;
          let beamGradient=null;
          if(owned&&!theme){
            beamGradient=el('linearGradient',{id:uid+'-beam-'+beamAudit.length,gradientUnits:'userSpaceOnUse',x1:a,x2:z,y1:0,y2:0},defs);
            const rows=regionsByStaff.get(staff.id)||[],stops=[[a,data.palette[members[0].theme]]];
            for(let i=1;i<members.length;i++){
              const left=members[i-1],right=members[i];if(left.theme===right.theme)continue;
              const l=rows.find(r=>r.theme===left.theme&&r.a<=left.x&&left.x<r.b),r=rows.find(r=>r.theme===right.theme&&r.a<=right.x&&right.x<r.b);
              const boundary=Math.max(left.x,Math.min(right.x,l&&r?(l.b+r.a)/2:(left.x+right.x)/2));
              stops.push([boundary,data.palette[left.theme]],[boundary,data.palette[right.theme]]);
            }
            stops.push([z,data.palette[members.at(-1).theme]]);
            for(const[x,c]of stops)el('stop',{offset:(x-a)/(z-a),'stop-color':c},beamGradient);
          }
          if(owned){
            const neutralRests=[...g.querySelectorAll('g.rest,g.mRest')].map(n=>n.id.replace(/^scene\d+-/,'')).filter(id=>!byEvent.has(id));
            if(neutralRests.length)inkStats.rest_bridged_beams++;
            beamAudit.push({svg_id:g.id.replace(/^scene\d+-/,''),members:members.map(n=>n.id),neutral_rests_preserved:neutralRests,colors:[...themes]});
          }
          if(theme)inkStats.homogeneous_beams++;else inkStats.gradient_beams++;
          for(const n of g.children)if(n.localName==='polygon'){
            const ink=theme?data.palette[theme]:serverFor(beamGradient||gradient,n);
            n.style.fill=ink;n.style.stroke=ink;inkStats.beam_polygons++;
          }
        }
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
  // Single-owner directions outside staff groups need their own colour inheritance.
  for(const c of scene.geometry.controls||[]){
    if(c.staves.length!==1||!regionsByStaff.has(c.staves[0]))continue;
    const n=native.get(c.svg_id);if(!n||n.closest('g.staff'))continue;
    const[a,z]=xBox(n);
    // Text and directions remain indivisible. A source-bound slur/tie may
    // cross adjacent variants of one family without becoming wholly black.
    // A point direction belongs to its source note, not the rectangle occupied
    // by its lettering. Duration directions deliberately have no point binding.
    const point=data.point_control_anchors?.[c.svg_id];
    const pointThemes=point&&new Set(point.event_ids.map(id=>byEvent.get(id)?.theme));
    const pointTheme=pointThemes?.size===1?[...pointThemes][0]:null;
    const color=pointTheme?data.palette[pointTheme]:spanColor(c.staves[0],a,z);
    if(color==='#000000'){
      const anchors=data.spanner_anchors?.[c.svg_id];
      if(!['slur','tie'].includes(c.class)||!anchors)continue;
      const reviewed=reviewedSpanners.get(c.svg_id);
      if(reviewed){
        if(reviewed.policy!=='follow_material_intervals'||reviewed.class!==c.class||reviewed.staff!==c.staves[0]
            ||reviewed.start!==anchors.start||reviewed.end!==anchors.end)
          throw Error('Stale or invalid reviewed spanner binding: '+c.svg_id);
        // A single native arc may cross a thematic boundary. Follow the
        // reviewed staff intervals without assigning its neutral notes a theme.
        for(const path of n.querySelectorAll('path')){
          const ink=serverFor(gradients.get(c.staves[0]),path);
          if(path.getAttribute('fill')!=='none')path.style.fill=ink;
          if(path.getAttribute('stroke')!=='none')path.style.stroke=ink;
        }
        spannerAudit.push({svg_id:c.svg_id,policy:reviewed.policy,anchors,world_x:[a,z]});
        inkStats.controls++;continue;
      }
      const family=familyOf.get(byEvent.get(anchors.start)?.theme);
      if(!family||familyOf.get(byEvent.get(anchors.end)?.theme)!==family)continue;
      const pieces=index.cover(c.staves[0],a,z);
      if(!pieces||pieces.some(r=>familyOf.get(r.theme)!==family))continue;
      const gradient=el('linearGradient',{id:uid+'-spanner-'+spannerAudit.length,gradientUnits:'userSpaceOnUse',x1:a,x2:z,y1:0,y2:0},defs);
      // Shared boundaries switch directly between the two owned shades;
      // the staff-line gradient's black edge fades do not belong on this arc.
      for(const r of pieces)for(const x of [r.a,r.b])el('stop',{offset:(x-a)/(z-a),'stop-color':data.palette[r.theme]},gradient);
      for(const path of n.querySelectorAll('path')){
        const ink=serverFor(gradient,path);
        if(path.getAttribute('fill')!=='none')path.style.fill=ink;
        if(path.getAttribute('stroke')!=='none')path.style.stroke=ink;
      }
      spannerAudit.push({svg_id:c.svg_id,family,anchors,pieces});inkStats.family_spanners++;
    }else remember(n,color);
    inkStats.controls++;
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
    last={seconds:F.seconds,staff_ink:inkStats,material_coordinate_audit:coordinateAudit,family_spanners:spannerAudit,owned_beam_continuity:beamAudit.filter(b=>b.neutral_rests_preserved.length),badges:shown,
      active: [...now].filter(id=>byEvent.has(id)).slice(0,12).map(id=>({id,theme:sourceAssignments[id],display_theme:byEvent.get(id).theme,color:notes.get(id)?.node.style.color,production_active_color:highlights[id].color,weight:highlights[id].weight,base:data.palette[byEvent.get(id).theme]}))};
  }
  return{draw,audit:()=>last};
}
