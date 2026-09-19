let images=[];
let mounts=[];
let currentFilter='all';
let nasPickerPath='/volume1';
let nasPickerDefault='/volume1';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];

async function api(url,opt={}){
  const controller=new AbortController();
  const timeout=opt.timeout||15000;
  const timer=setTimeout(()=>controller.abort(),timeout);
  try{
    const r=await fetch(url,{...opt,signal:controller.signal});
    if(!r.ok){
      let t=await r.text();
      try{t=JSON.parse(t).detail||t}catch{}
      throw new Error(t||`HTTP ${r.status}`)
    }
    return await r.json();
  }catch(e){
    if(e.name==='AbortError') throw new Error(`请求超时：${url}`);
    throw e;
  }finally{clearTimeout(timer)}
}
function fmt(n){if(n==null)return '—';if(n<1024)return `${n} B`;const u=['KB','MB','GB','TB','PB'];let i=-1,x=n;do{x/=1024;i++}while(x>=1024&&i<u.length-1);return `${x.toFixed(x>=100?0:x>=10?1:2)} ${u[i]}`}
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function toast(s,kind='ok'){const t=$('#toast');if(!t)return;t.textContent=s;t.className=`toast ${kind} show`;clearTimeout(window._toast);window._toast=setTimeout(()=>t.className='toast',2800)}
function labelFs(f){return ({ext2:'EXT2',ext3:'EXT3',ext4:'EXT4',xfs:'XFS',ntfs:'NTFS',ntfs3:'NTFS',exfat:'exFAT',vfat:'FAT32',msdos:'FAT',f2fs:'F2FS',iso9660:'ISO9660',udf:'UDF'})[f]||String(f||'UNKNOWN').toUpperCase()}

function setLibraryLoading(visible,text='正在读取映像库…'){
  const g=$('#imageGrid');
  if(!g)return;
  if(visible) g.innerHTML=`<div class="loading-card"><div class="loading-spinner"></div><div><strong>${esc(text)}</strong><span>正在连接数据库并恢复映像索引；不会读取 1TB IMG 的完整内容。</span></div><div class="loading-progress"><i></i></div></div>`;
}

