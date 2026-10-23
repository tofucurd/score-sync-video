import json,subprocess
from score_sync.workflow import write_chapters,chapter_mux_args

def test_chapters_use_sample_boundaries_and_survive_mov_mux(tmp_path):
    manifest={'sample_rate':96000,'chapters':[
        {'id':'m1','title':'第一乐章 # 行板; A=B','start_sample':0,'end_sample':109537},
        {'id':'m2','title':'第二乐章','start_sample':109537,'end_sample':192000}]}
    metadata=write_chapters(manifest,tmp_path)
    assert 'START=109537' in metadata.read_text()
    assert (tmp_path/'B站章节.txt').read_text().splitlines()[1]=='00:01 第二乐章'
    target=tmp_path/'test.mov'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','anullsrc=r=96000:cl=stereo','-f','ffmetadata','-i',str(metadata),'-t','2','-map','0:a','-c:a','alac']+chapter_mux_args(manifest,input_index=1)+[str(target)],check=True)
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_chapters','-of','json',str(target)]))
    assert len(info['chapters'])==2
    for got,want in zip(info['chapters'],manifest['chapters']):
        assert got['tags']['title']==want['title']
        assert abs(float(got['start_time'])-want['start_sample']/96000)<.002

def test_bilibili_hour_boundary_and_exact_json(tmp_path):
    data={'sample_rate':96000,'chapters':[{'id':'long','title':'测试长章','start_sample':345696123,'end_sample':345792456}]}
    write_chapters(data,tmp_path)
    assert (tmp_path/'B站章节.txt').read_text()=='01:00:01 测试长章\n'
    assert json.loads((tmp_path/'chapters.json').read_text())==data
