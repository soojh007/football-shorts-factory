import {readiness,ACTIONS_URL} from './workflow-client.mjs';
// The browser stores neither a GitHub token nor refresh token. HttpOnly cookies are server-owned.
export class SessionConnection{
 #ready=false;#csrf='';#login='';#fetch;#states=new Map();
 constructor(fetchImpl=globalThis.fetch.bind(globalThis)){this.#fetch=fetchImpl;}
 get connected(){return this.#ready&&Boolean(this.#csrf);}
 get login(){return this.#login;}
 state(id){return this.#states.get(id)||null;}
 disconnect(){this.#ready=false;this.#csrf='';this.#login='';}
 async #request(path,options={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
  try{return await this.#fetch(path,{...options,credentials:'same-origin',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer',signal:controller.signal,
   headers:{Accept:'application/json',...options.headers}});}finally{clearTimeout(timer);}
 }
 async restore(){
  this.disconnect();
  const r=await this.#request('/api/session');if(!r.ok)throw Error('Could not check your GitHub sign-in. Reload the page.');
  const data=await r.json();
  if(!data.configured)throw Error('Secure sign-in is not configured yet.');
  if(data.authenticated){
   if(typeof data.csrf_token!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(data.csrf_token))throw Error('Invalid sign-in response. Sign in again.');
   this.#csrf=data.csrf_token;this.#login=String(data.login||'');this.#ready=true;
   for(const item of data.requests||[])if(Number.isSafeInteger(item.fixture_id)&&['accepted','sending','uncertain'].includes(item.state))this.#states.set(item.fixture_id,{status:item.state,url:this.#safeRun(item.run_url)});
  }
  return this.connected;
 }
 #safeRun(value){try{const u=new URL(value);return u.origin==='https://github.com'&&/^\/soojh007\/football-shorts-factory\/actions\/(runs\/\d+|workflows\/create-prediction.yml)$/.test(u.pathname)&&!u.search&&!u.hash?u.href:ACTIONS_URL;}catch{return ACTIONS_URL;}}
 async signOut(){
  if(!this.connected)return;
  const r=await this.#request('/auth/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.#csrf},body:'{}'});
  if(!r.ok&&r.status!==401)throw Error('Sign-out could not be confirmed. Try again.');
  this.disconnect();
 }
 async create(match,{now=Date.now()}={}){
  if(!this.connected)throw Error('Sign in with GitHub first.');
  const gate=readiness(match,now);if(!gate.ready)throw Error(gate.message);
  if(this.#states.has(match.fixture_id))throw Error('This fixture already has a request. Check its Actions run.');
  this.#states.set(match.fixture_id,{status:'sending'});
  let r,data;
  try{r=await this.#request('/api/dispatch',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':this.#csrf},body:JSON.stringify({fixture_id:match.fixture_id})});}
  catch{this.#states.set(match.fixture_id,{status:'uncertain',url:ACTIONS_URL});throw Error('The request may have reached GitHub. Check Actions before starting another run.');}
  try{data=await r.json();}catch{
   this.#states.set(match.fixture_id,{status:'uncertain',url:ACTIONS_URL});throw Error('Could not confirm the request. Check Actions before trying again.');
  }
  if(!r.ok){
   if(r.status===401)this.disconnect();
   if(r.status>=500){this.#states.set(match.fixture_id,{status:'uncertain',url:ACTIONS_URL});}
   else this.#states.delete(match.fixture_id);
   throw Error(typeof data.error==='string'?data.error:'The workflow request failed.');
  }
  const status=['accepted','sending','uncertain'].includes(data.status)?data.status:'uncertain';
  const result={status,url:this.#safeRun(data.url)};this.#states.set(match.fixture_id,result);
  if(status==='uncertain'||status==='sending')throw Error('A workflow request is pending or uncertain. Check Actions; no duplicate was started.');
  return result;
 }
}
