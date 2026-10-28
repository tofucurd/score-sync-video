#!/usr/bin/env python3
"""Compile optional label-side notation and sparse source locators; no rendering."""
import argparse,json
from pathlib import Path
from score_sync.notation_labels import bindings,compile_signatures,compile_locators,read_xml

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--movement-dir',type=Path,required=True);p.add_argument('--score',type=Path,required=True)
 p.add_argument('--interval',type=int,default=8);p.add_argument('--number-offset',type=int,default=0)
 p.add_argument('--without-clefs',action='store_true');a=p.parse_args();d=a.movement_dir
 score=json.loads((d/'score.json').read_text());geo=json.loads((d/'geometry.json').read_text());xml=read_xml(a.score)
 signatures=compile_signatures(xml,score,geo,(d/'score.svg').read_text());signatures['options']['clef']=not a.without_clefs
 locators=compile_locators(xml,score,geo,interval=a.interval,number_offset=a.number_offset)
 for name,value in [('staff-signatures',signatures),('score-locators',locators)]:
  value['source_hashes']=bindings(d);(d/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'staves':len(signatures['staves']),'locators':len(locators['items']),'rendered':False}))
if __name__=='__main__':main()
