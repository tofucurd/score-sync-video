# score-sync-video

An agent skill and Python/JavaScript toolkit for continuous score-synchronized videos, structural navigation, and matching covers, built from MusicXML/MXL, an original score PDF, and a real recording.

中文说明如下。Music engraving is powered by [Verovio](https://www.verovio.org/). Code uses the [MIT license](LICENSE); bundled Source Han Serif fonts retain their [SIL OFL license](assets/fonts/LICENSE.txt).

## 功能

- 单列流动原生乐谱、固定蓝色时间线、持续音符高亮。
- 真实录音多阶段对齐、装饰音处理、局部约束和音频诊断。
- 稳定声部集合、平滑布局、滑动换章、持续材料配色。
- 双层曲式进度条、中文结构提示。
- 2160p60 HEVC 4:4:4 10-bit MOV、无损音频、内嵌章节和B站章节文本。
- 当前作品真实谱面生成16:9和4:3封面。
- 审片、冻结、分块续渲、缓存清理和组件指纹。

仓库只包含通用工具、样式、字体和合成测试，没有具体作品的原谱、转录、音频、成片、时间锚点或历史项目配置。

这不是任意录音的一键完美对齐器。PDF校勘、演奏路线、曲式、配色和实际录音复核仍由agent或人工完成。相同原料重新分析也不保证重现另一个项目的全部人工判断；精确重放依赖该项目保存的已审数据。

## 环境

| 组件 | 要求 |
|---|---|
| 系统 | POSIX；已验证锁定依赖可解析于Apple Silicon macOS 13+、Linux x86_64 |
| Python | 3.14，推荐uv管理独立环境 |
| Node.js | 22或以上，无npm依赖 |
| FFmpeg/FFprobe | FFmpeg含libx265及yuv444p10le支持 |
| 浏览器 | Chrome/Chromium，可用`SCORE_SYNC_CHROME`指定 |
| 字体 | 随包思源宋体2.003，保留原许可 |

当前不支持原生Windows；WSL和Intel Mac未完成安装/渲染验证。Intel Mac锁定依赖缺少部分wheel，不能承诺直接安装。依赖解析验证不等于跨平台完整渲染验证。

## 安装

先安装[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js、FFmpeg及Chrome/Chromium，再克隆：

```bash
git clone https://github.com/tofucurd/score-sync-video.git
cd score-sync-video
python3 scripts/bootstrap.py
.runtime/bin/python scripts/score_sync.py doctor
```

bootstrap建立仓库内`.runtime`，不改系统Python。doctor只检查环境，不渲染。浏览器不在默认位置时设置：

```bash
export SCORE_SYNC_CHROME=/absolute/path/to/chromium
```

作为agent skill使用时，把仓库放进支持`SKILL.md`的技能目录，或让agent读取[SKILL.md](SKILL.md)。例如放到`~/.codex/skills/score-sync-video`后用`$score-sync-video`调用；已有同名目录时不要直接覆盖。

## 使用

```bash
.runtime/bin/python scripts/score_sync.py init \
  --project /absolute/my-project/project.json \
  --score /absolute/materials/score.mxl \
  --pdf /absolute/materials/original.pdf \
  --audio /absolute/materials/performance.flac \
  --title "作品名称" --composer "作曲家"

.runtime/bin/python scripts/score_sync.py prepare --project /absolute/my-project/project.json
.runtime/bin/python scripts/score_sync.py align --project /absolute/my-project/project.json
```

多个乐章重复提供`--score`和`--audio`，PDF可共用。项目建在仓库之外，原素材保持只读。随后由agent核对原谱和完整录音、修正候选、补全结构/颜色/封面及真实审核记录。

```bash
.runtime/bin/python scripts/score_sync.py preflight --project /absolute/my-project/project.json
.runtime/bin/python scripts/score_sync.py preview --project /absolute/my-project/project.json
```

三名真实审阅者复核整套预览，用户确认后记录实际原话并渲染：

```bash
.runtime/bin/python scripts/score_sync.py approve \
  --project /absolute/my-project/project.json --statement "用户实际确认这套预览的原话"
.runtime/bin/python scripts/score_sync.py render --project /absolute/my-project/project.json
```

不能伪造review JSON跳过工作。暂停后用`resume`，状态用`status`；`clean`只列缓存，`clean --apply`才删除可重建缓存。默认保留25GiB可用空间。

## 文档与开发

- [项目格式](references/project.md)、[谱源与结构](references/score-and-structure.md)
- [算法与公式](references/alignment.md)、[视觉与封面](references/visual-style.md)
- [音频与交付](references/delivery.md)、[本地快照](references/reference-packs.md)
- [组件版本](references/components.json)、[验证范围](references/validation-results.json)

```bash
.runtime/bin/python -m pytest tests -q
node --check scripts/browser_render.mjs
python3 scripts/check_package.py
```

测试使用合成数据和短合成音频，不渲染完整视频。组件变更后运行`python3 scripts/release_manifest.py`刷新指纹。CI验证依赖安装、测试、JS语法和包内容，不代替实际作品同步验收。

## 许可

代码和原创文档使用MIT。Verovio是LGPLv3外部依赖，思源宋体使用SIL OFL 1.1。第三方软件及用户提供的乐谱、录音不受项目MIT许可重新授权，详见[第三方声明](THIRD_PARTY_NOTICES.md)。
