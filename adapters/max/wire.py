"""Passive native queue evidence from requests made by the owned MAX Web page.

Never sends a MAX request, intercepts/modifies traffic, reads app state/storage,
logs raw frames or decodes authentication traffic. UI drives every operation.
The observed v10 envelope uses bounded LZ4 + MessagePack with integer extension1.
Only history (49) frames are decoded; a scheduled response is retained only
after matching its socket/sequence to the UI request with itemType=DELAYED and
the exact authorized chatId. No raw frame is logged or sent by this module.
"""
from __future__ import annotations
import asyncio
import base64
import math

from .profile import MaxBlocked

MAX_FRAME = 2_000_000


def decode_queue_frame(encoded):
    import msgpack
    import lz4.block
    if not isinstance(encoded,str) or len(encoded)>MAX_FRAME*2:
        return None
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)<10 or raw[0]!=10 or int.from_bytes(raw[4:6],'big')!=49:
            return None
        size=int.from_bytes(raw[7:10],'big')
        if not size or size!=len(raw)-10 or size>MAX_FRAME:return None
        data=raw[10:]
        if raw[6]:
            bound=size*raw[6]
            if bound>MAX_FRAME:return None
            data=lz4.block.decompress(data,uncompressed_size=bound)
        def integer(code,body):
            if code!=1 or len(body)>9:raise ValueError('unsupported integer extension')
            value=msgpack.unpackb(body,raw=False)
            if type(value)!=int:raise ValueError('invalid integer extension')
            return value
        value=msgpack.unpackb(data,raw=False,strict_map_key=False,ext_hook=integer,
            max_array_len=1000,max_map_len=1000,max_str_len=100000,max_bin_len=MAX_FRAME,max_ext_len=9)
        if not isinstance(value,dict):return None
        return dict(sequence=int.from_bytes(raw[2:4],'big'),payload=value)
    except (ValueError,TypeError,UnicodeError,lz4.block.LZ4BlockError):
        return None


def queue_items(payload,target):
    if payload.get('chatId')!=int(target) or len(payload['messages'])>100:
        raise MaxBlocked('native_queue_scope_or_bound')
    result=[];ids=set()
    for raw in payload['messages']:
        if not isinstance(raw,dict):raise MaxBlocked('native_queue_schema')
        identity=raw.get('id');text=raw.get('text','');at=raw.get('delayedAttributes',{}).get('timeToFire')
        if (type(identity)!=int or identity<=0 or identity in ids or not isinstance(text,str)
                or type(at)!=int or at<=0 or not math.isfinite(at/1000)
                or not isinstance(raw.get('attaches',[]),list)):
            raise MaxBlocked('native_queue_schema')
        ids.add(identity)
        # No sender/account identity, signed URLs or unrelated messages retained.
        result.append(dict(id=str(identity),text=text,time_ms=at,
            media_count=len(raw.get('attaches',[])),status=raw.get('status'),correlation_id=str(raw['cid']) if type(raw.get('cid')) is int else None,
            elements=raw.get('elements',[])))
    return result


class QueueObserver:
    def __init__(self,page,target,origin,pages=()):
        self.page,self.target,self.origin=page,target,origin
        self.pages=tuple(pages) or (page,);self.sessions=[];self.sources={};self.pending={}
        self.rows=None;self.error=None;self.event=asyncio.Event()

    async def __aenter__(self):
        for index,page in enumerate(self.pages):
            session=await page.context.new_cdp_session(page)
            self.sessions.append(session)
            session.on('Network.webSocketFrameSent',lambda event,index=index:self._sent(event,index))
            session.on('Network.webSocketFrameReceived',lambda event,index=index:self._received(event,index))
            await session.send('Network.enable')
        return self

    def _frame(self,event,index):
        if self.page.url!=self.origin+'/'+self.target:return None,None
        response=event.get('response',{})
        if response.get('opcode')!=2:return None,None
        frame=decode_queue_frame(response.get('payloadData'))
        if frame is None:return None,None
        return (index,event.get('requestId'),frame['sequence']),frame['payload']

    def _sent(self,event,index=0):
        key,payload=self._frame(event,index)
        if payload is None:return
        if (payload.get('chatId')==int(self.target) and payload.get('itemType')=='DELAYED'
                and payload.get('from')==1 and type(payload.get('forward'))==int
                and 1<=payload['forward']<=1000 and len(self.pending)<100):
            self.pending[key]=payload['forward']

    def _received(self,event,index=0):
        key,payload=self._frame(event,index)
        if payload is None or key not in self.pending:return
        count=self.pending.pop(key)
        self.sources[index]=self.sources.get(index,0)+1
        try:
            if not isinstance(payload.get('messages'),list) or len(payload['messages'])>=count:
                raise MaxBlocked('native_queue_incomplete')
            self.rows=queue_items(dict(payload,chatId=int(self.target)),self.target)
        except MaxBlocked as exc:self.error=exc
        self.event.set()

    async def wait(self,timeout):
        await asyncio.wait_for(self.event.wait(),timeout)
        if self.error:raise self.error
        return self.rows

    async def __aexit__(self,*_):
        for session in self.sessions:await session.detach()
