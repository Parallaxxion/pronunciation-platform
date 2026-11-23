let state, view='recordings', selectedId=null;
const labels={overview:'采集概览',recordings:'录音核查',questions:'题目覆盖',speakers:'说话人',history:'操作记录'};
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const active=()=>state.recordings.filter(r=>!r.deleted);
function diagnosisLabel(diagnosis) {
  if (!diagnosis) {
    return '暂无诊断结果';
  }

  switch (diagnosis.status) {
    case 'pending':
      return '等待检测';
    case 'processing':
      return '检测中';
    case 'failed':
      return '检测失败';
    case 'completed':
      if (!Array.isArray(diagnosis.errors)) {
        return '诊断数据不完整';
      }

      return diagnosis.errors.length > 0
        ? `${diagnosis.errors.length} 条偏误标注`
        : '本次模型未检出偏误';
    default:
      return '诊断状态未知';
  }
}
function toast(message){const t=document.querySelector('#toast');t.textContent=message;t.style.display='block';setTimeout(()=>t.style.display='none',4000);}
async function refresh(){try{const response=await fetch('/api/state');if(!response.ok)throw Error('数据加载失败');state=await response.json();render();}catch(error){toast(error.message);}}
function render(){
 document.querySelector('#title').textContent=labels[view];
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
 const count=active().length,covered=state.questions.filter(q=>q.count>0).length,gap=state.questions.reduce((sum,q)=>sum+Math.max(0,q.target-q.count),0);
 document.querySelector('#metrics').innerHTML=[['注册说话人',state.speakers.length,'匿名背景信息'],['有效录音',count,'含同一题的多次录音'],['已覆盖题目',covered+' / '+state.questions.length,'至少有一条有效录音'],['采集缺口',gap,'按每题 3 条演示目标计算']].map(([l,v,d])=>`<div class="metric"><div class="label">${l}</div><strong>${v}</strong><div class="muted">${d}</div></div>`).join('');
 if(view==='recordings'){
 document.querySelector('#content').innerHTML='<div class="panel"><div class="toolbar"><input id="search" aria-label="搜索录音" placeholder="搜索题目、题号或说话人编号"><select id="level" aria-label="等级"><option value="">全部等级</option><option value="1">一级</option><option value="2">二级</option></select><select id="scope" aria-label="录音状态"><option value="active">有效录音</option><option value="deleted">已删除录音</option></select><button id="reload">刷新</button></div><div id="rows"></div></div>';
 ['search','level','scope'].forEach(id=>document.getElementById(id).addEventListener('input',renderRows));document.querySelector('#reload').onclick=refresh;renderRows();
 }else if(view==='questions'){
 document.querySelector('#content').innerHTML=`<div class="panel"><div class="toolbar"><h3>题目采集覆盖</h3><span class="muted">目标为演示假设，正式采集量待确认</span></div><table><thead><tr><th>题目</th><th>等级</th><th>收录 / 目标</th><th>缺口</th><th>覆盖进度</th></tr></thead><tbody>${state.questions.map(q=>`<tr><td>${escapeHtml(q.text)}<small>${q.id}</small></td><td>${q.level} 级</td><td>${q.count} / ${q.target}</td><td>${Math.max(0,q.target-q.count)}</td><td><div class="bar"><span style="width:${Math.min(100,q.count/q.target*100)}%"></span></div></td></tr>`).join('')}</tbody></table></div>`;
 }else if(view==='speakers'){
 document.querySelector('#content').innerHTML=`<div class="panel"><div class="toolbar"><h3>说话人背景信息</h3><span class="muted">全部为虚构演示信息</span></div><table><thead><tr><th>匿名编号</th><th>国籍</th><th>母语</th><th>水平</th><th>有效录音</th></tr></thead><tbody>${state.speakers.map(s=>`<tr><td>${s.id}</td><td>${s.nationality}</td><td>${s.language}</td><td>${s.level} 级</td><td>${active().filter(r=>r.speaker_id===s.id).length}</td></tr>`).join('')}</tbody></table></div>`;
 }else if(view==='history'){
 document.querySelector('#content').innerHTML=`<div class="panel"><div class="toolbar"><h3>操作记录与撤销</h3><span class="muted">后续修改冲突时保留当前记录</span></div><table><thead><tr><th>操作时间</th><th>录音</th><th>操作</th><th>处理</th></tr></thead><tbody>${state.actions.map(a=>`<tr><td>${new Date(a.created_at).toLocaleString('zh-CN')}</td><td>${a.recording_id}</td><td>${{note:'更新备注',delete:'删除录音',restore:'恢复录音'}[a.kind]}</td><td>${a.undone?'已撤销':`<button class="link" data-undo="${a.id}">撤销操作</button>`}</td></tr>`).join('')||'<tr><td colspan="4">暂无操作。可在录音详情中修改备注或删除录音。</td></tr>'}</tbody></table></div>`;
 document.querySelectorAll('[data-undo]').forEach(b=>b.onclick=()=>mutate('/api/undo',{action_id:Number(b.dataset.undo)}));
 }else{
 document.querySelector('#content').innerHTML=`<div class="grid"><div class="panel pad"><h2>等级采集进度</h2><p class="muted">每次录音独立计数，已删除记录不计入有效量。</p>${[1,2].map(l=>`<div class="metadata"><span>${l} 级<b>${active().filter(r=>r.level===l).length} 条录音</b></span><span>题目覆盖<b>${state.questions.filter(q=>q.level===l&&q.count>0).length} / ${state.questions.filter(q=>q.level===l).length}</b></span></div>`).join('')}</div><div class="panel pad"><h2>本地演示进展</h2><p>录音筛选、在线回听、偏误展示</p><p>备注保存、删除恢复、操作撤销</p><p>音频、信息清单、标注打包导出</p><p class="muted">真实接口、身份认证、HTTPS 与跨端联调待实施。</p><a class="primary" href="/api/export">下载演示数据包</a></div></div>`;
 }
}
function renderRows() {
  const search = document.querySelector('#search').value.toLowerCase();
  const level = document.querySelector('#level').value;
  const deleted = document.querySelector('#scope').value === 'deleted';

  const rows = state.recordings.filter(r =>
    Boolean(r.deleted) === deleted &&
    (!level || r.level === Number(level)) &&
    [r.id, r.speaker_id, r.question_id, r.text]
      .join(' ')
      .toLowerCase()
      .includes(search)
  );

  document.querySelector('#rows').innerHTML = `
    <table>
      <thead>
        <tr>
          <th>录音 / 题目</th>
          <th>说话人</th>
          <th>等级</th>
          <th>录音序号</th>
          <th>诊断状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>
              ${escapeHtml(r.text)}
              <small>
                ${escapeHtml(r.id)} · ${escapeHtml(r.question_id)}
              </small>
            </td>
            <td>
              ${escapeHtml(r.speaker_id)}
              <small>${escapeHtml(r.nationality)}</small>
            </td>
            <td>${escapeHtml(r.level)} 级</td>
            <td>第 ${escapeHtml(r.attempt)} 次</td>
            <td>
              <span class="tag">
                ${escapeHtml(diagnosisLabel(r.diagnosis))}
              </span>
            </td>
            <td>
              <button
                class="link"
                data-open="${escapeHtml(r.id)}"
              >核查详情 ↗</button>
            </td>
          </tr>
        `).join('') || `
          <tr>
            <td colspan="6">没有符合条件的录音。</td>
          </tr>
        `}
      </tbody>
    </table>
    <div class="foot">
      共 ${rows.length} 条记录 ·
      演示样本均可追溯到说话人、题目和录音序号
    </div>
  `;

  document.querySelectorAll('[data-open]').forEach(button => {
    button.onclick = () => showDetail(button.dataset.open);
  });
}
function showDetail(id) {
  const r = state.recordings.find(recording => recording.id === id);

  if (!r) {
    toast('未找到这条录音，请刷新列表');
    return;
  }

  selectedId = id;

  const diagnosis = r.diagnosis;
  const completed = diagnosis?.status === 'completed';
  const validErrors = Array.isArray(diagnosis?.errors);

  // 仅在诊断完成且结果结构完整时展示偏误。
  const errors = completed && validErrors ? diagnosis.errors : [];

  const snapshot = r.question_snapshot;
  const displayText = snapshot?.display_text ?? r.text;
  const characters = Array.from(displayText);
  const pinyin = Array.isArray(r.pinyin) ? r.pinyin : [];
  let questionTokens = null;
  if (Array.isArray(snapshot?.tokens)) {
    questionTokens = snapshot.tokens;
  } else if (!snapshot && characters.length === pinyin.length) {
    // 兼容旧原型中题文与逐字拼音一一对应的数据。
    questionTokens = characters.map((c, i) => ({
      c, display_py: pinyin[i], display_start: i
    }));
  }
  const names = { tone: '声调偏误', substitution: '声韵母误读', omission: '漏读' };
  let tokens = '';
  const validPositions = questionTokens && questionTokens.every((token, index) =>
    Number.isInteger(token.display_start) && token.display_start >= 0 &&
    characters[token.display_start] === token.c &&
    (index === 0 || token.display_start > questionTokens[index - 1].display_start)
  );
  if (!validPositions || questionTokens.length === 0) {
    tokens = '<p>' + escapeHtml(displayText) + '</p>' +
      '<p class="muted">缺少有效逐字位置数据，暂无法定位偏误。</p>';
  } else {
    const positions = new Map(questionTokens.map((token, index) =>
      [token.display_start, { token, index }]));
    const insertionHtml = boundary => errors.filter(error =>
      error.type === 'insertion' && error.boundary_index === boundary
    ).map(error => '<span class="insertion">增读<br>' +
      escapeHtml(error.actual) + '</span>').join('');
    characters.forEach((char, position) => {
      const entry = positions.get(position);
      if (!entry) {
        tokens += '<span>' + escapeHtml(char) + '</span>';
        return;
      }
      const { token, index } = entry;
      tokens += insertionHtml(index);
      const found = errors.filter(error =>
        Object.hasOwn(names, error.type) && error.char_index === index);
      const annotations = found.map(error => {
        if (error.type === 'omission') return '<small>漏读<br>未读出</small>';
        return '<small>' + names[error.type] + '<br>预期 ' +
          escapeHtml(error.expected) + '<br>实际 ' + escapeHtml(error.actual) + '</small>';
      }).join('');
      tokens += '<div class="char ' + (found[0]?.type || '') + '"><small>' +
        escapeHtml(token.display_py) + '</small><b>' + escapeHtml(char) +
        '</b>' + annotations + '</div>';
      // 句尾增读显示在最后一个发音字之后、尾部标点之前。
      if (index === questionTokens.length - 1) tokens += insertionHtml(questionTokens.length);
    });
  }
  document.querySelector('#detailContent').innerHTML = `
    <div class="dialog-head">
      <div>
        <div class="eyebrow">
          录音核查 / ${escapeHtml(r.id)}
        </div>
        <h2>${escapeHtml(displayText)}</h2>
      </div>
      <button id="close">关闭</button>
    </div>

    <div class="metadata">
      <span class="muted">
        匿名编号<b>${escapeHtml(r.speaker_id)}</b>
      </span>
      <span class="muted">
        题目编号<b>${escapeHtml(r.question_id)}</b>
      </span>
      <span class="muted">
        录音序号<b>第 ${escapeHtml(r.attempt)} 次</b>
      </span>
      <span class="muted">
        录音时间
        <b>${new Date(r.recorded_at).toLocaleString('zh-CN')}</b>
      </span>
    </div>

    <h3>诊断状态</h3>
    <p role="status">${escapeHtml(diagnosisLabel(diagnosis))}</p>

    <h3>逐字与字间偏误</h3>
    <div class="phonetics">${tokens}</div>

    <div class="legend">
      橙色 声调偏误　红色 声韵母误读　
      蓝色 漏读　紫色 字间增读<br>
      当前使用人工构造标注和合成音频验证展示效果。
    </div>

    <div class="audio">
      <span class="muted">${escapeHtml(r.device)} · WAV</span>
      <audio
        controls
        preload="metadata"
        src="/audio/${encodeURIComponent(r.audio)}"
      ></audio>
    </div>

    <label for="note">核查备注</label>
    <textarea
      id="note"
      rows="2"
      maxlength="500"
      placeholder="记录核查意见"
    >${escapeHtml(r.note)}</textarea>

    <div class="actions">
      <button id="delete" class="danger">
        ${r.deleted ? '恢复录音' : '删除录音'}
      </button>
      <button id="save" class="primary">保存备注</button>
    </div>
  `;

  const dialog = document.querySelector('#detail');

  document.querySelector('#close').onclick = () => dialog.close();

  document.querySelector('#save').onclick = () => {
    mutate('/api/recordings/update', {
      id: r.id,
      version: r.version,
      kind: 'note',
      note: document.querySelector('#note').value
    }, true);
  };

  document.querySelector('#delete').onclick = () => {
    if (
      r.deleted ||
      confirm('将录音移入已删除列表？可以恢复，文件会保留。')
    ) {
      mutate('/api/recordings/update', {
        id: r.id,
        version: r.version,
        kind: r.deleted ? 'restore' : 'delete'
      });
    }
  };

  if (!dialog.open) {
    dialog.showModal();
  }
}
async function mutate(url,body,keep=false){try{const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error);await refresh();if(keep)showDetail(selectedId);else document.querySelector('#detail').close();toast('操作已保存');}catch(error){toast(error.message);}}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{view=b.dataset.view;render();});refresh();
