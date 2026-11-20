import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {handle,hash,seal,unseal} from '../src/worker.mjs';
const NOW=Date.parse('2026-11-20T01:00:00Z'),ORIGIN='https://dashboard.example',ACCESS='synthetic_access_secret',REFRESH='synthetic_refresh_secret';
class D1 {
 constructor(){this.db=new DatabaseSync(':memory:');this.db.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));}
 prepare(sql){const stmt=this.db.prepare(sql);let values=[];return {bind(...v){values=v;return this;},async first(){return stmt.get(...values)||null;},async run(){const r=stmt.run(...values);return {meta:{changes:r.changes}};},async all(){return {results:stmt.all(...values)};}};}
}
function setup(){
 const env={DB:new D1(),APP_ORIGIN:ORIGIN,REPOSITORY:'soojh007/football-shorts-factory',REPOSITORY_ID:'42',ALLOWED_GITHUB_USER_ID:'123',ALLOWED_GITHUB_LOGIN:'owner',GITHUB_CLIENT_ID:'synthetic-client',GITHUB_CLIENT_SECRET:'synthetic-client-secret',TOKEN_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url'),SESSION_DAYS:'30',ASSET_BASE_URL:'https://pages.example/'};
 const calls=[];
 const network=async(url,options={})=>{
  calls.push({url,options});
  if(url==='https://github.com/login/oauth/access_token')return Response.json({access_token:ACCESS,refresh_token:REFRESH,expires_in:28800,refresh_token_expires_in:15897600});
  if(url==='https://api.github.com/user')return Response.json({id:123,login:'owner'});
  if(url==='https://api.github.com/repos/'+env.REPOSITORY)return Response.json({id:42});
  if(url.endsWith('/create-prediction.yml'))return Response.json({state:'active'});
  if(url==='https://pages.example/matches.json')return Response.json({fetched_at:new Date(NOW).toISOString(),matches:[{fixture_id:99,kickoff:new Date(NOW+3600000).toISOString()}]});
  if(url.endsWith('/dispatches'))return Response.json({html_url:'https://github.com/soojh007/football-shorts-factory/actions/runs/123'});
  throw Error('Unexpected URL');
 };
 return {env,calls,network,run:(request,fetch=network,now=NOW)=>handle(request,env,{fetch,now:()=>now})};
}
async function login(s){
 const start=await s.run(new Request(ORIGIN+'/auth/login?fixture=99'));
 assert.equal(start.status,303);
 const location=new URL(start.headers.get('Location')),state=location.searchParams.get('state');
 const result=await s.run(new Request(ORIGIN+'/auth/callback?code=example&state='+state,{headers:{Cookie:'__Host-factory_oauth='+state}}));
 assert.equal(result.status,303);
 const set=result.headers.getSetCookie();const cookie=set.find(x=>x.startsWith('__Host-factory_session=')).split(';')[0];
 const data=await (await s.run(new Request(ORIGIN+'/api/session',{headers:{Cookie:cookie}}))).json();
 return {cookie,data,start,result,location,state};
}
function post(path,auth,body={},extra={}){return new Request(ORIGIN+path,{method:'POST',headers:{Cookie:auth.cookie,Origin:ORIGIN,'Content-Type':'application/json','X-CSRF-Token':auth.data.csrf_token,...extra},body:JSON.stringify(body)});}

test('OAuth PKCE, single-use state, encrypted tokens and opaque HttpOnly persistent cookie',async()=>{
 const s=setup(),auth=await login(s);
 assert.equal(auth.result.headers.get('Location'),'/?fixture=99');
 assert.match(auth.result.headers.getSetCookie()[0],/Secure; HttpOnly; SameSite=Lax; Max-Age=2592000/);
 const exchange=s.calls.find(x=>x.url==='https://github.com/login/oauth/access_token');
 assert.equal(await hash(exchange.options.body.get('code_verifier')),auth.location.searchParams.get('code_challenge'));
 assert.equal(exchange.options.body.get('repository_id'),'42');
 const row=s.env.DB.db.prepare('SELECT * FROM sessions').get();
 assert.ok(!JSON.stringify(row).includes(ACCESS));assert.ok(!JSON.stringify(row).includes(REFRESH));
 const tokens=await unseal(row.encrypted_tokens,s.env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash);
 assert.equal(tokens.access_token,ACCESS);
 assert.ok(!JSON.stringify(auth.data).includes(ACCESS));assert.ok(!auth.cookie.includes(ACCESS));
 const replay=await s.run(new Request(ORIGIN+'/auth/callback?code=example&state='+auth.state,{headers:{Cookie:'__Host-factory_oauth='+auth.state}}));
 assert.equal(replay.status,400);
});
test('refreshing the page restores the session without another OAuth exchange',async()=>{
 const s=setup(),auth=await login(s),count=s.calls.length;
 const r=await s.run(new Request(ORIGIN+'/api/session',{headers:{Cookie:auth.cookie}}));
 assert.equal((await r.json()).authenticated,true);assert.equal(s.calls.length,count);
});
test('anonymous, wrong-origin, missing-CSRF and injected workflow arguments cannot dispatch',async()=>{
 const s=setup(),auth=await login(s);
 assert.equal((await s.run(new Request(ORIGIN+'/api/dispatch',{method:'POST'}))).status,401);
 assert.equal((await s.run(post('/api/dispatch',auth,{fixture_id:99},{Origin:'https://evil.example'}))).status,403);
 assert.equal((await s.run(post('/api/dispatch',auth,{fixture_id:99},{'X-CSRF-Token':'bad'}))).status,403);
 assert.equal((await s.run(post('/api/dispatch',auth,{fixture_id:99,ref:'evil'}))).status,400);
 assert.equal(s.calls.filter(x=>x.url.endsWith('/dispatches')).length,0);
});
test('only the allowlisted owner can establish a session',async()=>{
 const s=setup();const fetch=(url,options)=>url==='https://api.github.com/user'?Promise.resolve(Response.json({id:999,login:'other'})):s.network(url,options);
 const start=await s.run(new Request(ORIGIN+'/auth/login'));const state=new URL(start.headers.get('Location')).searchParams.get('state');
 const r=await s.run(new Request(ORIGIN+'/auth/callback?code=x&state='+state,{headers:{Cookie:'__Host-factory_oauth='+state}}),fetch);
 assert.equal(r.status,403);assert.equal(s.env.DB.db.prepare('SELECT COUNT(*) AS n FROM sessions').get().n,0);
});
test('cross-browser state theft and expired OAuth state fail closed',async()=>{
 const s=setup(),start=await s.run(new Request(ORIGIN+'/auth/login'));
 const state=new URL(start.headers.get('Location')).searchParams.get('state');
 assert.equal((await s.run(new Request(ORIGIN+'/auth/callback?code=x&state='+state))).status,400);
 const r=await s.run(new Request(ORIGIN+'/auth/callback?code=x&state='+state,{headers:{Cookie:'__Host-factory_oauth='+state}}),s.network,NOW+601000);
 assert.equal(r.status,400);assert.equal(s.calls.length,0);
});
test('expired session and signing out revoke server-side access',async()=>{
 const s=setup(),auth=await login(s);
 const r=await s.run(post('/auth/logout',auth));assert.equal(r.status,200);
 assert.match(r.headers.get('Set-Cookie'),/Max-Age=0/);
 assert.equal((await (await s.run(new Request(ORIGIN+'/api/session',{headers:{Cookie:auth.cookie}}))).json()).authenticated,false);
 const second=await login(s);
 s.env.DB.db.prepare('UPDATE sessions SET expires_at = 0').run();
 assert.equal((await (await s.run(new Request(ORIGIN+'/api/session',{headers:{Cookie:second.cookie}}))).json()).authenticated,false);
});
test('single click sends server-owned main/private workflow defaults; duplicate requests never re-dispatch',async()=>{
 const s=setup(),auth=await login(s);
 const responses=await Promise.all([s.run(post('/api/dispatch',auth,{fixture_id:99})),s.run(post('/api/dispatch',auth,{fixture_id:99}))]);
 assert.ok(responses.every(x=>x.status===200));
 assert.equal(s.calls.filter(x=>x.url.endsWith('/dispatches')).length,1);
 const call=s.calls.find(x=>x.url.endsWith('/dispatches'));
 assert.deepEqual(JSON.parse(call.options.body),{ref:'main',return_run_details:true,inputs:{match:'99',auto_retry:true,validate_only:false}});
 assert.equal(call.options.headers.Authorization,'Bearer '+ACCESS);
});
test('an uncertain dispatch persists across reloads and cannot be retried automatically',async()=>{
 const s=setup(),auth=await login(s);
 const fetch=(url,options)=>{if(url.endsWith('/dispatches'))throw Error('network '+ACCESS);return s.network(url,options);};
 const r=await s.run(post('/api/dispatch',auth,{fixture_id:99}),fetch);
 assert.equal(r.status,202);assert.equal((await r.json()).status,'uncertain');
 const again=await s.run(post('/api/dispatch',auth,{fixture_id:99}));
 assert.equal((await again.json()).already_requested,true);
 assert.equal(s.calls.filter(x=>x.url.endsWith('/dispatches')).length,0);
 const restored=await (await s.run(new Request(ORIGIN+'/api/session',{headers:{Cookie:auth.cookie}}))).json();
 assert.equal(restored.requests[0].state,'uncertain');assert.ok(!JSON.stringify(restored).includes(ACCESS));
});
test('expired access tokens refresh on the server and never reach the browser',async()=>{
 const s=setup(),auth=await login(s),row=s.env.DB.db.prepare('SELECT * FROM sessions').get();
 const tokens=await unseal(row.encrypted_tokens,s.env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash);tokens.access_expires_at=0;
 s.env.DB.db.prepare('UPDATE sessions SET encrypted_tokens = ?').run(await seal(tokens,s.env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash));
 const r=await s.run(post('/api/dispatch',auth,{fixture_id:99}));assert.equal(r.status,200);
 const exchanges=s.calls.filter(x=>x.url==='https://github.com/login/oauth/access_token');
 assert.equal(exchanges.length,2);assert.equal(exchanges[1].options.body.get('grant_type'),'refresh_token');
 assert.ok(!(await r.text()).includes(ACCESS));
});
test('invalid or revoked refresh is not replayed and invalidates the session',async()=>{
 const s=setup(),auth=await login(s),row=s.env.DB.db.prepare('SELECT * FROM sessions').get();
 const tokens=await unseal(row.encrypted_tokens,s.env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash);tokens.access_expires_at=0;
 s.env.DB.db.prepare('UPDATE sessions SET encrypted_tokens = ?').run(await seal(tokens,s.env.TOKEN_ENCRYPTION_KEY,'session:'+row.id_hash));
 const fetch=(url,options)=>url==='https://github.com/login/oauth/access_token'?Promise.resolve(Response.json({error:'bad_refresh_token',message:ACCESS},{status:400})):s.network(url,options);
 const r=await s.run(post('/api/dispatch',auth,{fixture_id:99}),fetch);assert.equal(r.status,401);assert.ok(!(await r.text()).includes(ACCESS));
 assert.equal(s.env.DB.db.prepare('SELECT COUNT(*) AS n FROM sessions').get().n,0);
 assert.equal(s.calls.filter(x=>x.url.endsWith('/dispatches')).length,0);
});
test('unknown fixtures, past matches and stale schedules do not start workflows',async()=>{
 const s=setup(),auth=await login(s);
 assert.equal((await s.run(post('/api/dispatch',auth,{fixture_id:100}))).status,409);
 const stale=(url,options)=>url==='https://pages.example/matches.json'?Promise.resolve(Response.json({fetched_at:new Date(NOW-3600000).toISOString(),matches:[{fixture_id:99,kickoff:new Date(NOW+3600000).toISOString()}]})):s.network(url,options);
 assert.equal((await s.run(post('/api/dispatch',auth,{fixture_id:99}),stale)).status,409);
 assert.equal(s.calls.filter(x=>x.url.endsWith('/dispatches')).length,0);
});
test('ciphertext is bound to its session and unknown errors never leak secrets',async()=>{
 const s=setup(),value=await seal({access_token:ACCESS},s.env.TOKEN_ENCRYPTION_KEY,'session:one');
 await assert.rejects(unseal(value,s.env.TOKEN_ENCRYPTION_KEY,'session:two'));
 const bad={...s.env,DB:{prepare(){throw Error(ACCESS);}}};
 const r=await handle(new Request(ORIGIN+'/api/session',{headers:{Cookie:'__Host-factory_session='+'a'.repeat(43)}}),bad,{fetch:s.network,now:()=>NOW});
 assert.equal(r.status,503);assert.ok(!(await r.text()).includes(ACCESS));
});
