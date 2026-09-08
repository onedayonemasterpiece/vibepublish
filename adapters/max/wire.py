"""Passive native queue evidence from requests made by the owned MAX Web page.

Never sends a MAX request, intercepts/modifies traffic, reads app state/storage,
logs raw frames or decodes authentication traffic. UI drives every operation.
The observed v10 envelope uses bounded LZ4 + MessagePack with integer extension1.
Only history (49) and own-reaction read (180) frames are decoded.
A scheduled response is retained only
after matching its socket/sequence to the UI request with itemType=DELAYED and
the exact authorized chatId. No raw frame is logged or sent by this module.
"""
from __future__ import annotations
import asyncio
import base64
import math

from .profile import MaxBlocked

MAX_FRAME = 2_000_000


def decode_queue_frame(encoded, *, opcode=49):
    import msgpack
    import lz4.block
    if opcode not in (49,180) or not isinstance(encoded,str) or len(encoded)>MAX_FRAME*2:
        return None
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)<10 or raw[0]!=10 or int.from_bytes(raw[4:6],'big')!=opcode:
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



def published_wire_id(copied_native_id):
    """Decode a copied native link's canonical 8-byte ID; never create a URL."""
    if not isinstance(copied_native_id,str) or len(copied_native_id)!=11:
        raise MaxBlocked('native_link_id_unverified')
    try:
        raw=base64.b64decode(copied_native_id+'=',altchars=b'-_',validate=True)
        if len(raw)!=8 or base64.urlsafe_b64encode(raw).decode().rstrip('=')!=copied_native_id:
            raise ValueError()
        value=int.from_bytes(raw,'big')
        if value<=0:raise ValueError()
        return str(value)
    except (ValueError,TypeError):
        raise MaxBlocked('native_link_id_unverified') from None


def own_reactions(value):
    """Only explicit native reactionInfo can prove presence or absence."""
    if not isinstance(value,dict):raise MaxBlocked('native_reactions_unverified')
    own=value.get('yourReaction')
    if own is None:return []
    if not isinstance(own,str) or not 0<len(own)<=100:raise MaxBlocked('native_reaction_schema')
    return [own]


def native_link(value, depth=0):
    """Retain only native relationship coordinates, never sender/account data."""
    if not isinstance(value,dict) or depth>2:return None
    result={}
    for key in ('type','id','chatId','messageId','message','chat'):
        if key not in value:continue
        current=value[key]
        if isinstance(current,dict):result[key]=native_link(current,depth+1)
        elif current is None or type(current) in (str,int):result[key]=current
    return result


class HistoryObserver(QueueObserver):
    """Passive feed history requested by our exact target's normal UI."""
    def _sent(self,event,index=0):
        key,payload=self._frame(event,index)
        if payload is None:return
        if (payload.get('chatId')==int(self.target) and payload.get('itemType') in (None,'MESSAGE')
                and payload.get('getMessages') is True and len(self.pending)<100):
            self.pending[key]=True

    def _received(self,event,index=0):
        key,payload=self._frame(event,index)
        if payload is None or key not in self.pending:return
        self.pending.pop(key)
        try:
            rows=payload.get('messages')
            if not isinstance(rows,list) or len(rows)>200:raise MaxBlocked('native_history_bound')
            result=[];ids=set()
            for row in rows:
                if (not isinstance(row,dict) or type(row.get('id')) is not int
                        or row['id'] <= 0 or row['id'] in ids
                        or not isinstance(row.get('text',''),str)
                        or not isinstance(row.get('attaches',[]),list)):
                    raise MaxBlocked('native_history_schema')
                ids.add(row['id'])
                content=row
                link=row.get('link')
                if isinstance(link,dict) and link.get('type')=='FORWARD':
                    content=link.get('message')
                    if (not isinstance(content,dict) or not isinstance(content.get('text',''),str)
                            or not isinstance(content.get('attaches',[]),list)
                            or row.get('text') or row.get('attaches')):
                        raise MaxBlocked('native_forward_body_unverified')
                result.append(dict(id=str(row['id']),text=content.get('text',''),time_ms=row.get('time'),
                    link=native_link(row.get('link')),media_count=len(content.get('attaches',[])),
                    **({'own_reactions':own_reactions(row['reactionInfo'])} if 'reactionInfo' in row else {})))
            self.rows=result
        except (TypeError,ValueError,MaxBlocked):self.error=MaxBlocked('native_history_unverified')
        self.event.set()


class ReactionObserver(QueueObserver):
    """Observe own-reaction metadata from UI-generated opcode180 reads only."""
    def __init__(self,page,target,origin,pages=(),*,native_item):
        super().__init__(page,target,origin,pages)
        self.native_item=native_item

    def _frame(self,event,index):
        if self.page.url!=self.origin+'/'+self.target:return None,None
        response=event.get('response',{})
        if response.get('opcode')!=2:return None,None
        frame=decode_queue_frame(response.get('payloadData'),opcode=180)
        if frame is None:return None,None
        return (index,event.get('requestId'),frame['sequence']),frame['payload']

    def _sent(self,event,index=0):
        key,payload=self._frame(event,index)
        if payload is None:return
        ids=payload.get('messageIds')
        if (payload.get('chatId')==int(self.target) and isinstance(ids,list) and len(ids)<=200
                and self.native_item in [str(value) for value in ids] and len(self.pending)<100):
            self.pending[key]=True

    def _received(self,event,index=0):
        key,payload=self._frame(event,index)
        if payload is None or key not in self.pending:return
        self.pending.pop(key)
        values=payload.get('messagesReactions')
        if not isinstance(values,dict) or len(values)>200:
            self.error=MaxBlocked('native_reactions_unverified')
        else:
            own=next((value for key,value in values.items() if str(key)==self.native_item),{})
            if not isinstance(own,dict):self.error=MaxBlocked('native_reactions_unverified')
            else:
                value=own.get('yourReaction')
                if value is not None and (not isinstance(value,str) or not 0<len(value)<=100):
                    self.error=MaxBlocked('native_reaction_schema')
                else:self.rows=dict(native_id=self.native_item,your_reaction=value)
        self.event.set()
