# 原生染色、长符号与开场

这些规则来自已交付项目的修正；作品的小节、音符身份、材料关系和录音锚点仍由各项目提供。不要复制某一作品的配色或局部更正到别的作品。

## 材料语义和完整墨迹

`material-regions.json` 的 `assignments/regions` 是音乐材料归属；可选 `display_assignments/display_regions` 表示经过核对的视觉补全。后者可以完成一个共享符杠或参考中实际使用的范围，但不应偷偷改写音乐分析。两套区间都用原生 world 坐标。

- 从参考视频学习材料位置和色彩关系，不复制其录音秒数或具体RGB。主题变体可通过 `semantic_families:{family_id:{members:[theme_id,…]}}` 保持同族关系，同时检查实际纸色背景上的可辨性。
- SVG `userSpaceOnUse` 属于受色节点的本地坐标。对五线、加线、共享符杠及连线，用节点CTM与world的关系转换渐变坐标；不要移动音符来补偿染色偏移。
- 同色音符共同拥有的符杠整体着色；相邻已归属颜色直接交接，不插黑色过渡。中间的无符干休止不应在符杠上打黑洞，但休止本身仍保留自己的归属。确有中性有音高成员时保留中性部分。
- 谱号、调号、拍号默认中性，不能因乐句边缘留白覆盖到它们而跟随前句变色。
- `spanner_anchors:{svg_id:{start:event_id,end:event_id}}` 绑定原生连线两端。同一语义族、全跨度连续被拥有的slur/tie可沿相邻材料分色；有空洞或跨不同族时不能仅凭两端染满。
- 人工核对的混合连线可提供 `spanner_ink_overrides:[{svg_id,class,staff,start,end,policy:"follow_material_intervals"}]`。身份或端点变化即报错，中性部分仍中性。
- 无时长文字/力度可通过 `point_control_anchors:{svg_id:{event_ids:[…]}}` 继承源音符归属；带 `endid/tstamp2` 的延长指示不能按起点强行染满。原生表情文字框在字体加载后按实际字形宽度补足，保留原高度和线宽。

这些可选字段由 `presentation_layers.py` 校验，并由 `layers/region_ink.mjs` 执行。`presentation_audit_output` 可记录坐标、共享符杠和连线归属，供有疑问的片段复核。

## 长符号的可见寿命

原生长弧线、渐强延长线和颤音可能挂在起始小节的SVG组下。按起始小节宽度加一两个邻居裁剪，会在尾端仍可见时把整个符号隐藏。

普通 `browser_render.mjs` 在字体与样式就绪后、所有小节尚挂载时，测量每个小节全部子墨迹的真实横向范围。每帧以该范围和实际world视窗（含 `score_offset`）决定是否保留父组。保留原生线形，直到整条符号滚出。仅按逻辑小节范围推算受影响重渲片段也会漏掉这种尾部。

可选spec字段 `visibility_inventory_output` 输出真实范围；`visibility_frame_audit_output` 记录逐帧可见控件与父组挂载状态；`visibility_audit_only` 可只执行状态计算。不要把几何候选数直接叫作可见错误数，因为部分控件可能被其他明确规则隐藏。该修正不替代导赏层自己的标签/连线寿命规则。

## 开头装饰音与可选前导

`camera.leading_grace_knots` 使用已对齐装饰音的真实起点和原生x位置补齐第一主音前的显示节点。音乐q轴、音频和音符时间不变；主音前没有装饰音时不介入。不要为了镜头限位跳过实际发声的倚音。

只有用户明确要求预留动画时间时，调用 `entrance.sampled_noise_prefix` 从实际录音中人工确认的无音乐区间采样底噪，写到新文件；原音频接在前导后逐样本保留。保存种子区间、采样数、交叉淡化和原PCM指纹，切勿把前导偏移写回alignment。

`entrance.make_delivery_frame` 按绝对输出帧生成开场状态：`source_time=max(0,delivery_time-prefix)`。动画先求出首尾完整布局，再插值屏幕位置与大小，避免每帧重算限位造成卡顿；动画结束留短暂停稳时间，再进入原录音。生成帧带 `delivery_entrance:true`，浏览器据此跳过已有 `presentation.json` 的另一轮开场；前导结束后不重新播放一轮声部展开。全程连续录音仍为默认行为，此接口不自动添加前导。

## 作品号封面

`cover.identifier:"opus"` 配合 `work.opus:"Op.18"` 使用阿拉伯作品号和同一行的小型 `Op.`。交响曲序号仍按原罗马数字逻辑处理。

可选 `cover.identifier_layout` 按 `16x9/4x3` 配置 `width,prefix_size,number_size,gap,tracking,baseline,heading_y,offset_y`，单位为2160高画布像素。`offset_y` 同时移动作品号和上方作品名称小字，二者的内部间距不变；字号和坐标仍须按当前版面判断。另存新版本供比较，不覆盖已有封面。
