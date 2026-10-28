# Linux 远程分块队列

`scripts/remote_render_worker.py start|run|status --job PACKAGE` 是从实际生产队列移植的独立 CLI，不负责登录、传输、制作场景或清理远程文件。包内所有路径相对包根，运行时工具路径由当前机器提供，不附带账户、网络地址或素材。

`queue.json` 必须包含 `purpose:"approved-full-production-2160p"`、`job_id`、`max_workers`（1–10，当前调度器接口范围）、`renderer`（默认 `scripts/browser_render.mjs`）、`files:{relative_path:sha256}`、`runtime` 和 `jobs`。冻结 renderer、场景和其依赖全部进入 files。runtime 包含 `tools:{node,ffmpeg,ffprobe,chrome}` 与 `binary_sha256:{absolute_tool_path:sha256}`；可选 `graphics_root` 仅用于已有 NVIDIA portable 图形运行库，否则沿用机器环境。工具路径与哈希须在目标机生成。

每项 job 包含 `id`（全局 start_frame 的9位补零值）、`scene`、`scene_sha256`、`start_frame`、`frames`、`duration`（frames/60）、`width:3840,height:2160,fps:60`。scene 是通用浏览器 renderer 的完整 spec，音频关闭 `silent:true`，启用 `final:true,encoder:"hevc_nvenc"`；帧内容由现有视觉代码生成，不自动转换其他项目场景格式。冻结 queue 后先获得该任务实际渲染授权，已有授权不需重复征求。

编码沿用实际生产参数：NVENC p7/hq/rext，输入像素格式 yuv444p16le，CQ16，maxrate25M/bufsize50M，编码输出由 FFprobe 核实为 HEVC 10bit 4:4:4。PNG输入、filter、编码 threads=1 降低内存。Chrome 的 raster 线程参数不代表真实占用相同核心数。NVENC 是否支持该格式取决于机器，不能静默降到420。

队列每10秒错峰启动；新任务 admission 至少留6GiB可用RAM，2GiB硬底线，磁盘至少10GiB并保留各活动任务预算。`execution-policy.json` 绑定 `queue_sha256`，可在运行中调 `max_workers,admission_ram_gib`；超过原队列上限时，另存同 queue 哈希的 `execution-cap-override.json`，含 `max_workers,user_statement`，记录已有明确指令。并发由显存、RAM、驱动及画面复杂度决定：曾8路发生 NVENC InitializeEncoder OOM、后来6路完成，是该次运行事实，6不是通用硬上限。

每块完成后校验格式、帧数，fsync并原子转正，再记源绑定哈希 receipt。恢复时校验完整分块和 receipt；完整 `.partial.mov` 可验收转正，资源/信号中断的不完整分块可重做。退出75是资源或信号checkpoint，退出1是永久失败；失败状态和 errors 不自动重试，必须先有明确 operator 决定并保留故障记录，再修正队列/执行策略。worker 锁避免同包重复调度。仅停止本任务子进程，不杀其他用户渲染。

最终拼接、原声无损封装、章节与交付沿用[交付规范](delivery.md)，此 worker 只产静音分块。当前 skill 更新仅做代码/单元与静态检查，未进行新远程端到端复现。

通用renderer现在导入 `scripts/layers/*.mjs`。远程包必须按相同相对路径携带这些模块并将其哈希列入 `queue.json.files`，即使某个场景没有启用可选层也不能只复制browser_render.mjs。字体及完整表现层payload已经在scene中；远端不重新编译歌词分组/布局或重新计算源标记。
