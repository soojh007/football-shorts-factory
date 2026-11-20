import test from 'node:test';
import assert from 'node:assert/strict';
import {TokenVault,VAULT_KEY,ITERATIONS,IdleLock} from '../docs/token-vault.mjs';
import {WorkflowConnection} from '../docs/workflow-client.mjs';
const TOKEN='github_pat_synthetic_not_a_real_token_1234567890',PASSWORD='several-random-words-for-testing';
function storage(){const map=new Map();return {map,getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};}
function cryptoWithEncrypt(encrypt){const s=crypto.subtle;return {getRandomValues:crypto.getRandomValues.bind(crypto),subtle:{importKey:s.importKey.bind(s),deriveKey:s.deriveKey.bind(s),decrypt:s.decrypt.bind(s),encrypt}};}

test('encrypted token survives a fresh instance without storing token, password or key',async()=>{
 const s=storage(),first=new TokenVault(s);await first.save(TOKEN,PASSWORD);
 assert.equal(first.hasSaved(),true);assert.deepEqual([...s.map.keys()],[VAULT_KEY]);
 const raw=s.getItem(VAULT_KEY);assert.ok(!raw.includes(TOKEN));assert.ok(!raw.includes(PASSWORD));
 const record=JSON.parse(raw);assert.deepEqual(Object.keys(record).sort(),['ciphertext','iterations','iv','kdf','salt','version']);
 assert.equal(record.iterations,ITERATIONS);
 const afterReload=new TokenVault(s);assert.equal(await afterReload.unlock(PASSWORD),TOKEN);
 assert.ok(!JSON.stringify(afterReload).includes(TOKEN));
});
test('every save uses fresh salt and IV',async()=>{
 const s=storage(),vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);const a=JSON.parse(s.getItem(VAULT_KEY));
 await vault.save(TOKEN,PASSWORD);const b=JSON.parse(s.getItem(VAULT_KEY));
 assert.notEqual(a.salt,b.salt);assert.notEqual(a.iv,b.iv);assert.notEqual(a.ciphertext,b.ciphertext);
 assert.equal(await vault.unlock(PASSWORD),TOKEN);
});
test('wrong password and altered ciphertext fail closed and keep the encrypted record',async()=>{
 const s=storage(),vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);const original=s.getItem(VAULT_KEY);
 await assert.rejects(vault.unlock('incorrect-password-long-enough'),e=>e.message.includes('Could not unlock')&&!e.message.includes(TOKEN));
 assert.equal(s.getItem(VAULT_KEY),original);
 const data=JSON.parse(original);data.ciphertext=(data.ciphertext[0]==='A'?'B':'A')+data.ciphertext.slice(1);s.setItem(VAULT_KEY,JSON.stringify(data));
 await assert.rejects(vault.unlock(PASSWORD),/Could not unlock/);assert.equal(vault.hasSaved(),true);
});
test('unsupported or corrupted records cannot change the KDF work factor or expose plaintext',async()=>{
 const s=storage(),vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);const original=JSON.parse(s.getItem(VAULT_KEY));
 for(const change of [{iterations:1},{iterations:999999999},{version:2},{iv:'bad'},{password:PASSWORD}]){
  s.setItem(VAULT_KEY,JSON.stringify({...original,...change}));await assert.rejects(vault.unlock(PASSWORD),/damaged or unsupported/);
 }
 s.setItem(VAULT_KEY,'not JSON');await assert.rejects(vault.unlock(PASSWORD),/damaged or unsupported/);
});
test('invalid token or weak password cannot overwrite a saved connection',async()=>{
 const s=storage(),vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);const original=s.getItem(VAULT_KEY);
 await assert.rejects(vault.save(TOKEN,'short'),/12–256/);
 await assert.rejects(vault.save('wrong-token',PASSWORD),/fine-grained/);
 assert.equal(s.getItem(VAULT_KEY),original);
});
test('forget removes only this application record',async()=>{
 const s=storage();s.setItem('another-app','keep');const vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);
 vault.forget();assert.equal(vault.hasSaved(),false);assert.equal(s.getItem('another-app'),'keep');
 await assert.rejects(vault.unlock(PASSWORD),/No encrypted token/);
});
test('lock or forget while encryption is pending cannot resurrect a saved token',async()=>{
 const s=storage();let started,release;
 const reached=new Promise(r=>started=r),gate=new Promise(r=>release=r);
 const mock=cryptoWithEncrypt(async(...args)=>{started();await gate;return crypto.subtle.encrypt(...args);});
 const vault=new TokenVault(s,mock),pending=vault.save(TOKEN,PASSWORD);
 await reached;vault.forget();release();await assert.rejects(pending,/cancelled/);assert.equal(vault.hasSaved(),false);
});
test('storage failures never fall back to plaintext or report a successful save',async()=>{
 let writes=0;
 const s={getItem:()=>null,setItem(){writes++;throw Error('storage private detail');},removeItem(){}};
 const vault=new TokenVault(s);
 await assert.rejects(vault.save(TOKEN,PASSWORD),e=>e.message.includes('could not be saved')&&!e.message.includes(TOKEN)&&!e.message.includes('private detail'));
 assert.equal(writes,1);
 assert.equal(new TokenVault(null).supported,false);
});
test('idle lock is based on elapsed time, resets on activity, and leaves ciphertext intact',async()=>{
 let now=0,connected=true;const s=storage(),vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);const record=s.getItem(VAULT_KEY);
 const idle=new IdleLock({now:()=>now,connected:()=>connected,lock:()=>{connected=false;},timeout:100});
 now=90;assert.equal(idle.check(),false);idle.touch();now=180;assert.equal(idle.check(),false);
 now=190;assert.equal(idle.check(),true);assert.equal(connected,false);assert.equal(s.getItem(VAULT_KEY),record);
});
test('unlocking never makes GitHub requests until the password is accepted',async()=>{
 const s=storage(),vault=new TokenVault(s);await vault.save(TOKEN,PASSWORD);
 let calls=0;const client=new WorkflowConnection(async()=>{calls++;return Response.json(calls===1?{}:{state:'active'});});
 async function unlock(password){const token=await vault.unlock(password);await client.connect(token);}
 await assert.rejects(unlock('wrong-long-password'));assert.equal(calls,0);assert.equal(client.connected,false);
 await unlock(PASSWORD);assert.equal(calls,2);assert.equal(client.connected,true);
 client.disconnect();assert.equal(client.connected,false);assert.equal(vault.hasSaved(),true);
});
test('locking during GitHub verification does not reconnect after the response arrives',async()=>{
 let release,calls=0;
 const gate=new Promise(r=>release=r),client=new WorkflowConnection(async()=>{calls++;await gate;return Response.json({});});
 const pending=client.connect(TOKEN);client.disconnect();release();await assert.rejects(pending,/locked/);
 assert.equal(client.connected,false);assert.equal(calls,1);
});
test('a cancelled older connect cannot clear a newer successful connection',async()=>{
 let release,calls=0;const gate=new Promise(r=>release=r);
 const client=new WorkflowConnection(async()=>{calls++;if(calls===1){await gate;return Response.json({});}return Response.json(calls===2?{}:{state:'active'});});
 const older=client.connect(TOKEN);client.disconnect();await client.connect(TOKEN);assert.equal(client.connected,true);
 release();await assert.rejects(older,/locked/);assert.equal(client.connected,true);
});
