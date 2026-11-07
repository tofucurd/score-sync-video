# PDF 导赏、谱面标签与联动线

这是可选的导赏模式。普通曲谱和唱词仍走原渲染器；乐章目录存在 `guide.json` 时，视频自动选择 `scripts/browser_guide.mjs`。封面不安装导赏层。它移植了实际成片使用的增量右栏、紧凑标签、连线调度和原生谱例排版；新作品的文字、分析、材料身份与显示时间必须重新提供。

## 从文档到画面

1. 逐页阅读原 PDF，按句、图、图内标记和音符建立 `units` 账本。每项记录原文、页码、来源位置；不能用摘要替换未展示的原文，也不能添加没有来源的解释标签。编译器只验证已提供账本的覆盖，不能发现转录时遗漏的 PDF 内容。
2. 把图中的主题范围、和声、配器及比较关系绑定到当前 MusicXML 的事件身份。PDF 图里的内容要翻译成当前滚动谱上的染色、标签和连接关系，不默认把图截图贴进视频。跨作品的比较谱例须准备完整、可追溯的原生 SVG，不裁掉谱号、加线、力度或音符。
3. 按实际乐段安排 `stages`。相邻页面的共同内容使用同一 block ID，新增内容使用新 ID；不要因换页重刷相同位置的相同文字。音乐连续播放，阅读窗口可适当前后展开，但须贴近文档指示的音乐位置。重复讲解保留原文归属，不通过删除源内容解决重复或冲突。
4. 核对分析勘误并保留原文。修正乐器名称等错误应写 `errata`，说明理由；不要为了迁就错误文案移动音乐选段。双层导航的段落和名称也应依据当前文档，单独写入 `structure.json`，导赏编译器不会自动推断曲式。
5. 编译完整乐章后再出预览/分块。按用户需要检查代表性片段，不必为了小改动重新渲染整部视频。源谱、几何或 alignment 改变后，重新编译绑定数据。

## 编译入口

完成普通 `prepare` 和对齐后，准备 `guide-input.json`：

```bash
.runtime/bin/python scripts/compile_guide.py \
  --movement-dir /project/.score-sync/movement-id \
  --input /project/content/guide-input.json
```

默认输出 `<movement-dir>/guide.json`，可用 `--output` 指定位置。正常预览读取乐章目录下的文件。`source_hashes` 必须绑定该目录实际的 `score.json`、`geometry.json`、`alignment.json`。下面仅示意结构，省略号哈希和事件 ID 必须换成真实值：

```json
{
  "id": "listening-guide",
  "source_hashes": {
    "score": {"path": "score.json", "sha256": "…"},
    "geometry": {"path": "geometry.json", "sha256": "…"},
    "alignment": {"path": "alignment.json", "sha256": "…"}
  },
  "units": [
    {"id": "u1", "text": "主题甲持续发展。", "provenance": {"document": "guide.pdf", "page": 1}}
  ],
  "palette": {"subject": "#345678"},
  "labels": {"subject": "主题甲"},
  "blocks": [
    {"id": "paragraph", "unit_id": "u1", "display_ranges": [[0, 8]], "theme": "subject", "keywords": ["主题甲"]}
  ],
  "stages": [
    {"id": "opening", "from": 0, "to": 20, "blocks": ["paragraph"]}
  ],
  "spans": [
    {"id": "phrase", "staff": "strings", "ids": ["n1", "n2"], "theme": "subject", "q0": 4, "q1": 8, "label": "主题甲"}
  ],
  "cues": [
    {"at": 1, "block": "paragraph", "keyword": "主题甲", "target_id": "phrase"}
  ],
  "label_representatives": [
    {"target_id": "phrase", "from": 2.5, "to": 8.5}
  ],
  "incremental_sidebar": true,
  "stable_reading_blocks": true,
  "compact_vertical": true,
  "typography": {"body": 52, "leading": 1.37},
  "label_typography": {"sizes": {"phrase": 42}}
}
```

`from/to/at` 是裁切后录音的乐章绝对秒数；`q0/q1` 是展开演奏路线中的四分音符位置，不能混用。`ids` 使用 geometry 中的事件 ID，`staff` 是实际声部身份。反复演奏的同一源位置要绑定对应的 occurrence 事件，不能直接拿印刷小节数充当事件身份。

`display_ranges` 是原始 unit 文本的 Python Unicode 字符半开区间。`units[].errata` 使用 `{start,end,original,replacement,reason}`；编译后保留原始来源与展示文本，不把改写伪装成逐字引文。全文必须在显示 blocks 中覆盖；图形 unit 可由 span 的 `source_unit_ids` 列表或 native comparison 的 `source_unit_id` 表示。存在图形时同时保留图中文字对应的文字单元。重复展示保留各自 provenance。

`blocks[].kind` 控制字体类别，默认正文可显式写为 `body`；`typography` 中各 kind 的字号以 3840×2160 画布计。52px 是可用的正文起点，不是必须缩放到每一页的常数。`font_text` 会收集导赏正文、标签、速度及谱例文字用于字体子集。

## 文案、颜色与标签

