const API='https://api.github.com/repos/soojh007/football-shorts-factory';
export const ACTIONS_URL='https://github.com/soojh007/football-shorts-factory/actions/workflows/create-prediction.yml';
const WORKFLOW='create-prediction.yml';
export function readiness(match,now=Date.now()){
 const seconds=(Date.parse(match.kickoff)-now)/1000;
 if(!Number.isSafeInteger(match.fixture_id)||match.fixture_id<=0||!Number.isFinite(seconds))return {ready:false,message:'Invalid fixture'};
 if(seconds<=0)return {ready:false,message:'Kickoff passed'};
 if(seconds>7200)return {ready:false,message:'Opens within 2h of kickoff'};
 return {ready:true,message:'Create video'};
}
export class WorkflowConnection{
 #token='';#ready=false;#fetch;#states=new Map();#generation=0;
 constructor(fetchImpl=globalThis.fetch.bind(globalThis)){this.#fetch=fetchImpl;}
 get connected(){return this.#ready&&Boolean(this.#token);}
 state(fixtureId){return this.#states.get(fixtureId)||null;}
 disconnect(){this.#generation++;this.#token='';this.#ready=false;}
 async #request(path,options={}){
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);
  try{return await this.#fetch(API+path,{...options,credentials:'omit',referrerPolicy:'no-referrer',redirect:'error',cache:'no-store',signal:controller.signal,
   headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10',Authorization:'Bearer '+this.#token,...options.headers}});}
  finally{clearTimeout(timer);}
 }
 async connect(token){
  this.disconnect();const generation=this.#generation;
  const check=()=>{if(this.#generation!==generation)throw Error('The connection was locked. Unlock or connect again.');};
  if(typeof token!=='string'||!/^github_pat_[A-Za-z0-9_]{20,500}$/.test(token.trim()))throw Error('Use a fine-grained GitHub token for this repository, with Actions: read and write.');
  this.#token=token.trim();
  try{
   const repo=await this.#request('');check();
   if(repo.status===401)throw Error('GitHub rejected this token. Check its expiry and try a new token.');
   if(!repo.ok)throw Error('This token cannot access football-shorts-factory. Select only this repository when creating it.');
   const workflow=await this.#request('/actions/workflows/'+WORKFLOW);check();
   if(!workflow.ok)throw Error('Allow Actions: read and write for football-shorts-factory.');
   const data=await workflow.json();check();
   if(data.state!=='active')throw Error('The prediction workflow is disabled on GitHub.');
   this.#ready=true;return true;
  }catch(error){if(this.#generation===generation)this.disconnect();throw Error(error instanceof TypeError||error.name==='AbortError'?'Could not connect to GitHub. Check your connection and try again.':error.message);}
 }
 async create(match,{validateOnly=false,now=Date.now()}={}){
  if(!this.connected)throw Error('Connect GitHub first.');
  const gate=readiness(match,now);if(!gate.ready)throw Error(gate.message);
  if(this.#states.has(match.fixture_id))throw Error('This fixture already has a request in this page session. Check its Actions run.');
  this.#states.set(match.fixture_id,{status:'sending'});
  let response;
  try{
   response=await this.#request('/actions/workflows/'+WORKFLOW+'/dispatches',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ref:'main',return_run_details:true,inputs:{match:String(match.fixture_id),auto_retry:!validateOnly,validate_only:validateOnly}})});
  }catch{
   this.#states.set(match.fixture_id,{status:'uncertain',url:ACTIONS_URL});
   throw Error('GitHub may have received the request. Check Actions before starting another run; this page will not retry automatically.');
  }
  if(response.status!==200&&response.status!==204){
   this.#states.delete(match.fixture_id);
   if(response.status===401){this.disconnect();throw Error('Your GitHub connection expired. Connect again.');}
   if(response.status===403)throw Error('GitHub denied the request. Check Actions: read and write and any repository approval requirements.');
   if(response.status===422)throw Error('GitHub could not start the current main workflow. Refresh this page or use Run workflow on GitHub.');
   if(response.status===429)throw Error('GitHub is rate limiting requests. Wait before trying again.');
   if(response.status>=500){this.#states.set(match.fixture_id,{status:'uncertain',url:ACTIONS_URL});throw Error('GitHub returned a server error. Check Actions before retrying this fixture.');}
   throw Error('GitHub did not accept the request. Check Actions before retrying.');
  }
  let url=ACTIONS_URL;
  if(response.status===200){
   try{const data=await response.json();const candidate=new URL(data.html_url);if(candidate.origin==='https://github.com'&&/^\/soojh007\/football-shorts-factory\/actions\/runs\/\d+$/.test(candidate.pathname))url=candidate.href;}catch{/* Accepted dispatch without readable run details still must not be retried. */}
  }
  const result={status:'accepted',url};this.#states.set(match.fixture_id,result);return result;
 }
}
