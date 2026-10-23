"""Compact review document with actual full-resolution rendered frames."""
from pathlib import Path
import base64,html,tempfile,subprocess,re
from .visual import font_css,chrome_path,ROOT

def create_review_pdf(cfg,artifacts,target):
    title=cfg.get('work',{}).get('title','曲谱同步');words=title+'审片说明真实渲染帧预览帧封面声部高亮结构进度条连续原声等待确认无口播无字幕'
    parts=[f'<h1>{html.escape(title)}</h1><h2>审片说明</h2><p>单列流动曲谱、固定蓝线、持续音符高亮、双层结构进度条；连续原录音，无口播或字幕。以下图片来自实际渲染。完整成片将在你确认预览后开始渲染。</p>']
    for path in artifacts:
        path=Path(path)
        if path.suffix.lower()!='.png':continue
        title=path.stem;words+=title
        parts.append('<section><h2>'+html.escape(title)+'</h2><img src="data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()+'"></section>')
    words=html.unescape(re.sub(r'<[^>]*>', '', ''.join(parts)))
    css=font_css(words)+'@page{size:A4;margin:15mm}body{font-family:Han,serif;color:#26352e;font-size:11pt;background:#faf8f1}h1{color:#287D9F;font-size:24pt}h2{font-size:13pt}section{break-inside:avoid;margin:14mm 0}img{width:100%;height:auto}p{line-height:1.8}'
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'review.html';p.write_text('<!doctype html><meta charset="utf-8"><style>'+css+'</style>'+''.join(parts))
        subprocess.run(['node',str(ROOT/'scripts/print_pdf.mjs'),str(p),str(Path(target).resolve()),chrome_path()],check=True)
    return Path(target)
