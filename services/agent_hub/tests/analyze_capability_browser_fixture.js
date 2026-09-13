// Execute actual inline dashboard JS locally. No production or provider action.
const vm=require('vm'),fs=require('fs'),assert=require('assert');
const html=fs.readFileSync(0,'utf8');
// Drive bootstrap explicitly so the OIDC auto-start cannot race the controlled test clock.
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('renderQuestions();refreshAll();','renderQuestions();');
let instant=1000000,fetches=0;
const elements=new Map();
function node(id){if(!elements.has(id))elements.set(id,{value:'',disabled:true,textContent:'',innerHTML:'',dataset:{},className:'',style:{},addEventListener(){}});return elements.get(id)}
const shared=node('sharedAnalyze'),phase9=node('phase9Create'),recent=node('recentAnalyze'),feedback=node('feedback');
shared.disabled=/\bdisabled\b/.test(html.match(/<button[^>]*id="sharedAnalyze"[^>]*>/)[0]);
const old=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const oldNodes={sharedAnalyze:{disabled:/\bdisabled\b/.test(old.raw_shared_button_html)},phase9Create:{disabled:false},phase9AccessNote:{textContent:''}};
const oldContext={document:{querySelectorAll(){return []}},$:(id)=>oldNodes[id]};
vm.createContext(oldContext);
vm.runInContext("let currentRole='';const phase9FeedbackPending=new Set(),phase9FeedbackSubmitted=new Set();"+old.old_phase9_can_write+'\n'+old.old_phase9_access_setter+"\nsetPhase9Access('viewer');",oldContext);
assert.strictEqual(oldNodes.sharedAnalyze.disabled,false,'old exact markup/setter reproduces enabled Analyze');
assert.strictEqual(oldNodes.phase9Create.disabled,true,'old gate affects only Phase9 create');
const context={console,Date:class extends Date {static now(){return instant}},URLSearchParams,Set,Map,JSON,
 sessionStorage:{getItem(){return ''},setItem(){}},clearTimeout(){},setTimeout(){return 1},
 document:{hidden:false,getElementById:node,addEventListener(){},querySelectorAll(selector){return selector==='[data-analyze]'?[shared,recent]:selector==='[data-phase9-write]'?[feedback]:[]}},
 fetch:async()=>{fetches++;throw Error('local fixture network unavailable')},location:{},confirm(){throw Error('unexpected action')}};
vm.createContext(context);vm.runInContext(script,context);
const run=code=>vm.runInContext(code,context);
const good=role=>({role,subject:role,auth_method:'bearer',capability_version:1,capabilities:role==='viewer'?[]:['agent_tasks.analyze'],issued_at:1000,expires_at:1300});
function accept(payload){context.payload=payload;return run('acceptCapabilityBootstrap(payload,bootstrapGeneration)')}
assert(shared.disabled&&phase9.disabled,'loading must be fail-closed');
for(const role of ['viewer','operator','owner']){
 assert(accept(good(role)));assert.strictEqual(run('canAnalyze()'),role!=='viewer');
 assert.strictEqual(shared.disabled,role==='viewer');assert.strictEqual(recent.disabled,role==='viewer');
}
for(const bad of [null,{}, {role:'operator'}, {...good('operator'),capabilities:undefined},
 {...good('operator'),capabilities:'agent_tasks.analyze'}, {...good('operator'),capability_version:0},
 {...good('operator'),role:'admin'}, {...good('operator'),role:'unknown'}, {...good('operator'),subject:''},
 {...good('operator'),auth_method:'unknown'}, {...good('operator'),expires_at:1000},
 {...good('operator'),issued_at:1001}, {...good('operator'),expires_at:1400},
 {...good('operator'),capabilities:['agent_tasks.analyze','unknown']},
 {...good('operator'),capabilities:['agent_tasks.analyze','agent_tasks.analyze']}]){
 assert.strictEqual(accept(bad),false);assert(shared.disabled&&phase9.disabled&&recent.disabled);
}
assert(accept(good('operator')));instant=1300000;
assert.strictEqual(run('canAnalyze()'),false);run('syncAnalyzeAccess()');assert(shared.disabled&&recent.disabled);
instant=1000000;assert(accept(good('operator')));
run('bootstrapGeneration++;resetCapabilityAccess()');context.payload=good('operator');
assert.strictEqual(run('acceptCapabilityBootstrap(payload,bootstrapGeneration-1)'),false);assert(shared.disabled);
assert(accept(good('viewer')));shared.disabled=false;node('objective').value='Local Viewer test';
(async()=>{
 await run('createTask()');await run("reanalyze('fixture')");await run('createPhase9ReviewTask()');
 assert.strictEqual(fetches,0,'Viewer must never issue Analyze/Create HTTP from any entrypoint');
 assert(accept(good('operator')));run('resetCapabilityAccess()');assert(shared.disabled&&phase9.disabled);
 assert(accept(good('operator')));await run('refreshAll()');assert(shared.disabled&&recent.disabled);assert.strictEqual(run('currentRole'),'');
 console.log(JSON.stringify({status:'PASS',old_behavior:'shared Analyze enabled for Viewer',viewer_ui:'disabled',viewer_action_requests:0,
   operator_ui:'enabled with fresh server capability',owner_ui:'enabled with fresh server capability',
   loading_missing_stale_malformed_unknown_expiry_race_error:'FAIL_CLOSED',production_requests:0}));
})().catch(e=>{console.error(e);process.exitCode=1});
