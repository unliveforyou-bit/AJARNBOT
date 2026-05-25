// Mark JS as available (enables CSS entrance animations)
document.documentElement.classList.add('js');

// ── CSRF-aware POST helper ─────────────────────────────────────────────────────
let _csrfToken = '';
let _csrfExpiry = 0;         // epoch ms — refresh before 55-min mark (server TTL = 1h)
const _CSRF_TTL_MS = 55 * 60 * 1000;

async function _getCSRF() {
  if (_csrfToken && Date.now() < _csrfExpiry) return _csrfToken;
  try {
    const r = await fetch('/api/csrf-token');
    if (r.ok) {
      const d = await r.json();
      _csrfToken  = d.token || '';
      _csrfExpiry = Date.now() + _CSRF_TTL_MS;
    } else {
      // 401/403 = session expired — redirect to login
      if (r.status === 401 || r.status === 403) { window.location.href = '/login'; }
      _csrfToken = '';
    }
  } catch (_) { /* network error — token stays empty, POST will get 403 */ }
  return _csrfToken;
}
async function _post(url, body = {}) {
  const tok = await _getCSRF();
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tok },
    body: JSON.stringify(body),
  });
  // If server rejects token (403), clear cache so next call re-fetches
  if (res.status === 403) { _csrfToken = ''; _csrfExpiry = 0; }
  return res;
}
// ──────────────────────────────────────────────────────────────────────────────
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
let _toastTimer=null;
function showToast(msg,err=false){
  const t=document.getElementById('toast');t.textContent=msg;
  t.className='toast show'+(err?' err':'');
  clearTimeout(_toastTimer);_toastTimer=setTimeout(()=>t.className='toast',2200);
}
let _loadGeneration=0;
function escHTML(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

// ── Avatar + profile-link helpers ────────────────────────────────────────────
/** Returns <img> or initial-circle for a user */
function _avImg(uid,name){
  const url=_avatarMap[uid];
  const init=escHTML((name||'?')[0].toUpperCase());
  return url
    ?`<img src="${escHTML(url)}?size=64" class="row-avatar" alt="" loading="lazy" decoding="async">`
    :`<div class="row-avatar row-avatar-init" aria-hidden="true">${init}</div>`;
}
/** Returns name wrapped in a profile link */
function _profileLink(uid,name){
  return`<a href="/profile/${encodeURIComponent(uid)}" target="_blank" class="row-name-link">${escHTML(name)}</a>`;
}
function debounce(fn,ms){let t;return(...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);};}
const _debouncedFilterHistory=debounce(v=>filterHistory(v),150);
const _debouncedFilterMembers=debounce(v=>filterMembers(v),150);
function withLoading(btn,fn){
  if(!btn)return fn();
  const orig=btn.innerHTML;
  btn.disabled=true;btn.classList.add('loading');
  btn.innerHTML='<i class="ph-bold ph-circle-notch"></i> กำลังบันทึก...';
  return Promise.resolve(fn()).finally(()=>{btn.disabled=false;btn.classList.remove('loading');btn.innerHTML=orig;});
}
function buildUI(){
  // #10 — toggle inputs: aria-label for screen readers (visible label is in .toggle-label span)
  document.getElementById('toggleGrid').innerHTML=TOGGLES.map(t=>`
    <div class="toggle-item"><span class="toggle-label" id="lbl_${t.key}">${t.label}</span>
    <label class="switch"><input type="checkbox" id="toggle_${t.key}" aria-labelledby="lbl_${t.key}" onchange="toggleConfig('${t.key}',this.checked)">
    <span class="slider"></span></label></div>`).join('');
  // #8 — number inputs: <label for="..."> wired to input id
  document.getElementById('numGrid').innerHTML=NUMBERS.map(n=>`
    <div class="config-item"><label for="num_${n.key}">${n.label}</label>
    <input type="number" id="num_${n.key}" min="${n.min}" max="${n.max}" value="0"></div>`).join('');
  document.getElementById('spamGrid').innerHTML=SPAM_NUMBERS.map(n=>`
    <div class="config-item"><label for="num_${n.key}">${n.label}</label>
    <input type="number" id="num_${n.key}" min="${n.min}" max="${n.max}" value="0"></div>`).join('');
}
function updateClock(){
  const now=new Date();
  const date=now.toLocaleDateString('th-TH',{timeZone:'Asia/Bangkok',day:'numeric',month:'short',year:'2-digit'});
  const time=now.toLocaleTimeString('th-TH',{timeZone:'Asia/Bangkok',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  document.getElementById('clockThai').innerHTML='<span aria-hidden="true">🕐</span> '+date+' '+time;
}
function applyConfig(c){
  TOGGLES.forEach(t=>{const el=document.getElementById('toggle_'+t.key);if(el)el.checked=!!c[t.key];});
  const sc=document.getElementById('toggle_send_content');if(sc)sc.checked=!!c.send_content;
  const sj=document.getElementById('toggle_send_jokes');if(sj)sj.checked=!!c.send_jokes;
  const st=document.getElementById('toggle_send_trivia');if(st)st.checked=!!c.send_trivia;
  const sr=document.getElementById('toggle_send_ready_message');if(sr)sr.checked=c.send_ready_message!==false;
  NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)el.value=c[n.key]??0;});
  SPAM_NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)el.value=c[n.key]??0;});
  // channel dropdowns populated by loadChannelDropdowns()
}
let currentGuildId = window.CURRENT_GUILD_ID || '';
if(currentGuildId)sessionStorage.setItem('currentGuildId',currentGuildId);
let isOwner=false;
function applyOwnerUI(owner){
  isOwner=owner;
  document.querySelectorAll('.owner-only').forEach(el=>{
    el.style.display=owner?'':'none';
  });
  const badge=document.getElementById('roleBadge');
  if(badge){
    const iconClass=owner?'ph-crown':'ph-shield-check';
    const label=owner?'Owner':'Guild Admin';
    badge.innerHTML='<i class="ph-bold '+iconClass+'" aria-hidden="true"></i> '+label;
    badge.setAttribute('aria-label',label);
    badge.style.background=owner?'#7d5300':'#3730a3';
    badge.style.color='white';
  }
}
async function loadConfig(){
  document.querySelector('main').setAttribute('aria-busy','true');
  try{
    // Always fetch global config first — for is_owner flag + version info
    const r=await fetch('/api/config');
    if(!r.ok)throw new Error(r.status);
    const c=await r.json();
    applyOwnerUI(!!c.is_owner);
    if(c.app_version){
      const ft=document.getElementById('appFooter');
      if(ft)ft.innerHTML='AjarnBot <span style="color:var(--accent);font-weight:700">v'+escHTML(c.app_version)+'</span>'
        +' · '+escHTML(c.app_build_date)
        +' · Built with discord.py + Flask'
        +' · <a href="https://github.com/unliveforyou-bit/AJARNBOT" target="_blank">GitHub</a>';
    }
    if(currentGuildId){
      // Apply effective per-guild config (guild overrides + global fallback)
      const gr=await fetch('/api/guild-config?guild_id='+currentGuildId);
      if(!gr.ok)throw new Error(gr.status);
      const gc=await gr.json();
      applyConfig(gc);
    }else{
      applyConfig(c);
    }
    // Load guilds after isOwner is known
    await loadGuilds();
  }finally{
    document.querySelector('main').setAttribute('aria-busy','false');
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
    const r=await fetch('/api/channels?guild_id='+encodeURIComponent(guildId));
    if(!r.ok)throw new Error(r.status);
    const channels=await r.json();
    const opts='<option value="">— ยังไม่เลือก —</option>'+channels.map(c=>`<option value="${escHTML(c.id)}">#${escHTML(c.name)}</option>`).join('');
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
    const r=await fetch('/api/my-guilds');
    if(!r.ok)throw new Error(r.status);
    const guilds=await r.json();
    // populate config-area guildSelect — show "Global" only for owners
    const sel=document.getElementById('guildSelect');
    const globalOpt=isOwner?'<option value="">🌐 Global (ค่าเริ่มต้นทุก Server)</option>':'';
    sel.innerHTML=globalOpt+guilds.map(g=>`<option value="${escHTML(g.id)}">${escHTML(g.name)}</option>`).join('');
    if(currentGuildId){sel.value=currentGuildId;await onGuildChange();}
    else if(isOwner){await loadGlobalChannels();}
    else if(guilds.length>0){
      // Non-owner: auto-select first guild
      currentGuildId=guilds[0].id;sel.value=currentGuildId;await onGuildChange();
    }
    // populate header guild switcher
    const sw=document.getElementById('guildSwitcher');
    sw.innerHTML='<option value="">— เลือก Server —</option>'+guilds.map(g=>`<option value="${escHTML(g.id)}">${escHTML(g.name)}</option>`).join('');
    if(currentGuildId)sw.value=currentGuildId;
  }catch(e){showToast('โหลดรายการ Server ไม่ได้',true);}
}
async function switchGuild(guildId){
  if(!guildId)return;
  const gen=++_loadGeneration;
  try{
    await _post('/api/set-guild',{guild_id:guildId});
    if(gen!==_loadGeneration)return; // user switched again before response
    currentGuildId=guildId;
    sessionStorage.setItem('currentGuildId',guildId);
    const sel=document.getElementById('guildSelect');
    if(sel){sel.value=guildId;await onGuildChange();}
    refreshStatus();loadHeatmap();loadHistory();loadContribGraph();loadVotes();
    loadChannelActivity();loadDAU();loadLeaderboard(_lbPeriod);loadInactive();loadRetention();
    loadDowHeatmap();loadHistogram();loadMembers();loadNotionStatus();
    loadUserGrowth();loadChannelDetails();loadCoPresence();loadMilestoneLog();loadLiveVoice();
    loadForecast();loadCohortMatrix();loadTimeOfDay();loadChurnRisk();loadRecords();loadFormRegistrations();loadPointsBoard();
    loadGuildHealth();loadStreakBoard();loadMarathon();loadEngagementScore();loadNewUserJourney();loadPeakSummary();
    showToast('เปลี่ยนเป็น '+document.getElementById('guildSwitcher').selectedOptions[0].text);
  }catch(e){showToast('เปลี่ยน Server ไม่ได้',true);}
}
async function loadGlobalChannels(){
  try{
    const r=await fetch('/api/config');if(!r.ok)throw new Error(r.status);const cfg=await r.json();
    const guilds_r=await fetch('/api/guilds');if(!guilds_r.ok)throw new Error(guilds_r.status);const guilds=await guilds_r.json();
    const gid=guilds.length?guilds[0].id:'';
    await loadChannelDropdowns(gid,cfg.channel_voice,cfg.channel_content,cfg.channel_stats);
  }catch(e){showToast('โหลด config ไม่ได้',true);}
}
async function onGuildChange(){
  currentGuildId=document.getElementById('guildSelect').value;
  if(!currentGuildId){await loadGlobalChannels();return;}
  try{
    const r=await fetch('/api/guild-config?guild_id='+encodeURIComponent(currentGuildId));
    if(!r.ok)throw new Error(r.status);
    const cfg=await r.json();
    applyConfig(cfg);
    await loadChannelDropdowns(currentGuildId,cfg.channel_voice,cfg.channel_content,cfg.channel_stats);
  }catch(e){showToast('โหลด guild config ไม่ได้',true);}
}
function _configUrl(extraBody={}){
  // Route saves: guild-config when guild selected, global config when owner + no guild
  if(currentGuildId){
    return ['/api/guild-config',{guild_id:currentGuildId,...extraBody}];
  }
  return ['/api/config',extraBody];
}
const toggleConfig=debounce(async function(key,val){
  const p={};p[key]=val;
  try{
    const [url,body]=_configUrl(p);
    const r=await _post(url,body);
    if(!r.ok)throw new Error(r.status);
    showToast('บันทึกแล้ว');
  }catch(e){showToast('บันทึกไม่สำเร็จ',true);}
},300);
async function saveNums(btn){
  withLoading(btn,async()=>{
    const p={};NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)p[n.key]=Number(el.value);});
    try{
      const [url,body]=_configUrl(p);
      const r=await _post(url,body);
      if(!r.ok)throw new Error(r.status);
      showToast('บันทึกแล้ว');
    }catch(e){showToast('บันทึกไม่สำเร็จ',true);}
  });
}
async function saveSpam(btn){
  withLoading(btn,async()=>{
    const p={};SPAM_NUMBERS.forEach(n=>{const el=document.getElementById('num_'+n.key);if(el)p[n.key]=Number(el.value);});
    try{
      const [url,body]=_configUrl(p);
      const r=await _post(url,body);
      if(!r.ok)throw new Error(r.status);
      showToast('บันทึก Anti-spam แล้ว');
    }catch(e){showToast('บันทึกไม่สำเร็จ',true);}
  });
}
async function saveChannels(btn){
  withLoading(btn,async()=>{
    const p={channel_voice:document.getElementById('ch_voice').value,
             channel_content:document.getElementById('ch_content').value,
             channel_stats:document.getElementById('ch_stats').value};
    try{
      if(currentGuildId){
        const sel=document.getElementById('guildSelect');
        const name=sel.selectedOptions[0]?sel.selectedOptions[0].text:'Server';
        const r=await _post('/api/guild-config',{guild_id:currentGuildId,...p});
        if(!r.ok)throw new Error(r.status);
        showToast('บันทึก Channel Routing สำหรับ '+name);
      }else{
        const r=await _post('/api/config',p);
        if(!r.ok)throw new Error(r.status);
        showToast('บันทึก Global Channel Routing แล้ว');
      }
    }catch(e){showToast('บันทึกไม่สำเร็จ',true);}
  });
}
async function action(type){
  try{
    const r=await _post('/api/action/'+type,{guild_id:currentGuildId||null});
    if(!r.ok)throw new Error(r.status);
    const d=await r.json();showToast(d.ok?'ส่งแล้ว!':'เกิดข้อผิดพลาด',!d.ok);
  }catch(e){showToast('เกิดข้อผิดพลาด',true);}
}
async function refreshStatus(){
  if(!currentGuildId)return;
  try{
    const r=await fetch('/api/status?guild_id='+currentGuildId);const d=await r.json();
    if(d.error)return;
    const dot=document.getElementById('statusDot');
    dot.className='status-dot'+(d.online?' online':'');
    // #16 — status dot is decorative shape; dynamic aria-label conveys state
    dot.setAttribute('aria-label',d.online?'บอทออนไลน์':'บอทออฟไลน์');
    document.getElementById('statusLabel').textContent=d.online?'ออนไลน์':'ออฟไลน์';
    document.getElementById('upVal').textContent=d.uptime||'-';
    // event_counts are global totals — hide them in multi-guild mode
    const ec=d.event_counts||{};
    const ecMap={evJoin:'join',evLeave:'leave',evMute:'mute',evDeaf:'deaf',evStream:'stream',evVideo:'video'};
    Object.entries(ecMap).forEach(([id,key])=>{
      const el=document.getElementById(id);if(!el)return;
      const newVal=ec[key]!=null?Number(ec[key]).toLocaleString():'—';
      if(el.textContent!==newVal){el.textContent=newVal;flashStat(id);}
    });
    const vl=document.getElementById('voiceList');
    if(d.voice_users.length===0){
      vl.innerHTML='<span class="empty-msg">ไม่มีใครอยู่</span>';
    }else{
      // user rows — แสดงชื่อ + ห้อง + เวลา
      const userRows=d.voice_users.map(u=>{
        const rowLabel=escHTML(u.name)+(u.channel?' อยู่ใน '+escHTML(u.channel):'')+' นาน '+escHTML(u.duration);
        const avatarEl=u.avatar
          ?'<img src="'+escHTML(u.avatar)+'" class="voice-avatar" alt="" loading="lazy">'
          :'<div class="voice-avatar-placeholder" aria-hidden="true">'+escHTML(u.name.charAt(0).toUpperCase())+'</div>';
        return '<div class="stat-row" aria-label="'+rowLabel+'">'
          +avatarEl
          +'<span class="stat-name" aria-hidden="true">'+escHTML(u.name)+'</span>'
          +(u.channel?'<span class="voice-ch" aria-hidden="true"># '+escHTML(u.channel)+'</span>':'')
          +'<span class="stat-time" aria-hidden="true">'+escHTML(u.duration)+'</span>'
          +'</div>';
      }).join('');
      // นับคนต่อห้อง → เรียงมากสุด
      const chMap={};
      d.voice_users.forEach(u=>{const c=u.channel||'?';chMap[c]=(chMap[c]||0)+1;});
      const chRanked=Object.entries(chMap).sort((a,b)=>b[1]-a[1]);
      const chRows=chRanked.map(([ch,cnt],i)=>
        '<div class="stat-row ch-rank-row">'
        +'<span class="stat-rank">'+(i+1)+'.</span>'
        +'<span class="stat-name"># '+escHTML(ch)+'</span>'
        +'<span class="stat-time">'+cnt+' คน</span>'
        +'</div>'
      ).join('');
      vl.innerHTML=userRows
        +'<div class="ch-rank-divider">ลำดับห้องเสียงยอดนิยม</div>'
        +chRows;
    }
    // avg session + total sessions
    const avgEl=document.getElementById('avgSess');if(avgEl)avgEl.textContent=d.avg_session_fmt||'—';
    const totEl=document.getElementById('totalSess');if(totEl)totEl.textContent=d.total_sessions!=null?d.total_sessions.toLocaleString():'—';
    // KPI bar — online now + avg session
    const ko=document.getElementById('kpiOnlineNow');if(ko)ko.textContent=d.voice_users?d.voice_users.length:0;
    const ka=document.getElementById('kpiAvgSession');if(ka)ka.textContent=d.avg_session_fmt||'—';
  }catch(e){document.getElementById('statusLabel').textContent='กำลังเชื่อมต่อ...';}
}
async function loadHeatmap(){
  const gp=currentGuildId?'?guild_id='+currentGuildId:'';
  let d;try{const r=await fetch('/api/heatmap'+gp);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d)return;
  const flat={};
  for(let h=0;h<24;h++)flat[String(h)]=0;
  if(typeof Object.values(d)[0]==='object'){
    for(const gdata of Object.values(d)){for(let h=0;h<24;h++){flat[String(h)]=(flat[String(h)]||0)+(Number(gdata[String(h)])||0);}}
  } else {
    for(let h=0;h<24;h++)flat[String(h)]=Number(d[String(h)]||0);
  }
  const values=Array.from({length:24},(_,h)=>Number(flat[String(h)]));
  const max=Math.max(...values,1);
  const total=values.reduce((a,b)=>a+b,0);
  const peakH=values.indexOf(Math.max(...values));

  // Color interpolation: dark navy → discord blue → soft violet
  function heatColor(pct){
    if(pct===0)return '#1a2436';
    if(pct<0.5){const t=pct*2;return`rgb(${Math.round(0x1e+(0x58-0x1e)*t)},${Math.round(0x3a+(0x65-0x3a)*t)},${Math.round(0x5f+(0xf2-0x5f)*t)}`+')';}
    const t=(pct-0.5)*2;return`rgb(${Math.round(0x58+(0xa7-0x58)*t)},${Math.round(0x65+(0x8b-0x65)*t)},${Math.round(0xf2+(0xfa-0xf2)*t)})`;
  }

  const chart=document.getElementById('heatmapChart');chart.innerHTML='';

  // Summary row
  const summary=document.createElement('div');summary.className='heatmap-summary';
  if(total){
    summary.innerHTML=`<span style="display:flex;align-items:center;gap:5px"><i class="ph-bold ph-lightning" style="color:var(--accent)"></i>Peak <strong>${String(peakH).padStart(2,'0')}:00</strong>&nbsp;·&nbsp;${values[peakH]} joins</span><span class="hm-total">${total.toLocaleString()} joins รวม</span>`;
  } else {
    summary.innerHTML='<span style="color:var(--muted)">ยังไม่มีข้อมูล — จะแสดงเมื่อมีคนเข้าห้อง Voice</span>';
  }
  chart.appendChild(summary);

  // Chart area = Y-axis label + bars
  const chartRow=document.createElement('div');chartRow.className='heatmap-chart-row';

  // Y-axis label
  const yAxis=document.createElement('div');yAxis.className='heatmap-yaxis';
  yAxis.innerHTML='<span>จำนวน joins</span>';
  chartRow.appendChild(yAxis);

  // Bar columns
  const barsWrap=document.createElement('div');barsWrap.className='heatmap-bars';
  const animated=[];
  for(let h=0;h<24;h++){
    const count=values[h];const pct=count/max;const isPeak=h===peakH&&count>0;
    const col=document.createElement('div');col.className='heatmap-col';
    const barArea=document.createElement('div');barArea.className='heatmap-bar-area';
    const bar=document.createElement('div');
    bar.className='heatmap-bar'+(isPeak?' peak':'');
    bar.style.background=heatColor(pct);
    const hLabel=String(h).padStart(2,'0')+':00 — '+count+' joins';
    bar.title=hLabel;bar.setAttribute('role','img');bar.setAttribute('aria-label',hLabel);bar.setAttribute('tabindex','0');
    barArea.appendChild(bar);
    const lbl=document.createElement('div');lbl.className='heatmap-hour-label';
    lbl.textContent=String(h).padStart(2,'0');  // show every hour
    col.appendChild(barArea);col.appendChild(lbl);
    barsWrap.appendChild(col);
    animated.push({el:bar,scale:Math.max(pct,0.02)});
  }
  chartRow.appendChild(barsWrap);
  chart.appendChild(chartRow);
  requestAnimationFrame(()=>{animated.forEach(({el,scale})=>{el.style.transform='scaleY('+scale+')';});});
}
async function loadContribGraph(){
  const gp=currentGuildId?'?guild_id='+currentGuildId+'&days=365':'?days=365';
  const container=document.getElementById('contribGrid');
  if(!container)return;
  try{
    const r=await fetch('/api/user-daily'+gp);
    const data=await r.json();
    const users=Object.entries(data);
    if(!users.length){container.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}

    // 53-week Sunday-based grid (GitHub style)
    // Use local date string to avoid UTC offset shifting dates by 1 day (UTC+7 issue)
    function localISO(d){const yr=d.getFullYear(),mo=String(d.getMonth()+1).padStart(2,'0'),dy=String(d.getDate()).padStart(2,'0');return`${yr}-${mo}-${dy}`;}
    const today=new Date();today.setHours(0,0,0,0);
    const todayDow=today.getDay();
    const startDate=new Date(today);
    startDate.setDate(today.getDate()-todayDow-52*7);
    const totalCells=53*7;
    const allDates=[];
    for(let i=0;i<totalCells;i++){
      const d=new Date(startDate);d.setDate(startDate.getDate()+i);
      allDates.push(localISO(d));
    }

    // Month labels: position at column where month changes
    const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const CELL_W=16; // 13px cell + 3px gap
    const monthLabels=[];
    allDates.forEach((dateStr,i)=>{
      const dt=new Date(dateStr);const col=Math.floor(i/7);
      if(dt.getDate()<=7&&!monthLabels.find(m=>m.col===col)){
        monthLabels.push({col,label:MONTHS[dt.getMonth()]});
      }
    });
    const monthRowHTML=monthLabels.map(m=>`<span class="contrib-month-lbl" style="left:${m.col*CELL_W}px">${m.label}</span>`).join('');
    const totalColsW=53*CELL_W-3; // subtract last gap

    // Day-of-week labels: show Mon, Wed, Fri only (rows 1,3,5)
    const DOWS=['','Mon','','Wed','','Fri',''];
    const dowHTML=DOWS.map(d=>`<span>${d}</span>`).join('');

    const legendCells=['l0','l1','l2','l3','l4'].map(l=>`<div class="contrib-cell ${l}" style="width:13px;height:13px"></div>`).join('');

    const html=users.map(([uid,udata])=>{
      const dateMap=udata.dates||{};
      const totalJoins=Object.values(dateMap).reduce((a,b)=>a+b,0);
      const activeDays=Object.keys(dateMap).length;
      const maxVal=Math.max(...Object.values(dateMap).map(Number),1);
      const initial=(udata.name||'?').charAt(0).toUpperCase();

      function level(count){
        if(!count)return 'l0';const rv=count/maxVal;
        if(rv<=0.25)return 'l1';if(rv<=0.50)return 'l2';if(rv<=0.75)return 'l3';return 'l4';
      }
      const cells=allDates.map(key=>{
        const dt=new Date(key);const isFuture=dt>today;const count=dateMap[key]||0;
        const lbl=dt.toLocaleDateString('th-TH',{day:'numeric',month:'short',year:'2-digit'});
        const tip=lbl+(count?' · '+count+' joins':' · ไม่มีกิจกรรม');
        return`<div class="contrib-cell ${isFuture?'lx':level(count)}" title="${tip}"></div>`;
      }).join('');

      const alltimeSec=udata.alltime_seconds||0;
      const streakMax=udata.streak_max||0;
      const sessCount=udata.session_count||0;
      function fmtSec(s){if(!s)return'-';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);return h?h+'h '+m+'m':m+'m';}
      return`<div class="contrib-user-block">
        <div class="contrib-user-header">
          <div class="contrib-avatar">${escHTML(initial)}</div>
          <div class="contrib-user-info">
            <span class="contrib-user-name">${escHTML(udata.name)}</span>
            <div class="contrib-user-badges">
              <span class="contrib-badge accent">${totalJoins.toLocaleString()} joins</span>
              <span class="contrib-badge">${activeDays} วันที่ active</span>
              ${alltimeSec?'<span class="contrib-badge">⏱ '+fmtSec(alltimeSec)+'</span>':''}
              ${streakMax?'<span class="contrib-badge">🔥 streak max '+streakMax+' วัน</span>':''}
              ${sessCount?'<span class="contrib-badge">'+sessCount+' sessions</span>':''}
            </div>
          </div>
        </div>
        <div class="contrib-graph-outer">
          <div class="contrib-month-row" style="width:${totalColsW}px">${monthRowHTML}</div>
          <div class="contrib-body-row">
            <div class="contrib-dow-labels">${dowHTML}</div>
            <div class="contrib-grid-wrap"><div class="contrib-grid">${cells}</div></div>
          </div>
        </div>
      </div>`;
    }).join('');

    container.innerHTML=html
      +`<div class="contrib-legend">น้อย<div class="contrib-legend-cells">${legendCells}</div>มาก</div>`;
  }catch(e){
    if(container)container.innerHTML='<span class="empty-msg">โหลดไม่ได้</span>';
  }
}
async function loadVotes(){
  let d;try{const r=await fetch('/api/votes');if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  const el=document.getElementById('votesList');
  if(!d||!d.length){el.innerHTML='<span class="empty-msg">ยังไม่มีคะแนน</span>';return;}
  el.innerHTML=d.slice(0,20).map(v=>
    '<div class="stat-row" style="gap:10px">'
    +'<span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'+(v.filtered?';color:var(--red)':'')+'" title="'+escHTML(v.joke)+'">'+escHTML(v.joke)+'</span>'
    +'<span style="color:var(--green);font-size:13px;min-width:36px;text-align:right"><span aria-hidden="true">👍</span><span class="sr-only">โหวตขึ้น:</span> '+v.up+'</span>'
    +'<span style="color:var(--red);font-size:13px;min-width:36px;text-align:right"><span aria-hidden="true">👎</span><span class="sr-only">โหวตลง:</span> '+v.down+'</span>'
    +(v.filtered?'<span style="font-size:11px;color:var(--red);min-width:40px">กรองแล้ว</span>':'<span style="min-width:40px"></span>')
    +'</div>').join('');
}
async function resetVotes(){
  if(!confirm('รีเซ็ตคะแนนมุขทั้งหมด?'))return;
  await _post('/api/votes/reset',{});
  showToast('รีเซ็ตแล้ว');loadVotes();
}
function toggleTheme(){
  // suppress all transitions during theme switch to avoid color flash
  document.documentElement.setAttribute('data-theme-switching','');
  requestAnimationFrame(()=>{
    const light=document.body.classList.toggle('light');
    localStorage.setItem('theme',light?'light':'dark');
    const btn=document.getElementById('themeBtn');
    btn.innerHTML=light
      ?'<i class="ph-bold ph-sun" aria-hidden="true"></i>'
      :'<i class="ph-bold ph-moon" aria-hidden="true"></i>';
    btn.setAttribute('aria-label',light?'สลับเป็นธีมมืด':'สลับเป็นธีมสว่าง');
    requestAnimationFrame(()=>{document.documentElement.removeAttribute('data-theme-switching');});
  });
}
async function loadChannelActivity(){
  if(!currentGuildId)return;
  const el=document.getElementById('channelList');if(!el)return;
  let d;try{const r=await fetch('/api/channel-stats?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length){el.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  el.innerHTML=d.slice(0,15).map((ch,i)=>{
    const pct=Math.round(ch.seconds/d[0].seconds*100);
    return'<div class="stat-row" style="flex-wrap:wrap;gap:4px">'
      +'<span class="stat-rank">'+(i+1)+'.</span>'
      +'<span class="stat-name"># '+escHTML(ch.channel)+'</span>'
      +'<span class="stat-time">'+escHTML(ch.duration)+'</span>'
      +'<div style="width:100%;height:4px;background:var(--border);border-radius:2px;margin-top:2px">'
      +'<div style="width:'+pct+'%;height:100%;background:var(--accent);border-radius:2px"></div></div>'
      +'</div>';
  }).join('');
}
function exportCSV(){
  const url='/api/export/csv'+(currentGuildId?'?guild_id='+currentGuildId:'');
  const a=document.createElement('a');a.href=url;a.download='sessions.csv';document.body.appendChild(a);a.click();a.remove();
}
// ── DAU Line Chart + WAU summary + 7-day rolling avg ─────────────────────────
async function loadDAU(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('dauChartWrap');const svgEl=document.getElementById('dauSvg');
  const summary=document.getElementById('dauSummary');if(!svgEl||!wrap)return;
  let data,wauData;
  try{
    const [r1,r2]=await Promise.all([
      fetch('/api/dau?guild_id='+currentGuildId+'&days=30'),
      fetch('/api/wau-mau?guild_id='+currentGuildId+'&weeks=4'),
    ]);
    if(!r1.ok)throw new Error(r1.status);
    data=await r1.json();
    if(r2.ok)wauData=await r2.json();
  }catch(e){return;}
  if(!data||!data.length){if(summary)summary.textContent='ยังไม่มีข้อมูล';return;}

  const dauVals=data.map(d=>d.dau);
  const joinVals=data.map(d=>d.joins);
  const maxDau=Math.max(...dauVals,1);
  const maxJoin=Math.max(...joinVals,1);
  const maxVal=Math.max(maxDau,maxJoin);
  const avgDAU=Math.round(dauVals.reduce((a,b)=>a+b,0)/dauVals.length);
  const peakDAU=Math.max(...dauVals);
  const todayDAU=dauVals[dauVals.length-1]||0;
  const wauNow=wauData&&wauData.length?wauData[wauData.length-1].wau:null;

  // Update KPI bar
  const kd=document.getElementById('kpiDauToday');if(kd)kd.textContent=todayDAU;

  if(summary)summary.innerHTML=
    '<span>Peak DAU: <strong>'+peakDAU+'</strong></span>'
    +'<span>Avg DAU: <strong>'+avgDAU+'</strong></span>'
    +(wauNow!==null?'<span>WAU: <strong>'+wauNow+'</strong></span>':'')
    +'<span style="color:var(--muted)">ช่วง 30 วัน</span>';

  // 7-day rolling average
  const rollAvg=dauVals.map((_,i)=>{
    if(i<6)return null;
    const slice=dauVals.slice(i-6,i+1);
    return slice.reduce((a,b)=>a+b,0)/7;
  });

  const W=wrap.clientWidth||300;const H=150;const PAD={t:10,r:10,b:18,l:28};
  const cW=W-PAD.l-PAD.r;const cH=H-PAD.t-PAD.b;
  function xPos(i){return PAD.l+i/(data.length-1||1)*cW;}
  function yPos(v){return PAD.t+cH-(v/maxVal*cH);}

  const dauPts=data.map((d,i)=>xPos(i)+','+yPos(d.dau)).join(' ');
  const joinPts=data.map((d,i)=>xPos(i)+','+yPos(d.joins)).join(' ');
  const areaPath=data.map((d,i)=>(i===0?'M':'L')+xPos(i)+' '+yPos(d.dau)).join(' ')
    +' L'+xPos(data.length-1)+' '+(PAD.t+cH)+' L'+PAD.l+' '+(PAD.t+cH)+' Z';

  // Rolling avg polyline (only draw where avg exists)
  const avgSegs=[];let curSeg=[];
  rollAvg.forEach((v,i)=>{
    if(v===null){if(curSeg.length){avgSegs.push(curSeg);curSeg=[];}return;}
    curSeg.push(xPos(i)+','+yPos(v));
  });
  if(curSeg.length)avgSegs.push(curSeg);
  const avgLines=avgSegs.map(seg=>`<polyline points="${seg.join(' ')}" class="dau-line-avg" vector-effect="non-scaling-stroke"/>`).join('');

  const yLabels=[0,Math.round(maxVal/2),maxVal].map(v=>{
    const y=yPos(v);return`<text x="${PAD.l-4}" y="${y+4}" text-anchor="end" font-size="9" fill="var(--muted)">${v}</text>`;
  }).join('');
  const xIdxs=[0,7,14,21,29].filter(i=>i<data.length);
  const xLabels=xIdxs.map(i=>{
    const d=data[i];const lbl=d.date.slice(5);
    return`<text x="${xPos(i)}" y="${PAD.t+cH+14}" text-anchor="middle" font-size="9" fill="var(--muted)">${lbl}</text>`;
  }).join('');

  svgEl.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svgEl.innerHTML=`<defs>
    <linearGradient id="dauGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${areaPath}" fill="url(#dauGrad)" class="dau-area"/>
    <polyline points="${joinPts}" class="dau-line-joins" vector-effect="non-scaling-stroke"/>
    <polyline points="${dauPts}" class="dau-line" vector-effect="non-scaling-stroke"/>
    ${avgLines}
    ${yLabels}${xLabels}
    ${data.map((d,i)=>{const avg7=rollAvg[i]!==null?'\n7d avg: '+rollAvg[i].toFixed(1):'';
      return`<circle class="dau-dot" cx="${xPos(i)}" cy="${yPos(d.dau)}" r="3" tabindex="0"
        aria-label="${d.date}: DAU ${d.dau}, joins ${d.joins}" role="img">
        <title>${d.date}\nDAU: ${d.dau}\nJoins: ${d.joins}${avg7}</title></circle>`;}).join('')}`;
}

// ── Leaderboard with period + sort ────────────────────────────────────────────
let _lbPeriod='7d';
let _lbSort='time';
function setLbSort(sort,btn){
  _lbSort=sort;
  document.querySelectorAll('.sort-btn').forEach(b=>{b.classList.remove('active');b.setAttribute('aria-pressed','false');});
  if(btn){btn.classList.add('active');btn.setAttribute('aria-pressed','true');}
  loadLeaderboard();
}
async function loadLeaderboard(period,btn){
  if(!currentGuildId)return;
  if(period)_lbPeriod=period;
  if(btn){
    document.querySelectorAll('.period-btn').forEach(b=>{b.classList.remove('active');b.setAttribute('aria-pressed','false');});
    btn.classList.add('active');btn.setAttribute('aria-pressed','true');
  }
  const el=document.getElementById('statsList');if(!el)return;
  let d;
  try{
    const r=await fetch('/api/leaderboard?guild_id='+currentGuildId+'&period='+_lbPeriod+'&sort='+_lbSort);
    if(!r.ok)throw new Error(r.status);d=await r.json();
  }catch(e){return;}
  const medals=['🥇','🥈','🥉'];
  const rankLabel=i=>medals[i]
    ?'<span aria-hidden="true">'+medals[i]+'</span><span class="sr-only">'+(i+1)+'.</span>'
    :(i+1)+'.';

  // Update KPI: sessions this week (from 7d leaderboard, sum session_count if sort=sessions or just total joins)
  if(_lbPeriod==='7d'){
    const weekSess=d.reduce((acc,s)=>acc+(s.session_count||0),0);
    const kw=document.getElementById('kpiWeekSessions');if(kw&&weekSess>0)kw.textContent=weekSess;
  }

  el.innerHTML=!d||!d.length?'<span class="empty-msg">ยังไม่มีข้อมูล</span>'
    :d.map((s,i)=>'<div class="stat-row"><span class="stat-rank">'+rankLabel(i)+'</span>'
      +_avImg(s.uid,s.name)
      +'<span class="stat-name"><a href="/profile/'+escHTML(s.uid)+'" target="_blank" class="row-name-link">'+escHTML(s.name)+'</a></span>'
      +'<span class="stat-time">'+escHTML(s.duration)+'</span></div>').join('');
}

// ── Inactive users ────────────────────────────────────────────────────────────
async function loadInactive(){
  if(!currentGuildId)return;
  const el=document.getElementById('inactiveList');if(!el)return;
  let d;try{const r=await fetch('/api/inactive?guild_id='+currentGuildId+'&days=7');if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length){el.innerHTML='<span class="empty-msg">ไม่มีสมาชิกที่ inactive เกิน 7 วัน</span>';return;}
  el.innerHTML=d.map(u=>{
    const days=u.days_inactive;
    const cls=days>=60?'gone':days>=30?'danger':'warn';
    const dmBtn='<button class="btn-dm" title="ส่ง DM" aria-label="ส่ง DM ถึง '+escHTML(u.name)+'" onclick="sendInactiveDM(\''+escHTML(u.uid)+'\',\''+escHTML(u.name.replace(/'/g,"\\'"))+'\')"><i class="ph-bold ph-paper-plane-tilt" aria-hidden="true"></i></button>';
    return'<div class="inactive-row">'
      +_avImg(u.uid,u.name)
      +'<span class="inactive-name">'+_profileLink(u.uid,u.name)+'</span>'
      +'<span class="inactive-date">'+escHTML(u.last_seen)+'</span>'
      +'<span class="inactive-badge '+cls+'">'+days+' วัน</span>'
      +dmBtn
      +'</div>';
  }).join('');
}

async function sendInactiveDM(uid,name){
  const msg=prompt('ข้อความ DM ถึง '+name+':','สวัสดี! แวะมาคุยใน Discord ด้วยนะ 😊');
  if(!msg||!msg.trim())return;
  try{
    const r=await _post('/api/action/dm-user',{guild_id:currentGuildId,uid,message:msg.trim()});
    if(r.ok)showToast('ส่ง DM ถึง '+name+' แล้ว');
    else showToast('ส่ง DM ไม่ได้ ('+r.status+')',true);
  }catch(e){showToast('ส่ง DM ไม่ได้',true);}
}

// ── Retention chart ───────────────────────────────────────────────────────────
async function loadRetention(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('retentionWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/retention?guild_id='+currentGuildId+'&weeks=8');if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length||d.every(w=>w.active_count===0)){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  const scales=d.map((w,i)=>i>0&&w.retention_pct!==null?(Math.max(w.retention_pct,0)/100).toFixed(3):'0.04');
  wrap.innerHTML=d.map((w,i)=>{
    const pct=w.retention_pct!==null?w.retention_pct:null;
    const lbl=w.week_start.slice(5);// MM-DD
    const title=lbl+'\nActive: '+w.active_count+(pct!==null?'\nRetention: '+pct+'%':'');
    return'<div class="retention-col" title="'+escHTML(title)+'">'
      +(i>0?'<div class="retention-pct">'+(pct!==null?pct+'%':'—')+'</div>':'<div class="retention-pct">—</div>')
      +'<div class="retention-bar-bg"><div class="retention-bar-fill"></div></div>'
      +'<div class="retention-week">'+escHTML(lbl)+'</div>'
      +'</div>';
  }).join('');
  // trigger CSS transition after paint
  requestAnimationFrame(()=>{
    wrap.querySelectorAll('.retention-bar-fill').forEach((el,i)=>{el.style.transform='scaleY('+scales[i]+')';});
  });
}

// ── 7×24 Day-of-Week Heatmap ──────────────────────────────────────────────────
async function loadDowHeatmap(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('dowWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/dow-heatmap?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d || !d.matrix || !d.days) return;
  const matrix=d.matrix;const days=d.days;
  const flat=matrix.flat();const maxV=Math.max(...flat,1);
  const total=flat.reduce((a,b)=>a+b,0);
  if(total===0){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล — รอให้บอทบันทึก session ก่อน</span>';return;}

  // Hour labels top
  const hourLbls=Array.from({length:24},(_,h)=>
    (h%6===0?'<div class="dow-hour-lbl">'+String(h).padStart(2,'0')+'</div>':'<div class="dow-hour-lbl"></div>')
  ).join('');

  // Build rows
  const rows=matrix.map((rowData,di)=>{
    const cells=rowData.map((cnt,h)=>{
      const pct=cnt/maxV;
      const alpha=cnt===0?0:0.1+pct*0.85;
      const tooltip=days[di]+' '+String(h).padStart(2,'0')+':00 — '+cnt+' sessions';
      return`<div class="dow-cell" style="background:rgba(88,101,242,${alpha.toFixed(2)})" title="${escHTML(tooltip)}" aria-label="${escHTML(tooltip)}"></div>`;
    }).join('');
    return`<div class="dow-row"><div class="dow-day-lbl">${escHTML(days[di])}</div><div class="dow-cells">${cells}</div></div>`;
  }).join('');

  wrap.innerHTML=
    `<div class="dow-header"><div class="dow-day-lbl"></div><div class="dow-hour-row">${hourLbls}</div></div>`
    +rows
    +`<div style="font-size:10px;color:var(--muted);margin-top:8px">รวม ${total} sessions · สีเข้ม = active มาก</div>`;
}

// ── Session length histogram ──────────────────────────────────────────────────
async function loadHistogram(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('histogramWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/histogram?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length||d.every(b=>b.count===0)){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  const maxC=Math.max(...d.map(b=>b.count),1);
  const total=d.reduce((a,b)=>a+b.count,0);
  wrap.innerHTML=d.map(b=>{
    const pct=Math.round(b.count/maxC*100);
    const pctTotal=total>0?Math.round(b.count/total*100):0;
    return'<div class="hist-row">'
      +'<div class="hist-lbl">'+escHTML(b.range)+'</div>'
      +'<div class="hist-bar-bg"><div class="hist-bar-fill" style="width:'+pct+'%"></div></div>'
      +'<div class="hist-count">'+b.count+' <span style="color:var(--muted);font-size:10px">('+pctTotal+'%)</span></div>'
      +'</div>';
  }).join('');
}

// ── History search filter ─────────────────────────────────────────────────────
let _historyCache=[];
async function loadHistory(){
  const gp=currentGuildId?'?guild_id='+currentGuildId:'';
  let d;try{const r=await fetch('/api/history'+gp);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d)return;
  _historyCache=d.slice().reverse();  // newest first
  filterHistory(document.getElementById('historySearch')?.value||'');
}
function filterHistory(q){
  const body=document.getElementById('historyBody');
  const rows=q
    ?_historyCache.filter(s=>(s.name||'').toLowerCase().includes(q.toLowerCase())||(s.channel||'').toLowerCase().includes(q.toLowerCase()))
    :_historyCache;
  if(!rows.length){body.innerHTML='<tr><td colspan="5" style="color:var(--muted);padding:12px">'+(q?'ไม่พบ "'+escHTML(q)+'"':'ยังไม่มีข้อมูล')+'</td></tr>';return;}
  body.innerHTML=rows.slice(0,200).map(s=>
    '<tr><td>'+escHTML(s.name)+'</td><td style="color:var(--muted)">'+escHTML(s.channel)+'</td>'
    +'<td style="color:var(--muted)">'+escHTML(s.join)+'</td><td style="color:var(--muted)">'+escHTML(s.leave)+'</td>'
    +'<td>'+escHTML(s.duration)+'</td></tr>').join('');
}

// ── Notion Sync ───────────────────────────────────────────────────────────────
async function loadNotionStatus(){
  const wrap=document.getElementById('notionStatus');if(!wrap)return;
  let d;
  try{const r=await fetch('/api/notion/status');if(!r.ok)throw new Error(r.status);d=await r.json();}
  catch(e){wrap.innerHTML='<span class="empty-msg">โหลด status ไม่ได้</span>';return;}
  if(!d.configured){
    wrap.innerHTML='<div style="color:var(--muted);font-size:13px">'
      +'<i class="ph-bold ph-warning" style="color:var(--yellow)"></i>'
      +' ยังไม่ได้ตั้งค่า — กรอก <code>NOTION_TOKEN</code> และ <code>NOTION_DATABASE_ID</code>'
      +' ใน Railway Variables แล้วกด <b>Setup DB</b>'
      +'</div>';
    return;
  }
  const syncInfo=d.last_sync
    ?'<span style="color:var(--green)"><i class="ph-bold ph-check-circle"></i> sync ล่าสุด: '+escHTML(d.last_sync)+'</span>'
    :'<span style="color:var(--muted)">ยังไม่เคย sync</span>';
  const errInfo=d.last_error
    ?'<div style="color:var(--red);font-size:12px;margin-top:4px"><i class="ph-bold ph-x-circle"></i> '+escHTML(d.last_error)+'</div>':'';
  wrap.innerHTML='<div style="font-size:13px">'
    +syncInfo+errInfo
    +'<div style="font-size:11px;color:var(--muted);margin-top:8px">'
    +'Auto-sync ทุก 6 ชั่วโมง · Sync จะอัพเดต/เพิ่ม row ใน Notion Database'
    +'</div></div>';
}
async function syncToNotion(btn){
  withLoading(btn,async()=>{
    try{
      const r=await _post('/api/notion/sync',{guild_id:currentGuildId||null});
      const d=await r.json();
      if(d.ok){showToast('Notion sync สำเร็จ · '+d.synced+' rows · '+escHTML(d.synced_at));}
      else{showToast('Sync ไม่สำเร็จ: '+escHTML(d.error||'unknown'),true);}
      loadNotionStatus();
    }catch(e){showToast('Notion sync error',true);}
  });
}
async function notionSetup(btn){
  withLoading(btn,async()=>{
    try{
      const r=await _post('/api/notion/setup',{});
      const d=await r.json();
      if(d.ok){showToast('Setup สำเร็จ — Database พร้อมใช้งาน');}
      else{showToast('Setup ไม่สำเร็จ: '+escHTML(d.error||'unknown'),true);}
      loadNotionStatus();
    }catch(e){showToast('Setup error',true);}
  });
}

// ── Member browser ────────────────────────────────────────────────────────────
let _membersCache=[];
let _avatarMap={};  // uid -> avatar_url (populated from /api/members)

const _STATUS_DOT={
  voice:   {color:'#5865f2', label:'ใน Voice'},
  online:  {color:'#3ba55c', label:'ออนไลน์'},
  idle:    {color:'#faa81a', label:'เปลี่ยนแปลง'},
  dnd:     {color:'#ed4245', label:'ห้ามรบกวน'},
  offline: {color:'#747f8d', label:'ออฟไลน์'},
};

async function loadMembers(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('membersList');if(!wrap)return;
  let d;
  try{
    const r=await fetch('/api/members?guild_id='+currentGuildId);
    if(!r.ok)throw new Error(r.status);
    d=await r.json();
  }catch(e){wrap.innerHTML='<span class="empty-msg">โหลดไม่ได้</span>';return;}
  _membersCache=d||[];
  // Build uid->avatar_url map for use in all list renders
  _avatarMap={};
  _membersCache.forEach(m=>{if(m.avatar_url)_avatarMap[m.uid]=m.avatar_url;});
  _renderMembersGrid(document.getElementById('membersSearch')?.value||'');
}

function _renderMembersGrid(q){
  const wrap=document.getElementById('membersList');if(!wrap)return;
  const rows=q
    ?_membersCache.filter(m=>(m.name||'').toLowerCase().includes(q.toLowerCase()))
    :_membersCache;
  if(!rows.length){
    wrap.innerHTML='<span class="empty-msg">'+(q?'ไม่พบ "'+escHTML(q)+'"':'ยังไม่มีข้อมูลสมาชิก')+'</span>';
    return;
  }
  const statusOrder={voice:0,online:1,idle:2,dnd:3,offline:4};
  const sorted=[...rows].sort((a,b)=>(statusOrder[a.status]??4)-(statusOrder[b.status]??4));
  wrap.innerHTML='<div class="members-grid">'
    +sorted.map(m=>{
      const st=m.status||'offline';
      const dot=_STATUS_DOT[st]||_STATUS_DOT.offline;
      const isOffline=(st==='offline');
      const avatarEl=m.avatar_url
        ?`<img src="${escHTML(m.avatar_url)}?size=128" alt="" loading="lazy" class="mgrid-img${isOffline?' mgrid-gray':''}">`
        :`<div class="mgrid-initial${isOffline?' mgrid-gray':''}">${escHTML((m.name||'?')[0].toUpperCase())}</div>`;
      const dotEl=st!=='offline'
        ?`<span class="mgrid-dot" style="background:${dot.color}" title="${escHTML(dot.label)}"></span>`
        :'';
      const href='/profile/'+encodeURIComponent(m.uid)+'?guild_id='+encodeURIComponent(currentGuildId);
      return`<a class="mgrid-card" href="${escHTML(href)}" title="${escHTML(m.name)} — ${escHTML(dot.label)}">`
        +`<div class="mgrid-avatar-wrap">${avatarEl}${dotEl}</div>`
        +`<div class="mgrid-name${isOffline?' mgrid-name-off':''}">${escHTML(m.name)}</div>`
        +'</a>';
    }).join('')
    +'</div>';
}

// Keep filterMembers name for backward compat (search input oninput calls it via _debouncedFilterMembers)
function filterMembers(q){ _renderMembersGrid(q); }

async function loadLogs(){
  try{
    const r=await fetch('/api/logs');const d=await r.json();
    const box=document.getElementById('logBox');
    box.textContent=d.lines.join('\n')||'(ยังไม่มี log)';
    box.scrollTop=box.scrollHeight;
  }catch(e){
    document.getElementById('logBox').textContent='⚠ โหลด log ไม่ได้';
  }
}
// ── User Growth: new vs returning users per week ──────────────────────────────
let _growthDays=7;
async function loadUserGrowth(days,btn){
  if(!currentGuildId)return;
  if(days){_growthDays=days;}
  if(btn){
    btn.closest('.period-btns').querySelectorAll('.period-btn').forEach(b=>{b.classList.remove('active');b.setAttribute('aria-pressed','false');});
    btn.classList.add('active');btn.setAttribute('aria-pressed','true');
  }
  const wrap=document.getElementById('userGrowthWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/user-growth?guild_id='+currentGuildId+'&days='+_growthDays);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length||d.every(w=>w.total===0)){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  const maxTotal=Math.max(...d.map(w=>w.total),1);
  const W=wrap.clientWidth||360,H=110,PAD=36,BAR_W=Math.max(6,Math.floor((W-PAD*2)/d.length)-2);
  const scaleY=v=>H-8-Math.round(v/maxTotal*(H-16));
  let bars='';
  d.forEach((w,i)=>{
    const x=PAD+i*((W-PAD*2)/d.length);
    const hN=Math.round(w.new_users/maxTotal*(H-16));
    const hR=Math.round(w.returning_users/maxTotal*(H-16));
    const hT=hN+hR;
    const label=w.week_start.slice(5);// MM-DD
    if(hT>0){
      bars+=`<rect x="${x.toFixed(1)}" y="${(H-8-hT).toFixed(1)}" width="${BAR_W}" height="${hR.toFixed(1)}" fill="var(--accent)" opacity="0.85" rx="2">
        <title>${label}: ${w.returning_users} returning</title></rect>`;
      if(hN>0)bars+=`<rect x="${x.toFixed(1)}" y="${(H-8-hT).toFixed(1)}" width="${BAR_W}" height="${hN.toFixed(1)}" fill="var(--green)" opacity="0.9" rx="2">
        <title>${label}: ${w.new_users} new</title></rect>`;
    }
    if(i===0||i===d.length-1||i===Math.floor(d.length/2))
      bars+=`<text x="${(x+BAR_W/2).toFixed(1)}" y="${H}" text-anchor="middle" font-size="9" fill="var(--muted)">${label}</text>`;
  });
  const totalNew=d.reduce((a,w)=>a+w.new_users,0);
  const totalRet=d.reduce((a,w)=>a+w.returning_users,0);
  wrap.innerHTML=`<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" style="overflow:visible">${bars}</svg>`
    +`<div style="display:flex;gap:12px;font-size:11px;margin-top:6px;color:var(--muted)">`
    +`<span style="color:var(--green)">■</span><span>ใหม่ ${totalNew} คน</span>`
    +`<span style="color:var(--accent)">■</span><span>กลับมา ${totalRet} คน</span></div>`;
}

// ── Channel Details: extended channel table ───────────────────────────────────
async function loadChannelDetails(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('channelDetailsWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/channel-details?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  wrap.innerHTML='<table class="chdet-table"><thead><tr>'
    +'<th>ช่อง</th><th>เวลารวม</th><th>Sessions</th><th>Users</th><th>เฉลี่ย</th><th>Peak</th><th>Top User</th>'
    +'</tr></thead><tbody>'
    +d.map(r=>'<tr>'
      +`<td class="chdet-name">${escHTML(r.channel)}</td>`
      +`<td>${escHTML(r.duration)}</td>`
      +`<td>${r.sessions}</td>`
      +`<td>${r.unique_users}</td>`
      +`<td>${r.avg_min}m</td>`
      +`<td>${String(r.peak_hour).padStart(2,'0')}:00</td>`
      +`<td style="color:var(--muted)">${escHTML(r.top_user)}</td>`
      +'</tr>').join('')
    +'</tbody></table>';
}

// ── Co-presence: user pairs heatmap ──────────────────────────────────────────
async function loadCoPresence(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('copresenceWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/copresence?guild_id='+currentGuildId+'&top=10');if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล — ต้องมี session ที่ overlap กัน</span>';return;}
  const maxC=Math.max(...d.map(p=>p.overlap_count),1);
  wrap.innerHTML='<div class="cop-list">'
    +d.map((p,i)=>{
      const pct=Math.round(p.overlap_count/maxC*100);
      const rank=i===0?'🥇':i===1?'🥈':i===2?'🥉':'';
      return'<div class="cop-row">'
        +`<span class="cop-rank">${rank||'#'+(i+1)}</span>`
        +`<span class="cop-names">${escHTML(p.name_a)} <span style="color:var(--muted)">+</span> ${escHTML(p.name_b)}</span>`
        +'<div class="cop-bar-bg"><div class="cop-bar-fill" style="width:'+pct+'%"></div></div>'
        +`<span class="cop-count">${p.overlap_count}×</span>`
        +'</div>';
    }).join('')+'</div>';
}

// ── Form Registrations ────────────────────────────────────────────────────────
async function loadFormRegistrations(){
  const wrap=document.getElementById('formRegWrap');
  const badge=document.getElementById('formRegTotal');
  if(!wrap)return;
  let d;
  try{
    const r=await fetch('/api/form-registrations');
    if(!r.ok)throw new Error(r.status);
    d=await r.json();
  }catch(e){wrap.innerHTML='<span class="empty-msg">โหลดไม่สำเร็จ</span>';return;}
  if(!d||!d.ok){wrap.innerHTML='<span class="empty-msg">'+(d?.error||'ไม่มีข้อมูล')+'</span>';return;}
  if(badge)badge.textContent=d.total+' คน';
  let html='<div class="formreg-grid">';
  // jobs bar
  if(d.jobs&&d.jobs.length){
    const max=d.jobs[0].count||1;
    html+='<div class="formreg-col"><div class="formreg-sub">อาชีพหลัก</div>';
    d.jobs.forEach(j=>{
      const pct=Math.round(j.count/max*100);
      html+=`<div class="formreg-row"><span class="formreg-label">${j.label}</span>`+
            `<div class="formreg-bar-wrap"><div class="formreg-bar" style="width:${pct}%"></div></div>`+
            `<span class="formreg-cnt">${j.count}</span></div>`;
    });
    html+='</div>';
  }
  // gw slots
  if(d.gw_slots&&d.gw_slots.length){
    const maxg=d.gw_slots[0].count||1;
    html+='<div class="formreg-col"><div class="formreg-sub">ช่วงเวลา GW</div>';
    d.gw_slots.forEach(g=>{
      const pct=Math.round(g.count/maxg*100);
      html+=`<div class="formreg-row"><span class="formreg-label">${g.label}</span>`+
            `<div class="formreg-bar-wrap"><div class="formreg-bar" style="width:${pct}%;background:var(--green,#22c55e)"></div></div>`+
            `<span class="formreg-cnt">${g.count}</span></div>`;
    });
    html+='</div>';
  }
  html+='</div>';
  // recent list
  if(d.recent&&d.recent.length){
    html+='<div class="formreg-recent"><div class="formreg-sub">ลงทะเบียนล่าสุด</div><ul class="formreg-list">';
    d.recent.forEach(r=>{html+=`<li><span class="formreg-name">${r.name}</span><span class="formreg-ts">${r.timestamp}</span></li>`;});
    html+='</ul></div>';
  }
  wrap.innerHTML=html||'<span class="empty-msg">ยังไม่มีข้อมูล</span>';
}

// ── Guild Points Board ────────────────────────────────────────────────────────
let _ptsPeriod = 'week';
async function loadPointsBoard(period){
  if(period) _ptsPeriod = period;
  const wrap = document.getElementById('pointsWrap');
  if(!wrap) return;
  // update active button
  document.querySelectorAll('#pointsPeriodBtns .period-btn').forEach(b=>{
    b.classList.toggle('active', b.dataset.period === _ptsPeriod);
  });
  wrap.innerHTML = '<span class="empty-msg">กำลังโหลด...</span>';
  let d;
  try {
    const r = await fetch(`/api/points?period=${_ptsPeriod}`);
    if(!r.ok) throw new Error(r.status);
    d = await r.json();
  } catch(e) {
    wrap.innerHTML = '<span class="empty-msg">โหลดไม่สำเร็จ</span>'; return;
  }
  if(!d || !d.ok || !d.rows || !d.rows.length) {
    wrap.innerHTML = '<span class="empty-msg">ยังไม่มีข้อมูลคะแนน</span>'; return;
  }
  const rows = d.rows;
  let html = '<div class="pts-table-wrap"><table class="pts-table"><thead><tr>'
    + '<th>#</th><th>ชื่อ</th>'
    + '<th title="GW session (เสาร์-อาทิตย์ 19:30-21:00)">🛡️ GW</th>'
    + '<th title="เข้าเสียงช่วงอื่น">🎙️ อื่นๆ</th>'
    + '<th title="ลงทะเบียน GW">📋 ลงทะเบียน</th>'
    + '<th>รวม</th>'
    + '</tr></thead><tbody>';
  const maxTotal = rows[0].total || 1;
  rows.forEach(r => {
    const medal = r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : r.rank;
    const barPct = Math.round(r.total / maxTotal * 100);
    html += `<tr class="pts-row" data-uid="${r.uid}">
      <td class="pts-rank">${medal}</td>
      <td class="pts-name">${r.name}</td>
      <td class="pts-cell gw">${r.gw_pts > 0 ? r.gw_pts : '-'}</td>
      <td class="pts-cell other">${r.other_pts > 0 ? r.other_pts : '-'}</td>
      <td class="pts-cell reg">${r.reg_pts > 0 ? r.reg_pts : '-'}</td>
      <td class="pts-total">
        <div class="pts-bar-wrap">
          <div class="pts-bar" style="width:${barPct}%"></div>
          <span class="pts-bar-label">${r.total}</span>
        </div>
      </td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  wrap.innerHTML = html;
}

// ── Milestone log ─────────────────────────────────────────────────────────────
async function loadMilestoneLog(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('milestoneLogWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/milestone-log?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มี milestone — เล่น voice ให้ครบ 1 ชั่วโมงแรก</span>';return;}
  const ICONS={1:'🌱',5:'⭐',10:'🔥',25:'💎',50:'👑',100:'🏆',250:'🌟',500:'⚡'};
  wrap.innerHTML=d.map(m=>'<div class="ms-row">'
    +`<span class="ms-icon">${ICONS[m.hours]||'🏅'}</span>`
    +`<span class="ms-name">${escHTML(m.name)}</span>`
    +`<span class="ms-badge">${m.hours}h</span>`
    +'</div>').join('');
}

// ── Live Voice: who's in voice right now ──────────────────────────────────────
async function loadLiveVoice(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('liveVoiceWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/voice-now?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  const count=document.getElementById('liveVoiceCount');
  if(count)count.textContent=d.length?d.length+' คน':'ว่าง';
  if(!d||!d.length){wrap.innerHTML='<span class="empty-msg">ไม่มีใครอยู่ใน voice ตอนนี้</span>';return;}
  // Group by channel
  const byChannel={};
  d.forEach(u=>{(byChannel[u.channel]=byChannel[u.channel]||[]).push(u);});
  wrap.innerHTML=Object.entries(byChannel).map(([ch,users])=>{
    const usersHtml=users.map(u=>{
      const av=u.avatar?`<img src="${escHTML(u.avatar)}?size=32" alt="" class="lv-avatar" loading="lazy">`
        :`<div class="lv-avatar lv-avatar-init">${escHTML((u.name||'?')[0].toUpperCase())}</div>`;
      return`<div class="lv-user">${av}<div class="lv-info"><div class="lv-name">${escHTML(u.name)}</div>`
        +`<div class="lv-dur">${escHTML(u.duration)}</div></div></div>`;
    }).join('');
    return`<div class="lv-channel"><div class="lv-ch-name"><i class="ph-bold ph-speaker-high" aria-hidden="true"></i> ${escHTML(ch)}</div>`
      +`<div class="lv-users">${usersHtml}</div></div>`;
  }).join('');
}

// ── DAU Forecast: history + 7-day predicted line ──────────────────────────────
async function loadForecast(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('forecastWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/forecast?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.history)return;
  const all=[...d.history,...d.forecast];
  if(all.every(p=>p.dau===0)){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูลพอ — ต้องมีข้อมูลอย่างน้อย 3 วัน</span>';return;}
  const W=wrap.clientWidth||400,H=120,PL=32,PR=8,PT=8,PB=20;
  const maxV=Math.max(...all.map(p=>p.dau),1);
  const n=all.length;
  const xOf=i=>PL+(i/(n-1))*(W-PL-PR);
  const yOf=v=>H-PB-Math.round(v/maxV*(H-PT-PB));
  const histPts=d.history.map((p,i)=>`${xOf(i).toFixed(1)},${yOf(p.dau).toFixed(1)}`).join(' ');
  const foreStart=d.history.length-1;
  const foreData=[d.history[foreStart],...d.forecast];
  const forePts=foreData.map((p,i)=>`${xOf(foreStart+i).toFixed(1)},${yOf(p.dau).toFixed(1)}`).join(' ');
  // Area under history
  const areaHist=`M${xOf(0).toFixed(1)},${(H-PB).toFixed(1)} `
    +d.history.map((p,i)=>`L${xOf(i).toFixed(1)},${yOf(p.dau).toFixed(1)}`).join(' ')
    +` L${xOf(d.history.length-1).toFixed(1)},${(H-PB).toFixed(1)} Z`;
  const dots=d.forecast.map((p,i)=>{
    const ix=foreStart+1+i;
    return`<circle cx="${xOf(ix).toFixed(1)}" cy="${yOf(p.dau).toFixed(1)}" r="3" fill="var(--yellow)">`
      +`<title>${p.date}: ~${p.dau} คน (forecast)</title></circle>`;
  }).join('');
  // x-axis labels (every 7th)
  const xLabels=all.map((p,i)=>{
    if(i%7!==0&&i!==all.length-1)return'';
    return`<text x="${xOf(i).toFixed(1)}" y="${H}" text-anchor="middle" font-size="9" fill="var(--muted)">${p.date.slice(5)}</text>`;
  }).join('');
  const avgDau=d.history.length?Math.round(d.history.reduce((a,p)=>a+p.dau,0)/d.history.length):0;
  const foreAvg=d.forecast.length?Math.round(d.forecast.reduce((a,p)=>a+p.dau,0)/d.forecast.length):0;
  wrap.innerHTML=`<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" style="overflow:visible">
    <defs><linearGradient id="fcGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--accent)" stop-opacity=".18"/><stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>
    <path d="${areaHist}" fill="url(#fcGrad)"/>
    <polyline points="${histPts}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>
    <polyline points="${forePts}" fill="none" stroke="var(--yellow)" stroke-width="2" stroke-dasharray="5 3" stroke-linejoin="round"/>
    ${dots}${xLabels}
  </svg><div style="display:flex;gap:16px;font-size:11px;margin-top:6px;color:var(--muted)">
    <span style="color:var(--accent)">━</span><span>จริง (avg ${avgDau})</span>
    <span style="color:var(--yellow)">- - -</span><span>Forecast 7d (avg ~${foreAvg})</span></div>`;
}

// ── Cohort retention matrix ───────────────────────────────────────────────────
async function loadCohortMatrix(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('cohortWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/cohort?guild_id='+currentGuildId+'&cohort_weeks=8&retain_weeks=6');if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.cohorts||!d.cohorts.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูลพอ — ต้องมี user ที่ใช้งานหลายสัปดาห์</span>';return;}
  const cols=d.retain_weeks;
  let html='<div class="cohort-wrap"><table class="cohort-table"><thead><tr><th>Cohort</th><th>Users</th>';
  for(let i=0;i<cols;i++)html+=`<th>W+${i}</th>`;
  html+='</tr></thead><tbody>';
  d.cohorts.forEach(c=>{
    html+=`<tr><td class="cohort-week">${c.cohort_week.slice(5)}</td><td class="cohort-n">${c.users}</td>`;
    for(let i=0;i<cols;i++){
      const w=c.weeks.find(x=>x.offset===i);
      if(!w){html+='<td class="cohort-cell" style="background:transparent"></td>';continue;}
      const pct=w.pct;
      const alpha=i===0?0.9:Math.max(0.05,pct/100*0.85);
      const txtColor=pct>50?'#fff':'var(--text)';
      html+=`<td class="cohort-cell" style="background:rgba(88,101,242,${alpha.toFixed(2)});color:${txtColor}" title="W+${i}: ${pct}% (${w.retained}/${c.users})">${pct>0?pct+'%':'-'}</td>`;
    }
    html+='</tr>';
  });
  html+='</tbody></table></div>';
  wrap.innerHTML=html;
}

// ── Time-of-day: 24-hour session profile ─────────────────────────────────────
async function loadTimeOfDay(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('timeOfDayWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/time-of-day?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||d.every(h=>h.total_sessions===0)){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  const maxV=Math.max(...d.map(h=>h.avg_sessions),0.01);
  const W=wrap.clientWidth||400,H=90,PB=18,BAR_W=Math.max(4,Math.floor(W/24)-1);
  const peakHour=d.reduce((a,h)=>h.avg_sessions>a.avg_sessions?h:a,d[0]);
  let bars='';
  d.forEach((h,i)=>{
    const bh=Math.round(h.avg_sessions/maxV*(H-PB-4));
    const x=i*(W/24)+(W/24-BAR_W)/2;
    const isDay=h.hour>=8&&h.hour<22;
    const color=h.hour===peakHour.hour?'var(--yellow)':(isDay?'var(--accent)':'rgba(88,101,242,.35)');
    if(bh>0)bars+=`<rect x="${x.toFixed(1)}" y="${(H-PB-bh).toFixed(1)}" width="${BAR_W}" height="${bh}" fill="${color}" rx="2" opacity="0.9">
      <title>${String(h.hour).padStart(2,'0')}:00 — avg ${h.avg_sessions} sessions</title></rect>`;
    if(h.hour%6===0||h.hour===peakHour.hour)
      bars+=`<text x="${(x+BAR_W/2).toFixed(1)}" y="${H}" text-anchor="middle" font-size="8" fill="${h.hour===peakHour.hour?'var(--yellow)':'var(--muted)'}">
        ${String(h.hour).padStart(2,'0')}</text>`;
  });
  wrap.innerHTML=`<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" style="overflow:visible">${bars}</svg>`
    +`<div style="font-size:11px;color:var(--muted);margin-top:4px">Peak: <span style="color:var(--yellow)">${String(peakHour.hour).padStart(2,'0')}:00</span> · avg ${peakHour.avg_sessions} sess/day</div>`;
}

// ── Churn risk list ───────────────────────────────────────────────────────────
async function loadChurnRisk(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('churnRiskWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/churn-risk?guild_id='+currentGuildId+'&limit=15');if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d||!d.length){wrap.innerHTML='<span class="empty-msg">ไม่มี user ที่มี churn risk สูง ทุกคน active ดี</span>';return;}
  const COLORS={high:'var(--red)',medium:'var(--yellow)',low:'var(--muted)'};
  const ICONS={high:'ph-warning',medium:'ph-warning-circle',low:'ph-info'};
  wrap.innerHTML='<div class="churn-list">'
    +d.map(u=>{
      const pct=Math.round(u.risk_score*100);
      const col=COLORS[u.risk_level]||'var(--muted)';
      return'<div class="churn-row">'
        +`<i class="ph-bold ${ICONS[u.risk_level]||'ph-info'}" style="color:${col};flex-shrink:0"></i>`
        +_avImg(u.uid,u.name)
        +`<span class="churn-name">${_profileLink(u.uid,u.name)}</span>`
        +`<span class="churn-meta" style="color:var(--muted)">${u.days_since_last}d ไม่มา</span>`
        +'<div class="churn-bar-bg"><div class="churn-bar-fill" style="width:'+pct+'%;background:'+col+'"></div></div>'
        +`<span class="churn-badge" style="color:${col}">${u.risk_level}</span>`
        +'</div>';
    }).join('')+'</div>';
}

// ── All-time records ──────────────────────────────────────────────────────────
async function loadRecords(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('recordsWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/records?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  if(!d){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  const cards=[
    {icon:'ph-timer',label:'Session ยาวที่สุด',val:escHTML(d.longest_session?.duration||'-'),sub:d.longest_session?escHTML(d.longest_session.name)+' · '+escHTML(d.longest_session.date):''},
    {icon:'ph-calendar-star',label:'วันที่คึกคักสุด',val:d.most_active_day?.sessions?escHTML(String(d.most_active_day.sessions))+' sessions':'-',sub:escHTML(d.most_active_day?.date||'')},
    {icon:'ph-users',label:'Peak DAU',val:d.peak_dau_day?.dau?escHTML(String(d.peak_dau_day.dau))+' คน':'-',sub:escHTML(d.peak_dau_day?.date||'')},
    {icon:'ph-crown',label:'Top User ตลอดกาล',val:escHTML(d.top_user_alltime?.duration||'-'),sub:d.top_user_alltime?escHTML(d.top_user_alltime.name):''},
    {icon:'ph-flag',label:'Session แรกของ Server',val:escHTML(d.first_session?.date||'-'),sub:d.first_session?escHTML(d.first_session.name)+' · '+escHTML(d.first_session.channel):''},
    {icon:'ph-lightning',label:'Peak Concurrent (est.)',val:d.peak_concurrent?.count?escHTML(String(d.peak_concurrent.count))+' sessions/hr':'-',sub:escHTML(d.peak_concurrent?.date||'')},
  ];
  wrap.innerHTML='<div class="records-grid">'
    +cards.map(c=>'<div class="record-card">'
      +`<i class="ph-bold ${c.icon} record-icon" aria-hidden="true"></i>`
      +`<div class="record-val">${c.val}</div>`
      +`<div class="record-label">${c.label}</div>`
      +(c.sub?`<div class="record-sub">${c.sub}</div>`:'')
      +'</div>').join('')
    +'</div>';
}

// ── Guild Health Score ────────────────────────────────────────────────────────
async function loadGuildHealth(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('guildHealthWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/guild-health?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  const pct=Math.round(Number(d.health_score)||0);
  const arc=Math.PI; // semicircle arc length ≈ 173px at r=55
  const arcLen=173;
  wrap.innerHTML=`
  <div class="health-layout">
    <div class="health-gauge-wrap">
      <svg viewBox="0 0 120 80" aria-hidden="true" style="display:block;width:180px;height:auto;overflow:visible">
        <path d="M10,70 A55,55 0 0,1 110,70" fill="none" stroke="var(--border)" stroke-width="12" stroke-linecap="round"/>
        <path d="M10,70 A55,55 0 0,1 110,70" fill="none" stroke="var(--accent)" stroke-width="12" stroke-linecap="round"
          stroke-dasharray="${((pct/100)*arcLen).toFixed(1)} ${arcLen}" style="transition:stroke-dasharray 0.8s ease"/>
        <text x="60" y="64" text-anchor="middle" class="gauge-num">${pct}</text>
        <text x="60" y="76" text-anchor="middle" class="gauge-label">${escHTML(d.label||'')}</text>
      </svg>
    </div>
    <div class="health-sub-rows">
      ${[['DAU Trend',((d.dau_trend??0)+1)/2],['Retention',d.retention_score??0],['Stability',1-(d.churn_score??0)],['Growth',d.growth_score??0]].map(([lbl,v])=>{const pv=Math.round(Math.max(0,Math.min(1,v))*100);return`
      <div class="health-sub-row"><span class="hsr-label">${lbl}</span>
        <div class="health-bar-track"><div class="health-bar-fill" style="width:${pv}%"></div></div>
        <span class="hsr-val">${pv}%</span>
      </div>`}).join('')}
    </div>
  </div>`;
}

// ── User Compare ──────────────────────────────────────────────────────────────
async function loadUserCompare(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('userCompareWrap');if(!wrap)return;
  const ia=document.getElementById('compareUidA'),ib=document.getElementById('compareUidB');
  const uid_a=(ia?.value||'').trim(),uid_b=(ib?.value||'').trim();
  if(!uid_a||!uid_b){wrap.innerHTML='<span class="empty-msg">กรอก User ID ทั้งคู่</span>';return;}
  let d;try{const r=await fetch(`/api/user-compare?guild_id=${encodeURIComponent(currentGuildId)}&uid_a=${encodeURIComponent(uid_a)}&uid_b=${encodeURIComponent(uid_b)}`);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){wrap.innerHTML='<span class="empty-msg">โหลดไม่ได้</span>';return;}
  function _col(s){
    return`<div class="compare-col">
      <div class="compare-col-name">${escHTML(s.name)}</div>
      ${[['เวลารวม',s.duration],['Sessions',s.session_count],['Streak Max',s.streak_max+' วัน'],['วันที่ active',s.active_days],['7 วันล่าสุด',s.last_7d_sessions+' sess'],['ห้องโปรด',s.favorite_channel],['เริ่มต้น',s.first_seen],['ล่าสุด',s.last_seen]].map(([k,v])=>`<div class="compare-stat"><span class="compare-stat-label">${k}</span><span class="compare-stat-val">${escHTML(String(v??'-'))}</span></div>`).join('')}
    </div>`;
  }
  wrap.innerHTML=`<div class="compare-grid">${_col(d.uid_a)}${_col(d.uid_b)}</div>`;
}

// ── Streak Board ──────────────────────────────────────────────────────────────
async function loadStreakBoard(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('streakBoardWrap');if(!wrap)return;
  let rows;try{const r=await fetch('/api/streak-board?guild_id='+currentGuildId+'&limit=10');if(!r.ok)throw new Error(r.status);rows=await r.json();}catch(e){return;}
  if(!rows.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  wrap.innerHTML='<div class="streak-list">'
    +rows.map((u,i)=>`<div class="streak-row">
      <span class="streak-rank">${i+1}</span>
      ${_avImg(u.uid,u.name)}
      <span class="streak-name">${_profileLink(u.uid,u.name)}</span>
      <span class="streak-fire">${u.current_streak}d</span>
      <span class="streak-days">${escHTML(u.duration)}</span>
    </div>`).join('')+'</div>';
}

// ── Session Day Timeline ───────────────────────────────────────────────────────
async function loadSessionDay(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('sessionDayWrap');if(!wrap)return;
  const inp=document.getElementById('sessionDayDate');
  const date=inp?.value||new Date().toISOString().slice(0,10);
  let rows;try{const r=await fetch(`/api/session-day?guild_id=${encodeURIComponent(currentGuildId)}&date=${encodeURIComponent(date)}`);if(!r.ok)throw new Error(r.status);rows=await r.json();}catch(e){return;}
  if(!rows.length){wrap.innerHTML='<span class="empty-msg">ไม่มี session วันนี้</span>';return;}
  wrap.innerHTML='<div class="session-day-list">'
    +rows.map(s=>`<div class="session-day-row">
      <span class="session-day-time">${escHTML(s.join.slice(11,16))}</span>
      <span class="session-day-name">${escHTML(s.name)}</span>
      <span class="session-day-ch">${escHTML(s.channel)}</span>
      <span class="session-day-dur">${escHTML(s.duration)}</span>
    </div>`).join('')+'</div>';
}

// ── Marathon Sessions ─────────────────────────────────────────────────────────
async function loadMarathon(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('marathonWrap');if(!wrap)return;
  let rows;try{const r=await fetch('/api/marathon?guild_id='+currentGuildId+'&limit=15');if(!r.ok)throw new Error(r.status);rows=await r.json();}catch(e){return;}
  if(!rows.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มี session 3 ชม.+</span>';return;}
  wrap.innerHTML='<div class="marathon-list">'
    +rows.map((s,i)=>`<div class="marathon-row">
      <span class="marathon-rank">${i+1}</span>
      ${_avImg(s.uid,s.name)}
      <span class="marathon-name">${_profileLink(s.uid,s.name)}</span>
      <span class="marathon-ch">${escHTML(s.channel)}</span>
      <span class="marathon-dur">${escHTML(s.duration)}</span>
      <span class="marathon-date">${escHTML(s.date?.slice(0,10)||'-')}</span>
    </div>`).join('')+'</div>';
}

// ── Engagement Score ──────────────────────────────────────────────────────────
async function loadEngagementScore(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('engagementWrap');if(!wrap)return;
  let rows;try{const r=await fetch('/api/engagement-score?guild_id='+currentGuildId+'&limit=15');if(!r.ok)throw new Error(r.status);rows=await r.json();}catch(e){return;}
  if(!rows.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มีข้อมูล</span>';return;}
  const max=rows[0].score||1;
  wrap.innerHTML='<div class="engage-list">'
    +rows.map((u,i)=>`<div class="engage-row">
      <span class="engage-rank">${i+1}</span>
      ${_avImg(u.uid,u.name)}
      <span class="engage-name">${_profileLink(u.uid,u.name)}</span>
      <div class="engage-bar-track"><div class="engage-bar-fill" style="width:${(u.score/max*100).toFixed(1)}%"></div></div>
      <span class="engage-score">${u.score}</span>
    </div>`).join('')+'</div>';
}

// ── Per-user Heatmap ──────────────────────────────────────────────────────────
async function loadUserHeatmap(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('userHeatmapWrap');if(!wrap)return;
  const inp=document.getElementById('userHeatmapUid');
  const uid=(inp?.value||'').trim();
  if(!uid){wrap.innerHTML='<span class="empty-msg">กรอก User ID</span>';return;}
  let d;try{const r=await fetch(`/api/user-heatmap?guild_id=${encodeURIComponent(currentGuildId)}&uid=${encodeURIComponent(uid)}`);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){wrap.innerHTML='<span class="empty-msg">โหลดไม่ได้</span>';return;}
  const mx=Math.max(1,...d.matrix.flat());
  const cells=d.days.map((day,di)=>`<div class="uhm-row">
    <span class="uhm-day">${day}</span>
    ${d.matrix[di].map(v=>`<div class="uhm-cell" style="opacity:${v?0.2+0.8*(v/mx):0.04}" title="${v}"></div>`).join('')}
  </div>`).join('');
  wrap.innerHTML=`<div class="uhm-title">${escHTML(d.name)} — ${d.total_sessions} sessions</div>
  <div class="uhm-grid">${cells}</div>
  <div class="uhm-hours">${Array.from({length:24},(_,h)=>`<span>${h}</span>`).join('')}</div>`;
}

// ── New User Journey ──────────────────────────────────────────────────────────
async function loadNewUserJourney(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('journeyWrap');if(!wrap)return;
  let rows;try{const r=await fetch('/api/new-user-journey?guild_id='+currentGuildId+'&cohort_weeks=8');if(!r.ok)throw new Error(r.status);rows=await r.json();}catch(e){return;}
  if(!rows.length){wrap.innerHTML='<span class="empty-msg">ยังไม่มี new users</span>';return;}
  wrap.innerHTML='<div class="journey-list">'
    +'<div class="journey-row journey-header"><span>ชื่อ</span><span>เข้าร่วม</span><span>D2</span><span>30d sess</span><span>W1</span></div>'
    +rows.map(u=>`<div class="journey-row">
      <span class="journey-name">${escHTML(u.name)}</span>
      <span class="journey-val">${escHTML(u.first_seen?.slice(0,10)||'-')}</span>
      <span class="journey-val">${u.days_to_second!=null?u.days_to_second+'d':'-'}</span>
      <span class="journey-val">${u.sessions_in_first_30d}</span>
      <span class="journey-retained ${u.retained_week1?'yes':'no'}">${u.retained_week1?'✓':'✗'}</span>
    </div>`).join('')+'</div>';
}

// ── Peak Summary ──────────────────────────────────────────────────────────────
async function loadPeakSummary(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('peakSummaryWrap');if(!wrap)return;
  let d;try{const r=await fetch('/api/peak-summary?guild_id='+currentGuildId);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  const fmt=h=>h!=null?`${String(Number(h)).padStart(2,'0')}:00`:'-';
  wrap.innerHTML=`<div class="peak-grid">
    <div class="peak-card"><div class="peak-card-label">Busiest Hour</div><div class="peak-card-value">${fmt(d.busiest_hour)}</div><div class="peak-card-sub">${escHTML(String(d.busiest_hour_count??'-'))} sessions</div></div>
    <div class="peak-card"><div class="peak-card-label">Quietest Hour</div><div class="peak-card-value">${fmt(d.quietest_hour)}</div></div>
    <div class="peak-card"><div class="peak-card-label">Busiest Day</div><div class="peak-card-value">${escHTML(d.busiest_dow_label??'-')}</div></div>
    <div class="peak-card"><div class="peak-card-label">Most Active Date</div><div class="peak-card-value" style="font-size:14px">${escHTML(d.most_active_date||'-')}</div><div class="peak-card-sub">${escHTML(String(d.most_active_sessions??'-'))} sessions</div></div>
    <div class="peak-card"><div class="peak-card-label">Avg Session</div><div class="peak-card-value">${escHTML(String(d.avg_session_min??'-'))} <span style="font-size:12px;font-weight:400">min</span></div></div>
    <div class="peak-card"><div class="peak-card-label">Total Users</div><div class="peak-card-value">${escHTML(String(d.total_users??'-'))}</div></div>
  </div>`;
}

// ── Voice Overlap Timeline ────────────────────────────────────────────────────
async function loadVoiceOverlapTimeline(){
  if(!currentGuildId)return;
  const wrap=document.getElementById('overlapTimelineWrap');if(!wrap)return;
  const inp=document.getElementById('overlapDate');
  const date=inp?.value||new Date().toISOString().slice(0,10);
  let d;try{const r=await fetch(`/api/voice-overlap-timeline?guild_id=${encodeURIComponent(currentGuildId)}&date=${encodeURIComponent(date)}`);if(!r.ok)throw new Error(r.status);d=await r.json();}catch(e){return;}
  const bkts=d.buckets;
  const maxC=Math.max(1,...bkts.map(b=>b.count));
  const W=600,H=100,pad=4;
  const bw=(W-2*pad)/bkts.length;
  const bars=bkts.map((b,i)=>{
    const bh=maxC?Math.round((b.count/maxC)*(H-20)):0;
    const x=pad+i*bw;const y=H-bh-4;
    return`<rect x="${x.toFixed(1)}" y="${y}" width="${(bw-1).toFixed(1)}" height="${bh}" fill="var(--accent)" opacity="0.7" rx="1"><title>${b.time}: ${b.count}</title></rect>`;
  }).join('');
  // hour labels every 4 buckets = every hour
  const xlbls=bkts.filter((_,i)=>i%4===0).map((b,i)=>{
    const x=pad+(i*4)*bw+bw*2;
    return`<text x="${x.toFixed(1)}" y="${H}" font-size="9" fill="var(--muted)" text-anchor="middle">${b.time}</text>`;
  }).join('');
  wrap.innerHTML=`<div class="overlap-date-lbl">${d.date}</div>
  <svg viewBox="0 0 ${W} ${H+4}" class="overlap-svg" aria-label="concurrent users timeline">${bars}${xlbls}</svg>`;
}

if(localStorage.getItem('theme')==='light'){document.body.classList.add('light');const btn=document.getElementById('themeBtn');btn.innerHTML='<i class="ph-bold ph-sun" aria-hidden="true"></i>';btn.setAttribute('aria-label','สลับเป็นธีมมืด');}

// ── Sidebar navigation ──
function toggleSidebar(){
  const sb=document.getElementById('sidebar');
  const ov=document.getElementById('sidebarOverlay');
  const btn=document.getElementById('menuToggle');
  const open=sb.classList.toggle('open');
  ov.classList.toggle('active',open);
  btn.setAttribute('aria-expanded',String(open));
}
function closeSidebar(){
  const sb=document.getElementById('sidebar');
  const ov=document.getElementById('sidebarOverlay');
  const btn=document.getElementById('menuToggle');
  sb.classList.remove('open');
  ov.classList.remove('active');
  if(btn)btn.setAttribute('aria-expanded','false');
}
// Highlight active sidebar link on scroll
function updateSidebarActive(){
  const links=document.querySelectorAll('.sidebar-nav a[href^="#"]');
  const sections=[...links].map(a=>document.querySelector(a.getAttribute('href'))).filter(Boolean);
  let active=null;
  sections.forEach((s,i)=>{if(s&&s.getBoundingClientRect().top<=80)active=i;});
  links.forEach((l,i)=>{l.classList.toggle('active',i===active);});
}
window.addEventListener('scroll',updateSidebarActive,{passive:true});
// Close sidebar on ESC
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeSidebar();});

buildUI();loadConfig();
refreshStatus();loadHeatmap();loadContribGraph();loadHistory();loadVotes();
loadChannelActivity();loadDAU();loadLeaderboard('7d');loadInactive();loadRetention();
loadDowHeatmap();loadHistogram();loadMembers();loadNotionStatus();loadLogs();
loadUserGrowth();loadChannelDetails();loadCoPresence();loadMilestoneLog();loadLiveVoice();
loadForecast();loadCohortMatrix();loadTimeOfDay();loadChurnRisk();loadRecords();loadFormRegistrations();loadPointsBoard();
loadGuildHealth();loadStreakBoard();loadMarathon();loadEngagementScore();loadNewUserJourney();loadPeakSummary();
// Note: loadGuilds() is called inside loadConfig() after isOwner is known
updateClock();setInterval(updateClock,1000);
// Pause polling when tab is hidden to save resources
function _poll(fn,ms){setInterval(()=>{if(!document.hidden)fn();},ms);}
_poll(loadLogs,30000);
_poll(refreshStatus,8000);_poll(loadHeatmap,30000);_poll(loadHistory,30000);
_poll(loadVotes,20000);_poll(loadContribGraph,120000);_poll(loadChannelActivity,60000);
_poll(loadDAU,120000);_poll(()=>loadLeaderboard(_lbPeriod),30000);
_poll(loadInactive,300000);_poll(loadRetention,300000);
_poll(loadDowHeatmap,300000);_poll(loadHistogram,120000);
_poll(loadUserGrowth,300000);_poll(loadChannelDetails,120000);
_poll(loadCoPresence,600000);_poll(loadMilestoneLog,300000);_poll(loadLiveVoice,10000);
_poll(loadForecast,600000);_poll(loadCohortMatrix,600000);_poll(loadTimeOfDay,300000);
_poll(loadChurnRisk,600000);_poll(loadRecords,300000);_poll(loadFormRegistrations,300000);_poll(()=>loadPointsBoard(),300000);
_poll(loadGuildHealth,300000);_poll(loadStreakBoard,300000);_poll(loadMarathon,300000);
_poll(loadEngagementScore,300000);_poll(loadNewUserJourney,600000);_poll(loadPeakSummary,300000);
// Resume immediately when tab becomes visible again
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden){refreshStatus();loadHeatmap();loadHistory();loadChannelActivity();loadDAU();loadLiveVoice();}
});

// ── Page Animations ───────────────────────────────────────────────────────────
(function initCardAnims(){
  // Respect user preference
  if(window.matchMedia('(prefers-reduced-motion:reduce)').matches){
    document.querySelectorAll('.card').forEach(c=>c.classList.add('entered'));
    return;
  }
  if(!('IntersectionObserver' in window)){
    document.querySelectorAll('.card').forEach(c=>c.classList.add('entered'));
    return;
  }
  const io=new IntersectionObserver(entries=>{
    entries.forEach(e=>{
      if(!e.isIntersecting)return;
      const card=e.target;
      // Trigger entrance transition
      card.classList.add('is-visible');
      // After entrance (500ms), switch to fast hover transition
      setTimeout(()=>{
        card.classList.remove('is-visible');
        card.classList.add('entered');
      },560);
      io.unobserve(card);
    });
  },{threshold:0.05,rootMargin:'0px 0px -24px 0px'});
  document.querySelectorAll('.card').forEach(c=>io.observe(c));
})();

// Flash a stat value element when data updates
function flashStat(id){
  const el=document.getElementById(id);if(!el)return;
  el.classList.remove('val-flash');
  void el.offsetWidth; // force reflow to restart animation
  el.classList.add('val-flash');
}
