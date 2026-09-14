"""Separate submitter for real SIGKILL regression; test-only scripted CLI."""
import asyncio
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adapters.codex_imagegen import CodexHost, CodexImagegen
from adapters.imagegen import ImagegenRequest
root=Path(sys.argv[1])
host=CodexHost((sys.executable,str(Path(__file__).with_name('scripted_codex_cli.py').absolute()),'hang',str(root/'external')),
    root/'codex-home','scripted-codex 1','image-only',('gpt-5.6-luna',),'a'*64,True,30,True)
request=ImagegenRequest('visual_'+'c'*32,'d'*64,'generate','Scripted fixture, no model.',(),
    'fixture','gpt-5.6-luna',1,time.time()+90)
asyncio.run(CodexImagegen(root/'results',host).submit(request))
