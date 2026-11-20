// Only authenticated ciphertext is persisted. Passwords, keys and unlocked tokens stay in memory.
export const VAULT_KEY='football-shorts-factory.github-token.v1';
export const ITERATIONS=600000;
const AAD=new TextEncoder().encode('football-shorts-factory|github-token|v1');
const TOKEN=/^github_pat_[A-Za-z0-9_]{20,500}$/;
const encode=bytes=>btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
function decode(text){
 if(typeof text!=='string'||!/^[A-Za-z0-9_-]+$/.test(text))throw Error();
 return Uint8Array.from(atob(text.replaceAll('-','+').replaceAll('_','/')),c=>c.charCodeAt(0));
}
export class VaultError extends Error{}
export function validatePassword(password){
 if(typeof password!=='string'||password.trim().length<12||password.length>256)throw new VaultError('Use an unlock password of 12–256 characters, ideally several random words.');
}
async function derive(password,salt,crypto){
 const bytes=new TextEncoder().encode(password);
 try{
  const material=await crypto.subtle.importKey('raw',bytes,'PBKDF2',false,['deriveKey']);
  return await crypto.subtle.deriveKey({name:'PBKDF2',hash:'SHA-256',salt,iterations:ITERATIONS},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
 }finally{bytes.fill(0);}
}
function defaultStorage(){try{return globalThis.localStorage||null;}catch{return null;}}
export class TokenVault{
 #storage;#crypto;#revision=0;
 constructor(storage=defaultStorage(),crypto=globalThis.crypto){this.#storage=storage;this.#crypto=crypto;}
 get supported(){if(!this.#storage||!this.#crypto?.subtle||!this.#crypto?.getRandomValues)return false;try{this.#storage.getItem(VAULT_KEY);return true;}catch{return false;}}
 hasSaved(){try{const value=this.#storage?.getItem(VAULT_KEY);return value!==null&&value!==undefined;}catch{throw new VaultError('Browser storage is unavailable. You can still connect for this visit.');}}
 #read(){
  let text;try{text=this.#storage.getItem(VAULT_KEY);}catch{throw new VaultError('Browser storage is unavailable.');}
  if(text===null)throw new VaultError('No encrypted token is saved on this device.');
  try{
   if(text.length>4096)throw Error();
   const r=JSON.parse(text);
   if(!r||Object.keys(r).sort().join(',')!=='ciphertext,iterations,iv,kdf,salt,version'||r.version!==1||r.kdf!=='PBKDF2-SHA256'||r.iterations!==ITERATIONS)throw Error();
   const salt=decode(r.salt),iv=decode(r.iv),ciphertext=decode(r.ciphertext);
   if(salt.length!==32||iv.length!==12||ciphertext.length<17||ciphertext.length>1024)throw Error();
   return {salt,iv,ciphertext};
  }catch{throw new VaultError('The saved connection is damaged or unsupported. Forget it and save your token again.');}
 }
 async save(token,password){
  if(!this.supported)throw new VaultError('Encrypted storage is unavailable in this browser. Connect for this visit instead.');
  if(typeof token!=='string'||!TOKEN.test(token.trim()))throw new VaultError('Use a fine-grained GitHub token for this repository.');
  validatePassword(password);
  const revision=this.#revision;
  const salt=this.#crypto.getRandomValues(new Uint8Array(32)),iv=this.#crypto.getRandomValues(new Uint8Array(12));
  const key=await derive(password,salt,this.#crypto),bytes=new TextEncoder().encode(token.trim());
  let encrypted;
  try{encrypted=await this.#crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:AAD,tagLength:128},key,bytes);}
  finally{bytes.fill(0);}
  const record={version:1,kdf:'PBKDF2-SHA256',iterations:ITERATIONS,salt:encode(salt),iv:encode(iv),ciphertext:encode(new Uint8Array(encrypted))};
  if(revision!==this.#revision)throw new VaultError('Saving was cancelled because the connection was locked or forgotten.');
  try{this.#storage.setItem(VAULT_KEY,JSON.stringify(record));}
  catch{throw new VaultError('Connected for this visit, but the encrypted token could not be saved. Check browser storage settings.');}
 }
 async unlock(password){
  if(!this.supported)throw new VaultError('Encrypted storage is unavailable in this browser.');
  validatePassword(password);
  const revision=this.#revision,r=this.#read();let bytes;
  try{
   const key=await derive(password,r.salt,this.#crypto);
   bytes=new Uint8Array(await this.#crypto.subtle.decrypt({name:'AES-GCM',iv:r.iv,additionalData:AAD,tagLength:128},key,r.ciphertext));
   if(revision!==this.#revision)throw Error();
   const token=new TextDecoder().decode(bytes);
   if(!TOKEN.test(token))throw Error();
   return token;
  }catch{throw new VaultError('Could not unlock the saved token. Check your password. If you forgot it, forget this saved connection and save your token again.');}
  finally{bytes?.fill(0);}
 }
 cancelPending(){this.#revision++;}
 forget(){this.cancelPending();try{this.#storage.removeItem(VAULT_KEY);}catch{throw new VaultError('Could not remove the saved connection. Check browser storage settings.');}}
}

export class IdleLock{
 #now;#lock;#connected;#last;#timeout;
 constructor({now=Date.now,lock,connected,timeout=15*60*1000}){this.#now=now;this.#lock=lock;this.#connected=connected;this.#timeout=timeout;this.#last=now();}
 touch(){this.#last=this.#now();}
 check(){if(this.#connected()&&this.#now()-this.#last>=this.#timeout){this.#lock();return true;}return false;}
}
