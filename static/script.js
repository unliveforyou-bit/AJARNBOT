const TOGGLES=[
  {key:'announce_join',label:'เข้าห้อง'},{key:'announce_leave',label:'ออกห้อง'},
  {key:'announce_move',label:'ย้ายห้อง'},{key:'announce_mute',label:'ปิด/เปิดไมค์'},
  {key:'announce_deaf',label:'ปิด/เปิดหู'},{key:'announce_stream',label:'Stream'},
  {key:'announce_video',label:'กล้อง'},
];
const NUMBERS=[
  {key:'content_interval',label:'ส่งมุข/Trivia ทุก (นาที)',min:5,max:240},
  {key:'joke_delay',label:'หน่วงมุข (วินาที)',min:0,max:60},
  {key:'trivia_delay',label:'หน่วง Trivia (วินาที)',min:0,max:60},
  {key:'mute_cooldown_sec',label:'Cooldown Mute (วิ)',min:0,max:30},
  {key:'summary_hour',label:'ส่งสรุปรายวัน (ชม.)',min:0,max:23},
  {key:'joke_downvote_threshold',label:'👎 เพื่อกรองมุข',min:1,max:20},
];
const SPAM_NUMBERS=[
  {key:'spam_max_events',label:'Anti-spam: ครั้งสูงสุด',min:2,max:30},
  {key:'spam_window_sec',label:'Anti-spam: ช่วงเวลา (วิ)',min:10,max:300},
];
function showToast(msg,err=false){
  const t=document.getElementById('toast');t.textContent=msg;
  t.className='toast show'+(err?' err':'');setTimeout(()=>t.className='toast',2200);
}
function buildUI(){
  document.getElementById('toggleGrid').innerHTML=TOGGLES.map(t=>`
    <div class="toggle-item"><span class="toggle-label">${t.label}</span>
    <label class="switch"><input type="checkbox" id="toggle_${t.key}" onchange="toggleConfig('${t.key}',this.checked)">
    <span class="slider"></span></label></div>`).join('');
  document.getElementById('numGrid').innerHTML=NUMBERS.map(n=>`
    <div class="config-item"><label>${n.label}</label>
    <input type="number" id="num_${n.key}" min="${n.min}" max="${n.max}" value="0"></div>`).join('');
  document.getElementById('spamGrid').innerHTML=SPAM_NUMBERS.map(n=>`
    <div class="config-item"><label>${n.label}</label>
    <input type="number" id="num_${n.key}" min="${n.min}" max="${n.max}" value="0"></div>`).join('');
}
function updateClock(){
  const now=new Date();
  const date=now.toLocaleDateString('th-TH',{timeZone:'Asia/Bangkok',day:'numeric',month:'short',year:'2-digit'});
  const time=now.toLocaleTimeString('th-TH',{timeZone:'Asia/Bangkok',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  document.getElementById('clockThai').textContent='🕐 '+date+' '+time;
}
function applyConfig(c){
  TOGGLES.forEach(t=>{const el=document.getElementById('toggle_'+t.key);if(el)el.checked=!!c[t.key];});
  const sc=document.getElementById('toggle_send_content');if(sc)sc.checked=!!c.send_content;
  const sj=document.getElementById('toggle_send_jokes');if(sj)sj.checked=c.send_jokes!==false;
  const st=document.getElementById('toggle_send_trivia');if(st)st.checked=c.send_trivia!==false;
  NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)el.value=c[n.key]??0;});
  SPAM_NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)el.value=c[n.key]??0;});
  // channel dropdowns populated by loadChannelDropdowns()
}
let currentGuildId = window.CURRENT_GUILD_ID || '';
let isOwner=false;
function applyOwnerUI(owner){
  isOwner=owner;
  // ซ่อน owner-only sections สำหรับ guild_admin
  document.querySelectorAll('.owner-only').forEach(el=>{
    el.style.display=owner?'':'none';
  });
  // แสดง badge
  const badge=document.getElementById('roleBadge');
  if(badge){badge.textContent=owner?'👑 Owner':'🛡️ Guild Admin';badge.style.background=owner?'#f0b232':'#5865f2';}
}
async function loadConfig(){
  const r=await fetch('/api/config');
  const c=await r.json();
  applyConfig(c);
  applyOwnerUI(!!c.is_owner);
  // update footer version
  if(c.app_version){
    const ft=document.getElementById('appFooter');
    if(ft)ft.innerHTML='AjarnBot <span style="color:var(--accent);font-weight:700">v'+c.app_version+'</span>'
      +' · '+c.app_build_date
      +' · Built with discord.py + Flask'
      +' · <a href="https://github.com/unliveforyou-bit/AJARNBOT" target="_blank">GitHub</a>';
  }
}
async function loadChannelDropdowns(guildId, savedVoice, savedContent, savedStats){
  const ids=['ch_voice','ch_content','ch_stats'];
  const saved=[String(savedVoice||''),String(savedContent||''),String(savedStats||'')];
  if(!guildId){
    ids.forEach((id,i)=>{
      const sel=document.getElementById(id);
      sel.innerHTML='<option value="">— ยังไม่เลือก (ใช้ Global) —</option>';
    });
    return;
  }
  try{
    const r=await fetch('/api/channels?guild_id='+guildId);
    const channels=await r.json();
    const opts='<option value="">— ยังไม่เลือก —</option>'+channels.map(c=>`<option value="${c.id}">#${c.name}</option>`).join('');
    ids.forEach((id,i)=>{
      const sel=document.getElementById(id);
      sel.innerHTML=opts;
      if(saved[i])sel.value=saved[i];
    });
  }catch(e){
    ids.forEach(id=>{
      document.getElementById(id).innerHTML='<option value="">— โหลดไม่ได้ —</option>';
    });
  }
}
async function loadGuilds(){
  try{
    const r=await fetch('/api/guilds');const guilds=await r.json();
    // populate config-area guildSelect
    const sel=document.getElementById('guildSelect');
    sel.innerHTML='<option value="">🌐 Global (ค่าเริ่มต้นทุก Server)</option>'+guilds.map(g=>`<option value="${g.id}">${g.name}</option>`).join('');
    if(currentGuildId){sel.value=currentGuildId;await onGuildChange();}
    else{await loadGlobalChannels();}
    // populate header guild switcher
    const sw=document.getElementById('guildSwitcher');
    sw.innerHTML='<option value="">— เลือก Server —</option>'+guilds.map(g=>`<option value="${g.id}">${g.name}</option>`).join('');
    if(currentGuildId)sw.value=currentGuildId;
  }catch(e){}
}
async function switchGuild(guildId){
  if(!guildId)return;
  try{
    await fetch('/api/set-guild',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:guildId})});
    currentGuildId=guildId;
    // sync config-area dropdown
    const sel=document.getElementById('guildSelect');
    if(sel){sel.value=guildId;await onGuildChange();}
    // reload all data panels
    refreshStatus();loadHeatmap();loadHistory();
    showToast('เปลี่ยนเป็น '+document.getElementById('guildSwitcher').selectedOptions[0].text);
  }catch(e){showToast('เปลี่ยน Server ไม่ได้',true);}
}
async function loadGlobalChannels(){
  const r=await fetch('/api/config');const cfg=await r.json();
  // For global, show all channels from first available guild
  const guilds_r=await fetch('/api/guilds');const guilds=await guilds_r.json();
  const gid=guilds.length?guilds[0].id:'';
  await loadChannelDropdowns(gid,cfg.channel_voice,cfg.channel_content,cfg.channel_stats);
}
async function onGuildChange(){
  currentGuildId=document.getElementById('guildSelect').value;
  if(!currentGuildId){await loadGlobalChannels();return;}
  const r=await fetch('/api/guild-config?guild_id='+currentGuildId);
  const cfg=await r.json();
  await loadChannelDropdowns(currentGuildId,cfg.channel_voice,cfg.channel_content,cfg.channel_stats);
}
async function toggleConfig(key,val){
  const p={};p[key]=val;
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  showToast('บันทึกแล้ว');
}
async function saveNums(){
  const p={};NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)p[n.key]=Number(el.value);});
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  showToast('บันทึกแล้ว');
}
async function saveSpam(){
  const p={};SPAM_NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)p[n.key]=Number(el.value);});
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  showToast('บันทึก Anti-spam แล้ว');
}
async function saveChannels(){
  const p={channel_voice:document.getElementById('ch_voice').value,
           channel_content:document.getElementById('ch_content').value,
           channel_stats:document.getElementById('ch_stats').value};
  // values from select are always valid IDs or empty
  if(currentGuildId){
    const sel=document.getElementById('guildSelect');
    const name=sel.selectedOptions[0]?sel.selectedOptions[0].text:'Server';
    await fetch('/api/guild-config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({guild_id:currentGuildId,...p})});
    showToast('บันทึก Channel Routing สำหรับ '+name);
  } else {
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
    showToast('บันทึก Global Channel Routing แล้ว');
  }
}
async function action(type){
  const body=JSON.stringify({guild_id:currentGuildId||null});
  const r=await fetch('/api/action/'+type,{method:'POST',headers:{'Content-Type':'application/json'},body});
  const d=await r.json();showToast(d.ok?'ส่งแล้ว!':'เกิดข้อผิดพลาด',!d.ok);
}
async function refreshStatus(){
  try{
    const gp=currentGuildId?'?guild_id='+currentGuildId:'';
    const r=await fetch('/api/status'+gp);const d=await r.json();
    document.getElementById('statusDot').className='status-dot'+(d.online?' online':'');
    document.getElementById('statusLabel').textContent=d.online?'ออนไลน์':'ออฟไลน์';
    document.getElementById('upVal').textContent=d.uptime||'-';
    document.getElementById('evJoin').textContent=d.event_counts.join||0;
    document.getElementById('evLeave').textContent=d.event_counts.leave||0;
    document.getElementById('evMute').textContent=d.event_counts.mute||0;
    document.getElementById('evDeaf').textContent=d.event_counts.deaf||0;
    document.getElementById('evStream').textContent=d.event_counts.stream||0;
    document.getElementById('evVideo').textContent=d.event_counts.video||0;
    const vl=document.getElementById('voiceList');
    if(d.voice_users.length===0){
      vl.innerHTML='<span class="empty-msg">ไม่มีใครอยู่</span>';
    }else{
      // user rows — แสดงชื่อ + ห้อง + เวลา
      const userRows=d.voice_users.map(u=>
        '<div class="stat-row">'
        +'<span class="stat-name">'+u.name+'</span>'
        +(u.channel?'<span class="voice-ch"># '+u.channel+'</span>':'')
        +'<span class="stat-time">'+u.duration+'</span>'
        +'</div>'
      ).join('');
      // นับคนต่อห้อง → เรียงมากสุด
      const chMap={};
      d.voice_users.forEach(u=>{const c=u.channel||'?';chMap[c]=(chMap[c]||0)+1;});
      const chRanked=Object.entries(chMap).sort((a,b)=>b[1]-a[1]);
      const chRows=chRanked.map(([ch,cnt],i)=>
        '<div class="stat-row ch-rank-row">'
        +'<span class="stat-rank">'+(i+1)+'.</span>'
        +'<span class="stat-name"># '+ch+'</span>'
        +'<span class="stat-time">'+cnt+' คน</span>'
        +'</div>'
      ).join('');
      vl.innerHTML=userRows
        +'<div class="ch-rank-divider">ลำดับห้องเสียงยอดนิยม</div>'
        +chRows;
    }
    const medals=['🥇','🥈','🥉'];const sl=document.getElementById('statsList');
    sl.innerHTML=d.weekly_stats.length===0?'<span class="empty-msg">ยังไม่มีข้อมูล</span>'
      :d.weekly_stats.map((s,i)=>'<div class="stat-row"><span class="stat-rank">'+(medals[i]||(i+1)+'.')+'</span>'
        +'<span class="stat-name"><a href="/profile/'+s.uid+'" target="_blank">'+s.name+'</a></span>'
        +'<span class="stat-time">'+s.time+'</span></div>').join('');
  }catch(e){document.getElementById('statusLabel').textContent='กำลังเชื่อมต่อ...';}
}
async function loadHeatmap(){
  const gp=currentGuildId?'?guild_id='+currentGuildId:'';
  const r=await fetch('/api/heatmap'+gp);const d=await r.json();
  // flatten multi-guild heatmap: sum all guilds
  const flat={};
  for(let h=0;h<24;h++)flat[String(h)]=0;
  if(typeof Object.values(d)[0]==='object'){
    for(const gdata of Object.values(d)){for(let h=0;h<24;h++){flat[String(h)]=(flat[String(h)]||0)+(Number(gdata[String(h)])||0);}}
  } else {
    for(let h=0;h<24;h++)flat[String(h)]=Number(d[String(h)]||0);
  }
  const max=Math.max(...Object.values(flat).map(Number),1);
  const chart=document.getElementById('heatmapChart');chart.innerHTML='';
  for(let h=0;h<24;h++){
    const count=Number(flat[String(h)]||0);const pct=Math.round((count/max)*100);
    const bar=document.createElement('div');bar.className='heatmap-bar';
    bar.style.cssText='background:rgba(88,101,242,'+(0.15+(pct/100)*0.85).toFixed(2)+');height:'+Math.max(pct,2)+'%';
    bar.title=String(h).padStart(2,'0')+':00 — '+count+' joins';chart.appendChild(bar);}
}
async function loadHistory(){
  const gp=currentGuildId?'?guild_id='+currentGuildId:'';
  const r=await fetch('/api/history'+gp);const d=await r.json();
  const body=document.getElementById('historyBody');
  if(!d.length){body.innerHTML='<tr><td colspan="5" style="color:var(--muted);padding:12px">ยังไม่มีข้อมูล</td></tr>';return;}
  body.innerHTML=d.slice().reverse().slice(0,50).map(s=>
    '<tr><td>'+s.name+'</td><td style="color:var(--muted)">'+s.channel+'</td>'
    +'<td style="color:var(--muted)">'+s.join+'</td><td style="color:var(--muted)">'+s.leave+'</td>'
    +'<td>'+s.duration+'</td></tr>').join('');
}
async function loadVotes(){
  const r=await fetch('/api/votes');const d=await r.json();
  const el=document.getElementById('votesList');
  if(!d.length){el.innerHTML='<span class="empty-msg">ยังไม่มีคะแนน</span>';return;}
  el.innerHTML=d.slice(0,20).map(v=>
    '<div class="stat-row" style="gap:10px">'
    +'<span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'+(v.filtered?';color:var(--red)':'')+'" title="'+v.joke+'">'+v.joke+'</span>'
    +'<span style="color:var(--green);font-size:13px;min-width:36px;text-align:right">👍 '+v.up+'</span>'
    +'<span style="color:var(--red);font-size:13px;min-width:36px;text-align:right">👎 '+v.down+'</span>'
    +(v.filtered?'<span style="font-size:11px;color:var(--red);min-width:40px">กรองแล้ว</span>':'<span style="min-width:40px"></span>')
    +'</div>').join('');
}
async function resetVotes(){
  if(!confirm('รีเซ็ตคะแนนมุขทั้งหมด?'))return;
  await fetch('/api/votes/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
  showToast('รีเซ็ตแล้ว');loadVotes();
}
function toggleTheme(){const light=document.body.classList.toggle('light');localStorage.setItem('theme',light?'light':'dark');document.getElementById('themeBtn').textContent=light?'☀️':'🌙';}
async function loadLogs(){
  try{
    const r=await fetch('/api/logs');const d=await r.json();
    const box=document.getElementById('logBox');
    box.textContent=d.lines.join('\n')||'(ยังไม่มี log)';
    box.scrollTop=box.scrollHeight;
  }catch(e){document.getElementById('logBox').textContent='โหลด log ไม่ได้';}
}
if(localStorage.getItem('theme')==='light'){document.body.classList.add('light');document.getElementById('themeBtn').textContent='☀️';}
buildUI();loadConfig();loadGuilds();refreshStatus();loadHeatmap();loadHistory();loadVotes();loadLogs();
updateClock();setInterval(updateClock,1000);
setInterval(loadLogs,30000);
setInterval(refreshStatus,8000);setInterval(loadHeatmap,30000);setInterval(loadHistory,15000);setInterval(loadVotes,20000);
