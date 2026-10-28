/** Full-source programme controller. Serialized into the owned browser; no module globals. */
export function installProgramVocals(actor,payload,installVocalOverlay){
  const {timeline,schedule}=payload,plans=payload.layout||schedule.layout;
  if(!timeline?.lanes||!schedule?.panel_presence)throw Error('Missing canonical programme payload');
  const NS='http://www.w3.org/2000/svg',smooth=v=>{const x=Math.max(0,Math.min(1,v));return x*x*(3-2*x);},quint=v=>{const x=Math.max(0,Math.min(1,v));return x*x*x*(x*(x*6-15)+10);};
  // Identical in the overlay and the programme bridge; source clocks stay intact.
  function promotionDuration(p){return Math.min(.30,p.motion.rise_seconds);}
  function promotionProgress(p,t){return smooth((t-p.start)/promotionDuration(p));}
  function motionOffset(p,t,step,panelEntry=false){
    if(panelEntry)return 0;
    if(!p.continuity_from_previous)return 10*(1-smooth((t-p.start)/Math.min(.15,(p.end-p.start)*.35)));
    return step*(1-promotionProgress(p,t));
  }
  function bodyScale(p,t,panelEntry=false){
    if(panelEntry)return 1;
    const u=p.continuity_from_previous?promotionProgress(p,t):smooth((t-p.start)/p.motion.entrance_seconds);
    return 40/55+(1-40/55)*u;
  }
  function followingPreviewOffset(p,t,step,previous,previousHeight,previousOffset,previousPanelEntry=false){
    return step+previousOffset-(previous?previousHeight*(1-bodyScale(previous,t,previousPanelEntry)):0);
  }
  function phraseExitDuration(p,next,blockHeight,nextStep){
    const original=p.motion.exit_seconds;
    if(!next?.continuity_from_previous||!Number.isFinite(nextStep))return original;
    // Clear the old complete body before the incoming top reaches it (4px gap).
    // This starts at the old final sounding end, never before the final syllable.
    const limit=Math.max(0,Math.min(1,(nextStep-blockHeight-4)/nextStep));
    let lo=0,hi=1;for(let i=0;i<28;i++){const mid=(lo+hi)/2;if(smooth(mid)<limit)lo=mid;else hi=mid;}
    const crossing=Math.max(0,next.start-p.end)+promotionDuration(next)*lo;
    return Math.min(original,.10,Math.max(1e-6,crossing));
  }
  const el=(tag,a,parent)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(a||{}))n.setAttribute(k,v);parent?.append(n);return n;};
  const sourceLanes=new Map(timeline.lanes.map(l=>[l.id,l])),phrases=new Map(timeline.lanes.flatMap(l=>l.phrases.map(p=>[p.id,p])));
  const defs=el('defs',{},actor.root),uid='vocal-programme-'+Math.random().toString(36).slice(2),gradient=el('linearGradient',{id:uid,gradientUnits:'userSpaceOnUse',x1:2620,x2:2700,y1:0,y2:0},defs);
  el('stop',{offset:0,'stop-color':'#FAF8F1','stop-opacity':0},gradient);el('stop',{offset:1,'stop-color':'#FAF8F1','stop-opacity':1},gradient);
  const paper=el('g',{'data-layer':'vocal-panel-paper'},actor.root);el('rect',{x:2620,y:0,width:80,height:1834,fill:`url(#${uid})`},paper);el('rect',{x:2700,y:0,width:1040,height:1834,fill:'#FAF8F1'},paper);
  const allLabels=(schedule.cohorts||[]).flatMap(c=>c.phases.flatMap(p=>p.groups.map(g=>g.label)));
  function materialize(c){
    const groups=c.phases[0].groups;
    return {...timeline,clip:{start:c.display_start,end:c.display_end},panel_presence:schedule.panel_presence,panel_entries:schedule.panel_entries,
      programme_options:{shared_paper:true,shared_markers:true,all_labels:allLabels},
      lanes:groups.map(g=>{const l=sourceLanes.get(g.id),ids=new Set([...g.context_phrase_ids,...g.representative_phrase_ids]),context=new Set(g.context_phrase_ids);
        return {...l,id:g.id,members:g.members,label:g.label,color:g.color,runs:l.runs.filter(r=>g.run_ids.includes(r.id)),phrases:l.phrases.filter(p=>ids.has(p.id)).map(p=>({...p,context_only:context.has(p.id)}))};})};
  }
  const instances=(schedule.cohorts||[]).map(c=>{
    const node=el('g',{'data-vocal-cohort':c.id},actor.root),tl=materialize(c),plan=plans?.cohorts.find(x=>x.id===c.id);
    if(!plan)throw Error('Missing immutable full-source layout '+c.id);
    tl.programme_layout={...plan.phases[0],phrase_layout:plan.phrase_layout};
    const renderer=installVocalOverlay({...actor,root:node},tl);
    return {c,node,renderer,plan,tl};
  });
  const byCohort=new Map(instances.map(i=>[i.c.id,i]));
  function planAt(instance,phase,t){
    const plan=instance.plan.phases.find(p=>p.id===phase.id);if(!plan)throw Error('Missing phase layout '+phase.id);
    const out=Object.fromEntries(plan.slots.map(s=>[s.id,{...s}])),keys=plan.reserve_keyframes||[];
    if(keys.length){let low=0,hi=keys.length-1,frame=t*(plans.fps||60);while(low<hi){const mid=Math.ceil((low+hi)/2);if(keys[mid].frame<=frame)low=mid;else hi=mid-1;}
      const a=keys[low],b=keys[Math.min(keys.length-1,low+1)],u=b.frame===a.frame?0:Math.max(0,Math.min(1,(frame-a.frame)/(b.frame-a.frame)));
      plan.slots.forEach((s,j)=>{out[s.id].top=a.tops[j]+(b.tops[j]-a.tops[j])*u;out[s.id].height=a.heights[j]+(b.heights[j]-a.heights[j])*u;});
    }
    // Geometry-only stages: membership/timing remains the canonical schedule.
    const stages=plan.stable_role_stages||[];
    if(stages.length){
      let k=0;while(k+1<stages.length&&stages[k+1].start<=t)k++;
      const stage=stages[k],previous=k?stages[k-1]:stage;
      const u=k?smooth((t-stage.start)/(stage.transition_seconds||.30)):1;
      const old=new Map(previous.slots.map(s=>[s.id,s]));
      for(const s of stage.slots){const a=old.get(s.id)||s;out[s.id]={...s,top:a.top+(s.top-a.top)*u,height:a.height+(s.height-a.height)*u};}
    }
    return out;
  }
  function phaseAt(c,t){return c.phases.find(p=>p.start<=t&&t<p.end)|| (t<c.phases[0].start?c.phases[0]:c.phases.at(-1));}
  function groupStates(instance,t){
    const c=instance.c,phase=phaseAt(c,t),slots=planAt(instance,phase,t),transition=c.merge_transitions.find(v=>v.start<=t&&t<v.end),result={};
    for(const initial of c.phases[0].groups){
      const group=phase.groups.find(g=>initial.members.every(m=>g.members.includes(m))),rep=group?.id===initial.id;
      result[initial.id]={top:slots[group?.id]?.top??instance.plan.phases[0].slots.find(s=>s.id===initial.id).top,height:slots[group?.id]?.height,opacity:rep?1:0,label:group?.label||initial.label,color:group?.color||initial.color,effective_group:group};
    }
    if(transition){
      const next=c.phases.find(p=>Math.abs(p.start-transition.end)<1e-7),nextSlots=planAt(instance,next,transition.end),move=smooth((t-transition.start-.15)/Math.max(.01,transition.end-transition.start-.15));
      for(const group of phase.groups){
        const target=next.groups.find(g=>group.members.every(m=>g.members.includes(m))),state=result[group.id];
        if(target.id!==group.id){state.opacity*=1-smooth((t-transition.start)/.15);continue;}
        state.top=slots[group.id].top+(nextSlots[target.id].top-slots[group.id].top)*move;
        if(target.label!==group.label){const first=t<transition.start+.15;state.label=first?group.label:target.label;state.effective_group=first?group:target;state.color=first?group.color:target.color;state.role_opacity=first?1-smooth((t-transition.start)/.15):smooth((t-transition.start-.15)/.15);}
      }
    }
    return {phase,result,transition};
  }
  // Bridge geometry is derived once from complete canonical cohorts. It is never
  // recomputed from the output frame list or shortened by a render chunk.
  const bridges=[];
  for(const handoff of schedule.handoffs||[]){
    const a=byCohort.get(handoff.from_cohort),b=byCohort.get(handoff.to_cohort);if(!a||!b)continue;
    const at=handoff.boundary,oldState=groupStates(a,at-1e-6),newState=groupStates(b,at+1e-6);
    a.renderer.draw({seconds:at-1e-6,vocal_group_state:oldState.result});
    const old=a.renderer.audit(),blocked=[];
    for(const l of old.lanes){if(l.group_opacity<=0)continue;const active=l.visible_phrases.filter(p=>p.source_interval[1]>=at-1e-5);if(!active.length&&l.role_opacity<=0)continue;blocked.push([l.slot_top-8,Math.max(l.slot_top+old.layout.role_size+8,...active.map(p=>p.body_bottom+12))]);}
    const incoming=new Map();
    for(let k=1;k<=27;k++){b.renderer.draw({seconds:at+k/60,vocal_group_state:newState.result});for(const l of b.renderer.audit().lanes){if(l.group_opacity<=0)continue;for(const p of l.visible_phrases){if(!incoming.has(l.id))incoming.set(l.id,new Map());incoming.get(l.id).set(p.id,p);}}}
    const sourcePlan=b.plan.phrase_layout,phasePlan=b.plan.phases[0],assigned=[],futureTargets=[];
    const occupied=blocked.map(v=>[...v]);
    function place(height,wanted,minimum=150){
      const candidates=[wanted,minimum];for(const p of occupied)candidates.push(p[1]+1,p[0]-height-1);
      const fit=candidates.filter(top=>top>=minimum&&top+height<=1770&&occupied.every(([a,z])=>top+height<=a||top>=z)).sort((x,y)=>Math.abs(x-wanted)-Math.abs(y-wanted))[0];
      if(fit===undefined)throw Error('No complete handoff atom fits '+JSON.stringify({handoff:handoff.id,height,wanted,minimum,occupied}));
      occupied.push([fit,fit+height]);return fit;
    }
    for(const [id,visible]of incoming){
      const slot=phasePlan.slots.find(v=>v.id===id),current=[...visible.values()].filter(p=>p.source_interval[0]<=at+.45),future=[...visible.values()].filter(p=>p.source_interval[0]>at+.45);
      if(!current.length)continue;
      const bodyHeight=Math.max(...current.map(p=>sourcePlan[p.id].block_height)),height=slot.role_height+bodyHeight,normal=newState.result[id].top,top=place(height,normal);
      assigned.push({id,top,height,normal_top:normal,offset:top-normal,phrase_targets:Object.fromEntries(current.map(p=>[p.id,top+slot.role_height]))});
      for(const p of future)futureTargets.push({id,p,height:sourcePlan[p.id].preview_height,wanted:normal+slot.role_height+sourcePlan[p.id].preview_offset,minimum:top+height+10});
    }
    for(const f of futureTargets){const top=place(f.height,f.wanted,f.minimum);assigned.find(g=>g.id===f.id).phrase_targets[f.p.id]=top;}
    // A nearest-gap bridge can place one group's preview below another
    // group's current text. Those paths cross when returning to normal rows.
    // Keep existing placements unless their vertical order is reversed; then
    // solve whole atoms in final source/layout order around outgoing tails.
    const atoms=[];
    for(const g of assigned){
      atoms.push({kind:'body',id:g.id,wanted:g.normal_top,height:g.height,top:g.top});
      for(const f of futureTargets.filter(v=>v.id===g.id))atoms.push({kind:'preview',id:g.id,phrase:f.p.id,wanted:f.wanted,height:f.height,top:g.phrase_targets[f.p.id]});
    }
    atoms.sort((a,b)=>a.wanted-b.wanted);
    const crossing=atoms.some((a,j)=>j&&atoms[j-1].top+atoms[j-1].height>a.top+1e-7);
    if(crossing){
      function orderedFit(index,placed){
        if(index===atoms.length)return placed;
        const atom=atoms[index],prior=placed.at(-1);
        const parent=placed.find(p=>p.kind==='body'&&p.id===atom.id);
        const lower=Math.max(150,prior?prior.top+prior.height+1:150,atom.kind==='preview'&&parent?parent.top+parent.height+10:150);
        const candidates=[lower,Math.max(lower,atom.wanted)];
        for(const [a,z]of blocked)candidates.push(Math.max(lower,z+1),a-atom.height-1);
        const possible=[...new Set(candidates)].filter(top=>top>=lower&&top+atom.height<=1770&&blocked.every(([a,z])=>top+atom.height<=a||top>=z)).sort((a,b)=>Math.abs(a-atom.wanted)-Math.abs(b-atom.wanted));
        for(const top of possible){const found=orderedFit(index+1,[...placed,{...atom,top}]);if(found)return found;}
        return null;
      }
      const ordered=orderedFit(0,[]);if(!ordered)throw Error('No order-preserving complete handoff fits '+handoff.id);
      for(const atom of ordered){const g=assigned.find(v=>v.id===atom.id);
        if(atom.kind==='body'){const delta=atom.top-g.top;g.top=atom.top;g.offset=atom.top-g.normal_top;for(const id of Object.keys(g.phrase_targets))if(!futureTargets.some(f=>f.p.id===id))g.phrase_targets[id]+=delta;}
        else g.phrase_targets[atom.phrase]=atom.top;
      }
    }
    bridges.push({...handoff,placement_strategy:crossing?'source_order_preserving_atoms':'existing_nearest_gap',groups:assigned,blocked,clear_seconds:handoff.clear_seconds??.25,settle_seconds:(handoff.bridge_duration_seconds??.45)-(handoff.clear_seconds??.25)});
  }
  const entryIds=new Set(schedule.panel_entries.phrases.map(p=>p.id));
  function phraseOffset(instance,id,t){
    const p=phrases.get(id),step=instance.plan.phrase_layout[id].preview_offset;
    const lane=sourceLanes.get(p.staff||id.split('-lyric-')[0]),all=lane.phrases,previous=all[all.findIndex(v=>v.id===id)-1];
    function current(q){const pl=instance.plan.phrase_layout[q.id],st=pl?.preview_offset??step;return motionOffset(q,t,st,entryIds.has(q.id));}
    let offset=t<p.start&&p.continuity_from_previous?followingPreviewOffset(p,t,step,previous,previous?instance.plan.phrase_layout[previous.id].block_height:0,previous?current(previous):0,previous?entryIds.has(previous.id):false):current(p);
    const localLane=instance.tl.lanes.find(l=>l.phrases.some(q=>q.id===id)),index=localLane?.phrases.findIndex(q=>q.id===id),next=localLane?.phrases[index+1];
    const pm=instance.plan.phrase_layout,exit=phraseExitDuration(p,next,pm[id].block_height,next?pm[next.id]?.preview_offset:undefined);
    if(t>=p.end)offset-=10*smooth((t-p.end)/exit);return offset;
  }

  const markerLayer=el('g',{'data-layer':'vocal-programme-markers'},actor.root),nativeLabels=new Map([...actor.labels.querySelectorAll('text')].map(n=>[n.getAttribute('data-staff'),n]));
  const markers=timeline.lanes.filter(l=>nativeLabels.has(l.id)).map(l=>({l,native:nativeLabels.get(l.id),node:el('rect',{width:4,height:32,'data-vocal-marker':l.id},markerLayer)}));
  const labelBox=n=>{const box=n.getBBox(),m=actor.root.getCTM().inverse().multiply(n.getCTM()),points=[[box.x,box.y],[box.x+box.width,box.y],[box.x,box.y+box.height],[box.x+box.width,box.y+box.height]].map(([x,y])=>[m.a*x+m.c*y+m.e,m.b*x+m.d*y+m.f]);const x=Math.min(...points.map(p=>p[0])),y=Math.min(...points.map(p=>p[1]));return{x,y,width:Math.max(...points.map(p=>p[0]))-x,height:Math.max(...points.map(p=>p[1]))-y};};
  function colorForStaff(t,staff){const colors=Object.fromEntries(timeline.lanes.map(l=>[l.id,l.color]));for(const i of instances)if(i.c.display_start<=t&&t<i.c.display_end)for(const g of phaseAt(i.c,t).groups)for(const m of g.members)colors[m]=g.color;return staff?colors[staff]:colors;}
  let last={seconds:null,lanes:[]};
  function draw(F){
    const t=Number(F.seconds);if(!Number.isFinite(t))throw Error('Programme requires movement F.seconds');
    // All native layout reads precede all overlay writes.
    const native=markers.map(m=>({m,b:labelBox(m.native),opacity:Number(m.native.style.opacity||1)}));
    const colors=colorForStaff(t);let presence=0,window=null;
    for(const w of schedule.panel_presence.windows){const v=quint((t-w.enter_start)/(w.enter_end-w.enter_start))*(1-quint((t-w.exit_start)/(w.exit_end-w.exit_start)));if(v>presence){presence=v;window=w;}}
    const offset=1220*(1-presence);paper.setAttribute('transform',`translate(${offset} 0)`);
    const cohorts=[],lanes=[];
    for(const i of instances){const active=i.c.display_start<=t&&t<i.c.display_end;i.node.setAttribute('display',active?'inline':'none');if(!active)continue;const state=groupStates(i,t);
      const bridge=bridges.find(h=>h.to_cohort===i.c.id&&h.boundary<=t&&t<(h.settle_end??h.boundary+.45));
      if(bridge){const u=1-smooth((t-bridge.boundary-bridge.clear_seconds)/bridge.settle_seconds);for(const g of bridge.groups){const st=state.result[g.id],slot=i.plan.phases[0].slots.find(s=>s.id===g.id);st.top+=g.offset*u;st.phrase_offsets={};for(const[id,target]of Object.entries(g.phrase_targets))st.phrase_offsets[id]=(target-(g.top+slot.role_height+phraseOffset(i,id,t)))*u;}}
      i.renderer.draw({...F,vocal_group_state:state.result});const audit=i.renderer.audit();
      for(const l of audit.lanes){if(l.group_opacity<=0)continue;const g=state.result[l.id].effective_group;l.members=g?.members||[l.id];l.effective_group=g;l.cohort_id=i.c.id;l.phase_id=state.phase.id;lanes.push(l);}
      cohorts.push({id:i.c.id,phase:state.phase.id,transition:state.transition,layout:audit.layout,bridge:bridge?.id||null});
    }
    const markerStates=native.map(({m,b,opacity})=>{const active=m.l.phrases.some(p=>p.segments.some(s=>(s.sounding_intervals_samples||[[s.start*timeline.sample_rate,s.end*timeline.sample_rate]]).some(([a,b])=>a<=t*timeline.sample_rate&&t*timeline.sample_rate<b))),x=b.x-24,y=b.y+b.height/2-16,alpha=opacity*(active?1:.28);m.node.setAttribute('x',x);m.node.setAttribute('y',y);m.node.setAttribute('opacity',alpha);m.node.setAttribute('fill',colors[m.l.id]);return{staff:m.l.id,x,y,opacity:alpha,active,color:colors[m.l.id],native_label_bbox:b};});
    const ownership=[];for(const l of lanes)for(const p of l.visible_phrases){const c=byCohort.get(l.cohort_id).c,g=l.effective_group;const representative=phrases.get(p.id);for(const member of g?.members||[l.id]){const source=(g?.source_phrase_ids[member]||[]).map(id=>phrases.get(id)).find(s=>s.start_sample===representative.start_sample&&s.de===representative.de);if(source)ownership.push({source_phrase_id:source.id,rendered_phrase_id:p.id,cohort:c.id});}}
    if(new Set(ownership.map(v=>v.source_phrase_id)).size!==ownership.length)throw Error('Duplicate source phrase ink');
    last={seconds:t,panel:{presence,window,paper_offset_x:offset,paper_edge_x:2620+offset},cohorts,lanes,markers:markerStates,color_map:colors,ownership};
  }
  return {draw,colorForStaff,audit:()=>({schema_version:1,one_shared_paper:true,canonical_cohorts:instances.map(i=>i.c.id),bridges,source_clock_unchanged:true,layout_source:'full_movement_canonical_phase_plans',...last})};
}
