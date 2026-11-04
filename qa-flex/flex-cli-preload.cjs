// QA-only external I/O fixture. No production policy/timer is replaced.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const undici = createRequire(path.join(process.env.QA_OPENCLAW_ROOT, 'package.json'))('undici/index.js');
const proofDir = process.env.QA_FLEX_PROOF_DIR;
const delayMs = Number(process.env.QA_FLEX_DELAY_MS);
const expectedTier = process.env.QA_FLEX_EXPECTED_TIER;
const marker = 'FLEX_WATCHDOG_PROOF_OK';
const record = (event, fields = {}) => fs.appendFileSync(path.join(proofDir, 'transport.jsonl'), JSON.stringify({event,time:Date.now(),...fields})+'\n');
let requestCount = 0;
const noNetwork = async (input, init) => {
  const url = new URL(input.url ?? String(input));
  if (url.origin !== 'https://api.openai.com' || url.pathname !== '/v1/responses' || (init?.method ?? input.method ?? 'GET').toUpperCase() !== 'POST') {
    record('unexpected-network', {origin:url.origin,path:url.pathname});
    throw new Error('QA fixture forbids all unexpected network requests');
  }
  requestCount++;
  const body = JSON.parse(typeof init.body === 'string' ? init.body : Buffer.from(init.body).toString('utf8'));
  record('request', {count:requestCount,model:body.model,tier:body.service_tier,reasoning:body.reasoning?.effort,tools:body.tools?.length ?? 0,dispatcherPresent:Boolean(init.dispatcher)});
  if (requestCount !== 1 || body.model !== 'gpt-5.5' || body.service_tier !== expectedTier || body.reasoning?.effort !== 'high' || (body.tools?.length ?? 0) !== 0 || !init.signal || !init.dispatcher) {
    return new undici.Response(JSON.stringify({error:{type:'invalid_request_error',code:'qa_shape_mismatch',message:'Unexpected QA request shape'}}), {status:400,headers:{'content-type':'application/json'}});
  }
  await new Promise((resolve,reject) => {
    let timer;
    const abort = () => {
      clearTimeout(timer);
      record('aborted', {reasonName:init.signal.reason?.name});
      reject(init.signal.reason ?? new DOMException('Aborted','AbortError'));
    };
    timer = setTimeout(() => {
      init.signal.removeEventListener('abort',abort);
      record('first-response-released',{delayMs});
      resolve();
    },delayMs);
    if (init.signal.aborted) abort();
    else init.signal.addEventListener('abort',abort,{once:true});
  });
  const message = {type:'message',id:'msg_flex_fixture',role:'assistant',status:'completed',content:[{type:'output_text',text:marker,annotations:[]}]};
  const events = [
    {type:'response.output_item.added',output_index:0,item:{...message,status:'in_progress',content:[]}},
    {type:'response.output_text.delta',item_id:message.id,output_index:0,content_index:0,delta:marker},
    {type:'response.output_text.done',item_id:message.id,output_index:0,content_index:0,text:marker},
    {type:'response.output_item.done',output_index:0,item:message},
    {type:'response.completed',response:{id:'resp_flex_fixture',model:'gpt-5.5',status:'completed',service_tier:expectedTier,output:[message],usage:{input_tokens:1,output_tokens:1,total_tokens:2}}},
  ];
  return new undici.Response(events.map(event=>'data: '+JSON.stringify(event)+'\n\n').join('')+'data: [DONE]\n\n', {status:200,headers:{'content-type':'text/event-stream','x-request-id':'synthetic-flex-watchdog-proof'}});
};
undici.fetch = noNetwork;
globalThis.fetch = noNetwork;
