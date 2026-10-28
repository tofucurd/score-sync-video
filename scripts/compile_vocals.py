#!/usr/bin/env python3
"""Compile reviewed full-movement lyric groups and stable layout, without rendering."""
import argparse,json
from pathlib import Path
from score_sync.vocal_schedule import compile_schedule
from score_sync.vocal_layout import compile_layout

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('timeline','entries','presence','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();read=lambda p:json.loads(p.read_text())
 full=read(a.timeline);schedule=compile_schedule(full,read(a.entries),read(a.presence))
 layout=compile_layout(full,schedule)
 a.output.mkdir(parents=True,exist_ok=True)
 for name,value in [('timeline.json',full),('cohort-schedule.json',schedule),('layout-schedule.json',layout)]:
  (a.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'cohorts':len(schedule['cohorts']),'layout':'stable full-source baseline; browser review required','rendered':False}))
if __name__=='__main__':main()
