import {WorkflowConnection,readiness,ACTIONS_URL} from './workflow-client.mjs?v=encrypted-vault-1';
import {TokenVault,VaultError,IdleLock,VAULT_KEY,validatePassword} from './token-vault.mjs?v=encrypted-vault-1';
const $=id=>document.getElementById(id),connection=new WorkflowConnection();
let scheduleData=null,connecting=false,operation=0,useOnce=false;
const vault=new TokenVault();
const idle=new IdleLock({connected:()=>connection.connected,lock:()=>lockConnection('Connection locked after 15 minutes without activity.')});
function saved(){try{return vault.hasSaved();}catch{return false;}}
function clearSecrets(){for(const id of ['githubToken','vaultPassword','vaultConfirm','unlockPassword'])$(id).value='';}
function busy(value){connecting=value;for(const id of ['connect','unlock'])$(id).disabled=value;}
function lockConnection(message){operation++;vault.cancelPending();connection.disconnect();clearSecrets();busy(false);useOnce=false;connectionView();renderMatches();if(message)$('connectionStatus').textContent=message;}
function passwordOptions(){const show=$('rememberToken').checked&&!saved();$('saveOptions').hidden=!show;for(const id of ['vaultPassword','vaultConfirm'])$(id).required=show;}
function connectionView(){
 const remembered=saved(),ready=connection.connected;
 $('connectForm').hidden=ready||(remembered&&!useOnce);$('unlockForm').hidden=ready||!remembered||useOnce;
 $('forget').hidden=!remembered;$('useOnce').hidden=!remembered||ready||useOnce;
 $('disconnect').hidden=!ready;$('disconnect').textContent=remembered?'Lock connection':'Disconnect';
 $('rememberToken').disabled=!vault.supported||remembered;
 if(!vault.supported||remembered)$('rememberToken').checked=false;
 $('connectionStatus').textContent=ready?(useOnce?'Connected for this visit only. Your previously saved connection is unchanged.':remembered?'Connected. Your encrypted token is saved on this browser. Lock it when you finish.':'Connected for this visit only. No token is saved.'): (remembered?'Saved connection locked. Enter your unlock password; no token pasting needed.':'Connect GitHub once. Optionally save an encrypted token on this device.');
 passwordOptions();
}
function openConnection(){
 $('connectionPanel').open=true;
 (saved()&&!useOnce?$('unlockPassword'):$('githubToken')).focus();
 $('connectionPanel').scrollIntoView({behavior:'smooth',block:'center'});
}

