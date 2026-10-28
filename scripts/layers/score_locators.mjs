export function installScoreLocators(actor, scene) {
  const data=scene.score_locators;
  if (!data) return {draw(){},audit(){return {enabled:false}}};
  const NS='http://www.w3.org/2000/svg';
  const world=actor.scoreClip.firstElementChild;
  if (!world) throw Error('Native score world required for locators');
  const layer=document.createElementNS(NS,'g');
  layer.setAttribute('class','score-locators');
  layer.setAttribute('font-family','Han');
  layer.setAttribute('font-size',data.font_size);
  layer.setAttribute('font-weight','400');
  layer.setAttribute('fill',data.color);
  layer.setAttribute('pointer-events','none');
  // Parent clip/opacity is shared with the score, including movement transitions.
  // Vocal paper overlays are later siblings and naturally occlude this layer.
  actor.scoreClip.append(layer);
  const rows=data.items.map(item=>{
    const node=document.createElementNS(NS,'text');
    node.textContent=item.text;
    node.setAttribute('text-anchor','middle');
    node.setAttribute('y',data.baseline_y);
    node.setAttribute('data-source-measure',String(item.source_index));
    node.setAttribute('data-occurrence',String(item.occurrence));
    node.style.display='none';layer.append(node);
    return {...item,node};
  });
  const smooth=x=>{x=Math.min(1,Math.max(0,x));return x*x*x*(10+x*(-15+6*x))};
  let last=[];
  function draw(){
    // consolidate() mutates the native SVG transform list and can change its
    // floating-point rasterization. Compose a separate matrix without touching it.
    const transforms=world.transform.baseVal;
    if (!transforms.numberOfItems) return;
    let matrix=new DOMMatrix();
    for(let i=0;i<transforms.numberOfItems;i++)matrix=matrix.multiply(transforms.getItem(i).matrix);
    last=[];
    for (const r of rows){
      const x=r.native_x*matrix.a+matrix.e;
      const opacity=data.opacity*smooth((x-data.left)/data.edge_fade_width)
        *smooth((data.right-x)/data.edge_fade_width);
      if (opacity<=1e-6){if(r.node.style.display!=='none')r.node.style.display='none';continue;}
      r.node.style.display='';r.node.setAttribute('x',x);r.node.setAttribute('opacity',opacity);
      last.push({id:r.id,text:r.text,x,y:data.baseline_y,opacity,
        source_index:r.source_index,occurrence:r.occurrence});
    }
  }
  return {draw,audit(){return {enabled:true,layout_mutations:false,baseline_y:data.baseline_y,visible:last}}};
}