async function loadImages(){
  setLibraryLoading(true);
  try{
    images=await api('/api/images', {timeout:12000});
    renderImages();
  }catch(e){
    $('#imageGrid').innerHTML=`<div class="error-state"><strong>映像库读取失败</strong><span>${esc(e.message)}</span><button onclick="loadImages()">重试</button></div>`;
  }
}
async function loadMounts(){
  try{mounts=await api('/api/mounts',{timeout:12000});renderMounts()}catch(e){$('#mountGrid').innerHTML=`<div class="error-state"><strong>挂载状态读取失败</strong><span>${esc(e.message)}</span><button onclick="loadMounts()">重试</button></div>`}
}
async function loadSummary(){
  try{
    const sum=await api('/api/summary',{timeout:12000});
    $('#mImages').textContent=sum.images;$('#mMounted').textContent=sum.mounted;$('#mIso').textContent=sum.iso;$('#mImg').textContent=sum.img;
    const p=sum.disk.total?sum.disk.used/sum.disk.total*100:0;
    $('#storageText').textContent=`${fmt(sum.disk.used)} / ${fmt(sum.disk.total)}`;
    $('#storageBar').style.width=`${Math.min(100,p)}%`;
    $('#storageFree').textContent=`可用 ${fmt(sum.disk.free)} · 使用 ${p.toFixed(1)}%`;
    updateScanIndicator(sum.scan);
  }catch(e){toast(`摘要读取失败：${e.message}`,'error')}
}
function updateScanIndicator(scan){
  const el=$('#libraryStatus');
  if(!el)return;
  if(!scan){el.textContent='数据库已连接';return}
  if(scan.status==='running') el.innerHTML=`<span class="status-dot busy"></span>${esc(scan.stage||'正在扫描')} ${scan.progress||0}%`;
  else el.innerHTML=`<span class="status-dot"></span>${esc(scan.detail||'映像库就绪')}`;
}
async function refreshAll(){
  await Promise.allSettled([loadImages(),loadMounts(),loadSummary(),loadAppVersion()]);
}
function renderImages(){
  const grid=$('#imageGrid');
  const list=currentFilter==='all'?images:images.filter(x=>x.kind===currentFilter);
  if(!list.length){grid.innerHTML='<div class="empty-state"><div class="empty-icon">◌</div><strong>还没有映像</strong><span>从 NAS 内部选择或从电脑上传一个 ISO / IMG。</span></div>';return}
  grid.innerHTML=list.map(img=>{
    const live=!!img.mounted; const missing=img.availability===0;
    const status=missing?'<span class="status bad"><i></i>源文件不可用</span>':live?'<span class="status live"><i></i>已挂载</span>':'<span class="status"><i></i>就绪</span>';
    return `<article class="image-card ${missing?'is-missing':''}">
      <div class="card-top"><div class="type-icon ${img.kind}">${img.kind==='iso'?'ISO':'IMG'}</div>
      <div class="card-title"><b title="${esc(img.name)}">${esc(img.name)}</b><span>${fmt(img.size)} · ${img.mount_mode?img.mount_mode.toUpperCase():'未挂载'}</span></div>${status}</div>
      <div class="card-meta"><span>来源 <b>${isManaged(img.path)?'本地映像库':'NAS 文件'}</b></span><span>文件系统 <b>${esc(img.fs_type?labelFs(img.fs_type):'未检测')}</b></span><span>SHA-256 <b>${img.sha256?img.sha256.slice(0,12)+'…':'未校验'}</b></span></div>
      <div class="card-actions"><button onclick="inspect('${img.id}')">检查</button><button onclick="checksum('${img.id}')">校验</button>${live?`<button class="primary" onclick="openBrowser('${img.mount_id}')">文件</button><button class="warn" onclick="unmount('${img.mount_id}')">卸载</button>`:`<button class="primary" ${missing?'disabled':''} onclick="mountFlow('${img.id}')">挂载</button>`}<button class="danger" onclick="removeImage('${img.id}')">移除</button></div>
    </article>`
  }).join('');
}
function isManaged(path){return String(path||'').startsWith('/volume1/docker/virtual-drive/images/')}
function renderMounts(){
  const el=$('#mountGrid');
  if(!mounts.length){el.innerHTML='<div class="empty-state compact"><div class="empty-icon">◫</div><strong>暂无活动挂载</strong><span>选择一个映像并点击“挂载”，完成后会显示 DSM File Station 路径。</span></div>';return}
  el.innerHTML=mounts.map(m=>`<article class="mount-card"><div class="mount-icon">◍</div><div class="mount-main"><div class="mount-title"><b>${esc(m.image_name)}</b><span class="mode ${m.mode}">${m.mode.toUpperCase()}</span></div><div class="mount-path">/volume1/docker/virtual-drive/mounts/${esc(m.id)}</div><div class="mount-tags"><span>${labelFs(m.fs_type||'unknown')}</span><span>${m.partition?'分区 '+esc(m.partition.split('/').pop()):'整盘'}</span><span id="usage-${m.id}">占用读取中…</span></div></div><div class="mount-actions"><button onclick="openFileStation('${encodeURIComponent('/volume1/docker/virtual-drive/mounts/'+m.id)}')">DSM 路径</button><button onclick="openBrowser('${m.id}')">文件</button><button class="warn" onclick="unmount('${m.id}')">卸载</button></div></article>`).join('');
  mounts.forEach(async m=>{try{const u=await api(`/api/mounts/${m.id}/usage`,{timeout:10000});const x=$(`#usage-${m.id}`);if(x)x.textContent=`${fmt(u.used)} / ${fmt(u.total)} · ${u.percent}%`}catch{}})
}