function runLink(url,label){const a=document.createElement('a');a.href=url;a.textContent=label;a.target='_blank';a.rel='noopener noreferrer';return a;}
async function createVideo(match){
 idle.check();
 if(!connection.connected){openConnection();return;}
 $('jobStatus').textContent='Starting '+match.home+' vs '+match.away+'…';
 const pending=connection.create(match);renderMatches();
 try{const result=await pending;$('jobStatus').textContent='GitHub accepted '+match.home+' vs '+match.away+'. The job checks lineups, then creates and uploads privately. ';$('jobStatus').appendChild(runLink(result.url,'Watch this run →'));}
 catch(error){$('jobStatus').textContent=error.message;if(connection.state(match.fixture_id)?.status==='uncertain')$('jobStatus').appendChild(runLink(ACTIONS_URL,' Check Actions →'));}
 finally{connectionView();renderMatches();}
}
function renderMatches(){
 $('schedule').replaceChildren();if(!scheduleData)return;
 const now=Date.now(),end=now+Number($('window').value)*3600000,league=$('competition').value;
 const rows=scheduleData.matches.filter(m=>Date.parse(m.kickoff)>now&&Date.parse(m.kickoff)<=end&&(league==='all'||String(m.league_id)===league));
 if(!rows.length){const p=document.createElement('p');p.textContent='No accessible upcoming matches are listed for this selection.';$('schedule').appendChild(p);return;}
 const table=document.createElement('table'),head=document.createElement('tr');
 for(const text of ['Match','Competition','Kickoff (SGT)','Create video']){const th=document.createElement('th');th.textContent=text;head.appendChild(th);}table.appendChild(head);
 for(const m of rows){
  const tr=document.createElement('tr');for(const text of [m.home+' vs '+m.away,m.competition||'Competition '+m.league_id,new Date(m.kickoff).toLocaleString('en-SG',{timeZone:'Asia/Singapore',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})]){const td=document.createElement('td');td.textContent=text;tr.appendChild(td);}
  const td=document.createElement('td'),button=document.createElement('button'),gate=readiness(m,now),state=connection.state(m.fixture_id);
  button.className='create';button.textContent=state?.status==='sending'?'Starting…':state?.status==='accepted'?'Requested':state?.status==='uncertain'?'Check Actions':gate.message;
  button.disabled=!gate.ready||Boolean(state);button.setAttribute('aria-label',button.textContent+' · '+m.home+' vs '+m.away);
  button.addEventListener('click',()=>createVideo(m));td.appendChild(button);
  const id=document.createElement('small');id.textContent='Fixture '+m.fixture_id;td.appendChild(id);
  if(state?.url)td.appendChild(runLink(state.url,'View run'));tr.appendChild(td);table.appendChild(tr);
 }$('schedule').appendChild(table);
}
async function loadMatches(){
 const button=$('refresh');button.disabled=true;$('scheduleStatus').textContent='Loading your accessible match schedule…';
 try{
  const r=await fetch('matches.json?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('The schedule has not refreshed yet. Use Refresh the schedule on GitHub.');scheduleData=await r.json();
  const selected=$('competition').value,leagues=new Map(scheduleData.matches.map(m=>[String(m.league_id),m.competition||'Competition '+m.league_id]));for(const league of scheduleData.leagues||[])leagues.set(String(league.id),league.name+(league.country?' — '+league.country:''));$('competition').replaceChildren();
  for(const [value,label] of [['all','All subscribed competitions'],...Array.from(leagues).sort((a,b)=>a[1].localeCompare(b[1]))]){const option=document.createElement('option');option.value=value;option.textContent=label;$('competition').appendChild(option);}
  $('competition').value=selected==='all'||leagues.has(selected)?selected:'all';
  const age=(Date.now()-Date.parse(scheduleData.fetched_at))/60000;$('scheduleStatus').textContent='Snapshot updated '+new Date(scheduleData.fetched_at).toLocaleString('en-SG',{timeZone:'Asia/Singapore'})+' SGT.'+(age>20?' This snapshot is older than 20 minutes; refresh it on GitHub.':'');renderMatches();
 }catch(error){$('scheduleStatus').textContent=error.message;}finally{button.disabled=false;}
}
$('connectForm').addEventListener('submit',async event=>{
 event.preventDefault();if(connecting)return;
 let token=$('githubToken').value,password=$('vaultPassword').value,confirmation=$('vaultConfirm').value;
 const remember=$('rememberToken').checked&&!saved(),current=++operation;
 clearSecrets();busy(true);$('connectionStatus').textContent='Checking GitHub access…';
 try{
  if(remember){validatePassword(password);if(password!==confirmation)throw new VaultError('The unlock passwords do not match.');}
  await connection.connect(token);if(current!==operation)return;
  let saveError=null;
  if(remember){
   try{await vault.save(token,password);}catch(error){saveError=error instanceof VaultError?error.message:'Connected for this visit, but encrypted storage failed. The token was not saved.';}
   if(current!==operation)return;
  }
  idle.touch();connectionView();renderMatches();if(saveError)$('connectionStatus').textContent=saveError;
 }catch(error){if(current===operation){connectionView();$('connectionStatus').textContent=error.message;}}
 finally{token='';password='';confirmation='';if(current===operation)busy(false);}
});
$('unlockForm').addEventListener('submit',async event=>{
 event.preventDefault();if(connecting)return;
 let password=$('unlockPassword').value,token='';const current=++operation;
 clearSecrets();busy(true);$('connectionStatus').textContent='Unlocking saved connection…';
 try{
  token=await vault.unlock(password);if(current!==operation)return;
  await connection.connect(token);if(current!==operation)return;
  idle.touch();connectionView();renderMatches();
 }catch(error){if(current===operation){connectionView();$('connectionStatus').textContent=error instanceof VaultError?error.message:error.message+' If the token expired, forget this saved connection and save a new token.';}}
 finally{token='';password='';if(current===operation)busy(false);}
});
$('rememberToken').addEventListener('change',passwordOptions);
$('disconnect').addEventListener('click',()=>lockConnection());
$('useOnce').addEventListener('click',()=>{useOnce=true;$('rememberToken').checked=false;connectionView();$('githubToken').focus();});
$('forget').addEventListener('click',()=>{
 if(!window.confirm('Forget the encrypted token saved in this browser? You will need your GitHub token to save it again. This does not revoke the token or cancel running jobs.'))return;
 try{operation++;vault.forget();$('rememberToken').checked=vault.supported;lockConnection('Saved connection removed from this browser.');}catch(error){lockConnection(error.message);}
});
window.addEventListener('pagehide',()=>lockConnection());
window.addEventListener('pageshow',()=>{idle.check();connectionView();renderMatches();});
window.addEventListener('storage',event=>{if(event.key===VAULT_KEY||event.key===null)lockConnection('Saved connection changed in another tab. Unlock it again.');});
for(const name of ['pointerdown','keydown','scroll'])window.addEventListener(name,()=>{idle.check();idle.touch();},{passive:true});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)idle.check();});
$('refresh').addEventListener('click',loadMatches);$('window').addEventListener('change',renderMatches);$('competition').addEventListener('change',renderMatches);
setInterval(()=>{idle.check();renderMatches();},30000);connectionView();
