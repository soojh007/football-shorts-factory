import test from 'node:test';
import assert from 'node:assert/strict';
import {WorkflowConnection,readiness,ACTIONS_URL} from '../docs/workflow-client.mjs';
const TOKEN='github_pat_synthetic_not_a_real_token_1234567890';
const NOW=Date.parse('2026-11-15T13:00:00Z');
const MATCH={fixture_id:19744985,kickoff:'2026-11-15T14:00:00Z'};
const reply=(status,data={})=>({status,ok:status>=200&&status<300,json:async()=>data});
function setup(dispatch=reply(200,{html_url:'https://github.com/soojh007/football-shorts-factory/actions/runs/123'})){
 const calls=[];const responses=[reply(200,{permissions:{push:true}}),reply(200,{state:'active'}),dispatch];
 const client=new WorkflowConnection(async(url,options)=>{calls.push({url,options});const response=responses.shift();if(response instanceof Error)throw response;return response;});
 return {client,calls};
}
test('one click sends selected fixture on main with private production defaults',async()=>{
 const {client,calls}=setup();await client.connect(TOKEN);const result=await client.create(MATCH,{now:NOW});
 assert.equal(result.status,'accepted');assert.match(result.url,/runs\/123$/);
 assert.equal(calls.length,3);assert.match(calls[2].url,/create-prediction.yml\/dispatches$/);
 assert.deepEqual(JSON.parse(calls[2].options.body),{ref:'main',return_run_details:true,inputs:{match:'19744985',auto_retry:true,validate_only:false}});
 assert.equal(calls[2].options.credentials,'omit');assert.equal(calls[2].options.referrerPolicy,'no-referrer');
 assert.equal(JSON.stringify(client).includes(TOKEN),false);
});
test('anonymous visitors cannot start paid generation',async()=>{
 const {client,calls}=setup();await assert.rejects(client.create(MATCH,{now:NOW}),/Connect GitHub/);assert.equal(calls.length,0);
});
test('rejects past fixtures, invalid IDs and fixtures beyond two-hour waiting window',()=>{
 for(const fixture of [{...MATCH,fixture_id:'19744985'},{...MATCH,kickoff:'invalid'},{...MATCH,kickoff:'2026-11-15T12:00:00Z'},{...MATCH,kickoff:'2026-11-15T15:00:01Z'}])assert.equal(readiness(fixture,NOW).ready,false);
 assert.equal(readiness({...MATCH,kickoff:'2026-11-15T15:00:00Z'},NOW).ready,true);
});
test('duplicate click while sending or after acceptance never dispatches again',async()=>{
 const {client,calls}=setup();await client.connect(TOKEN);const first=client.create(MATCH,{now:NOW});
 await assert.rejects(client.create(MATCH,{now:NOW}),/already has a request/);await first;
 await assert.rejects(client.create(MATCH,{now:NOW}),/already has a request/);assert.equal(calls.length,3);
});
test('network failure becomes uncertain and is never automatically retried',async()=>{
 const {client,calls}=setup(new TypeError('fetch failed '+TOKEN));await client.connect(TOKEN);
 await assert.rejects(client.create(MATCH,{now:NOW}),error=>!error.message.includes(TOKEN)&&error.message.includes('may have received'));
 assert.equal(client.state(MATCH.fixture_id).status,'uncertain');await assert.rejects(client.create(MATCH,{now:NOW}),/already/);assert.equal(calls.length,3);
});
test('403 tells owner required permission without exposing API body',async()=>{
 const {client}=setup(reply(403,{message:TOKEN}));await client.connect(TOKEN);await assert.rejects(client.create(MATCH,{now:NOW}),/Actions: read and write/);
 assert.equal(client.state(MATCH.fixture_id),null);
});
test('server failures lock uncertain result instead of encouraging duplicate upload',async()=>{
 const {client}=setup(reply(503));await client.connect(TOKEN);await assert.rejects(client.create(MATCH,{now:NOW}),/Check Actions/);assert.equal(client.state(MATCH.fixture_id).status,'uncertain');
});
test('disconnect clears credentials and prevents further authenticated requests',async()=>{
 const {client,calls}=setup();await client.connect(TOKEN);client.disconnect();assert.equal(client.connected,false);await assert.rejects(client.create(MATCH,{now:NOW}),/Connect GitHub/);assert.equal(calls.length,2);
});
test('refuses broad classic tokens and wrong repository permissions',async()=>{
 const {client}=setup();await assert.rejects(client.connect('ghp_synthetic_classic_token'),/fine-grained/);
 const denied=new WorkflowConnection(async()=>reply(200,{permissions:{push:false}}));await assert.rejects(denied.connect(TOKEN),/write access/);assert.equal(denied.connected,false);
});
test('expired token disconnects and does not reveal response text',async()=>{
 const {client}=setup(reply(401,{message:TOKEN}));await client.connect(TOKEN);await assert.rejects(client.create(MATCH,{now:NOW}),/expired/);assert.equal(client.connected,false);
});
test('accepts legacy empty dispatch response without sending a second job',async()=>{
 const {client}=setup(reply(204));await client.connect(TOKEN);const result=await client.create(MATCH,{now:NOW});assert.equal(result.url,ACTIONS_URL);
});
test('untrusted run URLs cannot become page links',async()=>{
 const {client}=setup(reply(200,{html_url:'https://attacker.example/steal'}));await client.connect(TOKEN);assert.equal((await client.create(MATCH,{now:NOW})).url,ACTIONS_URL);
});
test('validation smoke mode explicitly disables retries and generation',async()=>{
 const {client,calls}=setup();await client.connect(TOKEN);await client.create(MATCH,{now:NOW,validateOnly:true});assert.deepEqual(JSON.parse(calls[2].options.body).inputs,{match:'19744985',auto_retry:false,validate_only:true});
});
