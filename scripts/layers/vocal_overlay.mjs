/** Research-only selected-05 SVG overlay. This function is deliberately self-contained:
 * the native adapter serializes installVocalOverlay.toString() into its owned browser.
 * Fonts must have loaded before installation. All times are movement seconds.
 */
export function installVocalOverlay(actor, timeline) {
  const NS='http://www.w3.org/2000/svg', X=2910, WIDTH=840, TOP=150, BOTTOM=1770;
  const INK='#3D403A', PAST='#8D8A80', ZH='#56645F', UPCOMING='#91968C';
  const IN=.18, RISE=.30, OUT=.25, DRIFT=10;
  const MIN_HOLD=1.2, BAR_FADE=.1;
  const PRE_SIZE=40, PRE_ALPHA=.78, ENTRANCE=.2, ROLE_IN=.15;
  const smooth=v=>{const u=Math.max(0,Math.min(1,v));return u*u*(3-2*u);};
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
  function blendFill(a,b,u){
    if(u<=0)return a;if(u>=1)return b;
    const channel=(s,i)=>parseInt(s.slice(i,i+2),16);
    return 'rgb('+[1,3,5].map(i=>Math.round(channel(a,i)+(channel(b,i)-channel(a,i))*u)).join(',')+')';
  }
  const el=(tag,attrs={},parent)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent?.append(n);return n;};
  if (!actor?.root || !actor?.scoreClip || !actor?.labels || !timeline?.lanes?.length) throw Error('Missing native actor or vocal timeline');
  const options=timeline.programme_options||{}, supplied=timeline.programme_layout;
  const sr=timeline.sample_rate||44100;
  const lanes=timeline.lanes.map(l=>({...l,phrases:l.phrases.map(p=>({...p,segments:p.segments.map(s=>({...s}))})).sort((a,b)=>a.start-b.start)}));
  if(new Set(lanes.map(l=>l.id)).size!==lanes.length)throw Error('Duplicate vocal lane identity');
  if(lanes.some(l=>!l.runs?.length))throw Error('Full-movement continuity runs must be compiled before rendering');
  for(const lane of lanes)for(const p of lane.phrases){
    if(!p.de || !p.zh || !Number.isFinite(p.start) || !(p.end>p.start))throw Error('Incomplete source phrase '+p.id);
    for(const s of p.segments){
      if(p.de.slice(s.start_char,s.end_char)!==s.text)throw Error('Source character range mismatch '+p.id);
      if(!(s.end>s.start))throw Error('Empty source syllable interval '+s.source_lyric_event_id);
      const original=p.syllables?.find(v=>v.source_lyric_event_id===s.source_lyric_event_id);
      s.sounding=(original?.sounding_intervals_samples||s.sounding_intervals_samples||[[s.start*sr,s.end*sr]]).map(([a,b])=>[a/sr,b/sr]);
    }
  }

  // Paper overlay: constrain only the native right edge,
  // then cover its final 80 pixels with the existing paper color at increasing alpha.
  const defs=el('defs',{},actor.root),uid='vocal-overlay-'+Math.random().toString(36).slice(2);
  const grad=el('linearGradient',{id:uid+'-fade',gradientUnits:'userSpaceOnUse',x1:2620,x2:2700,y1:0,y2:0},defs);
  el('stop',{offset:0,'stop-color':'#FAF8F1','stop-opacity':0},grad);
  el('stop',{offset:1,'stop-color':'#FAF8F1','stop-opacity':1},grad);
  // Keep the native full-width clip. The paper-only covering relinquishes
  // future score ink continuously; it never changes score scale or clock.
  const panelPaper=options.shared_paper?null:el('g',{'data-layer':'vocal-panel-paper'},actor.root);
  if(panelPaper)el('rect',{x:2620,y:0,width:80,height:1834,fill:`url(#${uid}-fade)`},panelPaper);
  if(panelPaper)el('rect',{x:2700,y:0,width:1040,height:1834,fill:'#FAF8F1'},panelPaper);
  const panelWindows=timeline.panel_presence?.windows;
  if(!panelWindows?.length)throw Error('Full-source panel presence windows required');
  const panelEase=v=>{const x=Math.max(0,Math.min(1,v));return x*x*x*(x*(x*6-15)+10);};
  const entryByPhrase=new Map(timeline.panel_entries.phrases.map(p=>[p.id,p]));
  const entryByRun=new Map(timeline.panel_entries.phrases.map(p=>[p.run_id,p]));
  let panelState=null;
  function panelAt(t){
    let presence=0,window=null;
    for(const w of panelWindows){
      const weight=panelEase((t-w.enter_start)/(w.enter_end-w.enter_start))
        *(1-panelEase((t-w.exit_start)/(w.exit_end-w.exit_start)));
      if(weight>presence){presence=weight;window=w;}
    }
    return {presence,window,score_right_edge:3730,full_presence_fade:[2620,2700],
      paper_offset_x:1220*(1-presence),paper_edge_x:2620+1220*(1-presence),body_opacity_multiplied:true,body_opacity:presence,paper_global_opacity:1};
  }
  const layer=el('g',{'data-layer':'vocal-overlay-05',class:'vocal-overlay','font-family':'Han','font-weight':400},actor.root);
  const markerLayer=el('g',{'data-layer':'vocal-markers-05'},actor.root);
  const measure=el('text',{x:-10000,y:-10000,visibility:'hidden','font-family':'Han',style:'white-space:pre'},layer);
  const metrics=new Map();
  const width=(text,size)=>{
    const k=size+'|'+text;if(metrics.has(k))return metrics.get(k);
    measure.setAttribute('font-size',size);measure.textContent=text;
    const w=measure.getComputedTextLength();metrics.set(k,w);return w;
  };
  function wrap(text,size) {
    const tokens=[...text.matchAll(/\S+/gu)].map(m=>({a:m.index,b:m.index+m[0].length}));
    if(!tokens.length)return [];
    // Chinese has no whitespace, so line breaking uses complete characters.
    if(tokens.length===1 && width(text,size)>WIDTH){
      const result=[];let start=0,stop=0;
      while(stop<text.length){const step=String.fromCodePoint(text.codePointAt(stop)).length;
        if(stop>start && width(text.slice(start,stop+step),size)>WIDTH){result.push([start,stop]);start=stop;}
        stop+=step;
      }
      if(stop>start)result.push([start,stop]);return result;
    }
    const greedy=[];let first=0;
    while(first<tokens.length){let end=first+1;while(end<tokens.length && width(text.slice(tokens[first].a,tokens[end].b),size)<=WIDTH)end++;
      if(width(text.slice(tokens[first].a,tokens[end-1].b),size)>WIDTH)throw Error('An unbreakable source word exceeds the lane');
      greedy.push([tokens[first].a,tokens[end-1].b]);first=end;
    }
    const cache=new Map();
    function best(first,count){
      if(!count)return first===tokens.length?{cost:0,lines:[]}:{cost:Infinity,lines:[]};
      const k=first+':'+count;if(cache.has(k))return cache.get(k);let choice={cost:Infinity,lines:[]};
      for(let end=first+1;end<=tokens.length;end++){
        if(tokens.length-end<count-1)break;
        const a=tokens[first].a,b=tokens[end-1].b,w=width(text.slice(a,b),size);if(w>WIDTH)break;
        const tail=best(end,count-1);let cost=(1-w/WIDTH)**2+tail.cost;
        if(end<tokens.length && /[,;:!?.]$/.test(text.slice(a,b)))cost-=.12;
        if(count===1 && end-first===1)cost+=.3;
        if(cost<choice.cost)choice={cost,lines:[[a,b],...tail.lines]};
      }
      cache.set(k,choice);return choice;
    }
    const balanced=best(0,greedy.length).lines;
    const lines=balanced.length?balanced:greedy;
    if(lines.map(([a,b])=>text.slice(a,b)).join('').replace(/\s/gu,'')!==text.replace(/\s/gu,''))throw Error('Source text was lost while wrapping');
    return lines;
  }

  // Full-clip layout: two complete phrases can coexist inside a fixed lane.
  // Neither a changing syllable nor phrase admission can alter these stable slots.
  let layout;
  for(let size=supplied?.de_size||55;size>=16;size--){
    const role=Math.min(40,Math.max(16,Math.round(size*.72))),zh=Math.max(16,Math.round(size*.7));
    const lead=Math.round(size*1.28),zhLead=Math.round(zh*1.28),roleHeight=Math.round(role*1.3)+8;
    let total=0;const slots=[];
    for(const lane of lanes){
      let block=0;
      for(const p of lane.phrases){
        p.lines=wrap(p.de,size);p.zhLines=wrap(p.zh,zh);
        p.blockHeight=p.lines.length*lead+10+p.zhLines.length*zhLead;
        if(!p.context_only)block=Math.max(block,p.blockHeight);
      }
      const previewOffset=block+14;
      // At a phrase entrance: old current, promoted current and ONE next can
      // coexist. Reserve its complete source-text-only height from the beginning.
      const preScale=40/55,preHeight=Math.max(...lane.phrases.filter(p=>!p.context_only).map(p=>p.lines.length*lead*preScale));
      const height=roleHeight+2*previewOffset+preHeight+4;
      slots.push({id:lane.id,height,block_height:block,preview_offset:previewOffset,preview_height:preHeight,role_height:roleHeight});total+=height;
    }
    if(supplied){layout=JSON.parse(JSON.stringify(supplied));break;}
    if(total<=BOTTOM-TOP){layout={de_size:size,zh_size:zh,role_size:role,de_leading:lead,zh_leading:zhLead,height:total,top:Math.max(TOP,Math.min(1200-total/2,BOTTOM-total)),width:WIDTH,slots};break;}
  }
  if(!layout)throw Error('Complete current and preparation phrases do not fit stable voice slots');
  let y=layout.top;
  const text=(parent,value,x,baseline,size,fill,attrs={})=>{const n=el('text',{x,y:baseline,'font-size':size,fill,'font-family':'Han',style:'white-space:pre','xml:space':'preserve',...attrs},parent);n.textContent=value;return n;};
  for(let i=0;i<lanes.length;i++){
    const lane=lanes[i],slot=layout.slots.find(s=>s.id===lane.id);
    if(supplied)y=slot.top;else slot.top=y;lane.slot=slot;
    const g=el('g',{'data-vocal-lane':lane.id},layer);lane.node=g;
    const roleSize=Math.min(layout.role_size,layout.role_size*WIDTH/width(lane.label,layout.role_size));
    lane.roleNode=text(g,lane.label,X,y+roleSize,roleSize,lane.color,{'data-voice-label':lane.id});
    lane.roleRuns=lane.runs.map(r=>[r.start,r.end,entryByRun.get(r.id)]);
    lane.markers=(options.shared_markers?[]:(lane.members||[lane.id])).map(id=>{
      const node=el('rect',{width:4,height:32,fill:lane.color,'data-vocal-marker':id},markerLayer);
      const nativeLabel=[...actor.labels.querySelectorAll('text')].find(n=>n.getAttribute('data-staff')===id);
      if(!nativeLabel)throw Error('Missing native label for marker '+id);
      return {id,node,nativeLabel};
    });
    for(let j=0;j<lane.phrases.length;j++){
      const p=lane.phrases[j],previous=lane.phrases[j-1],next=lane.phrases[j+1];
      p.previous=previous;p.next=next;
      p.staged=p.continuity_from_previous;
      if(p.staged&&!previous&&!(p.start<=timeline.clip?.start))throw Error('A selected passage must retain the preceding phrase needed for its preview');
      p.panelEntry=!p.staged?entryByPhrase.get(p.id):null;
      p.admit=p.panelEntry?p.panelEntry.admit:p.staged?p.preview_at:p.start;
      if(p.staged&&previous&&Math.abs(p.admit-previous.start)>1/sr)throw Error('Next phrase must be admitted at current source onset');
      p.inDuration=p.staged?Math.min(IN,(p.start-p.admit)*.35):Math.min(.15,(p.end-p.start)*.35);
      if(!p.motion)throw Error('Full-source motion schedule must be compiled before selecting a window');
      p.riseDuration=promotionDuration(p);
      p.clearDuration=p.motion.clear_seconds;
      p.entranceDuration=p.motion.entrance_seconds;
      p.outDuration=p.motion.exit_seconds;
      p.full=p.panelEntry?p.panelEntry.full:p.admit+p.inDuration;
      // A phrase owns its exit; the next entrance must never prolong old lyrics.
      p.outStart=p.end;
      p.group=el('g',{'data-phrase':p.id,opacity:0},g);p.fragments=[];p.progress=[];
      const bodyY=y+slot.role_height;
      p.bodyY=bodyY;
      p.deGroup=el('g',{'data-language':'de'},p.group);
      p.translationGroup=el('g',{'data-language':'zh',opacity:0},p.group);
      for(let line=0;line<p.lines.length;line++){
        const [a,b]=p.lines[line],baseline=bodyY+layout.de_size+line*layout.de_leading;
        const bounds=new Set([a,b]);for(const s of p.segments){if(s.start_char>a&&s.start_char<b)bounds.add(s.start_char);if(s.end_char>a&&s.end_char<b)bounds.add(s.end_char);}
        const cuts=[...bounds].sort((v,w)=>v-w);
        for(let k=0;k<cuts.length-1;k++){
          const start=cuts[k],end=cuts[k+1],seg=p.segments.find(s=>s.start_char<=start&&s.end_char>=end);
          const px=X+width(p.de.slice(a,start),layout.de_size);
          const node=text(p.deGroup,p.de.slice(start,end),px,baseline,layout.de_size,INK,{'data-source-lyric-event':seg?.source_lyric_event_id||''});
          p.fragments.push({node,seg});
        }
        for(const s of p.segments){
          if(p.progress.some(v=>v.id===s.source_lyric_event_id))continue;
          const from=Math.max(a,s.start_char),to=Math.min(b,s.end_char);if(to<=from)continue;
          const sylWidth=width(p.de.slice(from,to),layout.de_size),length=Math.min(96,Math.max(6,sylWidth));
          const px=X+width(p.de.slice(a,from),layout.de_size)+(sylWidth-length)/2;
          const barY=baseline+Math.max(10,Math.ceil(layout.de_size*.14));
          const bg=el('line',{x1:px,x2:px+length,y1:barY,y2:barY,stroke:lane.color,'stroke-width':2,'stroke-opacity':.24},p.deGroup);
          const fg=el('line',{x1:px,x2:px,y1:barY,y2:barY,stroke:lane.color,'stroke-width':3},p.deGroup);
          p.progress.push({id:s.source_lyric_event_id,seg:s,bg,fg,x:px,y:barY,length});
        }
      }
      const zhY=bodyY+p.lines.length*layout.de_leading+10;
      p.zhLines.forEach(([a,b],line)=>text(p.translationGroup,p.zh.slice(a,b),X,zhY+layout.zh_size+line*layout.zh_leading,layout.zh_size,ZH));
    }
    y+=slot.height;
  }
  for(const label of (options.all_labels||[]))width(label,layout.role_size);
  measure.remove();

  const sourceState=(seg,t)=>{
    if(!seg)return 'future';
    if(seg.sounding.some(([a,b])=>a<=t&&t<b))return 'active';
    return t>=seg.end?'past':t<seg.start?'future':'rest';
  };
  const labelBox=n=>{
    const b=n.getBBox(),m=actor.root.getCTM().inverse().multiply(n.getCTM());
    const pts=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]].map(([x,y])=>({x:m.a*x+m.c*y+m.e,y:m.b*x+m.d*y+m.f}));
    const x=Math.min(...pts.map(v=>v.x)),y=Math.min(...pts.map(v=>v.y));
    return {x,y,width:Math.max(...pts.map(v=>v.x))-x,height:Math.max(...pts.map(v=>v.y))-y};
  };
  let last={seconds:null,lanes:[]};
  function currentOffset(p,t){
    return motionOffset(p,t,p.laneStep,!!p.panelEntry);
  }
  for(const lane of lanes)for(const p of lane.phrases){
    const plan=supplied?.phrase_layout?.[p.id];
    p.laneStep=plan?.preview_offset??lane.slot.preview_offset;
    if(!Number.isFinite(p.laneStep))throw Error('Missing source phrase preview offset '+p.id);
    if(plan && (plan.de_line_count!==p.lines.length || plan.zh_line_count!==p.zhLines.length))throw Error('Actual font wrapping differs from full-source plan '+p.id);
  }
  for(const lane of lanes)for(const p of lane.phrases){
    p.outDuration=phraseExitDuration(p,p.next,p.blockHeight,p.next?.laneStep);
  }
  function draw(F){
    const t=Number(F.seconds);if(!Number.isFinite(t))throw Error('Vocal draw requires F.seconds');
    const nativeLabelStates=new Map(lanes.flatMap(lane=>lane.markers.map(m=>[m.id,{b:labelBox(m.nativeLabel),nativeOpacity:Number(m.nativeLabel.style.opacity||1)}])));
    panelState=panelAt(t);
    panelPaper?.setAttribute('opacity',1);
    panelPaper?.setAttribute('transform',`translate(${panelState.paper_offset_x} 0)`);
    // Any body/role present is governed solely by its original source lifecycle.
    // This displacement has completed before source onset and starts only after
    // the final body/role has cleared; their actual onsets never fade grey.
    layer.setAttribute('transform',`translate(${panelState.paper_offset_x} 0)`);
    layer.setAttribute('opacity',panelState.presence);
    const records=[];
    for(const lane of lanes){
      const presentation=F.vocal_group_state?.[lane.id]||{},dy=(presentation.top??lane.slot.top)-lane.slot.top,groupOpacity=presentation.opacity??1;
      const color=presentation.color||lane.color,label=presentation.label||lane.label;
      lane.node.setAttribute('transform',`translate(0 ${dy})`);lane.node.setAttribute('opacity',groupOpacity);
      lane.roleNode.textContent=label;lane.roleNode.setAttribute('fill',color);
      const roleSize=Math.min(layout.role_size,layout.role_size*WIDTH/width(label,layout.role_size));lane.roleNode.setAttribute('font-size',roleSize);
      const visible=[],bars=[];let isActive=false;
      const roleOpacity=Math.max(0,...lane.roleRuns.map(([a,b,entry])=>(entry?(t>=entry.admit?1:0):smooth((t-a)/ROLE_IN))*(1-smooth((t-b)/OUT))));
      lane.roleNode.setAttribute('opacity',roleOpacity*(presentation.role_opacity??1));
      for(const p of lane.phrases){
        const incoming=p.panelEntry?(t>=p.admit?1:0):smooth((t-p.admit)/p.inDuration);
        const outgoing=1-smooth((t-p.outStart)/p.outDuration);
        let opacity=p.context_only?0:incoming*outgoing;
        // The incoming and outgoing full texts occupy separate rows before the
        // boundary. Outgoing ink clears before the incoming baseline traverses it.
        // Next enters immediately underneath the promoting current phrase.
        // They travel together at a full-block distance; nothing is delayed
        // until the old promotion has finished, and no words cross each other.
        let offset=t<p.start&&p.staged?followingPreviewOffset(p,t,p.laneStep,p.previous,p.previous?.blockHeight||0,p.previous?currentOffset(p.previous,t):0,!!p.previous?.panelEntry):currentOffset(p,t);
        offset+=presentation.phrase_offsets?.[p.id]||0;
        if(t>=p.outStart)offset-=DRIFT*smooth((t-p.outStart)/p.outDuration);
        p.group.setAttribute('opacity',opacity.toFixed(6));
        p.group.setAttribute('transform',`translate(0 ${offset.toFixed(4)})`);
        p.group.setAttribute('display',opacity>0?'inline':'none');
        const entrance=p.staged?promotionProgress(p,t):smooth((t-p.start)/p.entranceDuration);
        const deScale=bodyScale(p,t,!!p.panelEntry);
        const deAlpha=p.panelEntry?1:PRE_ALPHA+(1-PRE_ALPHA)*entrance;
        // Scale the whole premeasured German group around its own text origin;
        // fixed line breaks and syllable positions preserve spacing throughout.
        p.deGroup.setAttribute('transform',`translate(${X} ${p.bodyY}) scale(${deScale}) translate(${-X} ${-p.bodyY})`);
        p.deGroup.setAttribute('opacity',deAlpha);
        p.translationGroup.setAttribute('opacity',entrance);
        p.translationGroup.setAttribute('transform',`translate(${X} ${p.bodyY}) scale(${deScale}) translate(${-X} ${-p.bodyY})`);
        for(const f of p.fragments){
          const st=sourceState(f.seg,t);
          // The active source syllable receives its voice color immediately,
          // independently of the size/position transition.
          const neutral=st==='past'||st==='rest'?PAST:INK;
          const fill=t<p.start?(p.panelEntry?INK:UPCOMING):st==='active'?color:p.staged?blendFill(UPCOMING,neutral,entrance):neutral;
          f.node.setAttribute('fill',fill);
        }
        for(const v of p.progress){
          v.bg.setAttribute('stroke',color);v.fg.setAttribute('stroke',color);
          const active=sourceState(v.seg,t)==='active';isActive ||= active;
          const interval=active?v.seg.sounding.find(([a,b])=>a<=t&&t<b):null;
          const show=interval&&interval[1]-interval[0]>=MIN_HOLD-1e-9;
          v.bg.setAttribute('visibility',show?'visible':'hidden');v.fg.setAttribute('visibility',show?'visible':'hidden');
          if(show){
            const [a,b]=interval;
            const progress=Math.max(0,Math.min(1,(t-a)/(b-a)));
            const barOpacity=smooth((t-a)/BAR_FADE)*smooth((b-t)/BAR_FADE);
            v.bg.setAttribute('opacity',barOpacity);v.fg.setAttribute('opacity',barOpacity);
            v.fg.setAttribute('x2',v.x+v.length*progress);
            const bx=X+(v.x-X)*deScale,by=p.bodyY+(v.y-p.bodyY)*deScale+offset;
            if(opacity>0)bars.push({phrase_id:p.id,source_lyric_event_id:v.id,syllable:v.seg.text,interval,progress,opacity:barOpacity*deAlpha*opacity*groupOpacity,bounds:[bx,by+dy,bx+v.length*deScale,by+dy],max_length_px:v.length*deScale});
          }
        }
        if(opacity>0&&groupOpacity>0)visible.push({group_opacity:groupOpacity,id:p.id,de:p.de,zh:p.zh,opacity,german_opacity:opacity*deAlpha*panelState.presence*groupOpacity,translation_opacity:opacity*entrance*panelState.presence*groupOpacity,panel_opacity:panelState.presence,panel_offset_x:panelState.paper_offset_x,effective_de_size:layout.de_size*deScale,upcoming_fill:UPCOMING,offset_y:offset,source_interval:[p.start,p.end],main_baseline:lane.slot.top+dy+lane.slot.role_height+layout.de_size,body_top:p.bodyY+offset+dy,body_bottom:p.bodyY+offset+dy+(t<p.start&&!p.panelEntry?p.lines.length*layout.de_leading*deScale:p.blockHeight*deScale),staged:p.staged,admitted_at:p.admit,fully_readable_at:p.full,rise_seconds:p.riseDuration,promotion_progress:entrance,promotion_style_and_position_shared:p.staged,out_seconds:p.outDuration,run_id:p.run_id,panel_entry:!!p.panelEntry,phase:t<p.start?(p.panelEntry?'panel_entry_preroll':'upcoming'):t<p.end?'current':'exiting'});
      }
      const markers=lane.markers.map(m=>{
        const {b,nativeOpacity}=nativeLabelStates.get(m.id),x=b.x-24,y=b.y+b.height/2-16;
        const alpha=nativeOpacity*(isActive?1:.28);
        m.node.setAttribute('x',x);m.node.setAttribute('y',y);m.node.setAttribute('opacity',alpha);
        return {staff:m.id,x,y,width:4,height:32,opacity:alpha,native_label_bbox:b};
      });
      records.push({id:lane.id,label,color,group_opacity:groupOpacity,role_opacity:roleOpacity*panelState.presence*groupOpacity*(presentation.role_opacity??1),role_runs:lane.roleRuns,slot_top:lane.slot.top+dy,slot_height:presentation.height??lane.slot.height,visible_phrases:visible,bars,marker:markers[0],markers});
    }
    last={seconds:t,lanes:records,panel:panelState};
  }
  function audit(){return {schema_version:4,panel_entry:{scope:'whole_panel_windows_first_batch_only',window_seconds:timeline.panel_presence.entry_slide_seconds,stable_before_source:timeline.panel_presence.fully_clear_before_onset_seconds,within_panel_run_behavior:'source_timing_preserved'},layout,upcoming:{german_size:layout.de_size*40/55,fill:UPCOMING,opacity:PRE_ALPHA,translation_visible:false,admission:'preceding_connected_phrase_source_onset'},sidebar_roles:{entry_seconds:ROLE_IN,exit_seconds:OUT,visibility:'complete_continuous_run_including_inter_phrase_breaths'},transition:{maximum_preview_fade_seconds:IN,maximum_promotion_seconds:RISE,promotion:'single_shared_smoothstep_for_position_scale_opacity_neutral_color_and_translation',outgoing_clearance_px:4,short_phrase_promotion:'at_most_75_percent_of_next_source_onset_distance',maximum_outgoing_fade_seconds:OUT,exit_bound_to:'own_final_sounding_end',temporary_third_position:true,small_drift_px:DRIFT},progress_line:{minimum_continuous_seconds:MIN_HOLD,edge_fade_seconds:BAR_FADE,short_syllables_keep_color_and_marker:true},score_mask:{fade_start:2620,fade_end:2700,native_clip_right:3730,paper_opacity_follows_panel:false,full_horizontal_slide:true,navigation_touched:false},full_source_text_retained:true,source_clock_is_not_letter_phonetics:true,...last};}
  return {draw,audit};
}
