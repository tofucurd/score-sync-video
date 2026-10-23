# 用户自己的本地参考快照

公开包不包含任何作品预设。普通新作品使用`init → prepare → align → 实际复核`。如果用户已持有符合本接口的已审快照，可以指定外部目录导入；该目录中的素材权利与审核由快照提供者记录。

```text
score_sync.py profiles --profile-dir /absolute/local-packs
score_sync.py init --reference my-reference --profile-dir /absolute/local-packs --project /absolute/new/project.json --score /inputs/source.mxl --pdf /inputs/source.pdf --audio /inputs/recording.flac
```

`my-reference`只是示意标识，不是仓库附带的数据。多份输入按快照的角色/index顺序提供。导入验证全部原始文件哈希、归档成员和已有目标，拒绝覆盖；缺少归档时明确报错。此接口读取已有包，不从原始素材自动推导一个已审包，也不从网络获取数据。

目录包含`<id>.json`和其`archive`字段指定的ZIP。manifest采用`schema:1`，包含`id/version/title`、`archive_sha256`、`files`（归档路径到SHA256）、`inputs`（role/index/sha256）、`movements`（每章audio_index/pdf_index）和`frozen_files`。所有归档路径相对且不得越界。

ZIP包含`project-template.json`、修订谱及`.score-sync/<id>/`中已审事件、原生谱面/几何、对齐、结构、颜色、标签和源复核记录。模板的原音频/PDF路径在导入时替换为用户提供的文件。`audio.json`可保留实际规格，准备后的音频缓存不应加入冻结文件清单。不得把`approval.json`、预览批准或当前团队批准放入快照；导入不等于获得新项目渲染授权。

导入后`prepare`只准备原音频，保持冻结数据。`align`拒绝覆盖快照中的已审时间。`verify_reference`验证源素材、配置语义和冻结文件；外部快照目录须保留供核验。更换录音、路线或谱源时创建普通新项目。
