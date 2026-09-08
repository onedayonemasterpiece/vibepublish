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


def social_observer(kind):
    from types import SimpleNamespace
    from adapters.max.wire import HistoryObserver,ReactionObserver
    page=SimpleNamespace(url='https://web.max.ru/-101')
    if kind=='history':return HistoryObserver(page,'-101','https://web.max.ru')
    return ReactionObserver(page,'-101','https://web.max.ru',native_item='42')


def social_event(value,*,opcode=49,socket='owned'):
    return {'requestId':socket,'response':{'opcode':2,'payloadData':packet(value,opcode=opcode)}}


@pytest.mark.parametrize('kind',['history','reaction'])
def test_social_read_requires_exact_target_owned_socket_and_page(kind):
    o=social_observer(kind);opcode=49 if kind=='history' else 180
    request={'chatId':-101,'getMessages':True,'messageIds':[42]}
    response={'messages':[{'id':42,'text':'Owned'}]} if kind=='history' else {'messagesReactions':{'42':{'yourReaction':'👍'}}}
    o._received(social_event(response,opcode=opcode));assert o.rows is None
    o._sent(social_event(dict(request,chatId=-202),opcode=opcode))
    o._received(social_event(response,opcode=opcode));assert o.rows is None
    o._sent(social_event(request,opcode=opcode))
    o._received(social_event(response,opcode=opcode,socket='other'));assert o.rows is None
    o._received(social_event(response,opcode=opcode),index=1);assert o.rows is None
    o._received(social_event(response,opcode=opcode));assert o.rows is not None


@pytest.mark.parametrize('bad',[True,{},[],1,'', 'x'*101])
def test_reaction_metadata_is_not_guessed_or_coerced(bad):
    o=social_observer('reaction')
    o._sent(social_event({'chatId':-101,'messageIds':[42]},opcode=180))
    o._received(social_event({'messagesReactions':{'42':{'yourReaction':bad}}},opcode=180))
    assert o.rows is None and o.error


def test_only_correlated_explicit_read_can_prove_empty_own_reactions():
    o=social_observer('reaction')
    o._sent(social_event({'chatId':-101,'messageIds':[99]},opcode=180))
    o._received(social_event({'messagesReactions':{}},opcode=180));assert o.rows is None
    o._sent(social_event({'chatId':-101,'messageIds':[42]},opcode=180))
    o._received(social_event({'messagesReactions':{}},opcode=180))
    assert o.rows=={'native_id':'42','your_reaction':None}


def test_history_relationship_projection_excludes_account_body_and_urls():
    o=social_observer('history')
    o._sent(social_event({'chatId':-101,'getMessages':True}))
    o._received(social_event({'messages':[{'id':42,'text':'Owned','sender':999,
        'link':{'type':'REPLY','message':{'id':21,'sender':888,'text':'private','url':'secret'}}}]}))
    assert o.rows[0]['link']=={'type':'REPLY','message':{'id':21}}
    assert 'sender' not in o.rows[0]


@pytest.mark.parametrize('rows',[[{'id':True}],[{'id':-1}],[{'id':42},{'id':42}],[{'id':42,'text':{}}],[{'id':42,'attaches':{}}]])
def test_history_malformed_or_duplicated_identity_is_rejected(rows):
    o=social_observer('history');o._sent(social_event({'chatId':-101,'getMessages':True}))
    o._received(social_event({'messages':rows}));assert o.rows is None and o.error


def test_decoder_cannot_be_repurposed_for_auth_or_mutation():
    for opcode in (18,178,179):
        assert decode_queue_frame(packet({'private':'data'},opcode=opcode),opcode=opcode) is None


def test_published_link_identity_decodes_without_fabricating_urls():
    from adapters.max.wire import published_wire_id
    for n in [1,2**61+37]:
        copied=base64.urlsafe_b64encode(n.to_bytes(8,'big')).decode().rstrip('=')
        assert published_wire_id(copied)==str(n)
    for bad in ['https://max.ru/c/-101/item','42','AAAAAAAAAAA','!!!!!!!!!!!','AAAAAAAAAAB']:
        with pytest.raises(MaxBlocked):published_wire_id(bad)


@pytest.mark.parametrize('info,expected',[(None,None),({},[]),({'yourReaction':'👍'},['👍'])])
def test_history_only_explicit_reaction_info_proves_own_state(info,expected):
    o=social_observer('history');o._sent(social_event({'chatId':-101,'getMessages':True}))
    row={'id':42,'text':'Owned'}
    if info is not None:row['reactionInfo']=info
    o._received(social_event({'messages':[row]}))
    assert o.rows[0].get('own_reactions')==expected
    assert ('own_reactions' in o.rows[0])==(info is not None)
