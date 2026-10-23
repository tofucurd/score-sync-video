# 录音对齐、连续精修与证据

`alignment_pipeline.py`采用音区特征、密集序列匹配、音高起音链和装饰音顺序匹配。人工核实的局部时间修正属于对应录音的数据，不能作为另一录音的通用参数。原音频始终是播放主时钟，分析信号单独生成。

## 新会话入口

乐章配置使用 `"alignment":{"pipeline":"refined","config":{},"constraints":"timing-constraints.json"}`。没有已审约束时省略 `constraints`，不得编造。通用 `align` 入口调用 `refine_movement`，不需要先运行旧 `align_movement`。

可直接调用以下接口进行候选诊断：

```python
from pathlib import Path
from score_sync.alignment_pipeline import refine_movement

result = refine_movement(
    Path("project/.score-sync/m1"),
    source_path=Path("project/materials/m1.musicxml"),
    constraints=reviewed_constraints,
    config={"step_q": 0.03125},
)
```

默认写 `alignment-refined.json` 及同名前缀证据文件，不覆盖 `alignment.json`。正式工作流显式传 `output_path=movement_dir/'alignment.json'` 时会使旧的 `alignment-review.json` 失效。输出必须重新复核，不能凭程序运行成功沿用旧审阅。

`source_path` 是生成 `score.json` 的原始未展开 XML/MXL；装饰音归属从它读取，SHA 必须一致。不要传经过演奏路线展开的 `normalized.musicxml`，否则源音符编号不再匹配。

## 算法与参数

1. **谱面建模。** 使用 Fraction 谱位 q、响音音高、声部、voice、显式 tie 与已核实演奏路线。占用矩阵保留持续音；攻击集合排除 cue、装饰音及 tie-stop。音域从实际谱面推导至整八度边界，微分音不能静默取整。
2. **录音特征。** 24 kHz 分析 PCM；CQT 为半音格、hop 256。多声道按功率合并，避免反相抵消。另以 10 ms 步长计算 1024/4096 Hann 双窗 FFT，组合前四谐波，得到短窗/长窗 dB 正变化：`R=.65[short(t+.03)-short(t-.03)]₊+.35[long(t+.03)-long(t-.03)]₊`。按每音高第94百分位归一；分析缓存绑定 PCM 哈希、音高范围和特征版本。
3. **音区粗路线。** 全音域色度与低、中、高三个音区色度组成48维向量，分音区权重 .65，去均值后 L2 归一。`C=clip(1-X·Y,0,2)`；DTW 使用 `(1,1),(1,2),(1,3),(1,4),(2,1),(3,1),(4,1)` 步型及非对角惩罚。成本矩阵默认单轴不超过约2000；记录真实网格密度。首音以RMS进入门限和预期音高变化峰提出软候选，避免把粗DTW的文件0秒端点当成开头静音后的物理起音；已审首音约束优先，无约束候选保留复核flag。文件末尾静音不作为最后物理起音。
4. **密集 state+attack DTW。** 音频网格默认10 ms，粗路线两侧默认各3秒。乐谱格 `step_q` 可配置，默认根据粗路线的秒/q选取1/128至1/8之间的二进制步长。状态与攻击代价为 `.7(1-state_cosine)+.3(1-attack_cosine)`，局部速度惩罚为 `.12 ln²(ratio)`。步型允许 `(1,1..8)` 与 `(2,1)`，局部速度比限制 .4至2.5。完整回溯必须连到谱面开头，不能把断开的路径插值成“成功”。显式限制回溯矩阵内存，超限要求调整参数，不暗中粗化。
5. **全局有序音高链。** 同 q 攻击按具体音高汇总，重复音高权重为声部数平方根。每个攻击在密集路线默认±2秒内取音高正变化峰与稀疏候选；局部成本 `-pitch_evidence+.02((t-seed)/width)²`。相邻候选加 `tempo_weight·ln²(Δt/expected)`，默认权重4。expected 由附近真实路线斜率推导，不使用固定 BPM。过短、过长或倒序边不可选。末次攻击默认只允许在密集末端±.30秒内选择；首尾有独立证据时优先加入约束。
6. **音符投影与尾音。** 所有谱位、音符起止都投影到样本域。显式 tie 链持续高亮。最后攻击之后用尾噪声及和弦衰减阈值提供显示终点候选，完整录音尾音另保留，不剪掉、不补帧静音。这个终点不是每件乐器独立测得的结束时刻。
7. **装饰音。** 从源 XML 的 `steal-time-*`、同声部/voice前后关系、颤音结尾和源顺序判断归属；同时音是同一攻击簇。每组在实际音高正变化中以至少18 ms次序间隔联合匹配，不能按谱面写法推断固定时值。before/after归属和音频置信度分开记录；弱或重叠峰保留 `ambiguous_audio_candidate`，未明归属保留 unresolved。颤音尾花出现时截短所属主音的显示区间。禁止把旧50 ms占位窗描述为已测起音。
8. **逐攻击节点审计。** 输出所有攻击点的局部峰残差、原候选变化和缺峰情况，而非只抽开头。该审计与拟合共享特征，不能作为独立准确率证明。大残差需要按连续音序核实，不自动吸到最近或最强峰。

