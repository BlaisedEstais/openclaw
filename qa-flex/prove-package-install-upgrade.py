"""Install a candidate package fresh and over the exact npm latest stable.

Intended for a disposable secretless GitHub Actions runner. Uses normal npm
package lifecycle scripts and the installed CLI, with separate install/state
prefixes. No global install, operator HOME, real credentials or Gateway.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--node', default='node')
    parser.add_argument('--npm', default='npm')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stable-version')
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    assert hashlib.sha256(candidate.read_bytes()).hexdigest()==args.candidate_sha256, 'candidate hash mismatch'
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('OPENAI_', 'ANTHROPIC_', 'GOOGLE_', 'GEMINI_', 'OPENROUTER_', 'OPENCLAW_', 'QA_FLEX_', 'QA_OPENCLAW_')) or key=='NODE_OPTIONS':
            env.pop(key,None)
    home = output/'home'
    home.mkdir()
    env.update({'HOME':str(home),'npm_config_cache':str(output/'npm-cache'),'npm_config_userconfig':str(home/'npmrc'),'npm_config_globalconfig':str(home/'global-npmrc')})
    if Path(args.node).is_absolute():
        env['PATH'] = str(Path(args.node).parent)+os.pathsep+env.get('PATH','')
    metadata_url = 'https://registry.npmjs.org/openclaw/'+(args.stable_version or 'latest')
    with urllib.request.urlopen(metadata_url,timeout=30) as response:
        metadata = json.load(response)
    stable_version = metadata['version']
    assert not args.stable_version or stable_version==args.stable_version
    pin = {'version':stable_version,'tarball':metadata['dist']['tarball'],'integrity':metadata['dist']['integrity']}
    (output/'stable-pin.json').write_text(json.dumps(pin,indent=2)+'\n')
    with urllib.request.urlopen(pin['tarball'],timeout=120) as response:
        stable_bytes = response.read()
    algorithm,encoded = pin['integrity'].split('-',1)
    assert base64.b64encode(hashlib.new(algorithm,stable_bytes).digest()).decode()==encoded, 'stable integrity mismatch'
    stable_tgz = output/'stable.tgz'
    stable_tgz.write_bytes(stable_bytes)
    commands=[]

    def run(command, label, command_env=None, timeout=900):
        with (output/(label+'.stdout')).open('w') as stdout, (output/(label+'.stderr')).open('w') as stderr:
            result = subprocess.run(command,env=command_env or env,cwd=output,stdout=stdout,stderr=stderr,timeout=timeout)
        commands.append({'step':label,'exitCode':result.returncode})
        if result.returncode:
            raise RuntimeError(label+' failed; see its captured logs')

    def install(prefix, tgz, label):
        run([args.npm,'install','--prefix',str(prefix),'--no-audit','--no-fund','--package-lock=false','--loglevel=error',str(tgz)],label)
        return prefix/'node_modules'/'openclaw'

    fresh = install(output/'fresh-prefix',candidate,'fresh-install')
    run([sys.executable,str(Path(__file__).with_name('prove-flex-cli.py')),'--root',str(fresh),'--node',args.node,'--output',str(output/'fresh-agent'),'--delay-ms','1'],'fresh-agent',timeout=360)
    upgrade_prefix = output/'upgrade-prefix'
    installed = install(upgrade_prefix,stable_tgz,'stable-install')
    state = output/'saved-state'
    state.mkdir()
    config = output/'saved-config.json'
    upgrade_env = {**env,'OPENCLAW_HOME':str(state),'OPENCLAW_STATE_DIR':str(state),'OPENCLAW_CONFIG_PATH':str(config)}
    settings = {'agents':{'defaults':{'model':'openai/gpt-5.5','thinkingDefault':'high','timeoutSeconds':321,'userTimezone':'Europe/Paris','models':{'openai/gpt-5.5':{'agentRuntime':{'id':'openclaw'},'params':{'serviceTier':'flex','maxTokens':512,'transport':'sse','responsesServerCompaction':False}}},'contextInjection':'never'}},'tools':{'deny':['*'],'web':{'search':{'enabled':False}},'toolSearch':False},'plugins':{'allow':['openai']}}
    operations = [{'path':key,'value':value} for key,value in settings.items()]
    run([args.node,str(installed/'openclaw.mjs'),'config','set','--batch-json',json.dumps(operations)],'stable-save-settings',upgrade_env)
    run([args.node,str(installed/'openclaw.mjs'),'config','get','agents.defaults','--json'],'stable-read-settings',upgrade_env)
    before = json.loads((output/'stable-read-settings.stdout').read_text())
    upgraded = install(upgrade_prefix,candidate,'upgrade-install')
    run([args.node,str(upgraded/'openclaw.mjs'),'config','get','agents.defaults','--json'],'upgraded-read-settings',upgrade_env)
    after = json.loads((output/'upgraded-read-settings.stdout').read_text())
    assert before==after, 'saved defaults changed across package upgrade'
    run([sys.executable,str(Path(__file__).with_name('prove-flex-cli.py')),'--root',str(upgraded),'--node',args.node,'--output',str(output/'upgraded-agent'),'--config-file',str(config),'--ambient-state',str(state),'--delay-ms','1'],'upgraded-agent',timeout=360)
    run([args.node,str(upgraded/'openclaw.mjs'),'config','get','agents.defaults','--json'],'final-read-settings',upgrade_env)
    assert json.loads((output/'final-read-settings.stdout').read_text())==before, 'agent changed saved defaults'
    summary = {'stable':pin,'candidateSha256':args.candidate_sha256,'freshAgentPassed':True,'upgradedAgentPassed':True,'savedDefaultsPreserved':True,'commands':commands,'paidRequests':0,'scope':'npm package installs + real CLI/agent; external response is synthetic'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':
    main()
