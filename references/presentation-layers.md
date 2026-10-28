# 可选唱词栏与谱面材料染色

两层已接入正常 `preview`、`frame`、`render_program` 和分块渲染。每乐章按自己的工作目录自动发现；不靠“第四乐章”、作品名或固定声部ID触发。没有配置时保持普通滚动谱面。封面不安装这些层。

## 右侧文字栏

用途是与实际演唱同步的原文、译文和声部身份，不是自动生成导赏或滚动大段稿子。代码为 `scripts/layers/program_vocals.mjs`、`vocal_overlay.mjs`；载入/校验在 `score_sync/presentation_layers.py`。

在 `.score-sync/<movement>/vocals/` 提供：

- `timeline.json`：完整乐章的声部、句子、音节时段、连续唱段。
- `cohort-schedule.json`：完整乐章的精确齐唱分组、整栏出入与交接。
- `layout-schedule.json`：与上两者绑定的稳定位置、字号、完整句子占用高度。

保留生产协议字段 `de`/`zh`，分别表示原文/译文，**不要求德语或中文**。常用汉字和拉丁文字可直接使用；其他文字需确认随附字体覆盖，非BMP字符需先统一 Python/JS 字符索引。字体必须覆盖全部正文、译文、声部标签及主题短名。

### 时间与动画

- 所有秒数是**裁切后录音的乐章时间**，所有样本采用该乐章的采样率，独立于输出分块起点。禁止在每个chunk里重新归组或重新适配字号。
- 只将经音乐段落判断的连续下一句标为 `continuity_from_previous=true`，`preview_at` 必须等于上一句的实际起唱时刻。普通停顿可先以约1.2秒作候选，赋格中的较长间隔须结合句链、休止和段落判断；不得单凭全局秒数阈值串起不同段落。
- 下一句小、淡、不带译文；成为当前句时，位置、字号和颜色在同一段最长0.30秒的动画中变化。唱完后淡出，不长期挂着旧词。
- label沿完整连续唱段保留；有下一句时不随当前句消失。布局从完整段落预编译，避免每句上下跳动。
- 整栏从右侧滑入并遮盖原本全宽的谱面，退出时向右移、逐渐露出谱面。默认让首音节前约0.2秒完成入场，初始可用1.4秒提前量，但必须先核对人声起音，不能用提前动画掩盖对齐误差。
- 只有 `next.enter_start - current.exit_end >= 15` 秒，才允许两次整栏出入分开；否则合并面板窗口。最后一次退出不受“下一次”限制。窗口与内部声部唱段独立，禁止为保持整栏而延长已唱完的歌词。
- 持续音节的下方进度短线仅对至少1.2秒的实际连续发声段显示。默认阈值用于减少短音节闪烁，不可将跨休止的总跨度算作持续音。
- 声部保持各自颜色及左侧短竖标记。合并标签列出实际成员，原文/译文/起止/音节发声区间/后续句链都完全相同时才允许合并；不同译文分别显示。独唱与合唱由 `family` 明示，不能靠文字猜测。

### 数据协议与编译

`timeline.json` 顶层：`sample_rate`, `movement`, `source_hashes`, `unowned_notes`（可为空）, `lanes`。

每个lane：`id`（原生staff身份）、`label`、`color`（#RRGGBB）、`family`（solo/choir）、`runs`、`phrases`。

每个run：`id`, `staff`, `start`, `end`, `phrases`（句子ID列表）。每句：`id`, `staff`, `run_id`, `de`, `zh`, `start`, `end`, `start_sample`, `end_sample`, `start_q`, `end_q`, `continuity_from_previous`, `preview_at`（独立句为null）, `motion`, `segments`。`motion`含 `rise_seconds`、`clear_seconds`、`entrance_seconds`、`exit_seconds`；常用初始值分别为0.30、0.10、0.20、0.25，但不改动实际起音时刻。

每个segment：`source_lyric_event_id`, `text`, `start_char`, `end_char`（原文半开区间）, `start`, `end`, `sounding_intervals_samples`。如存在句级 `syllables`，同ID音节也必须携带实际发声区间。不要把相邻词或伴奏起音误当人声起音。译文由当前项目核对并采用用户指定版本；不随skill分发具体诗歌或译本。

准备 `panel-entries.json`，形如 `{"phrases":[{"id":"句ID","run_id":"runID","admit":1.0,"full":2.2}]}`，仅列整栏入场首批句子；`panel-presence.json` 含 `windows`，每个窗口含 `enter_start, enter_end, exit_start, exit_end`，均为严格递增的乐章秒数。结合上述15秒规则制作完整乐章的窗口。

```bash
.runtime/bin/python scripts/compile_vocals.py \
  --timeline /project/content/vocals/timeline.json \
  --entries /project/content/vocals/panel-entries.json \
  --presence /project/content/vocals/panel-presence.json \
  --output /project/.score-sync/movement-id/vocals
```

该入口移植完整句链齐唱判定，并提供保守的全段固定槽位编译器：尽量55px原文，按完整句/译文/预告所需高度选择字号；合并后保留代表声部原位置。**不是原项目所有密集段落的特制空间优化器**。超过容量应调整全段布局、审查实际帧，不能删词或缩短内容。也可直接提供经复核的生产 `layout-schedule.json`（支持 `stable_role_stages`、`reserve_keyframes`、交接布局），渲染器保留这些能力。

layout的每个cohort含 `id`, `de_size`, `phrase_layout`, `phases`。phrase_layout按句ID存 `de_line_count, zh_line_count, block_height, preview_height, preview_offset`。每个phase含 `id,start,end,de_size,zh_size,role_size,de_leading,zh_leading,top,height,width,slots`；slot含 `id,top,height,role_height`。坐标统一按3840×2160，右侧文本宽840，垂直范围150—1770。浏览器会核对实际换行与编译结果，不一致必须修正布局而非忽略错误。