支持的 `config` 参数：`step_q`、`audio_step_seconds`（默认.01）、`dense_halfwidth_seconds`（3）、`attack_halfwidth_seconds`（2）、`tempo_weight`（4）、`initial_search_seconds`（10）、`terminal_search_seconds`（1）、`last_attack_halfwidth_seconds`（.30）、`coarse_max_axis`（2000）、`max_backtrack_cells`（100000000）。`use_existing_guide=true` 默认关闭；开启时，现有 `alignment.json` 必须有完整且匹配的 `input_binding`：score.json哈希、原谱哈希、展开路线、原录音哈希、实际准备PCM文件哈希、裁切区间、采样率/样本数/声道/位深。等长不同录音仍拒绝复用；旧映射缺这些身份字段也拒绝，先产生新的候选。核对发生在特征分析前。通过后只能把它当宽搜索走廊，不继承批准。

## 已核实约束与局部修正

约束是列表，或 `{"source_sha256":"…","rows":[…]}`。每行必须有 `q`、`seconds`、`events`，可有 `tolerance_seconds`（默认.015）与证据说明。`events` 列出该 q 所有实际攻击的 `source_id`、`source_measure`、`pitch`；更改源谱后身份不符即拒绝。相同源小节的不同演奏次数靠展开 q 区分。不能用粗DTW结果冒充已审约束。

已有 `anchors:[[q,seconds],…]` 通过 `constraints_from_anchors(score,anchors,duration)` 迁移，保留精确秒数而非四舍五入到10 ms。攻击锚点的DP候选精确锁定；无新攻击的谱位及末尾释放点转为绑定源谱哈希的 `kind:"clock"`、`exact:true` 约束，加入最终时间图并重新投影音符。若与邻近候选冲突则报错，不能静默忽略旧锚点。显式约束与旧锚点在同一 q 存在不同秒数时须先消除冲突。

局部纠错只替换指定开放区间的时间图，保留区间外已审结果。通用函数 `apply_local_clock_patch(baseline,candidate,score,start_q,end_q)` 保留边界样本，验证同源、同样本域和单调性；它只产生待复核的新图。随后重新运行装饰音投影及受影响区间审计，不把远处未经核实的全局重优化顺带写入。

## 独立的原始PCM检查

`refinement_diagnostics.py` 提供与拟合特征分离的局部诊断：

- `audit_recording_interval(out_dir,alignment,score,start_seconds,end_seconds,neighbor_pitches=None)`：仅读取指定区间的24k PCM。每个预期音高用基频±4%的带通、Hilbert包络、8 ms平滑和20 ms正变化；对整段预期音序评估共同时间偏移。
- `joint_neighbor_envelopes(signal,rate,pitches)`：100 ms窗口内同时拟合邻近音高的正弦/余弦基函数，使用加权最小二乘，帮助分辨相邻半音泄漏。保留矩阵条件数；颤音、泛音和同音叠奏仍有歧义。

这些工具不会修改时间图。只有音高身份、连续顺序及原谱语义支持的差异才能转为约束或局部修正。不得因为某个峰大或残差超过80 ms便整体移拍。

## 复现与验证边界

已审项目应保存最终时间图、源谱修订、演奏路线和原素材哈希。使用相同素材可回放最终映射；重新运行自动算法不能保证逐样本重建所有人工判断。新录音必须重新生成候选与证据，不能套用另一录音的时间锚点。

小型合成音测试验证算法连通性、音高次序、源身份守卫、尾音处理和数据接口，不证明真人演奏精度。无渲染数据检查只验证输入身份、源语义与数值不变量。只有实际录音、局部波形/音高证据和视觉同步的复核，才支持具体成片精度；候选不确定性保留在内部审阅资料中。

旧 `alignment.py:align_movement` 仍作为兼容候选入口；其12维粗路线、稀疏候选DP和固定50 ms装饰音占位不等同于上述精修流程，也不应覆盖已审复现配置。