async function inspect(id){
  const img=images.find(x=>x.id===id); if(!img)return;
  openModal(`<div class="job-modal"><div class="job-kicker">IMAGE INSPECTOR</div><h3>正在分析 ${esc(img.name)}</h3><p>正在读取分区表与文件系统信息。对 1TB 级 IMG 仅做结构扫描，不会读取整盘内容。</p><div class="job-progress"><i id="jobBar"></i></div><div class="job-line"><span id="jobPct">0%</span><b id="jobStage">排队</b></div><small id="jobDetail">准备中…</small></div>`);
  try{
    const {job_id}=await api(`/api/images/${id}/inspect/start`,{method:'POST'});
    const result=await pollInspect(job_id);
    if(result.error){throw new Error(result.error)}
    showInspectResult(result);
  }catch(e){toast(e.message,'error');closeModal()}
}
function pollInspect(jobId){return new Promise((resolve,reject)=>{const timer=setInterval(async()=>{try{const j=await api(`/api/inspect/${jobId}`,{timeout:10000});$('#jobBar').style.width=`${j.progress||0}%`;$('#jobPct').textContent=`${j.progress||0}%`;$('#jobStage').textContent=j.stage||'';$('#jobDetail').textContent=j.detail||'';if(j.status==='done'){clearInterval(timer);resolve(j.result)}else if(j.status==='error'){clearInterval(timer);reject(new Error(j.error||'分析失败'))}}catch(e){clearInterval(timer);reject(e)}},700)})}
function showInspectResult(x){
  const table=x.partition_table?`<div class="callout small"><b>分区表：</b>${esc(x.partition_table.toUpperCase())} · ${x.partitions?.length||0} 个分区</div>`:'';
  const body=x.partitions?.length
    ? `<div class="subhead">检测到 ${x.partitions.length} 个分区</div><div class="partition-list">${x.partitions.map(p=>`<div class="partition"><div><b>${esc(p.name||p.path)}</b><span>${esc(p.fs_label)} · ${fmt(p.size)}${p.label?' · '+esc(p.label):''}${p.partuuid?' · '+esc(p.partuuid):''}</span></div><em class="${p.supported?'good':'bad'}">${p.supported?'可挂载':'不支持'}</em></div>`).join('')}</div>`
    : x.whole_image
      ? `<div class="callout good-callout"><b>整盘文件系统镜像</b><br>${esc(x.filesystem_label)} · 未发现 MBR/GPT 分区表。该 IMG 可以作为单一文件系统直接挂载，无需选择分区。</div>`
      : `<div class="callout">未检测到可用的分区表或可识别文件系统。请检查镜像格式或在 NAS 宿主机执行 blkid / file -sL 进行诊断。</div>`;
  openModal(`<div class="modal-head"><div><div class="kicker">IMAGE INSPECTOR</div><h3>${esc(x.name)}</h3></div><button class="close" onclick="closeModal()">×</button></div><div class="inspect-grid"><div><span>类型</span><b>${x.kind.toUpperCase()}</b></div><div><span>容量</span><b>${fmt(x.size)}</b></div><div><span>文件系统</span><b>${esc(x.filesystem_label)}</b></div><div><span>状态</span><b class="${x.supported||x.partitions?.some(p=>p.supported)?'good':'bad'}">${x.supported||x.partitions?.some(p=>p.supported)?'支持':'需人工处理'}</b></div></div>${x.error?`<div class="callout">${esc(x.error)}</div>`:''}${table}${body}</div>`)
}
async function mountFlow(id){
  const img=images.find(x=>x.id===id); if(!img)return;
  try{
    let x;
    if(img.kind==='iso') x=await inspectForMount(id);
    else x=await inspectForMount(id);
    if(x.kind==='iso'){await startMount(id,'ro',null);return}
    const parts=x.partitions||[];
    if(!parts.length){await startMount(id,'rw',null);return}
    openModal(`<div class="modal-head"><div><div class="kicker">MOUNT IMAGE</div><h3>选择 IMG 分区</h3></div><button class="close" onclick="closeModal()">×</button></div><div class="mount-options">${parts.map(p=>`<button class="partition-option ${p.supported?'':'disabled'}" ${p.supported?'':'disabled'} onclick="startMount('${id}','rw','${esc(p.path || p.name)}')"><div><b>${esc(p.name||p.path)}</b><span>${esc(p.fs_label)} · ${fmt(p.size)}${p.label?' · '+esc(p.label):''}</span></div><em>${p.supported?'读写':'不可用'}</em></button>`).join('')}</div><div class="callout small">选择后将执行真实宿主机挂载。完成后会立即显示 DSM File Station 路径。</div>`)
  }catch(e){toast(e.message,'error')}
}
async function inspectForMount(id){const {job_id}=await api(`/api/images/${id}/inspect/start`,{method:'POST'});const r=await pollInspectWithProgress(job_id);return r}
function pollInspectWithProgress(jobId){return new Promise((resolve,reject)=>{if($('#modalCard')){$('#modalCard').innerHTML=`<div class="job-modal"><div class="job-kicker">PREPARE MOUNT</div><h3>正在准备映像</h3><p>读取分区与文件系统信息，不会读取 1TB IMG 的全部内容。</p><div class="job-progress"><i id="jobBar"></i></div><div class="job-line"><span id="jobPct">0%</span><b id="jobStage">排队</b></div><small id="jobDetail">准备中…</small></div>`};const timer=setInterval(async()=>{try{const j=await api(`/api/inspect/${jobId}`,{timeout:10000});const b=$('#jobBar');if(b)b.style.width=`${j.progress||0}%`;const p=$('#jobPct');if(p)p.textContent=`${j.progress||0}%`;const st=$('#jobStage');if(st)st.textContent=j.stage||'';const d=$('#jobDetail');if(d)d.textContent=j.detail||'';if(j.status==='done'){clearInterval(timer);resolve(j.result)}else if(j.status==='error'){clearInterval(timer);reject(new Error(j.error||'分析失败'))}}catch(e){clearInterval(timer);reject(e)}},700)})}
async function startMount(id,mode,part){
  try{
    openModal(`<div class="job-modal"><div class="job-kicker">HOST MOUNT</div><h3>正在挂载映像</h3><p>正在执行宿主机 mount / loop 操作。大容量 IMG 请保持此页面打开。</p><div class="job-progress"><i id="jobBar"></i></div><div class="job-line"><span id="jobPct">0%</span><b id="jobStage">排队</b></div><small id="jobDetail">准备中…</small></div>`);
    const f=new URLSearchParams({mode,partition:part||''});
    const {job_id}=await api(`/api/images/${id}/mount/start`,{method:'POST',body:f});
    const m=await pollMountJob(job_id);
    await refreshAll();
    showMountSuccess(m);
  }catch(e){toast(e.message,'error');await refreshAll();}
}
function pollMountJob(jobId){return new Promise((resolve,reject)=>{const timer=setInterval(async()=>{try{const j=await api(`/api/mount-job/${jobId}`,{timeout:10000});const b=$('#jobBar');if(b)b.style.width=`${j.progress||0}%`;const p=$('#jobPct');if(p)p.textContent=`${j.progress||0}%`;const st=$('#jobStage');if(st)st.textContent=j.stage||'';const d=$('#jobDetail');if(d)d.textContent=j.detail||'';if(j.status==='done'){clearInterval(timer);resolve(j.mount)}else if(j.status==='error'){if(b)b.style.width=`${Math.min(j.progress||100,100)}%`;if(st)st.textContent='挂载失败';clearInterval(timer);reject(new Error(j.error||'挂载失败'))}}catch(e){clearInterval(timer);reject(e)}},700)})}
async function unmount(id){if(!confirm('确认卸载？建议先关闭正在访问此目录的 File Station 窗口或程序。'))return;try{await api(`/api/mounts/${id}/unmount`,{method:'POST'});toast('已卸载');await refreshAll()}catch(e){toast(e.message,'error')}}
async function removeImage(id){if(!confirm('确认从映像库移除？NAS 外部映像不会删除原文件；项目 images/ 内的上传文件会删除。'))return;try{await api(`/api/images/${id}`,{method:'DELETE'});toast('已移除');await refreshAll()}catch(e){toast(e.message,'error')}}
async function checksum(id){try{const {job_id}=await api(`/api/images/${id}/checksum`,{method:'POST'});openModal(`<div class="modal-head"><div><div class="kicker">SHA-256</div><h3>正在校验映像</h3></div><button class="close" onclick="closeModal()">×</button></div><div class="checksum-box"><div class="progress"><i id="hashBar"></i></div><b id="hashPct">任务已开始</b><code id="hashResult">校验采用 DSM 宿主机 sha256sum；大文件可能耗时较长。</code></div>`);const timer=setInterval(async()=>{try{const j=await api(`/api/checksum/${job_id}`,{timeout:10000});$('#hashBar').style.width=`${j.progress||0}%`;$('#hashPct').textContent=j.status==='running'?'正在计算…':j.status==='done'?'完成':'失败';if(j.status==='done'||j.status==='error'){clearInterval(timer);$('#hashResult').textContent=j.status==='done'?j.sha256:j.error;if(j.status==='done')await refreshAll()}}catch(e){clearInterval(timer);toast(e.message,'error')}},1200)}catch(e){toast(e.message,'error')}}

