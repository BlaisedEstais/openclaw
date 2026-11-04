"""Full packaged CLI watchdog proof with a synthetic delayed Responses transport.

Runs the real agent, request assembly, SDK, watchdog, transcript and CLI. The
external response is synthetic, with no API key or paid request. Timers in the
product are real. This is not live provider capacity evidence.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--node', default='node')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tier', choices=['flex', 'default'], default='flex')
    parser.add_argument('--delay-ms', type=int, default=130_000)
    parser.add_argument('--expect', choices=['success', 'timeout'], default='success')
    parser.add_argument('--legacy-opt-in', action='store_true')
    parser.add_argument('--config-file', type=Path)
    parser.add_argument('--ambient-state', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    proof = args.output.resolve()
    proof.mkdir(parents=True, exist_ok=False)
    for name in ['state', 'ambient', 'workspace']:
        (proof/name).mkdir()
    (proof/'workspace'/'.openclaw').mkdir()
    (proof/'workspace'/'.openclaw'/'settings.json').write_text(json.dumps({'retry':{'provider':{'maxRetries':0}}})+'\n')
    params = {'serviceTier':args.tier,'maxTokens':512,'transport':'sse','responsesServerCompaction':False}
    if args.legacy_opt_in:
        params['flexProcessing'] = True
    cfg = {'agents':{'defaults':{'model':'openai/gpt-5.5','thinkingDefault':'high','models':{'openai/gpt-5.5':{'agentRuntime':{'id':'openclaw'},'params':params}},'contextInjection':'never'}},'tools':{'deny':['*'],'web':{'search':{'enabled':False}},'toolSearch':False},'plugins':{'allow':['openai']}}
    config = args.config_file.resolve() if args.config_file else proof/'config.json'
    if not args.config_file:
        config.write_text(json.dumps(cfg,indent=2)+'\n')
    ambient = args.ambient_state.resolve() if args.ambient_state else proof/'ambient'
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('OPENAI_', 'ANTHROPIC_', 'GOOGLE_', 'GEMINI_', 'OPENROUTER_', 'OPENCLAW_')) or key == 'NODE_OPTIONS':
            env.pop(key,None)
    env.update({'HOME':str(proof/'ambient'),'XDG_CONFIG_HOME':str(proof/'ambient'/'config'),'XDG_CACHE_HOME':str(proof/'ambient'/'cache'),'OPENAI_API_KEY':'synthetic-test-key-not-a-secret','OPENCLAW_HOME':str(ambient),'OPENCLAW_STATE_DIR':str(ambient),'OPENCLAW_CONFIG_PATH':str(config),'QA_OPENCLAW_ROOT':str(root),'QA_FLEX_PROOF_DIR':str(proof),'QA_FLEX_DELAY_MS':str(args.delay_ms),'QA_FLEX_EXPECTED_TIER':args.tier,'NODE_OPTIONS':'--require='+json.dumps(str(Path(__file__).with_name('flex-cli-preload.cjs').resolve()))})
    node = Path(args.node)
    if node.is_absolute():
        env['PATH'] = str(node.parent)+os.pathsep+env.get('PATH','')
    command = [args.node,str(root/'openclaw.mjs'),'agent','exec','Reply exactly FLEX_WATCHDOG_PROOF_OK.','--config',str(config),'--model','openai/gpt-5.5','--thinking','high','--code-mode','direct','--cwd',str(proof/'workspace'),'--state-dir',str(proof/'state'),'--timeout','240','--json']
    started = time.monotonic()
    with (proof/'stdout.json').open('w') as out, (proof/'stderr.log').open('w') as err:
        child = subprocess.Popen(command,cwd=root,env=env,stdout=out,stderr=err,start_new_session=True)
        try:
            exit_code = child.wait(timeout=330)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(child.pid,signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL)
                child.wait()
            raise
    elapsed = round(time.monotonic()-started,3)
    events = [json.loads(line) for line in (proof/'transport.jsonl').read_text().splitlines()] if (proof/'transport.jsonl').exists() else []
    try:
        envelope = json.loads((proof/'stdout.json').read_text())
    except json.JSONDecodeError:
        envelope = {}
    requests = [event for event in events if event['event']=='request']
    aborts = [event for event in events if event['event']=='aborted']
    releases = [event for event in events if event['event']=='first-response-released']
    success = exit_code == 0 and envelope.get('ok') is True and envelope.get('final','').strip() == 'FLEX_WATCHDOG_PROOF_OK'
    abort_ms = aborts[0]['time']-requests[0]['time'] if requests and aborts else None
    valid = len(requests)==1 and not any(event['event']=='unexpected-network' for event in events)
    if args.expect=='success':
        valid = valid and success and len(releases)==1 and not aborts
        valid = valid and releases[0]['time']-requests[0]['time'] >= args.delay_ms-50
    else:
        valid = valid and not success and abort_ms is not None and 115_000 <= abort_ms <= 125_000 and not releases
    build_info = root/'dist'/'build-info.json'
    summary = {'scenario':'full CLI with synthetic delayed provider','expected':args.expect,'tier':args.tier,'delayMs':args.delay_ms,'exitCode':exit_code,'elapsedSeconds':elapsed,'success':success,'requestCount':len(requests),'abortAfterMs':abort_ms,'transportEvents':events,'valid':bool(valid),'paidRequests':0,'build':json.loads(build_info.read_text()) if build_info.exists() else None}
    (proof/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))
    if not valid:
        raise SystemExit(1)


if __name__=='__main__':
    main()
