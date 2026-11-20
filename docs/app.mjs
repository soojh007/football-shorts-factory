import {WorkflowConnection,readiness,ACTIONS_URL} from './workflow-client.mjs';
import {SessionConnection} from './session-client.mjs';
const $=id=>document.getElementById(id);
let connection=new WorkflowConnection(),secureOrigin=null,serverMode=false,sameOriginAuth=false;
let scheduleData=null,connecting=false;
function connectionView(){
 if(serverMode){
  $('tokenConnection').hidden=true;$('secureConnection').hidden=false;
  $('connectionSummary').textContent='GitHub sign-in';
  $('githubSignIn').href=secureOrigin+'/auth/login';
  $('githubSignIn').textContent=sameOriginAuth?'Sign in with GitHub':'Open secure dashboard';
  $('githubSignIn').hidden=connection.connected;
  $('connectionStatus').textContent=connection.connected?'Signed in as '+connection.login+'. Sign-in is remembered for up to 30 days on this browser.':'Sign in once to create videos without pasting a GitHub token.';
  $('disconnect').textContent='Sign out';
 }else{
  $('connectionStatus').textContent=connection.connected?'Connected for this page session. Closing or reloading the page disconnects.':'Connect GitHub once to start videos from this page.';
  $('connectForm').hidden=connection.connected;
 }
 $('disconnect').hidden=!connection.connected;
}
function openConnection(fixtureId){
 if(serverMode){
  const target=new URL(sameOriginAuth?'/auth/login':'/',secureOrigin);
  if(fixtureId)target.searchParams.set('fixture',String(fixtureId));
  window.location.assign(target.href);return;
 }
 $('connectionPanel').open=true;$('githubToken').focus();$('connectionPanel').scrollIntoView({behavior:'smooth',block:'center'});
}
async function initializeSignIn(){
 try{
  const r=await fetch('auth-config.json?t='+Date.now(),{cache:'no-store'});if(!r.ok)return;
  const config=await r.json();if(!config.backend_url)return;
  const target=new URL(config.backend_url);
  if(target.protocol!=='https:'||target.pathname!=='/'||target.username||target.password||target.search||target.hash)throw Error('Invalid secure dashboard address.');
  secureOrigin=target.origin;serverMode=true;sameOriginAuth=window.location.origin===secureOrigin;
  connection.disconnect();connection=new SessionConnection();$('githubToken').value='';
  if(!sameOriginAuth){const destination=new URL(secureOrigin);const fixture=new URLSearchParams(window.location.search).get('fixture');if(fixture&&/^\d{1,15}$/.test(fixture))destination.searchParams.set('fixture',fixture);window.location.replace(destination.href);return;}
  await connection.restore();
  connectionView();await loadMatches();
 }catch(error){if(serverMode){connectionView();$('connectionStatus').textContent=error.message;}}
}

function runLink(url,label){const a=document.createElement('a');a.href=url;a.textContent=label;a.target='_blank';a.rel='noopener noreferrer';return a;}
async function createVideo(match){
 if(!connection.connected){openConnection(match.fixture_id);return;}
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
 event.preventDefault();if(connecting)return;connecting=true;const token=$('githubToken').value;$('githubToken').value='';$('connect').disabled=true;$('connectionStatus').textContent='Connecting to GitHub…';
 try{await connection.connect(token);connectionView();renderMatches();}catch(error){$('connectionStatus').textContent=error.message;}finally{connecting=false;$('connect').disabled=false;}
});
$('disconnect').addEventListener('click',async()=>{try{if(serverMode&&sameOriginAuth)await connection.signOut();else connection.disconnect();$('githubToken').value='';connectionView();renderMatches();}catch(error){$('connectionStatus').textContent=error.message;}});
window.addEventListener('pagehide',()=>{connection.disconnect();$('githubToken').value='';});
window.addEventListener('pageshow',async event=>{if(event.persisted&&sameOriginAuth){try{await connection.restore();}catch{}}connectionView();renderMatches();});
$('refresh').addEventListener('click',loadMatches);$('window').addEventListener('change',renderMatches);$('competition').addEventListener('change',renderMatches);
setInterval(renderMatches,30000);connectionView();initializeSignIn();
