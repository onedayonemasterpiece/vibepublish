"""Bounded passive queue decoding, never an API client or synthetic native ID."""
import base64
import math
import msgpack
import lz4.block
import pytest
from adapters.max.wire import decode_queue_frame,queue_items,MAX_FRAME
from adapters.max.profile import MaxBlocked


def packet(value,opcode=49,compressed=False):
    body=msgpack.packb(value,use_bin_type=True);factor=0
    if compressed:
        encoded=lz4.block.compress(body,store_size=False);factor=math.ceil(len(body)/len(encoded));body=encoded
    return base64.b64encode(bytes([10,1])+b'\0\1'+opcode.to_bytes(2,'big')+bytes([factor])+len(body).to_bytes(3,'big')+body).decode()


@pytest.mark.parametrize('compressed',[False,True])
def test_queue_decodes_exact_native_integer_and_schedule(compressed):
    n=2**61+37
    message={'id':msgpack.ExtType(1,msgpack.packb(n)),'text':'Owned Unicode 😀','delayedAttributes':{'timeToFire':1893456000000},'attaches':[],'stats':{1:2}}
    payload=decode_queue_frame(packet({'chatId':-101,'messages':[message]},compressed=compressed))['payload']
    item=queue_items(payload,'-101')[0]
    assert item['id']==str(n) and item['time_ms']==1893456000000
    assert 'sender' not in item
    with pytest.raises(MaxBlocked,match='scope'):queue_items(payload,'-202')


def test_auth_other_opcode_and_malformed_frames_are_not_decoded():
    assert decode_queue_frame(packet({'auth':'never retain'},opcode=18)) is None
    for raw in [None,'%',base64.b64encode(b'bad').decode(),'x'*(MAX_FRAME*2+1)]:
        assert decode_queue_frame(raw) is None
    value=packet({'chatId':-101,'messages':[]})
    assert decode_queue_frame(value[:-4]) is None


def test_queue_requires_unique_provider_ids_and_bounded_items():
    message={'id':1,'text':'Owned','delayedAttributes':{'timeToFire':1893456000000}}
    for rows in [[message,message],[dict(message,id='invented')],[dict(message,delayedAttributes={})]]:
        with pytest.raises(MaxBlocked,match='schema'):queue_items({'chatId':-101,'messages':rows},'-101')


def test_response_requires_ui_delayed_request_same_socket_and_sequence():
    from types import SimpleNamespace
    from adapters.max.wire import QueueObserver
    page=SimpleNamespace(url='https://web.max.ru/-101')
    observer=QueueObserver(page,'-101','https://web.max.ru')
    def event(value,socket='owned'):
        return {'requestId':socket,'response':{'opcode':2,'payloadData':packet(value)}}
    request={'chatId':-101,'from':1,'forward':150,'getMessages':True,'itemType':'DELAYED'}
    response={'messages':[{'id':2,'text':'Owned','delayedAttributes':{'timeToFire':1893456000000}}]}
    observer._received(event(response))
    assert observer.rows is None
    observer._sent(event(dict(request,itemType='NORMAL')))
    observer._received(event(response))
    assert observer.rows is None
    observer._sent(event(dict(request,chatId=-202)))
    observer._received(event(response))
    assert observer.rows is None
    observer._sent(event(request))
    observer._received(event(response,socket='other'))
    observer._received(event(response),index=1)
    assert observer.rows is None
    observer._received(event(response))
    assert observer.rows[0]['id']=='2' and observer.rows[0]['time_ms']==1893456000000
    assert observer.event.is_set() and observer.pending=={}


def test_full_page_is_not_fabricated_complete_queue():
    from types import SimpleNamespace
    from adapters.max.wire import QueueObserver
    observer=QueueObserver(SimpleNamespace(url='https://web.max.ru/-101'),'-101','https://web.max.ru')
    def event(value):return {'requestId':'owned','response':{'opcode':2,'payloadData':packet(value)}}
    observer._sent(event({'chatId':-101,'from':1,'forward':1,'itemType':'DELAYED'}))
    observer._received(event({'messages':[{}]}))
    assert observer.rows is None and str(observer.error)=='native_queue_incomplete'