let browserState={id:null,path:'/'};
async function openBrowser(id){browserState={id,path:'/'};await renderBrowser()}
async function renderBrowser(){const m=mounts.find(x=>x.id===browserState.id);if(!m)return;const r=await api(`/api/mounts/${m.id}/files?path=${encodeURIComponent(browserState.path)}`);const canWrite=m.mode==='rw';const rows=r.items.map(x=>{const p=(r.path==='/'?'':r.path)+'/'+x.name;return `<div class="file-row"><div class="file-main" onclick="${x.dir?`browserState.path='${esc(p)}';renderBrowser()`: `downloadFile('${m.id}','${encodeURIComponent(p)}')`}"><span>${x.dir?'▰':'▤'}</span><b>${esc(x.name)}</b></div><span class="file-size">${x.dir?'':fmt(x.size)}</span><button class="link-btn" onclick="${x.dir?`browserState.path='${esc(p)}';renderBrowser()`: `downloadFile('${m.id}','${encodeURIComponent(p)}')`}">${x.dir?'打开':'下载'}</button>${canWrite?`<button class="icon-delete" onclick="deleteFile('${m.id}','${encodeURIComponent(p)}')">×</button>`:''}</div>`}).join('')||'<div class="empty-inline">此目录为空</div>';openModal(`<div class="modal-head"><div><div class="kicker">FILE MANAGER</div><h3>${esc(m.image_name)}</h3><div class="browser-path">${esc(r.path)}</div></div><button class="close" onclick="closeModal()">×</button></div><div class="browser-toolbar"><div class="crumbs"><button onclick="browserState.path='/';renderBrowser()">根</button> ${browserState.path!=='/'?' / '+esc(browserState.path):''}</div><div class="toolbar-actions"><button onclick="openFileStation('${encodeURIComponent('/volume1/docker/virtual-drive/mounts/'+m.id)}')">打开 File Station 路径</button>${canWrite?`<button onclick="uploadInto('${m.id}','${encodeURIComponent(r.path)}')">上传</button><button onclick="mkdirInto('${m.id}','${encodeURIComponent(r.path)}')">新建文件夹</button>`:''}</div></div><div class="file-table">${rows}</div><div class="callout small">真实 NAS 路径：<code>/volume1/docker/virtual-drive/mounts/${esc(m.id)}</code></div>`)}
function downloadFile(id,p){location.href=`/api/mounts/${id}/download?path=${p}`}
async function deleteFile(id,p){if(!confirm('删除该文件/目录？'))return;try{await api(`/api/mounts/${id}/file?path=${p}`,{method:'DELETE'});toast('已删除');await renderBrowser()}catch(e){toast(e.message,'error')}}
async function uploadInto(id,path){const inp=document.createElement('input');inp.type='file';inp.onchange=async()=>{if(!inp.files[0])return;const f=new FormData();f.append('path',decodeURIComponent(path));f.append('file',inp.files[0]);try{toast('正在写入…');await api(`/api/mounts/${id}/upload`,{method:'POST',body:f});toast('写入完成');renderBrowser()}catch(e){toast(e.message,'error')}};inp.click()}
async function mkdirInto(id,path){const name=prompt('新文件夹名称');if(!name)return;const f=new FormData();f.append('path',decodeURIComponent(path));f.append('name',name);try{await api(`/api/mounts/${id}/mkdir`,{method:'POST',body:f});toast('创建成功');renderBrowser()}catch(e){toast(e.message,'error')}}
async function copyPath(path){try{await navigator.clipboard.writeText(path);toast('NAS 路径已复制')}catch{toast('复制失败，请手动复制')}}
function fileStationRoute(path){const decoded=decodeURIComponent(path).replace(/^\/volume1\/?/,'');const parts=decoded.split('/').filter(Boolean);return parts.length?parts.join('  /  '):'NAS 根目录'}
function openFileStation(encodedPath){const path=decodeURIComponent(encodedPath);if(navigator.clipboard){navigator.clipboard.writeText(path).catch(()=>{});toast('DSM 路径已复制');}else toast(path)}
function showMountSuccess(m){const abs=`/volume1/docker/virtual-drive/mounts/${m.id}`;const route=fileStationRoute(abs);openModal(`<div class="success-modal"><div class="success-icon">✓</div><div class="kicker">MOUNT COMPLETE</div><h3>映像挂载成功</h3><p class="success-sub">真实宿主机挂载已经完成。下面的路径可直接在 DSM File Station 打开。</p><div class="path-card"><div><span>DSM 真实路径</span><code>${esc(abs)}</code></div><button onclick="copyPath(decodeURIComponent('${encodeURIComponent(abs)}'))">复制路径</button></div><div class="route-card"><span>File Station</span><b>${esc(route)}</b></div><div class="success-meta"><span>${esc((m.mode||'ro').toUpperCase())}</span><span>${esc(labelFs(m.fs_type||'unknown'))}</span><span>${m.partition?'分区 '+esc(m.partition.split('/').pop()):'整盘'}</span></div><div class="modal-actions"><button class="secondary-btn" onclick="closeModal()">继续</button><button class="primary-btn" onclick="closeModal();openBrowser('${m.id}')">打开 Web 文件管理器</button></div></div>`)}
function openHistory(){api('/api/history?limit=100').then(rows=>openModal(`<div class="modal-head"><div><div class="kicker">ACTIVITY LOG</div><h3>挂载历史</h3></div><button class="close" onclick="closeModal()">×</button></div><div class="history-list">${rows.map(r=>`<div class="history-row"><span class="history-dot ${r.event}"></span><div><b>${eventLabel(r.event)} · ${esc(r.image_name||'系统')}</b><small>${new Date(r.created_at).toLocaleString()} · ${esc(r.detail||'')}</small></div></div>`).join('')||'<div class="empty-inline">暂无记录</div>'}</div>`)).catch(e=>toast(e.message,'error'))}
function eventLabel(e){return ({mount:'挂载',unmount:'卸载',upload:'导入',import:'加入映像库',delete:'删除/移除',checksum:'校验'})[e]||e}
function openModal(html){$('#modalCard').innerHTML=html;$('#modal').classList.remove('hidden')}
function closeModal(){$('#modal').classList.add('hidden');$('#modalCard').innerHTML=''}
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal()});
$$('.filter').forEach(b=>b.addEventListener('click',()=>{$$('.filter').forEach(x=>x.classList.remove('active'));b.classList.add('active');currentFilter=b.dataset.filter;renderImages()}));

