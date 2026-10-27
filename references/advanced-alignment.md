# 源速度分段与宽走廊候选

当原有密集匹配在速度突变、长持续音、人声或弱器乐出现压缩/步型饱和时，使用显式候选入口；默认 `align` 保留既有 refined 算法。代码来自实际项目的 full-route core、guarded v1/v2/v3、state-refinement-v2 和末尾休止导出实现，移除对已安装目录及项目的导入。没有附带人工 fit 数据。

`python scripts/alignment_candidate.py --help` 查看入口。输入是当前项目已准备的 `score.json`、`audio.json`、原始 MusicXML、准备 PCM、`alignment-features.npz` 与用户持有的 fit JSON；所有路径显式传入。特征同目录须有基础 refined 生成的 `alignment-features-key.json`，其 key 必须绑定当前 PCM 哈希、音域和 feature-v2；不能只给等形状矩阵冒充同录音。fit 字段：

- `score_sha256`、`audio_metadata_sha256`、`prepared_audio_sha256`、`features_sha256`、`source_sha256`：各输入文件实际 SHA256。
- `pitch_low`、`pitch_high`：该特征缓存实际音域，不能只按矩阵宽度猜音域。
- `music_search_end_seconds`：已核实音乐搜索边界，排除掌声等分析污染，完整原录音仍保留。
- `fit_anchors`：有序的 `{q,target,window:[lower_seconds,upper_seconds]}`。至少两个独立核实的边界；这些用于拟合，必须从独立验证集排除，不能把其他录音的锚点搬来。源身份由整份 score/source 哈希绑定；源或路线变化后须重核。
- 可选 `step_q`（1/32）、`audio_hop`（.01）、`corridor_halfwidth_seconds`（16）、`coarse_max_axis`（4000）、`max_backtrack_cells`（100000000）。它们是参考参数，较宽走廊需要真实内存预算。
- 可选 `terminal_rest_policy`：源绑定的 `source_sha256,last_attack_q,rest_q,fermata_rest_q`，可加 `tempo_interval_count`。仅适用于最后攻击之后确有普通休止及延长记号休止的谱源；不能套到任意结尾。

输出写入全新目录，只有候选与证据，不覆盖正式映射。CLI 尚不自动细化装饰音；须用原始 XML 归属及 `refinement_graces` 接口单独处理并复核。它也不继承任何批准或已审身份。

## 实际实现

- `coarse_block` 每个核实边界区间重新从 source/PCM 求粗 DTW：状态/攻击权重 .8/.2，允许粗层零轴步以容纳长保持；旧 clock 不输入。
- `source_tempo_events` 按演奏路线映射第一声部 `<sound tempo>`，跳转或片段起点恢复继承速度。未知速度令整个窗口退回无量纲平坦假设，不能伪造为 1 BPM。速度倒数积分只给相对先验，总长度由外部边界约束归一；不是按节拍器生成成片时间。
- `global_banded_path` 以 .7/.3 状态/攻击成本及 .06 对数速率惩罚，在宽走廊做严格正向全局 DP。步型 `(1,1..16),(1,24/32/48/64),(2..8,1)`，速率比范围 1/16–16；跨越 fit 网格行的步也检查插值边界。断链即失败，不能插值冒充成功。
- 最后的有序音高链按源速度边界限制速率统计窗口。速度边界从完整源路线提取，包含恰好位于 fit 区间端点的变速，不能只合并各区间内部的边界（实际最终 revision09 修复）。跨速度边界的边使用密集音频时钟端点差，避免用一个中点速度代表两种速度。最终采用 `source_aware_rate=True,retain_state=False`；持续音状态加权只是试验，不能说已证明改善人声，更不是人声分离。
- 输出步型饱和、走廊贴边、候选分歧与分速度区段压缩诊断；同特征分数不能代替独立证据。弱音、同音叠奏、持续合唱都可能缺乏可辨识物理起音。
- 末尾声学衰减与写出的静默休止分开投影。休止上的延长记号不等于最后一个发声音符延长；原声不裁切、不拉伸。

基础 `correct_guide` 同步采用实际项目的正向时间域分段仿射变换：已审时间边界只修正搜索先验，避免非线性先验加 q 域线性残差时倒序。

## 证据边界

实际项目最后按乐章及局部证据混合选用新候选和已审旧结果，并非统一以最新全局结果覆盖全部。91个人工 fit 锚点属于那一次录音，未进入公开 skill。宽参数、完整计算、拟合窗命中都不能证明每个攻击更准。可见谱面、实际演奏、cue 与隐藏辅助音必须分别核对：当前 `attacks` 的代码过滤 pitch/is_player/grace/tie_stop，并不把 `visible` 自动等同于演奏身份。
