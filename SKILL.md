---
name: score-sync-video
description: "Use when producing a continuous score-synchronized video and matching covers from MusicXML/MXL, an original score PDF, and a real recording. Also use for alignment corrections, preview review, paused render recovery, or cover revisions within this workflow."
---

# 曲谱同步视频与封面

从MusicXML/MXL、原谱PDF和实际录音制作连续曲谱同步视频。使用纸色、思源宋体、固定蓝游标、单列流动谱面、持续音符高亮及双层曲式导航。作品信息、演奏路线、时间、结构和颜色由当前项目决定；不附带任何作品的乐谱、录音、锚点或项目修订。原始素材只读。

版本 **1.0.1**。组件及文件指纹见[清单](references/components.json)，验证范围见[记录](references/validation-results.json)。安装条件见[README](README.md)。乐谱排版由[Verovio](https://www.verovio.org/)提供；第三方许可见[声明](THIRD_PARTY_NOTICES.md)。

## 环境与入口

运行`python3 scripts/bootstrap.py`，后续使用输出的独立Python。`scripts/score_sync.py doctor`检查POSIX、Python、Node、FFmpeg/FFprobe、Chromium与编码支持，不渲染。非标准浏览器路径用`SCORE_SYNC_CHROME`指定。

```bash
.runtime/bin/python scripts/score_sync.py init \
  --project /absolute/project/project.json \
  --score /absolute/score.mxl --pdf /absolute/original.pdf \
  --audio /absolute/recording.flac --title "作品名称" --composer "作曲家"
```

每个乐章各提供score/audio，PDF可共用。整曲XML先按实际乐章拆分工作副本。补全演奏者、乐团、乐章名和编号；没有编号则留空。格式见[项目接口](references/project.md)，不要让不懂乐理的用户制作小节索引。

## 制作流程

1. **核对谱源与路线。** `prepare`解析事件和原生谱面。逐页查看PDF，核对音符、休止、移调、节奏、装饰音、连线和表情；有依据的修订写入独立副本。实际反复/跳转写入`source_route`，不假定全做或全省。[谱源与结构](references/score-and-structure.md)说明身份与排谱约束。
2. **对齐真实录音。** 默认`align`使用`refined`多阶段匹配，输出候选、装饰音证据与全攻击节点审计。检查整条路线、快速织体、入口、变速、重复段与尾声；按录音证据补充源身份约束，再更新受影响映射。[对齐算法](references/alignment.md)提供公式和参数。`coarse`仅为旧候选诊断入口。
3. **完善结构与画面。** 自行填写两级`structure.json`、自然声部段、`materials.json`、标签和封面配置。跨乐器同材料沿用颜色，未知关系用主色。所有曲式内容来自当前作品，待完成项不能进入预览。详见[视觉规范](references/visual-style.md)。
4. **记录真实复核。** 当前谱源/录音对应的`pdf-review.json`和`alignment-review.json`由实际工作填写。`preflight`检查绑定、场景数据与封面配置，不启动浏览器。谱源、路线、录音或裁切变化使`alignment-inputs.json`失效，不能只改哈希冒充新复核。
5. **制作并审查预览。** 默认每章开头30秒，另交实际高清帧、两比例封面和审片PDF。补查快速段、密集页、转场和实际最终编码样段。三名真实agent各看同一完整方案并交叉复核；并发不足可顺次独立审查，不伪造姓名或批准。按发现的问题修复复查，不固定重复轮数。
6. **确认后冻结渲染。** 新项目默认交预览确认，再用`approve --statement "实际确认原话"`记录授权并`render`。已有渲染授权的同任务用户修正沿用原授权，更新受影响预览/复核后，以`approve --inherit --statement "实际修正指令"`绑定新指纹。冻结后专注渲染，不自行改美术。
7. **恢复与交付。** 用户暂停时只停本项目渲染，保留完整分块，`resume`续渲。必要检查通过即交成片、封面和章节，不追加无期限审核。`clean`默认仅列缓存，已授权时才`clean --apply`。[交付规范](references/delivery.md)说明音频、章节、恢复与空间管理。

## 成片约束

- 默认3840×2160、60fps、HEVC Main44410 MOV，原音频无损封装。音频是唯一主时钟，不归一化、不变速、不剪尾音、不为整帧添加乐章间静音。
- 无讲解、课堂暂停、片段重播、MIDI音轨、SRT、教学小标题、额外动机框或抽象装饰；保留导航中的当前结构与简短乐章标识。
- 实际演奏的源可见音符具有可追溯图形绑定和完整高亮区间。符干、附点、跨谱表关系保留，音符不变形。
- 自然小段中发声过的声部及跨段延音保留，不因一两小节休止反复隐藏。声部边界固定，同一4秒权重控制透明度和空间，不另启动二次展开。
- 蓝色竖线固定，谱面横向流动。主色与有限材料色持续跟随音乐关系，不只按乐器换色。
- 双层导航整体使用`navigation.py`：当前标题、居中段落标签、蓝色当前段、短竖指针、8px纸色分隔及父子/乐章过渡。宽度与指针按实际录音样本计算。
- 字体仅用随附思源宋体，原生音乐字形保留。封面从当前作品原生谱面摘取，两比例独立选段，类别文字可选，不使用其他作品谱面装饰。
- 仅排版修正用带身份、旧值及输出校验的`engraving_overrides`/`layout_overrides`。ID或几何变化时重新检查，不盲移旧坐标。

最终MOV内嵌乐章名与起点，另交`B站章节.txt`和`chapters.json`。边界来自实际拼接PCM累计样本，不能用谱面速度、估计时长或帧数代替。

## 适用边界

自动对齐是候选。自由速度、重复织体、弱声和被遮蔽装饰音需证据复核，不宣称一次自动得到逐乐器物理起音真值。校勘、结构和配色也不是自动完成的。

接受partwise MusicXML/MXL；timewise、微分音、无固定音高为主和复杂删改需先适配。混合采样率与attacca边界见交付规范。只检查代码/数据时，不调用`preview`、`covers`、`render`或PDF输出。

通用[本地参考快照接口](references/reference-packs.md)可恢复用户自己持有的已审数据。公开仓库不附带具体作品快照；快照不能跨录音套用，也不携带新用户批准。
