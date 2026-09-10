"""Deterministic subprocess double for Codex exec. Never a real model/backend."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
from PIL import Image

scenario, directory = sys.argv[1:3]
args = sys.argv[3:]
state = Path(directory)
state.mkdir(parents=True, exist_ok=True)
if args == ['--version']:
    print('scripted-codex 1'); raise SystemExit(0)
if args == ['exec', '--help']:
    print('--json --output-schema --output-last-message --cd --skip-git-repo-check --sandbox --model --profile --image')
    raise SystemExit(0)
assert args[0] == 'exec' and args[-1] == '-'
with (state/'effects').open('a') as log:
    log.write('one-scripted-exec\n');log.flush();os.fsync(log.fileno())
(state/'pid').write_text(str(os.getpid()))
prompt = sys.stdin.read()
job = json.loads(prompt.split('\nJOB_JSON\n')[1])
assert '$imagegen' in prompt
assert args[args.index('--sandbox')+1] == 'read-only'
assert args[args.index('--model')+1] == 'gpt-5.6-luna'
assert json.loads(Path(args[args.index('--output-schema')+1]).read_text())['properties']['job_key']['const'] == job['job_key']
images = [args[i+1] for i,v in enumerate(args) if v == '--image']
assert len(images) == len(job['sources'])
for path, source in zip(images, job['sources']):
    assert path == source['path'] and hashlib.sha256(Path(path).read_bytes()).hexdigest() == source['sha256']
(state/'seen.json').write_text(json.dumps({'job':job,'env_names':sorted(os.environ),'images':images}))

def emit(event):
    print(json.dumps(event), flush=True)

thread = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
emit({'type':'thread.started','thread_id':thread})
emit({'type':'turn.started'})
if scenario == 'bad_tool':
    emit({'type':'item.started','item':{'id':'tool','type':'command_execution','command':'forbidden'}})
    time.sleep(20)
if scenario == 'huge':
    print('x'*100000, flush=True); time.sleep(20)
if scenario == 'hang':
    time.sleep(20)
if scenario == 'bad_json':
    print('not json',flush=True); raise SystemExit(1)
if scenario == 'exit':
    raise SystemExit(2)
root = Path(os.environ['CODEX_HOME'])/'generated_images'/thread
work = Path(args[args.index('--cd')+1])
if scenario == 'workspace': root = work/'generated_images'
if scenario == 'foreign_thread': root = root.parent/'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
if scenario == 'foreign_root': root = state/'foreign'
root.mkdir(parents=True, exist_ok=True)
paths = []
for n in range(job['candidate_budget']+(1 if scenario == 'over_budget' else 0)):
    path = root/f'fixture-{n}.png'
    buffer = io.BytesIO();Image.new('RGB',(80,100)).save(buffer,format='PNG')
    path.write_bytes(buffer.getvalue() if scenario != 'bad_image' else b'not an image')
    if scenario == 'symlink':
        other = state/f'outside-{n}.png';other.write_bytes(buffer.getvalue());path.unlink();path.symlink_to(other)
    if scenario == 'hardlink': os.link(path, state/f'hardlink-{n}.png')
    paths.append(str(path))
if scenario == 'duplicate': paths = paths*2
if scenario == 'missing': paths = []
if scenario == 'traversal': paths = [str(root/'..'/root.name/'fixture-0.png')]
if scenario == 'dir_symlink':
    real = state/'saved'; root.rename(real); root.symlink_to(real, target_is_directory=True)
report = {'job_key':job['job_key'], 'input_digest':job['input_digest'], 'saved_paths':paths}
if scenario == 'wrong_binding': report['input_digest'] = '0'*64
if scenario == 'extra_keys': report['actual_model']='guessed-model'
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(report))
message = dict(report)
if scenario == 'report_mismatch': message['saved_paths']=[]
emit({'type':'item.completed','item':{'id':'message','type':'agent_message','text':json.dumps(message)}})
if scenario == 'no_terminal': raise SystemExit(0)
emit({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':20,'cached_input_tokens':0}})
if scenario == 'after_terminal': emit({'type':'turn.started'})
