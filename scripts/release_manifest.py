"""Record the released component files; run after validated packaging changes."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.1'
GROUPS={
 'workflow':('通用流程、输入绑定与交付',['scripts/score_sync.py','scripts/score_sync/workflow.py','scripts/score_sync/bindings.py'],'章节标题、可继承授权、失败状态'),
 'reference':('外部参考快照接口',['scripts/score_sync/profiles.py'],'读取用户自己提供的已审数据；不附带作品快照'),
 'score':('谱源与原生排谱',['scripts/score_sync/score.py','scripts/score_sync/dashes.py','scripts/score_sync/hidden_ink.py'],'全谱校勘兼容、表情虚线、隐藏墨迹'),
 'engraving_overrides':('受校验的排版覆盖',['scripts/score_sync/engraving_overrides.py','scripts/score_sync/layout_overrides.py'],'按源身份验证的局部排版修订'),
 'alignment':('连续录音对齐',['scripts/score_sync/alignment.py','scripts/score_sync/alignment_pipeline.py'],'多阶段连续匹配与受约束细化'),
 'graces_diagnostics':('装饰音与独立声学诊断',['scripts/score_sync/refinement_graces.py','scripts/score_sync/refinement_diagnostics.py'],'源XML归属、bandpass/Hilbert、邻音联合最小二乘'),
 'ties':('连音链',['scripts/score_sync/ties.py'],'延音/色彩链'),
 'animation':('谱面流动、高亮、声部与换章',['scripts/score_sync/visual.py','scripts/browser_render.mjs','assets/style.json'],'稳定布局、8.33ms攻击、滑动转场'),
 'navigation':('双层结构导航',['scripts/score_sync/navigation.py'],'双层几何、移动指针与段落分隔'),
 'covers':('双比例封面场景',['scripts/score_sync/covers.py','scripts/browser_render.mjs'],'通用纸色模板与原生摘谱'),
 'audio':('原声准备与无损主音轨',['scripts/score_sync/audio.py','scripts/score_sync/workflow.py'],'原PCM样本、裁切身份、连续主音轨'),
 'review':('审片PDF与浏览器传输',['scripts/score_sync/review_pdf.py','scripts/print_pdf.mjs','scripts/cdp-transport.mjs'],'实际帧审片与字体嵌入'),
 'runtime':('独立环境与依赖',['scripts/bootstrap.py','scripts/score_sync/environment.py','requirements.lock'],'锁定Python依赖；无渲染环境检查'),
}

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def main():
 components=[]
 for ident,(name,files,origin) in GROUPS.items():
  components.append({'id':ident,'name':name,'version':VERSION,'origin':origin,
                     'files':{n:digest(ROOT/n) for n in files}})
 components.append({'id':'fonts','name':'思源宋体','version':'2.003',
                    'files':{str(f.relative_to(ROOT)):digest(f) for f in sorted((ROOT/'assets/fonts').glob('*.otf'))}})
 data={'schema':1,'skill':'score-sync-video','version':VERSION,
       'versioning_note':'Generic public release. No work-specific presets or datasets are bundled.',
       'components':components,'reference_profiles':[]}
 (ROOT/'references/components.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'version':VERSION,'components':len(components),'manifest':'references/components.json'}))

if __name__=='__main__':main()