function openImport(){
  nasPickerPath=nasPickerDefault;
  openModal(`<div class="modal-head"><div><div class="kicker">IMPORT IMAGE</div><h3>导入映像</h3><div class="browser-path">NAS 默认目录：${esc(nasPickerDefault)}</div></div><button class="close" onclick="closeModal()">×</button></div><div class="import-tabs"><button class="import-tab active" id="tabNas" onclick="switchImport('nas')">NAS 内部选择</button><button class="import-tab" id="tabPc" onclick="switchImport('pc')">电脑上传</button></div><div id="importPane"></div>`);
  renderNasPicker();
}
function switchImport(mode){$('#tabNas').classList.toggle('active',mode==='nas');$('#tabPc').classList.toggle('active',mode==='pc');if(mode==='nas')renderNasPicker();else renderPcPicker()}
async function renderNasPicker(path=nasPickerPath){
  try{
    nasPickerPath=path;
    const r=await api(`/api/nas/browse?path=${encodeURIComponent(path)}`,{timeout:30000});
    const rows=(r.items||[]).map(x=>{const size=x.size==null?'':fmt(x.size);const icon=x.dir?'▰':(x.image?'◉':'▤');return `<div class="nas-row" onclick="${x.dir?`renderNasPicker('${esc(x.path)}')`:''}"><span class="nas-icon">${icon}</span><div class="nas-name" title="${esc(x.path)}"><b>${esc(x.name)}</b><div class="nas-meta">${x.dir?'文件夹':size}</div></div>${x.image?`<span class="nas-kind">${x.kind.toUpperCase()}</span><button class="nas-select primary" onclick="event.stopPropagation();addNasImage('${encodeURIComponent(x.path)}')">添加</button>`:''}</div>`}).join('')||'<div class="nas-empty">当前目录没有内容</div>';
    $('#importPane').innerHTML=`<div class="nas-picker"><div class="nas-toolbar"><button onclick="renderNasPicker(decodeURIComponent('${encodeURIComponent(r.parent||'/volume1')}'))">← 上级</button><button onclick="renderNasPicker(nasPickerDefault)">默认目录</button><button onclick="renderNasPicker('/volume1')">根目录</button><div class="nas-path" title="${esc(r.path)}">${esc(r.path)}</div></div><div class="nas-list">${rows}</div></div><div class="import-foot"><small>NAS 内部选择不会复制映像，只登记原文件路径；移除索引不会删除源文件。</small></div>`;
  }catch(e){
    $('#importPane').innerHTML=`<div class="callout"><b>NAS 浏览失败</b><div>${esc(e.message)}</div></div>`;
  }
}
async function addNasImage(encodedPath){const path=decodeURIComponent(encodedPath);try{toast('正在加入映像库…');const f=new FormData();f.append('path',path);const r=await api('/api/library/add',{method:'POST',body:f});toast(r.existing?'该映像已经在映像库中':'已加入映像库');closeModal();await refreshAll()}catch(e){toast(e.message,'error')}}
function renderPcPicker(){$('#importPane').innerHTML=`<div class="dropzone" style="margin:0" onclick="$('#pcImportInput').click()"><span class="drop-icon">⇧</span><div><strong>选择电脑上的 ISO / IMG</strong><small>上传后文件保存到 /volume1/docker/virtual-drive/images/</small></div><input id="pcImportInput" type="file" multiple accept=".iso,.img,.ima,.raw,.bin" hidden></div><div class="import-foot"><small>适合电脑本地还没有存到 NAS 的映像；NAS 已有文件请使用“NAS 内部选择”。</small></div>`;$('#pcImportInput').addEventListener('change',e=>{if(e.target.files.length)submitFiles([...e.target.files]).then(closeModal)})}
async function submitFiles(files){
  for(const file of files){
    const f=new FormData();
    f.append('file',file);
    try{
      toast(`正在导入 ${file.name}…`);
      await api('/api/upload',{method:'POST',body:f,timeout:3600000});
    }catch(e){
      toast(`${file.name}: ${e.message}`,'error');
    }
  }
  toast('导入完成');
  await refreshAll();
}

function setupUpload(){
  const input=$('#uploadInput'); if(input) input.addEventListener('change',e=>{if(e.target.files.length)submitFiles([...e.target.files]);e.target.value=''});
  const dz=$('#dropzone');
  if(dz){
    ['dragenter','dragover'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('dragging')}));
    ['dragleave','drop'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('dragging')}));
    dz.addEventListener('drop',e=>{if(e.dataTransfer.files.length)submitFiles([...e.dataTransfer.files])});
  }
  const di=$('#dropInput'); if(di) di.addEventListener('change',e=>{if(e.target.files.length)submitFiles([...e.target.files]);e.target.value=''})
}
async function loadAppVersion(){try{const v=await api('/api/version',{timeout:8000});const el=document.querySelector('.brand-title span');if(el&&v.version)el.textContent=v.version;const root=await api('/api/nas/status',{timeout:10000});if(root.import_root){nasPickerDefault=root.import_root;nasPickerPath=root.import_root;const d=$('#defaultNasRoot');if(d)d.textContent=root.import_root}}catch{}}

document.addEventListener('DOMContentLoaded',()=>{setupUpload();refreshAll()});