## 谱面材料染色

在 `.score-sync/<movement>/material-regions.json` 提供：

```json
{
  "source_hashes": {},
  "x_shift": 0,
  "palette": {"theme_a": "#353BB5", "theme_b": "#737B16"},
  "short_names": {"theme_a": "主题甲", "theme_b": "主题乙"},
  "regions": [
    {"staff":"native-staff-id", "start_x":1000, "end_x":2000, "theme":"theme_a"}
  ],
  "assignments": {"native-note-event-id":"theme_a"},
  "shared_staff_neutral_intervals": [],
  "vocal_phrase_themes": []
}
```

例中的身份和坐标是占位说明，必须替换为当前谱面实际值，并补齐绑定。`x_shift=0`时区间直接使用原生world坐标；迁移旧数据时显式设置其坐标偏移，不能默认沿用其他工程的240。

`regions`控制五线谱及共有墨迹的材料区间，`assignments`控制每个音符的材料归属，**两者都要完成**；不能只按主题开头几个匹配音染色。逐声部通读完整乐句、变体、转交、延音和应答；同一材料跨乐器保持同色。只选择具有辨析价值的复杂段落，不自动全曲染色。

使用原生谱面本身染色，包括五线、加线、符头/符干/附点、连梁、休止及归属明确的表情，不加方框、不改几何或笔画宽度。共享声部同时存在多个材料时，无法明确归属的共有墨迹保留黑色，个别音符仍可独立赋色；原有 `fill=none` 保留。

静态材料色、正在发声的高亮色、蓝游标和人声部颜色是不同语义。挑选色差明显、纸色背景上可读的少量颜色；不要将材料色直接复用成人声颜色。高亮结束恢复材料底色。右栏继续按声部着色，必要时在label旁加主题短名：`vocal_phrase_themes=[{"phrase_id":"…","theme":"theme_a"}]`；合并成员主题不一致时不显示歧义标识。

## 输入绑定、冻结与检查

两个层的 `source_hashes` 都必须绑定本乐章的 `score.json`、`geometry.json`、`alignment.json`：

```json
{"score":{"path":"score.json","sha256":"实际文件SHA256"},
 "geometry":{"path":"geometry.json","sha256":"实际文件SHA256"},
 "alignment":{"path":"alignment.json","sha256":"实际文件SHA256"}}
```

路径相对于该 `.score-sync/<movement>/`，不得越出。唱词schedule/layout还分别绑定上游对象的规范JSON哈希（`vocal_schedule.digest`）。不要通过只改哈希掩盖谱源、歌词或对齐变更。

正常流程冻结指纹已递归包含这些JSON及模块代码；更改任一层会使旧批准失效。先检查首音节、长音、不同步换句、最多同时声部、连续/非连续句边界、整栏入退场、换章与分块边界，以及染色段首中尾和高亮退回底色。自动配色不等于音乐分析，分组通过不等于像素布局已经通过。

## 谱号、调号、移调名称、小节号和排练号

`scripts/compile_notation_labels.py` 从当前修订MusicXML/MXL与冻结演奏路线生成两个可选文件：

```bash
.runtime/bin/python scripts/compile_notation_labels.py \
  --movement-dir /project/.score-sync/movement-id \
  --score /project/derived/current.musicxml --interval 8
```

- `staff-signatures.json`：左侧label旁的小五线谱/谱号、八度记号、调号数量和升降号；明确存在移调信息时给名称加音高标签。复用本谱SVG字形轮廓，按实际演奏q更新，反复跳回时恢复源状态。不能把调号直接叫作某大调/小调。未声明谱号不猜高音谱号，特殊非传统调号需另作适配。缺少原生字形时报错，需从同一刻谱字体补齐，不能换字体凑符号。
- `score-locators.json`：谱面上方稀疏源小节数及原谱真实排练号；每8小节为起始密度，按最密声部布局下至少120px的估计间距裁减。排练号优先于重叠的小节号；没有原谱排练号则不创造。保留源小节、演奏次序和出现次数的区别，同一小节反复时仍显示相同源编号。

使用跨乐章累计编号的XML时，可在核对PDF后显式指定 `--number-offset`。不要套用其他作品的偏移。非数字/隐含小节不擅自补号。小节中间的排练号按其源拍位映射到原生横坐标，需与PDF核对。

两个文件均自动载入并参与冻结；移除相应可选文件即可关闭。谱号/调号/移调名称也可分别由 `staff-signatures.json.options` 的 `clef/key/transposition` 开关控制，编译时 `--without-clefs` 可只关谱号。小节号字号30、基线y=80、灰绿低对比；标签随谱面水平滑动和边缘淡入淡出，不调整声部间距、谱面缩放、蓝线或底部双导航。右栏自然遮住其下方的谱面定位标签。

原生声部标签带 `data-staff` 身份，所有人声声部左侧的小竖线由唱词模块按当前声部色绘制；无需另造标签或重新排版。小竖线随该声部谱面可见性变化，演唱时更醒目。

## 开场与换章

生产版开场权重渐显函数已移植。需要时在指定乐章工作目录增加 `presentation.json`，如 `{"duration_seconds":2,"initial_phase":0.1}`，仅控制既有声部权重的渐入，不改音频、横向位置、拍位或高亮时钟。实际时长由当前作品决定，不强制套用这个示例。原有乐章滑动交接继续由通用renderer控制；右侧人声栏随所属乐章一起淡出，谱面定位随父级遮罩和透明度过渡。
