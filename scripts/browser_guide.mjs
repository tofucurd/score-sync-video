import {installGuide} from './layers/guide_runtime.mjs';
import {packCompactLabelRows} from './layers/guide_layout.mjs';
import {installScoreLocators} from './layers/score_locators.mjs';
import {openingState} from './layers/opening.mjs';
import {installStaffSignatures} from './layers/staff_signatures.mjs';
import {installProgramVocals} from './layers/program_vocals.mjs';
import {installVocalOverlay} from './layers/vocal_overlay.mjs';
import {createMaterialIndex,installMaterialRegions} from './layers/guide_ink.mjs';
// Owned Chromium, native SVG only. No connection to the user's browser session.
import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import {spawn,spawnSync} from 'node:child_process';import {once} from 'node:events';import {setTimeout as delay} from 'node:timers/promises';
const args=process.argv.slice(2),arg=k=>args[args.indexOf(k)+1],spec=JSON.parse(fs.readFileSync(arg('--spec'),'utf8')),out=arg('--output'),mode=arg('--mode')||'video';
const candidates=[process.env.SCORE_SYNC_CHROME,'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','/usr/bin/chromium','/usr/bin/chromium-browser','/usr/bin/google-chrome'];const chromePath=candidates.find(p=>p&&fs.existsSync(p));if(!chromePath)throw Error('Chromium not found: set SCORE_SYNC_CHROME');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'score-chrome-'));let chrome,ws,encoder,chromeLog;let browserClosing=false;let seq=0;const pending=new Map();let cancelled=false;
for(const sig of ['SIGTERM','SIGINT'])process.on(sig,()=>{cancelled=true;encoder?.kill('SIGTERM');chrome?.kill('SIGTERM');for(const p of pending.values())p.reject(Error('Render cancelled'));pending.clear();ws?.close();setTimeout(()=>{try{fs.rmSync(profile,{recursive:true,force:true})}catch{}process.exit(130)},1000).unref();});
const call=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method))},method==='Browser.close'?1000:(spec.cdp_timeout_ms||120000));pending.set(id,{resolve:v=>{clearTimeout(timer);resolve(v)},reject:e=>{clearTimeout(timer);reject(e)}});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
// Serialize one diagnostic entry at a time; never allocate the complete report
// as a second browser string or ask CDP for a multi-megabyte response.
async function writeRemoteDiagnostic(send,target,expression){
 const remote=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 const keys=await remote(`Object.keys(${expression}||{})`),fd=fs.openSync(target,'w');let bytes=0,entries=0;
 const put=text=>{bytes+=fs.writeSync(fd,text);};
 const entry=async expr=>{const length=await remote(`window.__diagnosticEntry=JSON.stringify(${expr});window.__diagnosticEntry.length`);let carry='';for(let offset=0;offset<length;offset+=262144){let piece=carry+await remote(`window.__diagnosticEntry.slice(${offset},${offset+262144})`);carry='';const code=piece.charCodeAt(piece.length-1);if(code>=0xD800&&code<=0xDBFF){carry=piece.slice(-1);piece=piece.slice(0,-1);}put(piece);}if(carry)put(carry);await remote('window.__diagnosticEntry=null');entries++;};
 try{put('{');for(let k=0;k<keys.length;k++){const key=keys[k],expr=`(${expression})[${JSON.stringify(key)}]`;if(k)put(',');put(JSON.stringify(key)+':');const count=await remote(`Array.isArray(${expr})?${expr}.length:-1`);if(count>=0){put('[');for(let i=0;i<count;i++){if(i)put(',');await entry(`${expr}[${i}]`);}put(']');}else await entry(expr);}put('}');}finally{fs.closeSync(fd);}
 process.stderr.write(JSON.stringify({diagnostic_entries:entries,diagnostic_bytes:bytes})+'\n');
}
function sceneCode(S=window.spec){

let verticalAudit={};
 const NS='http://www.w3.org/2000/svg';
 const el=(name,a={},parent)=>{const e=document.createElementNS(NS,name);for(const[k,v]of Object.entries(a))e.setAttribute(k,v);parent?.append(e);return e;};
 const root=el('svg',{xmlns:NS,'xmlns:xlink':'http://www.w3.org/1999/xlink',viewBox:'0 0 3840 2160',width:S.width,height:S.height},document.body);root.style.cssText='display:block;position:absolute;left:0;top:0';
 el('style',{},root).textContent=S.fonts+'text{font-family:Han,serif}';const background=el('rect',{width:3840,height:2160,fill:'#FAF8F1'},root);
 const defs=el('defs',{},root),clip=el('clipPath',{id:'screenclip'+(window.sceneCount||0)},defs);el('rect',{x:380,y:40,width:3350,height:1770},clip);
 const readingLine=el('line',{x1:1344,x2:1344,y1:50,y2:1810,stroke:'#287D9F','stroke-width':3},root);
 const scoreClip=el('g',{'clip-path':'url(#screenclip'+(window.sceneCount||0)+')'},root),world=el('g',{},scoreClip);
 const parsed=new DOMParser().parseFromString(S.svg,'image/svg+xml').documentElement;
 const prefix='scene'+(window.sceneCount=(window.sceneCount||0)+1)+'-';
 const ids=new Map([...parsed.querySelectorAll('[id]')].map(e=>[e.id,prefix+e.id]));
 for(const e of parsed.querySelectorAll('*')){for(const a of [...e.attributes]){let v=a.value;if(a.name==='id')v=ids.get(v)||v;else{if(v[0]==='#'&&ids.has(v.slice(1)))v='#'+ids.get(v.slice(1));v=v.replace(/url\(#([^)]*)\)/g,(all,id)=>ids.has(id)?'url(#'+ids.get(id)+')':all)}if(v!==a.value)e.setAttributeNS(a.namespaceURI,a.name,v)}}
 const nativeId=id=>ids.get(id)||id;
 const worldId=prefix+parsed.id;world.id=worldId;world.setAttribute('color','black');world.setAttribute('font-family','Han, serif');
 for(const style of parsed.querySelectorAll('style')){const c=style.cloneNode(true);c.textContent=c.textContent.replaceAll('#'+parsed.id,'#'+worldId);root.append(c);}
 const inner=parsed.querySelector('svg.definition-scale')||parsed.querySelector('svg')||parsed;
 // defs can be siblings of definition-scale; transfer them before native groups.
 for(const d of [...parsed.querySelectorAll('defs')])root.append(d.cloneNode(true));
 for(const c of [...inner.children])if(c.tagName!=='defs')world.append(document.importNode(c,true));
 const nativeNodes=new Map([...world.querySelectorAll('[id]')].map(e=>[e.id,e]));
 const notes=new Map(S.geometry.notes.map(n=>[n.id,nativeNodes.get(nativeId(n.svg_id))]));
 const measures=S.geometry.measures.map(m=>({...m,e:nativeNodes.get(nativeId(m.svg_id))}));
 const controls=(S.geometry.controls||[]).map(c=>({...c,e:nativeNodes.get(nativeId(c.svg_id))}));
 const staffs=S.geometry.staves.map(st=>({...st,groups:st.svg_ids.map(id=>nativeNodes.get(nativeId(id))).filter(Boolean)}));
 for(const st of staffs)for(const g of st.groups)g.dataset.originalTransform=g.getAttribute('transform')||'';
 const indices=new Map(staffs.map((st,i)=>[st.id,i])),parents=staffs.map((_,i)=>i),find=i=>parents[i]===i?i:(parents[i]=find(parents[i]));
 const unite=(a,b)=>{parents[find(b)]=find(a)};
 for(const dep of [...(S.geometry.staff_dependencies||staffs.map(st=>({staves:st.dependencies||[st.id]}))),...controls.filter(c=>c.staves.length>1)]){const ii=dep.staves.map(id=>indices.get(id)).filter(i=>i!==undefined);if(ii.length)for(let i=Math.min(...ii);i<Math.max(...ii);i++)unite(i,i+1);}
 const componentMap=new Map();for(let i=0;i<staffs.length;i++){const k=find(i);if(!componentMap.has(k))componentMap.set(k,[]);componentMap.get(k).push(staffs[i]);}
 const pointBox=e=>{const b=e.getBBox(),m=world.getCTM().inverse().multiply(e.getCTM());return {top:b.y*m.d+m.f,bottom:(b.y+b.height)*m.d+m.f};};
 const extents=new Map(staffs.map(r=>[r.id,{top:r.y-r.height/2-450,bottom:r.y+r.height/2+450}]));
 for(const n of S.geometry.notes){const b=extents.get(n.staff);if(b&&Number.isFinite(n.y)){b.top=Math.min(b.top,n.y-750);b.bottom=Math.max(b.bottom,n.y+750)}}
 const components=[...componentMap.values()].map(rows=>({rows,top:Math.min(...rows.map(r=>extents.get(r.id).top)),bottom:Math.max(...rows.map(r=>extents.get(r.id).bottom))}));
 const generated=[...world.querySelectorAll('g.grpSym, g.barLine>path, g.system>path')].filter(e=>!e.closest('g.staff')).map(e=>({...pointBox(e),e,isBracket:e.classList.contains('grpSym'),parentY:world.getCTM().inverse().multiply(e.parentNode.getCTM()).f,original:e.getAttribute('transform')||''}));
 for(const c of controls)c.original=c.e?.getAttribute('transform')||'';
 const labels=el('g',{'font-family':'Han','font-size':28,fill:'#59645F'},root);
 for(const st of staffs)st.labelNode=el('text',{x:350,'text-anchor':'end','data-staff':st.id},labels),st.labelNode.textContent=st.label;
 // Original first-system labels scroll out; fixed labels below own the identity.
 for(const x of world.querySelectorAll('.label,.labelAbbr,.mNum'))x.style.display='none';
 const nav=el('g',{'font-family':'Han','font-weight':400,class:'structural-navigation'},root);
 const setNavigation=markup=>{nav.innerHTML=(markup||'').replaceAll('nav-header-',prefix+'nav-header-')};
 const movementCorner=el('text',{x:72,y:64,'font-family':'Han','font-size':36,'font-weight':400,fill:'#59645F',class:'movement-corner'},root);movementCorner.textContent=S.movement_label||'';
 const qq=x=>Array.isArray(x)?x[0]/x[1]:+x;
 const sharedInk=new Map();for(const[id,n]of notes){const chord=n?.closest('g.chord');if(chord){if(!sharedInk.has(chord))sharedInk.set(chord,[]);sharedInk.get(chord).push(id)}}
 const noteChords=new Map();for(const[ch,ids]of sharedInk)for(const id of ids)noteChords.set(id,ch);
 let prev=[],lastDy={},prevChords=new Set();
 const referenceSlots=new Map(),labelSlots=new Map(),smooth=x=>{x=Math.max(0,Math.min(1,x));return x*x*(3-2*x)};
 window.draw=F=>{
  const weights=F.weights,dy={},reserved=components.map(c=>Math.sqrt(Math.max(...c.rows.map(r=>weights[r.id]||0))));
  const referenceRows=(S.guide_payload?.native_comparisons||[]).filter(c=>c.placement!=='sidebar').map(c=>({c,alpha:smooth((F.seconds-c.from)/.6)*(1-smooth((F.seconds-c.to)/.35))*(weights[c.anchor_staff]||0),component:components.findIndex(v=>v.rows.some(s=>s.id===c.anchor_staff)),nativeHeight:c.native_height??c.height/.06}));
  const rawLabelRows=(S.guide_payload?.label_bands||[]).map(b=>({...b,alpha:(()=>{const u=Math.max(0,Math.min(1,(F.seconds-b.from+4)/4,(b.to+4-F.seconds)/4));return u*u*u*(10+u*(-15+6*u))})()*Math.sqrt(weights[b.staff]||0),component:components.findIndex(c=>c.rows.some(r=>r.id===b.staff))}));
  const labelRows=packCompactLabelRows(rawLabelRows,F.seconds),labelPadding=labelRows.reduce((n,b)=>n+b.effective_height,0);
  const referenceNative=referenceRows.reduce((sum,r)=>sum+(r.component>=0?(r.c.fixed_display_scale?0:r.nativeHeight)*r.alpha:0),0),referencePadding=referenceRows.reduce((sum,r)=>sum+(r.component>=0?((r.c.row_padding_px??85)+(r.c.fixed_display_scale?r.nativeHeight*r.c.fixed_display_scale:0))*r.alpha:0),0);
  const total=components.reduce((sum,c,i)=>sum+(c.bottom-c.top+240)*reserved[i],0),scale=Math.min(.22,Math.max(800,1640-referencePadding-labelPadding)/Math.max(1,total+referenceNative));let cursor=0;referenceSlots.clear();labelSlots.clear();
  for(let i=0;i<components.length;i++){
   const c=components[i],insert=side=>{for(const band of labelRows.filter(b=>b.component===i&&b.effective_height>0&&(b.side||'below')===side)){
    for(const entry of band.aliases){const v=entry.band;labelSlots.set(v.staff+':'+(v.side||'below'),{y:100+cursor*scale+entry.offset,height:v.effective_height,row_height:v.row_height||64,alpha:v.slot_alpha,slot_offsets:v.slot_offsets});}
    cursor+=band.effective_height/scale;
   }};
   insert('above');const h=c.bottom-c.top,w=reserved[i],center=cursor+h*w/2;for(const row of c.rows)dy[row.id]=center-(c.top+c.bottom)/2;cursor+=(h+240)*w;insert('below');
   for(const row of referenceRows.filter(r=>r.component===i)){const height=(row.nativeHeight*(row.c.fixed_display_scale||scale)+(row.c.row_padding_px??85))*row.alpha;referenceSlots.set(row.c.id,{y:100+cursor*scale+(row.c.row_inset_px??30),alpha:row.alpha,height});cursor+=height/scale;}
  }
  verticalAudit={seconds:F.seconds,scale,label_padding:labelPadding,legacy_label_padding:rawLabelRows.reduce((n,b)=>n+(b.legacy_height??b.height)*b.alpha,0),reference_padding:referencePadding,shared_corridors:labelRows.filter(b=>b.aliases.length>1&&b.effective_height>0).map(b=>({height:b.effective_height,staves:b.aliases.map(a=>a.band.staff)})),slots:[...labelSlots].map(([key,v])=>({key,...v}))};
  lastDy=dy;const offset=100;world.setAttribute('transform',`translate(${1344-F.x*scale+(F.score_offset||0)} ${offset}) scale(${scale})`);
  let verticalChanged=false;
  for(const st of staffs){const w=weights[st.id]||0;if(st.lastWeight!==w||st.lastDy!==(dy[st.id]||0)){verticalChanged=true;for(const g of st.groups){g.style.opacity=w;g.setAttribute('transform',`translate(0 ${dy[st.id]||0}) ${g.dataset.originalTransform}`)}st.lastWeight=w;st.lastDy=dy[st.id]||0;}st.labelNode.setAttribute('y',(st.y+(dy[st.id]||0))*scale+offset+10);st.labelNode.style.opacity=w;}
  if(verticalChanged){
  for(const c of controls)if(c.e&&c.staves.length&&!c.e.closest('g.staff')){c.e.style.opacity=Math.max(...c.staves.map(id=>weights[id]||0));c.e.setAttribute('transform',`translate(0 ${dy[c.staves[0]]||0}) ${c.original}`);}
  for(const item of generated){const candidates=staffs.filter(st=>st.y>=item.top-400&&st.y<=item.bottom+400),presence=1-candidates.reduce((p,st)=>p*(1-(weights[st.id]||0)),1);const one=candidates.reduce((sum,st,i)=>sum+(weights[st.id]||0)*candidates.reduce((p,s,j)=>p*(i===j?1:1-(weights[s.id]||0)),1),0);item.e.style.opacity=item.isBracket?Math.max(0,presence-one):presence;if(presence>1e-9&&item.bottom-item.top>1){const edge=(rows,sign)=>{let remaining=1,sum=0;for(const st of rows){const p=remaining*(weights[st.id]||0);sum+=p*(st.y+dy[st.id]+sign*st.height/2);remaining*=1-(weights[st.id]||0)}return sum/presence};const a=edge(candidates,-1),b=edge([...candidates].reverse(),1),k=(b-a)/(item.bottom-item.top);item.e.setAttribute('transform',`matrix(1 0 0 ${k} 0 ${a-k*item.top+(k-1)*item.parentY}) ${item.original}`);}}
  }
  // Keep immediate-neighbour measures mounted for ties and spanning controls.
  const left=F.x-(1344-380)/scale,right=F.x+(3730-1344)/scale;
  for(let i=0;i<measures.length;i++){const m=measures[i];if(m.e){const show=(m.x+m.width*2>=left&&m.x-m.width<=right)?'':'none';if(m.e.style.display!==show)m.e.style.display=show;}}
  for(const id of prev){const n=notes.get(id);if(n){n.style.color='';n.style.fill='';}}
  prev=Object.keys(F.highlights);
  for(const[id,h]of Object.entries(F.highlights)){const n=notes.get(id);if(!n)continue;const rgb=[1,3,5].map(i=>Math.round(parseInt(h.color.slice(i,i+2),16)*h.weight));n.style.color=n.style.fill=`rgb(${rgb.join(',')})`;}
  const nowChords=new Set(Object.keys(F.highlights).map(id=>noteChords.get(id)).filter(Boolean));
  for(const chord of new Set([...prevChords,...nowChords])){const ids=sharedInk.get(chord);const h=ids.map(id=>F.highlights[id]).filter(Boolean).sort((a,b)=>b.weight-a.weight)[0];const color=h?'rgb('+[1,3,5].map(i=>Math.round(parseInt(h.color.slice(i,i+2),16)*h.weight)).join(',')+')':'';for(const c of chord.children)if(c.classList.contains('stem')||c.classList.contains('flag')||c.classList.contains('dots'))c.style.color=c.style.fill=color;}
  prevChords=nowChords;
  if(F.navigation!==undefined)setNavigation(F.navigation);
 };
 window.cover=F=>{
  if(S.cover_layout==='paper'){
   const styles=[...root.querySelectorAll('style')].map(x=>x.cloneNode(true));root.setAttribute('viewBox',`0 0 ${S.width} ${S.height}`);root.replaceChildren();for(const s of styles)root.append(s);el('style',{},root).textContent=S.fonts+'text{font-family:Han,serif}';el('rect',{width:S.width,height:S.height,fill:'#FAF8F1'},root);
   const wide=S.width===3840,margin=wide?220:170,blue='#287D9F',ink='#282B29',words=S.cover_words;
   const txt=(x,y,str,size,weight,color,spacing=0,anchor='start')=>{const n=el('text',{x,y,'font-size':size,'font-weight':weight,fill:color,'letter-spacing':spacing,'text-anchor':anchor},root);n.textContent=str;return n;};
   txt(margin,210,words.composer_en,43,400,'#59645F',9);
   txt(margin-6,wide?555:560,words.composer_zh,wide?188:176,500,ink,12);
   txt(margin-10,wide?880:858,S.work.title,wide?267:224,500,ink,3);
   txt(margin-3,1090,'曲谱同步',wide?144:136,500,blue,10);
   txt(wide?1040:940,1045,words.performer_zh,wide?65:60,400,ink,8);
   txt(wide?1040:940,1138,words.ensemble_zh,wide?49:46,400,'#626A63',5);
   const cx=wide?3000:2220;
   if(words.work_type_en)txt(cx,wide?380:450,words.work_type_en,wide?34:32,400,blue,8,'middle');
   const number=txt(cx,1000,S.number,wide?730:640,300,blue,wide?-20:-18,'middle');
   const maxNumberWidth=wide?920:820;
   if(number.getComputedTextLength()>maxNumberWidth)number.setAttribute('font-size',+number.getAttribute('font-size')*maxNumberWidth/number.getComputedTextLength());
   const defs=el('defs',{},root);for(const d of [...parsed.querySelectorAll('defs')])defs.append(d.cloneNode(true));
   const native=el('g',{id:worldId,color:ink},root);
   for(const c of [...inner.children])if(c.tagName!=='defs')native.append(document.importNode(c,true));
   const nodes=new Map([...native.querySelectorAll('[id]')].map(n=>[n.id,n]));
   const phrase=S.geometry.measures.filter(m=>S.cover_selection.measures.includes(m.svg_id)),selected=S.cover_selection.staves.map(id=>staffs.find(s=>s.id===id)),selectedIds=new Set(S.cover_selection.staves),phraseIds=new Set(phrase.map(m=>nativeId(m.svg_id)));
   for(const m of S.geometry.measures){const n=nodes.get(nativeId(m.svg_id));if(n)n.style.display=phraseIds.has(n.id)?'':'none';}
   for(const st of staffs)if(!selectedIds.has(st.id))for(const id of st.svg_ids){const n=nodes.get(nativeId(id));if(n)n.style.display='none';}
   for(const c of controls){const n=nodes.get(nativeId(c.svg_id));if(n&&c.staves.length&&!c.staves.some(id=>selectedIds.has(id)))n.style.display='none';}
   for(const n of native.querySelectorAll('.label,.labelAbbr,.mNum'))n.style.display='none';
   for(const[id,h]of Object.entries(F.highlights)){
    const geo=S.geometry.notes.find(n=>n.id===id),n=geo&&nodes.get(nativeId(geo.svg_id));if(!n)continue;
    const rgb=[1,3,5].map(i=>Math.round(parseInt(h.color.slice(i,i+2),16)*h.weight));const color=`rgb(${rgb.join(',')})`;n.style.color=n.style.fill=color;
    const chord=n.closest('g.chord');if(chord)for(const c of chord.children)if(c.classList.contains('stem')||c.classList.contains('flag')||c.classList.contains('dots'))c.style.color=c.style.fill=color;
   }
   const baseX=wide?480:425,width=S.width-margin-baseX,left=phrase[0].x-900,right=phrase.at(-1).x+phrase.at(-1).width;let scale=width/(right-left);
   const rows=[],bounds=n=>{const b=n.getBBox(),m=native.getCTM().inverse().multiply(n.getCTM());return{top:b.y*m.d+m.f,bottom:(b.y+b.height)*m.d+m.f};};
   for(let i=0;i<selected.length;i++){
    const st=selected[i],boxes=[];
    for(const id of st.svg_ids){const n=nodes.get(nativeId(id));if(n&&phraseIds.has(n.closest('g.measure')?.id))boxes.push(bounds(n));}
    for(const c of controls){const n=nodes.get(nativeId(c.svg_id));if(n&&c.staves.includes(st.id)&&phraseIds.has(n.closest('g.measure')?.id)&&!n.closest('g.staff'))boxes.push(bounds(n));}
    const top=Math.min(...boxes.map(b=>b.top)),bottom=Math.max(...boxes.map(b=>b.bottom));rows.push({st,top,bottom});
   }
   defs.append(native);
   // Match the reference's three aligned, horizontally flowing rows. Each row
   // uses the real native score; clipping never substitutes or re-draws notes.
   const bandTop=1210,bandBottom=1933,totalNativeHeight=rows.reduce((sum,r)=>sum+r.bottom-r.top,0);
   scale=Math.min(scale,(bandBottom-bandTop-64)/totalNativeHeight);
   const usedWidth=(right-left)*scale,x=baseX+(width-usedWidth)/2;
   const spare=bandBottom-bandTop-totalNativeHeight*scale,gaps=Math.max(0,rows.length-1),gap=gaps?Math.min(90,spare/gaps):0;
   let rowTop=bandTop+(spare-gap*gaps)/2;const rowGroups=[];
   for(let i=0;i<rows.length;i++){
    const {st,top,bottom}=rows[i],dy=rowTop-top*scale,height=(bottom-top)*scale;
    const clip=el('clipPath',{id:`reference-row-${i}`},defs);el('rect',{x,y:rowTop-10,width:usedWidth,height:height+20},clip);
    const g=el('g',{'clip-path':`url(#reference-row-${i})`},root);el('use',{href:'#'+worldId,transform:`translate(${x-left*scale} ${dy}) scale(${scale})`},g);rowGroups.push(g);
    txt(margin,st.y*scale+dy+15,st.label,wide?35:31,400,'#737C75');
    rowTop+=height+gap;
   }
   const line=x+(F.x-left)*scale,playhead=el('path',{d:`M${line} 1218V1937`,stroke:blue,'stroke-width':4},root);rowGroups[0].before(playhead);
   el('path',{d:`M${margin} 1960H${S.width-margin}`,stroke:'#CBD2C9','stroke-width':2},root);el('path',{d:`M${margin} 1975H${S.width-margin}`,stroke:'#DFE2D9','stroke-width':2},root);
   txt(margin,2075,words.performer_en,37,400,'#4E5B53',5);
   txt(S.width-margin,2075,words.ensemble_en,wide?33:28,400,'#727C74',3,'end');
   return new XMLSerializer().serializeToString(root);
  }
  const nativeStyles=[...root.querySelectorAll('style')].map(x=>x.cloneNode(true));root.setAttribute('viewBox',`0 0 ${S.width} ${S.height}`);root.replaceChildren();for(const style of nativeStyles)root.append(style);el('style',{},root).textContent=S.fonts+'text{font-family:Han,serif}';el('rect',{width:S.width,height:S.height,fill:'#FAF8F1'},root);
  const wide=S.width===3840,margin=wide?220:180,ink='#282B29',blue='#287D9F';
  const text=(x,y,value,size,weight=400,color=ink,anchor='start')=>{const t=el('text',{x,y,'font-size':size,'font-weight':weight,fill:color,'text-anchor':anchor},root);t.textContent=value;return t;};
  text(margin,215,S.work.composer||'',wide?65:60,400,'#59645F');
  const title=text(margin-6,wide?590:555,S.work.title||'',wide?244:218,500);
  if(title.getComputedTextLength()>(wide?2600:1910))title.setAttribute('font-size',+(title.getAttribute('font-size'))*(wide?2600:1910)/title.getComputedTextLength());
  if(S.number)text(S.width-margin,wide?585:550,S.number,wide?248:220,300,blue,'end');
  text(margin,wide?885:850,'曲谱同步',wide?176:164,500,blue);
  for(const d of [...parsed.querySelectorAll('defs')])root.append(d.cloneNode(true));
  if(S.cover_native){
   const music=el('g',{id:worldId,color:'black'},root);
   for(const c of [...inner.children])if(c.tagName!=='defs')music.append(document.importNode(c,true));
   for(const n of music.querySelectorAll('.mNum'))n.remove();
   const byId=new Map([...music.querySelectorAll('[id]')].map(e=>[e.id,e]));
   for(const[id,h]of Object.entries(F.highlights)){
    const geom=S.geometry.notes.find(n=>n.id===id),n=geom&&byId.get(nativeId(geom.svg_id));if(!n)continue;
    const rgb=[1,3,5].map(i=>Math.round(parseInt(h.color.slice(i,i+2),16)*h.weight));const color=`rgb(${rgb.join(',')})`;n.style.color=n.style.fill=color;
    const chord=n.closest('g.chord');if(chord)for(const c of chord.children)if(c.classList.contains('stem')||c.classList.contains('flag')||c.classList.contains('dots'))c.style.color=c.style.fill=color;
   }
   const bb=music.getBBox(),top=wide?1030:965,areaHeight=wide?850:965,available=S.width-2*margin;
   const sc=Math.min(available/bb.width,areaHeight/bb.height),x=margin+(available-bb.width*sc)/2,y=top+(areaHeight-bb.height*sc)/2;
   music.setAttribute('transform',`translate(${x-bb.x*sc} ${y-bb.y*sc}) scale(${sc})`);
   const hits=Object.keys(F.highlights).map(id=>S.geometry.notes.find(n=>n.id===id)).filter(Boolean).map(n=>byId.get(nativeId(n.svg_id))?.querySelector('.notehead')).filter(Boolean).map(n=>{const b=n.getBBox(),m=music.getCTM().inverse().multiply(n.getCTM());return{x:(b.x+b.width/2)*m.a+m.e,y:(b.y+b.height/2)*m.d+m.f};});
   if(hits.length){const xs=hits.map(n=>n.x).sort((a,b)=>a-b),line=x+(xs[Math.floor(xs.length/2)]-bb.x)*sc;const playhead=el('line',{x1:line,x2:line,y1:y+(Math.min(...hits.map(n=>n.y))-bb.y)*sc-28,y2:y+(Math.max(...hits.map(n=>n.y))-bb.y)*sc+28,stroke:blue,'stroke-width':4},root);music.before(playhead);}
   text(margin,2035,S.work.performer||'',wide?60:52,400,'#59645F');text(S.width-margin,2035,S.work.ensemble||'',wide?60:52,400,'#59645F','end');
   return new XMLSerializer().serializeToString(root);
  }
  const cw=world.cloneNode(true);root.append(cw);cw.setAttribute('transform','');
  const coverNodes=new Map([...cw.querySelectorAll('[id]')].map(e=>[e.id,e]));
  const selection=S.cover_selection||{},phrase=S.geometry.measures.filter(m=>(selection.measures||S.geometry.measures.slice(0,4).map(x=>x.svg_id)).includes(m.svg_id));
  const active=staffs.filter(s=>(F.weights[s.id]||0)>.5),chosen=selection.staves?selection.staves.map(id=>staffs.find(s=>s.id===id)):active.slice(0,3);
  if(!phrase.length||chosen.some(x=>!x)||!chosen.length)throw Error('Cover requires an actual excerpt and existing staves');
  const chosenIds=new Set(chosen.map(s=>s.id)),phraseIds=new Set(phrase.map(m=>nativeId(m.svg_id)));
  for(const m of S.geometry.measures){const e=coverNodes.get(nativeId(m.svg_id));if(e)e.style.display=phraseIds.has(e.id)?'':'none';}
  for(const st of staffs)for(const id of st.svg_ids){const g=coverNodes.get(nativeId(id));if(g){g.style.opacity=1;g.style.display=chosenIds.has(st.id)?'':'none';g.setAttribute('transform',g.dataset.originalTransform||'');}}
  // Reflow whole native rows, preserving the excerpt's noteheads, beams and controls.
  // Full-orchestra system bars cannot span a three-staff excerpt.
  for(const e of [...cw.querySelectorAll('g.grpSym,g.barLine>path,g.system>path')])if(!e.closest('g.staff'))e.remove();
  for(const c of controls){const e=coverNodes.get(nativeId(c.svg_id));if(!e)continue;e.setAttribute('transform',c.original||'');e.style.opacity=1;if(c.staves.length&&!c.staves.every(id=>chosenIds.has(id)))e.style.display='none';}
  const inPhrase=e=>phraseIds.has(e.closest('g.measure')?.id);
  const bbox=e=>{const b=e.getBBox(),m=cw.getCTM().inverse().multiply(e.getCTM());return {top:b.y*m.d+m.f,bottom:(b.y+b.height)*m.d+m.f};};
  let cursor=0;const rows=[];
  for(const st of chosen){
   const nodes=st.svg_ids.map(id=>coverNodes.get(nativeId(id))).filter(e=>e&&inPhrase(e));
   const extra=controls.filter(c=>c.staves.length===1&&c.staves[0]===st.id).map(c=>coverNodes.get(nativeId(c.svg_id))).filter(e=>e&&inPhrase(e)&&!e.closest('g.staff'));
   const boxes=[...nodes,...extra].map(bbox),top=Math.min(...boxes.map(b=>b.top)),bottom=Math.max(...boxes.map(b=>b.bottom));
   if(!Number.isFinite(top)||bottom<=top)throw Error('Invalid cover staff extent '+st.id);
   const dy=cursor-top;
   for(const n of nodes)n.setAttribute('transform',`translate(0 ${dy}) ${n.dataset.originalTransform||''}`);
   for(const n of extra)n.setAttribute('transform',`translate(0 ${dy}) ${n.getAttribute('transform')||''}`);
   rows.push({staff:st,center:st.y+dy,top:cursor,bottom:cursor+bottom-top});cursor+=bottom-top+550;
  }
  const left=phrase[0].x,right=phrase.at(-1).x+phrase.at(-1).width,scoreTop=wide?1090:1060,scoreHeight=wide?760:790,labelWidth=wide?250:230;
  const scoreLeft=margin+labelWidth,available=S.width-margin-scoreLeft;
  const sc=Math.min(available/(right-left),scoreHeight/Math.max(1,cursor-550));
  const usedW=(right-left)*sc,usedH=(cursor-550)*sc,x0=scoreLeft+(available-usedW)/2,y0=scoreTop+(scoreHeight-usedH)/2;
  cw.setAttribute('transform',`translate(${x0-left*sc} ${y0}) scale(${sc})`);
  for(const row of rows)text(margin,y0+row.center*sc+13,row.staff.label,wide?48:44,400,'#59645F');
  const line=x0+(F.x-left)*sc;
  if(line>=x0&&line<=x0+usedW){const playhead=el('line',{x1:line,x2:line,y1:y0-24,y2:y0+usedH+24,stroke:blue,'stroke-width':4},cw.parentNode);cw.before(playhead);}
  text(margin,2035,S.work.performer||'',wide?60:52,400,'#59645F');
  text(S.width-margin,2035,S.work.ensemble||'',wide?60:52,400,'#59645F','end');
  return new XMLSerializer().serializeToString(root);
 };
 window.ready=true;return {root,draw:window.draw,cover:window.cover,background,readingLine,scoreClip,labels,nav,movementCorner,setNavigation,referenceSlots,labelSlots,verticalComponents:components.map(c=>c.rows.map(r=>r.id)),verticalLayoutAudit:()=>verticalAudit};
}
try{
 chromeLog=fs.openSync(out+'.chrome.log','a');chrome=spawn(chromePath,['--headless','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-extensions','--force-color-profile=srgb','about:blank'],{stdio:['ignore','ignore',chromeLog]});chrome.on('exit',(code,signal)=>{process.stderr.write(JSON.stringify({owned_chromium_exit:true,code,signal,closing:browserClosing})+'\n');});
 let endpoint;for(let i=0;i<300;i++){const p=path.join(profile,'DevToolsActivePort');if(fs.existsSync(p)){const [port,url]=fs.readFileSync(p,'utf8').trim().split('\n');if(url){endpoint=`ws://127.0.0.1:${port}${url}`;break;}}await delay(50);}if(!endpoint)throw Error('Chromium start failed');
 ws=new WebSocket(endpoint);await once(ws,'open');ws.addEventListener('close',ev=>{if(!browserClosing)process.stderr.write(JSON.stringify({cdp_disconnected:true,code:ev.code,reason:ev.reason})+'\n');for(const p of pending.values())p.reject(Error('Owned Chromium disconnected'));pending.clear();});ws.addEventListener('message',ev=>{const m=JSON.parse(ev.data);if(m.method==='Runtime.consoleAPICalled'&&m.params?.args?.[0]?.value==='__GUIDE_PREFLIGHT__')process.stderr.write((m.params.args[1]?.value||'')+'\n');const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}});
 const target=await call('Target.createTarget',{url:'about:blank'}),session=await call('Target.attachToTarget',{targetId:target.targetId,flatten:true});const send=(m,p)=>call(m,p,session.sessionId);
 await send('Runtime.enable');
 const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails){if(spec.route_diagnostic_output){await writeRemoteDiagnostic(send,spec.route_diagnostic_output,'window.guideRouteDiagnostics');}throw Error(JSON.stringify(r.exceptionDetails));}return r.result.value;};
 const auditFonts=async()=>{
  if(!spec.font_audit_output)return;
  await send('DOM.enable');await send('CSS.enable');const doc=await send('DOM.getDocument');
  const selector=spec.font_audit_selector||(mode==='cover'?'body>svg text,body>svg tspan':'body>svg>g[font-family="Han"] text');
  const ids=await send('DOM.querySelectorAll',{nodeId:doc.root.nodeId,selector});const rows=[];
  for(const nodeId of ids.nodeIds){const html=await send('DOM.getOuterHTML',{nodeId}),fonts=await send('CSS.getPlatformFontsForNode',{nodeId});rows.push({element:html.outerHTML,fonts:fonts.fonts});}
  fs.writeFileSync(spec.font_audit_output,JSON.stringify(rows,null,2));
 };
 if(spec.transport_probe){await evaluate(`window.transportProbe={entries:Array.from({length:40},(_,i)=>({index:i,text:'谱🌿'.repeat(131073)}))};true`);await writeRemoteDiagnostic(send,out,'window.transportProbe');}else{
 await send('Emulation.setDeviceMetricsOverride',{width:spec.width,height:spec.height,deviceScaleFactor:1,mobile:false});await evaluate(`document.body.style.cssText='margin:0;background:#FAF8F1;overflow:hidden';window.spec=${JSON.stringify(spec)};window.packCompactLabelRows=${packCompactLabelRows.toString()};window.sceneCode=${sceneCode.toString()};window.actors=(window.spec.scenes||[window.spec]).map(s=>window.sceneCode({...s,width:window.spec.width,height:window.spec.height}));if(window.spec.scenes)window.actors.forEach((a,i)=>{a.background.style.display=i?'none':'';a.readingLine.style.display=i?'none':''});window.drawFrame=f=>{if(f.actors){for(const a of window.actors){a.scoreClip.style.opacity=0;a.labels.style.opacity=0;a.nav.style.opacity=0;a.movementCorner.style.opacity=0;if(a.vocalLayer)a.vocalLayer.style.opacity=0}for(const p of f.actors){const a=window.actors[p.scene];a.draw({...p.state,score_offset:p.offset||0});a.scoreClip.style.opacity=a.labels.style.opacity=p.opacity;a.movementCorner.style.opacity=p.title_opacity??p.opacity;if(a.vocalLayer)a.vocalLayer.style.opacity=p.opacity}window.actors[0].setNavigation(f.navigation);window.actors[0].nav.style.opacity=1}else window.actors[0].draw(f)};document.fonts.ready`);
 await evaluate("Promise.all([document.fonts.load('30px Han'),document.fonts.load('300 30px Han'),document.fonts.load('500 30px Han')])");
 if(mode!=='cover')await evaluate(`window.openingState=${openingState.toString()};window.installScoreLocators=${installScoreLocators.toString()};window.installStaffSignatures=${installStaffSignatures.toString()};window.actors.forEach((a,i)=>{const s=(window.spec.scenes||[window.spec])[i];a.locators=window.installScoreLocators(a,s);a.signatures=window.installStaffSignatures(a,s);const native=a.draw;a.draw=f=>{const presented=window.openingState(f,s.presentation);native(presented);a.signatures.draw(presented);a.locators.draw(presented);const loc=a.scoreClip.querySelector('.score-locators');if(loc)loc.style.opacity=s.presentation&&f.seconds<s.presentation.duration_seconds?Math.max(0,...Object.values(presented.weights)):1}});`);
 if(mode!=='cover')await evaluate(`window.installProgramVocals=${installProgramVocals.toString()};window.installVocalOverlay=${installVocalOverlay.toString()};window.createMaterialIndex=${createMaterialIndex.toString()};window.installMaterialRegions=${installMaterialRegions.toString()};window.actors.forEach((a,i)=>{const s=(window.spec.scenes||[window.spec])[i];if(s.vocalProgramme){a.vocalLayer=document.createElementNS('http://www.w3.org/2000/svg','g');a.root.append(a.vocalLayer);a.programme=window.installProgramVocals({...a,root:a.vocalLayer},s.vocalProgramme,window.installVocalOverlay);const native=a.draw;a.draw=f=>{const colors=a.programme.colorForStaff(f.seconds);const highlights=Object.fromEntries(Object.entries(f.highlights).map(([id,h])=>[id,s.vocal_note_staves?.[id]?{...h,color:colors[s.vocal_note_staves[id]]||h.color}:h]));native({...f,highlights});a.programme.draw(f)}}if(s.material_regions){a.materialRegions=window.installMaterialRegions(a,s,window.createMaterialIndex);const native=a.draw;a.draw=f=>{native(f);a.materialRegions.draw(f)}}});`);
 if(mode!=='cover'&&(spec.scenes||[spec]).some(s=>s.guide_payload))await evaluate(`window.installGuide=${installGuide.toString()};window.actors.forEach((a,i)=>{const s=(window.spec.scenes||[window.spec])[i];if(!s.guide_payload)return;a.guide=window.installGuide(a,s);const native=a.draw;a.drawScoreForLifetimeProbe=f=>native(f);a.draw=f=>{native(f);a.guide.draw(f)};});`);
 if(spec.layout_compilation_audit_output)fs.writeFileSync(spec.layout_compilation_audit_output,JSON.stringify(await evaluate('window.actors[0].guide.layoutPlan()'),null,2));
 if(spec.route_plan_output){const plan=await evaluate('window.actors[0].guide.routePlan()');if(!plan?.assignments?.length)throw Error('No complete route plan to freeze');fs.writeFileSync(spec.route_plan_output,JSON.stringify({schema:'verified-global-route-plan-1',fingerprint:spec.routing_plan_fingerprint,plan},null,2));}
 if(mode==='cover'){
  await evaluate(`window.draw(${JSON.stringify(spec.frames[0])})`);const svg=await evaluate(`window.cover(${JSON.stringify(spec.frames[0])})`);fs.writeFileSync(out,svg);await auditFonts();
  const im=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});const png=out.replace(/\.svg$/,'.png');fs.writeFileSync(png,Buffer.from(im.data,'base64'));
  const r=spawnSync('ffmpeg',['-v','error','-y','-i',png,'-q:v','2',out.replace(/\.svg$/,'.jpg')],{stdio:'inherit'});if(r.status!==0)throw Error('Cover JPG conversion failed');
 }else{
  if(mode==='video'){
   const encoding=spec.encoder==='hevc_nvenc'?['-c:v','hevc_nvenc','-preset','p7','-tune','hq','-profile:v','rext','-pix_fmt','yuv444p16le','-rc','vbr','-cq','16','-b:v','0','-maxrate','25M','-bufsize','50M','-tag:v','hvc1','-threads:v','1']:spec.final?['-c:v','libx265','-preset','medium','-crf','16','-profile:v','main444-10','-maxrate','16M','-bufsize','32M','-x265-params','pools=4:frame-threads=2:log-level=error:open-gop=0:cbqpoffs=-8:crqpoffs=-8','-pix_fmt','yuv444p10le','-tag:v','hvc1']:['-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p'];
   encoder=spawn('ffmpeg',['-nostdin','-v','error','-y','-filter_threads','1','-threads','1','-f','image2pipe','-vcodec','png','-framerate',String(spec.fps),'-i','pipe:0',...(spec.silent?[]:['-ss',String(spec.start_seconds),'-i',spec.audio]),'-t',String(spec.duration),'-map','0:v:0',...(spec.silent?['-an']:['-map','1:a:0','-c:a',spec.bits>24?'pcm_s32le':'alac',...(spec.bits>24?[]:['-sample_fmt',spec.bits<=16?'s16p':'s32p','-bits_per_raw_sample',String(spec.bits)])]),...encoding,'-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart','-movie_timescale',String(spec.movie_timescale||96000),out],{stdio:['pipe','ignore','inherit']});
  }
  // Long 4K jobs otherwise leave discarded SVG/DOM work to a very large
  // browser heap. Collect between frames, never during a draw or screenshot.
  const gcInterval=Number(spec.browser_gc_interval_frames??30);
  const visibilitySamples=[];let frameOrdinal=0;
  for(const f of spec.frames){const frameOutputs=spec.frame_outputs?.[frameOrdinal]||null;frameOrdinal++;if(frameOutputs&&mode!=='frame')throw Error('Named frame outputs require frame mode');if(cancelled)throw Error('Render cancelled');if(gcInterval>0&&(frameOrdinal-1)%gcInterval===0)await send('HeapProfiler.collectGarbage');await evaluate(spec.display_lifetime_probe_output?`window.actors[0].drawScoreForLifetimeProbe(${JSON.stringify(f)})`:`window.drawFrame(${JSON.stringify(f)})`);if(spec.display_lifetime_probe_output){visibilitySamples.push(await evaluate('window.actors[0].guide.lifetimeProbe('+JSON.stringify(f)+','+JSON.stringify(f.lifetime_probe)+')'));if(frameOrdinal%100===0)process.stdout.write(JSON.stringify({lifetime_probe_frames:frameOrdinal,total:spec.frames.length,seconds:f.seconds})+'\n');continue;}if(spec.paper_exit_audit_output){visibilitySamples.push({seconds:f.seconds,windows:await evaluate('window.actors[0].guide.paperExitProbe('+JSON.stringify(f.paper_probe_window_indices)+')')});continue;}if(spec.visibility_audit_output){const views=await evaluate('window.actors.map(a=>{const v=a.guide?.audit();return v?{native_comparisons:v.native_comparisons,...('+JSON.stringify(!!spec.visibility_audit_include_labels)+'?{motif_labels:v.motif_labels,visible_materials:v.visible_materials}:{}),...('+JSON.stringify(!!spec.visibility_audit_include_layout)+'?{layout:{connections:v.connections,joint_routing:v.joint_routing,vertical_layout:v.vertical_layout,compact_vertical_policy:v.compact_vertical_policy,band_lifetime_risks:v.band_lifetime_risks,reading_stage:v.reading_stage,text_bottom:v.text_bottom,cursor_topmost:v.cursor_topmost,motif_label_collisions:v.motif_label_collisions,motif_label_ink_collisions:v.motif_label_ink_collisions,unplaced_visible_labels:v.unplaced_visible_labels,unexplained_visible_materials:v.unexplained_visible_materials,motif_label_placements:undefined}}:{})}:null}).filter(Boolean)');visibilitySamples.push({seconds:f.seconds,...(spec.visibility_audit_include_layout?{layout:views.map(v=>v.layout)}:{}),figures:views.flatMap(v=>v.native_comparisons||[]),...(spec.visibility_audit_include_labels?{labels:views.flatMap(v=>v.motif_labels||[]),materials:views.flatMap(v=>v.visible_materials||[])}:{})});continue;}if(mode==='frame'){if(spec.native_dom_audit_output)fs.writeFileSync(spec.native_dom_audit_output,JSON.stringify(await evaluate(`Array.from(window.actors[0].scoreClip.querySelectorAll('*')).filter(n=>{const m=n.closest('g.measure');const st=n.closest('g.staff');return (!m||m.style.display!=='none')&&(!st||Number(st.style.opacity||1)>.01)}).map((n,i)=>({ordinal:i,paint:(()=>{const c=getComputedStyle(n);return[c.fill,c.stroke,c.opacity,c.visibility,c.filter,c.fontFamily,c.fontSize]})(),attrs:Object.fromEntries([...n.attributes].filter(a=>!(a.name==='style'&&!a.value)).map(a=>[a.name,a.value])),id:n.id,tag:n.tagName,cls:n.getAttribute('class'),transform:n.getAttribute('transform'),style:n.getAttribute('style'),text:n.tagName==='text'?n.textContent:null,bounds:n.id?(()=>{const b=n.getBBox(),m=n.getCTM();return{x:b.x,y:b.y,w:b.width,h:b.height,m:[m.a,m.b,m.c,m.d,m.e,m.f]}})():undefined}))`)));if(spec.presentation_audit_output||frameOutputs){const audit=JSON.stringify(await evaluate('window.actors.map(a=>({vocal:a.programme?.audit(),material:a.materialRegions?.audit(),locators:a.locators?.audit(),signatures:a.signatures?.audit(),guide:a.guide?.audit()}))'),null,2);for(const target of frameOutputs||[{layers:spec.presentation_audit_output}])fs.writeFileSync(target.layers,audit);}if(!frameOutputs||frameOrdinal===1)await auditFonts();if(spec.navigation_audit_output)fs.writeFileSync(spec.navigation_audit_output,await evaluate('window.actors[0].nav.outerHTML'));}const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,optimizeForSpeed:true});const png=Buffer.from(r.data,'base64');if(encoder){if(!encoder.stdin.write(png))await once(encoder.stdin,'drain');}else{for(const target of frameOutputs||[{image:out}])fs.writeFileSync(target.image,png);if(frameOutputs)process.stdout.write(JSON.stringify({seconds:f.seconds,outputs:frameOutputs.map(v=>v.image)})+'\n');}}
  if(spec.display_lifetime_probe_output)fs.writeFileSync(spec.display_lifetime_probe_output,JSON.stringify(visibilitySamples));
  if(spec.paper_exit_audit_output)fs.writeFileSync(spec.paper_exit_audit_output,JSON.stringify(visibilitySamples,null,2));
  if(spec.visibility_audit_output)fs.writeFileSync(spec.visibility_audit_output,JSON.stringify(visibilitySamples,null,2));
  if(encoder){encoder.stdin.end();const [code]=await once(encoder,'exit');if(code)throw Error('FFmpeg failed '+code);}
 }
}
}finally{
 browserClosing=true;
 if(encoder&&encoder.exitCode===null)encoder.kill();try{if(!cancelled&&ws?.readyState===WebSocket.OPEN)await call('Browser.close')}catch{}ws?.close();if(chrome&&chrome.exitCode===null)chrome.kill();await delay(200);fs.rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});if(chromeLog!==undefined)fs.closeSync(chromeLog);
}