- 增量右栏保留相同 block 的显示状态，新增段落独立进入；文字字号、位置和颜色应同步过渡。段落高度按实际字体和换行决定，不能只靠字数估算。
- 同一关键词在全篇沿用同一材料色，连线收回后也保留语义颜色，可降低强调强度但不能直接变黑。`palette/labels` 是共同身份来源；冲突的关键词色或音符归属会报错。
- 主谱使用完整原生墨迹染色，包含符头、符干、符梁、连音及相关谱线；共享符梁按成员和实际几何归属处理。局部渐变使用元素自身 CTM，避免平移后出现黑残片或色差。`x_shift` 默认 0，外部有偏移的几何必须显式声明。
- 材料颜色要彼此可辨，并避开播放高亮、蓝游标及人声身份颜色；不要凭空把中性材料加入某个主题。范围底色保持浅，不能靠加粗边框增强。谱面墨色应比底色清楚得多。
- 标签用常规字重的浅色字和实心材料色底，不加粗。`label_representatives` 选择这一画面/段落能说明颜色身份的代表位置，不要求每个重复片段都标；也不能让某种颜色整段没有名字。
- 标签固定在源谱位置并随谱面滚动，不能为避开蓝游标临时左右跳动。先在生命周期内求稳定位置，再复用；以实际音乐墨迹和小节号/速度文字作为障碍物。
- `compact_vertical` 启用按实际文字宽度、固定锚点、可用横向空隙和共同通道计算的紧凑排版；保持字号及指代距离，不通过无条件缩减安全区省高度。没有预制 label bands 时使用源谱附近的固定位置；复杂保留区可提供 `label_bands/label_space_decisions`，字段与运行时一致，不能套用另一作品的坐标。

## 连接线与显示寿命

`cues` 绑定右栏关键词到 `spans`；编译器按冻结 alignment 计算目标起止，将线从右栏逐渐画到谱面，退出时收回。默认 `connection_capacity_policy` 同时最多 2 个语义要点、3 个分支，可显式调整。先判断应展示哪些要点，再对重叠窗口统一分配路线，避免每条线各自寻找最短路径而相互穿越。

默认 `connection_timing_policy` 以目标起奏前约 0.8 秒画完、延展约 0.65 秒作为起点；实际窗口受文字是否存在、目标段落和容量限制。使用绝对时钟和全章 `routing_reference_frames`，跨 chunk 或倒序取帧不改变通道。声部上下移动时，端点和水平线跟随同一布局动画，不能切到新声部位置后再补画。蓝游标始终最后绘制。

标签提前显示时，连接线也应使用对应的扩展窗口；后面空闲且谱面尚未离开时可继续保留，不能无理由提前消失。`label_representatives` 可给出明确的 `display_from/display_to`，但这不自动证明无遮挡。需要自动延长时提供真实探针结果：

```json
{
  "display_lifetimes": {
    "source_hashes": {"score": {}, "geometry": {}, "alignment": {}},
    "fps": 60,
    "requests": [{"target_id": "phrase", "from": 1.5, "to": 10}],
    "samples": [
      {"seconds": 1.5, "target_id": "phrase", "label_safe": true, "route_safe": true, "source_visible": true}
    ]
  }
}
```

这是字段示意：哈希需完整，samples 要覆盖实际请求的逐帧范围，不能只填一个 true 伪造证据。连续安全前缀才允许提前；遇缺帧、遮挡、谱面出界、后继同材料或容量冲突即停止延长。保留原音乐/布局窗口，展示寿命不反向改变音乐身份。浏览器暴露 `layoutPlan/routePlan/lifetimeProbe/paperExitProbe` 供有需要的项目采集；编译器本身不启动浏览器。

## 对照谱例与和声

`native_comparisons` 接收已抽取并排好的原生 SVG。每项有 `id,source_unit_id,from,to,anchor_staff,theme,height,source_hashes,source_note_ids,svg,pairs`；`pairs` 是 `{ref_id,score_id}` 列表。图形须完整包含声明的 ID，绑定真实主谱音符。禁止脚本、外部资源和外部链接。不能依赖项目遗留的 `native_controls` 修补裁图；先把 SVG 准备正确。

比较谱例尽量靠近对应主谱、统一音符尺度；太小的引用可放右栏，与文案一起排版。用不同且可辨的浅范围框及连接线表达对应关系，不能让插入谱例挤出巨大空白。来源标题只用文档已有文字，不能新增“圈出的音符”等无来源说明。

复杂原生谱例位置、双向端口以及和声排版可直接在已编译 payload 上配置 `host_block`、`source_ports`、`harmony_anchors` 等字段，协议见 [runtime](../scripts/layers/guide_runtime.mjs)。这些是显式的底层布局接口，不是自动分析器。和声原始记号及位置仍保留；为了可读性调整展示，不能擅自改和声结论。

## 实现与边界

- [guide.py](../scripts/score_sync/guide.py)：来源、全文覆盖、颜色、目标、谱例及显示寿命编译；[guide_connections.py](../scripts/score_sync/guide_connections.py)：容量与全章路线参考。
- [guide_runtime.mjs](../scripts/layers/guide_runtime.mjs)：正文、标签、比较谱例、连接动画；[guide_layout.mjs](../scripts/layers/guide_layout.mjs)：紧凑行与共享通道；[guide_ink.mjs](../scripts/layers/guide_ink.mjs)：原生墨迹染色。
- [browser_guide.mjs](../scripts/browser_guide.mjs) 独立于普通 renderer；不执行输入文件携带的 JavaScript。当前导赏栏与唱词栏不能在同一乐章自动共存，冲突会报错。既有独立 `material-regions.json` 与导赏材料不一致时也会报错，先统一数据来源。
- 源绑定、schema 和代码测试不等于作品分析准确或视觉无碰撞。此次移植只做轻量检查，未在新包中重跑完整浏览器或远程成片。新作品的 PDF 解读、时机、原生谱例准备及实际画面适配仍由项目负责。

远程冻结、分块与复用规则见[远程渲染](remote-render.md)。公开包不含任何作品的 PDF、文字全文、图谱、录音、声部 ID 表、时间映射或服务器配置。
