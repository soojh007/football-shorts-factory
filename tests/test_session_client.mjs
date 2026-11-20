import test from 'node:test';
import assert from 'node:assert/strict';
import {SessionConnection} from '../docs/session-client.mjs';
const NOW=Date.parse('2026-11-20T01:00:00Z'),MATCH={fixture_id:99,kickoff:new Date(NOW+3600000).toISOString()};
const reply=(data,status=200)=>Response.json(data,{status});
const session={authenticated:true,configured:true,login:'owner',csrf_token:'a'.repeat(43),requests:[]};
test('reload restores sign-in with same-origin cookie and no GitHub credentials',async()=>{
 const calls=[],client=new SessionConnection(async(url,options)=>{calls.push({url,options});return reply(session);});
 await client.restore();assert.equal(client.connected,true);assert.equal(client.login,'owner');
 assert.equal(calls[0].url,'/api/session');assert.equal(calls[0].options.credentials,'same-origin');
 assert.equal('Authorization' in calls[0].options.headers,false);
 assert.ok(!JSON.stringify(client).includes(session.csrf_token));
 client.disconnect();assert.equal(client.connected,false);
 await client.restore();assert.equal(client.connected,true);
});
test('sign-out is explicit; forgetting page memory never logs out server session',async()=>{
 const calls=[],client=new SessionConnection(async(url,options)=>{calls.push({url,options});return reply(url==='/api/session'?session:{authenticated:false});});
 await client.restore();client.disconnect();assert.equal(calls.length,1);
 await client.restore();await client.signOut();
 assert.equal(calls.at(-1).url,'/auth/logout');assert.equal(calls.at(-1).options.method,'POST');assert.equal(calls.at(-1).options.headers['X-CSRF-Token'],session.csrf_token);
 assert.equal(client.connected,false);
});
test('create sends fixture only to server and preserves duplicate guard',async()=>{
 const calls=[],client=new SessionConnection(async(url,options)=>{calls.push({url,options});return reply(url==='/api/session'?session:{status:'accepted',url:'https://github.com/soojh007/football-shorts-factory/actions/runs/123'});});
 await client.restore();await client.create(MATCH,{now:NOW});
 assert.deepEqual(JSON.parse(calls[1].options.body),{fixture_id:99});
 assert.equal(calls[1].url,'/api/dispatch');assert.equal(calls[1].options.headers['X-CSRF-Token'],session.csrf_token);
 await assert.rejects(client.create(MATCH,{now:NOW}),/already has a request/);assert.equal(calls.length,2);
});
test('pending server requests restore after closing and reopening page',async()=>{
 const client=new SessionConnection(async()=>reply({...session,requests:[{fixture_id:99,state:'uncertain',run_url:'https://github.com/soojh007/football-shorts-factory/actions/runs/123'}]}));
 await client.restore();assert.equal(client.state(99).status,'uncertain');
 await assert.rejects(client.create(MATCH,{now:NOW}),/already has a request/);
});
test('uncertain dispatch is never automatically retried',async()=>{
 let calls=0;const client=new SessionConnection(async url=>{calls++;if(url==='/api/session')return reply(session);throw new TypeError('secret network detail');});
 await client.restore();await assert.rejects(client.create(MATCH,{now:NOW}),/may have reached/);
 assert.equal(client.state(99).status,'uncertain');await assert.rejects(client.create(MATCH,{now:NOW}));assert.equal(calls,2);
});
test('expired sign-in clears local session; untrusted run links are not followed',async()=>{
 const client=new SessionConnection(async url=>reply(url==='/api/session'?session:{error:'Sign in again.'},url==='/api/session'?200:401));
 await client.restore();await assert.rejects(client.create(MATCH,{now:NOW}),/Sign in again/);assert.equal(client.connected,false);
 const second=new SessionConnection(async()=>reply({...session,requests:[{fixture_id:99,state:'accepted',run_url:'https://evil.example/'}]}));
 await second.restore();assert.ok(second.state(99).url.startsWith('https://github.com/soojh007/football-shorts-factory/'));
});
