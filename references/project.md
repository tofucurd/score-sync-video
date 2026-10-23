# 项目与审核接口

运行入口 `python scripts/score_sync.py COMMAND --project /path/project.json`。相对输入路径以配置目录为基准；所有生成物位于项目 `.score-sync` 和配置的 `output`。

```json
{
  "schema": 1,
  "work": {"title":"作品名称","composer":"作曲家","number":"","performer":"指挥","ensemble":"乐团"},
  "movements": [{"id":"m1","title":"第一乐章","score":"score.mxl","pdf":"original.pdf","audio":"performance.flac"}],
  "output":"output",
  "settings":{"preview_height":360,"final_height":2160,"fps":60,"chunk_seconds":30,"min_free_gib":25}
}
```

可选乐章属性：`audio_range:[start_seconds,end_seconds]` 指原文件解码后的片段；`source_route:[1,2,1,2,3]` 为实际演奏的一基原始小节序号；`anchors:[[score_q,recording_seconds],...]` 为已核查的谱位（四分音符单位）与本乐章所选音频中的相对时间。anchors也可指向相对JSON文件。所有定位依据由agent产生，不让无乐理基础的用户填索引。重编源路线后必须重做对齐。

每个乐章目录有 `score.json`（有理数事件）、`score.svg`/`score.mei`、`geometry.json`、`audio.json`/`audio.wav`、`alignment.json`、`alignment-evidence.jsonl.gz`。事件保留source_id与演奏occurrence；不能用“SVG中第几个音”替代身份。

默认`alignment.pipeline`为`refined`；用`alignment:{"pipeline":"refined","constraints":"reviewed-times.json","config":{...}}`指定源身份绑定约束与参数，详见[对齐算法](alignment.md)。旧`anchors`转换为同谱源约束并精确锁定；重复谱位冲突须先消除。`coarse`仅为旧算法诊断入口。

`engraving_overrides`和`layout_overrides`接受相对路径或对象，分别作用于临时XML排谱和SVG文字位置，格式见[视觉规范](visual-style.md)，配置文件纳入冻结指纹。`alignment-inputs.json`绑定源谱、事件、路线、录音、样本规格及裁切区间，不能手改哈希冒充新复核。

封面配置`cover.words`六项文字、原生`staves`、两比例`aspect_ranges`和`sample_q`，由agent按实际作品填写；格式见[视觉规范](visual-style.md)。`native_excerpt_builder`不再使用，不依赖旧项目脚本。

## 音乐结构与自然段落

`structure.json` 中谱位为数值，覆盖从0到total_q、连续且不重叠；每个父段有覆盖完整的子段。字段不要求特定曲式。

```json
{"reviewed":true,"sections":[{"label":"呈示部","start_q":0,"end_q":120,"children":[{"label":"引入","start_q":0,"end_q":8},{"label":"第一主题群","start_q":8,"end_q":120}]}]}
```

这只是格式示例，不是任何作品的预设结构。填写实际分析；默认以导航子段计算稳定声部集合。需要更细的自然段落时，在同一对象增加 `cohort_sections:[{"start_q":0,"end_q":8},{"start_q":8,"end_q":120}]`，与导航分离；它必须连续覆盖全乐章。不能伪造音乐曲式标签来驱动隐藏。

`materials.json` 格式 `{"assignments":{"event_id":"main","another_event":"purple"}}`。允许值main/purple/green/ochre；跨乐器同材料沿用颜色，未知关系用main。`labels.json` 可用 `{ "staff_id":"中提琴" }` 翻译固定声部名，保留明确的分部/独奏区别。

## 审核是实际工作记录

`pdf-review.json`：
```json
{"reviewed":true,"source_pdf_sha256":"实际PDF哈希","source_score_sha256":"实际MusicXML哈希","pages_checked":[1,2],"findings":[],"unresolved":[]}
```
确认当前PDF与当前XML的相关范围；完整新作品不能只核两页。修订用独立输入副本，不改原谱。未核全范围时列出剩余项，不能直接空unresolved。

`alignment-review.json`：
```json
{"reviewed":true,"alignment_sha256":"当前alignment.json哈希","checked_ranges":[[0,30]],"findings":[],"unresolved":[]}
```
要写实际检查过的范围及修正。构造信号测试不能代替实际录音听检；历史锚点回放不能代替新录音对齐。

预览生成 `preview-manifest.json`。三组检查后，在output的`team-review.json`记录：
```json
{"fingerprint":"当前预览fingerprint","reviewers":[{"name":"真实审阅agent标识","scope":"whole-program","approved":true,"findings":[]}]}
```
需三名不同实际审阅者，全部看同一完整方案。上面只示一条，不能复制名字凑数。用户明确确认后，调用`approve --statement "用户原话"`。源/谱/时钟/材质/字体/代码变更会使确认失效。

## 命令顺序

`init → prepare → align → agent核对/修订 → preview → 三组复核 → 用户确认 → approve → render`。
`resume`继续同一冻结版本；`status`读状态；`covers`仅重新生成封面；`clean`列缓存，`clean --apply`在交付存在时执行清理。不要在普通命令前加shell插值的未经转义用户文本。

`doctor`、`profiles`、`components`无需project，分别检查环境、列出本地参考快照和组件版本。公开包没有预设快照；用`--profile-dir`指定用户自己的快照目录。`init --reference ...`按[本地快照](reference-packs.md)导入；`preflight`不调用浏览器，不生成图像/音频。同项目已授权的用户修订可用`approve --inherit`保留原授权并绑定新审核，不能从参考项目继承批准。
