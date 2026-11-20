// GitHub credentials stay encrypted on the server; browser receives an opaque session cookie.
const API='https://api.github.com',OAUTH='https://github.com/login/oauth/access_token';
const SESSION='__Host-factory_session',FLOW='__Host-factory_oauth';
const enc=new TextEncoder(),dec=new TextDecoder();
export class SafeError extends Error {constructor(status,message,clear=false){super(message);this.status=status;this.clear=clear;}}
const random=()=>b64(crypto.getRandomValues(new Uint8Array(32)));
function b64(bytes){return btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');}
function unb64(value){return Uint8Array.from(atob(value.replaceAll('-','+').replaceAll('_','/')),c=>c.charCodeAt(0));}
export async function hash(value){return b64(new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(value))));}
export async function seal(value,secret,aad){
 const key=await crypto.subtle.importKey('raw',unb64(secret),'AES-GCM',false,['encrypt']);
 const iv=crypto.getRandomValues(new Uint8Array(12));
 const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:enc.encode(aad)},key,enc.encode(JSON.stringify(value)));
 return b64(iv)+'.'+b64(new Uint8Array(encrypted));
}
export async function unseal(value,secret,aad){
 const [iv,data]=value.split('.');
 const key=await crypto.subtle.importKey('raw',unb64(secret),'AES-GCM',false,['decrypt']);
 return JSON.parse(dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:unb64(iv),additionalData:enc.encode(aad)},key,unb64(data))));
}
function cookie(name,value,age){return `${name}=${value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${age}`;}
function cookies(request){return Object.fromEntries((request.headers.get('Cookie')||'').split(';').map(s=>s.trim().split(/=(.*)/s)).filter(v=>v.length>1));}
function response(data,status=200,extra={}){return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',...extra}});}
function redirect(url,extra={}){return new Response(null,{status:303,headers:{Location:url,'Cache-Control':'no-store',...extra}});}
function configured(env){return Boolean(env.DB&&env.APP_ORIGIN&&env.GITHUB_CLIENT_ID&&env.GITHUB_CLIENT_SECRET&&env.TOKEN_ENCRYPTION_KEY&&env.ALLOWED_GITHUB_USER_ID&&env.REPOSITORY_ID);}
function secureHeaders(r){
 const headers=new Headers(r.headers);
 headers.set('X-Content-Type-Options','nosniff');headers.set('Referrer-Policy','no-referrer');
 headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");
 return new Response(r.body,{status:r.status,headers});
}
async function fetchTimed(fetchImpl,url,options={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 try{return await fetchImpl(url,{...options,redirect:'error',signal:controller.signal});}finally{clearTimeout(timer);}
}
async function github(fetchImpl,path,token,options={}){
 return fetchTimed(fetchImpl,API+path,{...options,headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10','User-Agent':'FootballShortsFactory',Authorization:'Bearer '+token,...options.headers}});
}
async function tokensFromGithub(env,fetchImpl,fields,now){
 let r;
 try{r=await fetchTimed(fetchImpl,OAUTH,{method:'POST',headers:{Accept:'application/json','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({client_id:env.GITHUB_CLIENT_ID,client_secret:env.GITHUB_CLIENT_SECRET,...fields})});}
 catch{throw new SafeError(401,'GitHub authorization could not be confirmed. Sign in again.',true);}
 let data;try{data=await r.json();}catch{throw new SafeError(401,'GitHub authorization returned an invalid response. Sign in again.',true);}
 if(!r.ok||typeof data.access_token!=='string'||!data.access_token||typeof data.refresh_token!=='string'||!data.refresh_token
    ||!Number.isFinite(data.expires_in)||data.expires_in<=0||!Number.isFinite(data.refresh_token_expires_in)||data.refresh_token_expires_in<=0)
  throw new SafeError(401,'GitHub authorization expired or was denied. Sign in again.',true);
 return {access_token:data.access_token,access_expires_at:now+data.expires_in,refresh_token:data.refresh_token,refresh_expires_at:now+data.refresh_token_expires_in};
}
async function sessionFor(request,env,now){
 const id=cookies(request)[SESSION];if(!id||!/^[A-Za-z0-9_-]{43}$/.test(id))return null;
 const row=await env.DB.prepare('SELECT * FROM sessions WHERE id_hash = ?').bind(await hash(id)).first();
 if(!row)return null;
 if(row.expires_at<=now){await env.DB.prepare('DELETE FROM sessions WHERE id_hash = ?').bind(row.id_hash).run();return null;}
 if(row.github_id!==String(env.ALLOWED_GITHUB_USER_ID))return null;
 return row;
}
async function accessToken(env,row,fetchImpl,now){
 let tokens;try{tokens=await unseal(row.encrypted_tokens,env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash);}catch{throw new SafeError(401,'This sign-in is no longer valid. Sign in again.',true);}
 if(tokens.access_expires_at>now+60)return tokens.access_token;
 if(tokens.refresh_expires_at<=now)throw new SafeError(401,'Your GitHub authorization expired. Sign in again.',true);
 const locked=await env.DB.prepare('UPDATE sessions SET refresh_lock_until = ? WHERE id_hash = ? AND refresh_lock_until <= ?').bind(now+60,row.id_hash,now).run();
 if(locked.meta.changes!==1)throw new SafeError(409,'Your sign-in is being refreshed. Wait a moment, then try again.');
 // Refresh tokens rotate: do not replay an uncertain refresh exchange.
 try{
  tokens=await tokensFromGithub(env,fetchImpl,{grant_type:'refresh_token',refresh_token:tokens.refresh_token},now);
  const saved=await env.DB.prepare('UPDATE sessions SET encrypted_tokens = ?, refresh_lock_until = 0 WHERE id_hash = ?').bind(await seal(tokens,env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash),row.id_hash).run();
  if(saved.meta.changes!==1)throw new SafeError(401,'Your session was signed out. Sign in again.',true);
  return tokens.access_token;
 }catch(error){await env.DB.prepare('DELETE FROM sessions WHERE id_hash = ?').bind(row.id_hash).run();throw error;}
}
function verifyWrite(request,url,row){
 if(request.headers.get('Origin')!==url.origin)throw new SafeError(403,'Request origin was not accepted.');
 if(request.headers.get('X-CSRF-Token')!==row.csrf_token)throw new SafeError(403,'Reload this page before trying again.');
 if(!(request.headers.get('Content-Type')||'').toLowerCase().startsWith('application/json'))throw new SafeError(415,'JSON request required.');
}
async function readBody(request){
 const reader=request.body?.getReader();if(!reader)throw new SafeError(400,'Request body required.');
 const decoder=new TextDecoder();let size=0,parts=[];
 try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>2048){await reader.cancel();throw new SafeError(413,'Request is too large.');}parts.push(decoder.decode(value,{stream:true}));}
  parts.push(decoder.decode());return JSON.parse(parts.join(''));
 }catch(e){if(e instanceof SafeError)throw e;throw new SafeError(400,'Invalid request body.');}
}
function validRunUrl(value,repo){try{const u=new URL(value);return u.origin==='https://github.com'&&new RegExp('^/'+repo+'/actions/runs/\\d+$').test(u.pathname)&&!u.search&&!u.hash?u.href:null;}catch{return null;}}
async function dispatch(request,url,env,row,fetchImpl,now){
 verifyWrite(request,url,row);
 const data=await readBody(request);
 if(!data||typeof data!=='object'||Array.isArray(data)||Object.keys(data).some(k=>k!=='fixture_id')||!Number.isSafeInteger(data.fixture_id)||data.fixture_id<=0)
  throw new SafeError(400,'Select a valid fixture from the available matches.');
 const fallback=`https://github.com/${env.REPOSITORY}/actions/workflows/create-prediction.yml`;
 const previous=await env.DB.prepare('SELECT * FROM dispatches WHERE fixture_id = ?').bind(data.fixture_id).first();
 if(previous)return response({status:previous.state,url:previous.run_url,already_requested:true});
 let schedule;
 try{const r=await fetchTimed(fetchImpl,env.ASSET_BASE_URL+'matches.json',{headers:{'Cache-Control':'no-cache'}});if(!r.ok)throw Error();schedule=await r.json();}
 catch{throw new SafeError(503,'The match schedule is temporarily unavailable. Try again later.');}
 const age=now-Date.parse(schedule.fetched_at)/1000;
 if(!Number.isFinite(age)||age < -60 ||age>2700)throw new SafeError(409,'The match schedule needs refreshing before starting a video. Refresh the schedule on GitHub.');
 const match=(schedule.matches||[]).find(m=>m.fixture_id===data.fixture_id);
 const seconds=match?(Date.parse(match.kickoff)/1000-now):NaN;
 if(!Number.isFinite(seconds)||seconds<=0||seconds>7200)throw new SafeError(409,'Choose a listed match starting within the next two hours.');
 const token=await accessToken(env,row,fetchImpl,now);
 const reserved=await env.DB.prepare("INSERT OR IGNORE INTO dispatches(fixture_id,state,run_url,created_at) VALUES (?,'sending',?,?)").bind(data.fixture_id,fallback,now).run();
 if(reserved.meta.changes!==1){const saved=await env.DB.prepare('SELECT * FROM dispatches WHERE fixture_id = ?').bind(data.fixture_id).first();return response({status:saved.state,url:saved.run_url,already_requested:true});}
 let r;
 try{r=await github(fetchImpl,`/repos/${env.REPOSITORY}/actions/workflows/create-prediction.yml/dispatches`,token,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ref:'main',return_run_details:true,inputs:{match:String(data.fixture_id),auto_retry:true,validate_only:false}})});}
 catch{await env.DB.prepare("UPDATE dispatches SET state = 'uncertain' WHERE fixture_id = ?").bind(data.fixture_id).run();return response({status:'uncertain',url:fallback},202);}
 if(r.status>=200&&r.status<300){
  let run=fallback;if(r.status===200){try{run=validRunUrl((await r.json()).html_url,env.REPOSITORY)||fallback;}catch{}}
  await env.DB.prepare("UPDATE dispatches SET state = 'accepted', run_url = ? WHERE fixture_id = ?").bind(run,data.fixture_id).run();
  return response({status:'accepted',url:run});
 }
 if(r.status>=500||r.status===408){await env.DB.prepare("UPDATE dispatches SET state = 'uncertain' WHERE fixture_id = ?").bind(data.fixture_id).run();return response({status:'uncertain',url:fallback},202);}
 await env.DB.prepare('DELETE FROM dispatches WHERE fixture_id = ?').bind(data.fixture_id).run();
 if(r.status===401){await env.DB.prepare('DELETE FROM sessions WHERE id_hash = ?').bind(row.id_hash).run();throw new SafeError(401,'Your GitHub sign-in expired or was revoked. Sign in again.',true);}
 if(r.status===403||r.status===404)throw new SafeError(403,'Allow this GitHub App Actions read/write access to football-shorts-factory.');
 if(r.status===429)throw new SafeError(429,'GitHub is rate limiting requests. Wait before trying again.');
 throw new SafeError(502,'GitHub did not accept this workflow request. Check Actions before retrying.');
}
export async function handle(request,env,{fetch:fetchImpl=globalThis.fetch,now:clock=Date.now}={}){
 const url=new URL(request.url),now=Math.floor(clock()/1000);
 let row=null;
 try{
  if(url.pathname==='/health')return secureHeaders(response({ok:true,configured:configured(env)}));
  if(env.APP_ORIGIN&&url.origin!==env.APP_ORIGIN)throw new SafeError(400,'This dashboard address was not accepted.');
  if(url.pathname==='/auth-config.json')return secureHeaders(response({backend_url:env.APP_ORIGIN||url.origin,same_origin_auth:true}));
  if(url.pathname==='/api/session'&&!configured(env))return secureHeaders(response({authenticated:false,configured:false,login_url:'/auth/login'}));
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/auth/')){
   if(!configured(env))throw new SafeError(503,'Secure GitHub sign-in is not configured yet.');
   row=await sessionFor(request,env,now);
  }
  if(url.pathname==='/auth/login'&&request.method==='GET'){
   const state=random(),verifier=random(),stateHash=await hash(state);
   const fixture=url.searchParams.get('fixture');const returnTo=fixture&&/^\d{1,15}$/.test(fixture)?'/?fixture='+fixture:'/';
   await env.DB.prepare('DELETE FROM auth_flows WHERE expires_at <= ?').bind(now).run();
   await env.DB.prepare('DELETE FROM sessions WHERE expires_at <= ?').bind(now).run();
   await env.DB.prepare('INSERT INTO auth_flows(state_hash,verifier,return_to,expires_at) VALUES (?,?,?,?)').bind(stateHash,await seal(verifier,env.TOKEN_ENCRYPTION_KEY,'flow:'+stateHash),returnTo,now+600).run();
   const login=new URL('https://github.com/login/oauth/authorize');
   for(const [k,v] of Object.entries({client_id:env.GITHUB_CLIENT_ID,redirect_uri:env.APP_ORIGIN+'/auth/callback',state,code_challenge:await hash(verifier),code_challenge_method:'S256',scope:'offline_access',login:env.ALLOWED_GITHUB_LOGIN,allow_signup:'false'}))login.searchParams.set(k,v);
   return secureHeaders(redirect(login.href,{'Set-Cookie':cookie(FLOW,state,600)}));
  }
  if(url.pathname==='/auth/callback'&&request.method==='GET'){
   const state=url.searchParams.get('state'),code=url.searchParams.get('code');
   if(!state||!/^[A-Za-z0-9_-]{43}$/.test(state)||state!==cookies(request)[FLOW]||!code||code.length>512)throw new SafeError(400,'Sign-in verification failed. Start sign-in again.');
   const stateHash=await hash(state);
   const flow=await env.DB.prepare('DELETE FROM auth_flows WHERE state_hash = ? RETURNING *').bind(stateHash).first();
   if(!flow||flow.expires_at<=now)throw new SafeError(400,'This sign-in link expired or was already used. Start again.');
   const verifier=await unseal(flow.verifier,env.TOKEN_ENCRYPTION_KEY,'flow:'+stateHash);
   const tokens=await tokensFromGithub(env,fetchImpl,{code,code_verifier:verifier,redirect_uri:env.APP_ORIGIN+'/auth/callback',repository_id:env.REPOSITORY_ID},now);
   const userResponse=await github(fetchImpl,'/user',tokens.access_token);
   if(!userResponse.ok)throw new SafeError(401,'GitHub identity could not be verified.');
   const user=await userResponse.json();
   if(String(user.id)!==String(env.ALLOWED_GITHUB_USER_ID))throw new SafeError(403,'This dashboard is restricted to its owner.');
   const repository=await github(fetchImpl,'/repos/'+env.REPOSITORY,tokens.access_token);
   if(!repository.ok)throw new SafeError(403,'Install the GitHub App on football-shorts-factory, then sign in again.');
   const repo=await repository.json();if(String(repo.id)!==String(env.REPOSITORY_ID))throw new SafeError(403,'The authorized repository did not match.');
   const workflow=await github(fetchImpl,`/repos/${env.REPOSITORY}/actions/workflows/create-prediction.yml`,tokens.access_token);
   if(!workflow.ok||(await workflow.json()).state!=='active')throw new SafeError(403,'Enable the prediction workflow and grant the GitHub App Actions access.');
   if(row)await env.DB.prepare('DELETE FROM sessions WHERE id_hash = ?').bind(row.id_hash).run();
   const id=random(),idHash=await hash(id),csrf=random();
   const days=Math.max(1,Math.min(30,Number(env.SESSION_DAYS)||30));
   await env.DB.prepare('INSERT INTO sessions(id_hash,github_id,login,encrypted_tokens,csrf_token,expires_at) VALUES (?,?,?,?,?,?)').bind(idHash,String(user.id),user.login,await seal(tokens,env.TOKEN_ENCRYPTION_KEY,'session:'+idHash),csrf,now+days*86400).run();
   const r=redirect(flow.return_to,{'Set-Cookie':cookie(SESSION,id,days*86400)});r.headers.append('Set-Cookie',cookie(FLOW,'',0));
   return secureHeaders(r);
  }
  if(url.pathname==='/api/session'&&request.method==='GET'){
   if(!row)return secureHeaders(response({authenticated:false,configured:true,login_url:'/auth/login'}));
   const requests=await env.DB.prepare('SELECT fixture_id,state,run_url FROM dispatches ORDER BY created_at DESC LIMIT 100').all();
   return secureHeaders(response({authenticated:true,configured:true,login:row.login,csrf_token:row.csrf_token,expires_at:row.expires_at,requests:requests.results}));
  }
  if(url.pathname==='/auth/logout'&&request.method==='POST'){
   if(!row)throw new SafeError(401,'You are signed out.',true);
   verifyWrite(request,url,row);await env.DB.prepare('DELETE FROM sessions WHERE id_hash = ?').bind(row.id_hash).run();
   return secureHeaders(response({authenticated:false},200,{'Set-Cookie':cookie(SESSION,'',0)}));
  }
  if(url.pathname==='/api/dispatch'&&request.method==='POST'){
   if(!row)throw new SafeError(401,'Sign in with GitHub first.',true);
   return secureHeaders(await dispatch(request,url,env,row,fetchImpl,now));
  }
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/auth/'))throw new SafeError(404,'Route not found.');
  if(request.method!=='GET'&&request.method!=='HEAD')throw new SafeError(405,'Method not allowed.');
  const assets=new Set(['/','/index.html','/app.mjs','/workflow-client.mjs','/session-client.mjs','/matches.json']);
  if(!assets.has(url.pathname))throw new SafeError(404,'Page not found.');
  const upstream=await fetchTimed(fetchImpl,env.ASSET_BASE_URL+(url.pathname==='/'?'index.html':url.pathname.slice(1)));
  if(!upstream.ok)throw new SafeError(503,'The dashboard is temporarily unavailable.');
  const headers=new Headers();headers.set('Content-Type',upstream.headers.get('Content-Type')||'application/octet-stream');headers.set('Cache-Control','no-store');
  return secureHeaders(new Response(request.method==='HEAD'?null:upstream.body,{status:200,headers}));
 }catch(error){
  if(error instanceof SafeError){
   if(error.clear&&row)await env.DB.prepare('DELETE FROM sessions WHERE id_hash = ?').bind(row.id_hash).run();
   return secureHeaders(response({error:error.message},error.status,error.clear?{'Set-Cookie':cookie(SESSION,'',0)}:{}));
  }
  return secureHeaders(response({error:'The secure dashboard could not complete this request. Try again later.'},503));
 }
}
export default {fetch:handle};
