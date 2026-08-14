#!/usr/bin/env python3
"""Patch Songy's compiled Flutter bundle with a tiny just_audio control bridge."""
from pathlib import Path
import sys


source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
source = source_path.read_text()

constructor = 'ajk:function ajk(a,b){this.b=a\nthis.a=b},'
patched_constructor = '''ajk:function ajk(a,b){this.b=a
this.a=b
;(self.__courseStudyspacePlayers||(self.__courseStudyspacePlayers=[])).push(this)},'''
if constructor not in source:
    raise SystemExit("just_audio player constructor signature changed")
source = source.replace(constructor, patched_constructor, 1)

runner = '''var s=A.cdq
if(typeof dartMainRunner==="function")'''
bridge = '''self.__courseStudyspaceJustAudio={
call:function(method,index,positionMs){
var args=method==="seek"?A.z(["position",Math.max(0,Math.round(positionMs*1000)),"index",index],t.z,t.z):A.A(t.z,t.z)
var players=self.__courseStudyspacePlayers||[],i=players.length-1
function attempt(){
if(i<0)return Promise.reject(new Error("just_audio player not ready"))
var p=players[i--]
return Promise.resolve(p.b.e4(method,args,!1,t.f)).catch(attempt)
}
return attempt()
}}
var s=A.cdq
if(typeof dartMainRunner==="function")'''
if runner not in source:
    raise SystemExit("Dart runner signature changed")
source = source.replace(runner, bridge, 1)
target_path.parent.mkdir(parents=True, exist_ok=True)
target_path.write_text(source)
print(f"wrote {target_path} ({target_path.stat().st_size} bytes)")
