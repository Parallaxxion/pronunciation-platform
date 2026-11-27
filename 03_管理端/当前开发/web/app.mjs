import {
  escapeHtml as e,
  detailView,
  statisticsView,
  ManagementClient
} from '/components/management.mjs';
import {
  displayPinyin
} from './pinyin.mjs';
import {
  queueStore,
  uploadForm,
  assertReceipt
} from './queue.mjs';
const $ = s => document.querySelector(s),
  api = new ManagementClient();
const state = {
  admin: null,
  student: null,
  config: {},
  page: 'home',
  offset: 0,
  filter: {},
  question: null,
  recorder: null,
  stream: null,
  uploading: false,
  preview: null,
  epoch: 0,
  questionPending: false,
  recordingPending: false,
  finalizing: false
};
const mediaBusy = () => state.questionPending || state.recordingPending || state.finalizing || state.recorder?.state === 'recording';
const han = /\p{Unified_Ideograph}/u;
const names = {
  home: '项目工作台',
  student: '跟读采集',
  queue: '我的上传',
  proposition: '命题工作区',
  overview: '采集概览',
  recordings: '录音核查',
  questions: '题目管理',
  speakers: '说话人管理',
  history: '操作记录'
};
const sn = {
  draft: '草稿',
  validated: '已校验',
  ready: '待发布',
  published: '已发布',
  rejected: '未通过',
  unknown: '待核查',
  pending: '等待检测',
  processing: '检测中',
  completed: '已完成',
  failed: '失败'
};
import {levelOptions as levels} from './options.mjs';
const button = (text, action, cls = '') => `<button type="button" class="${cls}" data-action="${action}">${text}</button>`;
const panel = (html, cls = '') => `<div class="panel pad ${cls}">${html}</div>`;
const tag = value => `<span class="tag ${['failed','rejected'].includes(value)?'bad':['pending','processing','unknown','暂无结果'].includes(value)?'warn':''}">${e(sn[value]??value??'暂无结果')}</span>`;

function toast(text) {
  $('#toast').textContent = text;
  $('#toast').style.display = 'block';
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('#toast').style.display = 'none', 5000)
}

function failure(err) {
  const text=err.message||'操作失败';
  if($('#detail').open && $('#dialog-error')){ $('#dialog-error').textContent=text;$('#dialog-error').hidden=false;}else toast(text);
}
async function json(path, options = {}) {
  const headers = options.body instanceof FormData ? {} : {
    'Content-Type': 'application/json'
  };
  const r = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...headers,
      ...options.headers
    }
  });
  let d;
  try {
    d = await r.json()
  } catch {
    throw new Error('服务返回了无法识别的响应')
  }
  if (!r.ok) {
    const err = new Error(typeof(d.error ?? d.detail) === 'string' ? (d.error ?? d.detail) : `请求失败（${r.status}），请检查输入或登录状态`);
    err.status = r.status;
    throw err;
  }
  return d;
}
const adminJson = async (path, options = {}) => (await api.request('/api/v1/admin/' + path, options)).json();

function modal(html) {
  $('#detailContent').innerHTML = `<div class="row space"><span class="muted">声采工作台</span>${button('关闭','close')}</div><div id="dialog-error" class="error" role="alert" hidden></div>${html}`;
  $('#detail').showModal()
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

function navigate() {
  const page = location.hash.slice(1).split('?')[0] || 'home';
  if (mediaBusy()) {
    location.hash = state.page;
    toast('请先结束并保存当前录音');
    return;
  }
  state.page = names[page] ? page : 'home';
  state.offset = 0;
  state.filter = {};
  return render();
}
async function render() {
  const epoch = ++state.epoch,
    page = state.page;
  $('#title').textContent = names[page];
  $('#nav').innerHTML = Object.entries(names).map(([id, name]) => `<a href="#${id}" ${id===page?'aria-current="page"':''} class="${id===page?'active':''}">${name}</a>`).join('');
  $('#identity').innerHTML = state.admin ? `${e(state.admin.actor)} · ${state.admin.role==='admin'?'管理员':'只读'} ${button('退出管理','logout-admin')}` : button('管理登录', 'login');
  $('#notice').innerHTML = state.config.mode === 'isolated_demo' ? '<div class="notice">本机独立联调环境 · 示例录音与偏误为构造数据。真实采集与算法效果需另行验收。</div>' : '';
  $('#content').innerHTML = '<div class="empty">正在读取…</div>';
  try {
    let html;
    if (page === 'home') html = home();
    else if (['student', 'queue'].includes(page)) {
      await studentIdentity();
      html = state.student ? (page === 'student' ? student() : await queuePage()) : studentLogin();
    } else if (!state.admin) html = login();
    else if (page === 'proposition') html = await proposition();
    else if (page === 'overview') html = await overview();
    else if (page === 'history') html = await history();
    else html = await entities(page);
    if (epoch === state.epoch) $('#content').innerHTML = html;
  } catch (err) {
    if (epoch === state.epoch) $('#content').innerHTML = panel(`<div class="error">${e(err.message)}</div><p>${button('重试','refresh')}</p>`)
  }
}

function home() {
  return `<div class="hero"><span class="badge">第一阶段 · 音频数据采集</span><h2>让每一段声音<br>成为可追溯的学习样本。</h2><p>命题、采集、核查在同一个工作台完成。选择你的工作空间，继续今天的任务。</p></div><div class="cards"><a href="#student" class="card"><span class="number">学生空间 / STUDENT</span><h2>开始跟读采集</h2><p>选择等级，查看逐字拼音。录音、试听与重录，上传你的每一次练习。</p><span class="primary">进入采集</span></a><a href="#proposition" class="card"><span class="number">命题空间 / AUTHORING</span><h2>建设分级题库</h2><p>查看题目，运行校验和覆盖统计。根据缺口完善题库，通过检查后发布。</p><span class="primary">进入命题</span></a><a href="#overview" class="card"><span class="number">管理空间 / MANAGEMENT</span><h2>核查采集成果</h2><p>回听录音，核对诊断偏误，掌握覆盖进度。导出规范、完整的数据。</p><span class="primary">进入管理</span></a></div><div class="panel pad" style="margin-top:24px"><h3>本期工作流程</h3><p class="muted">题库校验与发布 → 按等级跟读 → 录音上传 → 后台诊断 → 管理核查 → 统计与导出</p><p class="muted">学生端仅完成采集，不显示诊断或评分。每次录音保留独立记录。</p></div>`
}

function login() {
  return panel(`<h2>管理与命题工作区登录</h2><p class="auth-hint">使用部署维护者分配的访问令牌。登录后按授权范围查看或管理数据。</p><form data-form="admin-login" class="stack"><label>访问令牌<input name="token" type="password" autocomplete="off" minlength="32" required></label><button class="primary">登录工作区</button></form>`, 'login')
}
async function overview() {
  const s = await adminJson('statistics' + (state.filter.level ? '?level=' + state.filter.level : ''));
  const v = statisticsView(s);
  return `<div class="toolbar"><label>等级<select id="overview-level">${levels(state.filter.level)}</select></label>${button('刷新统计','overview-filter')}${button('导出完整数据包','export','primary')}</div><div id="metrics">${v.metrics}</div><div class="grid">${panel(`<h2>等级采集分布</h2>${s.by_level.map(l=>`<div class="row space"><p>${l.level} 级</p><b>${l.recording_count} 条录音 · ${l.unique_speaker_count} 人</b></div><progress max="${Math.max(1,...s.by_level.map(x=>x.recording_count))}" value="${l.recording_count}"></progress>`).join('')}`)}${panel(`<h2>数据与统计口径</h2><p>活动题目 ${s.active_question_count} 道，已有录音覆盖 ${s.covered_active_question_count} 道。</p><p>${s.target_unknown_question_count} 道题目的目标尚未确认。</p><p class="muted">每次重录独立计数，重复请求不重复计数，已删除录音不计入有效数量。</p><p class="receipt">快照 ${e(s.snapshot_version)}</p><h3>诊断状态</h3>${Object.entries(s.by_diagnosis).map(([k,v])=>`<p>${e(sn[k]??(k==='unavailable'?'暂无结果':k))}：${v}</p>`).join('')||'<p>暂无录音</p>'}`)}</div><h2 style="margin-top:28px">题目覆盖与缺口</h2><div class="scroll-table">${v.coverage}</div>`
}

function filters() {
  return `<form data-form="filter" class="toolbar"><label>等级<select name="level">${levels(state.filter.level)}</select></label><label>题目编号<input name="question_id" value="${e(state.filter.question_id??'')}" placeholder="例如 L1-001"></label><label>说话人编号<input name="speaker_id" value="${e(state.filter.speaker_id??'')}" placeholder="匿名编号"></label>${state.page==='recordings'?'<label>检测状态<select name="status"><option value="">全部状态</option>'+['pending','processing','completed','failed'].map(status=>`<option value="${status}" ${state.filter.status===status?'selected':''}>${sn[status]}</option>`).join('')+'</select></label>':''}<label>记录范围<select name="deleted"><option value="false">有效记录</option><option value="true" ${state.filter.deleted==='true'?'selected':''}>已删除</option></select></label><button class="primary">查询</button>${button('清空','clear-filter')}</form>`
}
async function entities(kind) {
  const r = await api.list(kind, {
    ...state.filter,
    offset: state.offset,
    limit: 20
  });
  state.rows = r.items;
  state.total = r.total;
  const isRec = kind === 'recordings';
  const headers = isRec ? ['录音 / 题目', '说话人', '录音时间', '状态', '操作'] : kind === 'questions' ? ['题目编号', '文本', '等级', '状态', '操作'] : ['说话人编号', '国籍 / 母语', '等级', '版本', '操作'];
  return `<div class="panel">${filters()}<div class="toolbar row space"><span>共 ${r.total} 条记录</span>${state.admin.role==='admin'&&!isRec?button(kind==='speakers'?'新增说话人':'新增管理题目','create','primary'):''}${isRec?button('导出有效样本','export','primary'):''}</div><div class="scroll-table"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${r.items.map((x,i)=>`<tr>${(isRec?[`${e(x.recording_id)}<small>${e(x.question_id)} · 第 ${x.take_no} 次</small>`,e(x.speaker_id),e(new Date(x.recorded_at).toLocaleString()),tag(x.diagnosis_available?x.diagnosis.status:'暂无结果')]:kind==='questions'?[e(x.question_id),e(x.display_text),x.level+' 级',tag(x.status)]:[e(x.speaker_id),e(x.nationality)+' / '+e(x.language),x.level+' 级','v'+x.version]).map(v=>`<td>${v}</td>`).join('')}<td><button class="link" data-action="detail" data-index="${i}">查看详情</button></td></tr>`).join('')||`<tr><td colspan="5" class="empty">没有符合条件的记录</td></tr>`}</tbody></table></div><div class="pagination"><button data-action="prev" ${state.offset===0?'disabled':''}>上一页</button><span>${r.total?state.offset+1:0}–${Math.min(state.offset+20,r.total)} / ${r.total}</span><button data-action="next" ${state.offset+20>=r.total?'disabled':''}>下一页</button></div></div>`
}

function recordDetail(row) {
  const view = detailView(row);
  return `<h2>录音核查</h2><div class="detail-grid">${[['录音编号',row.recording_id],['说话人',row.speaker_id],['题目 / 版本',row.question_id+' / '+(row.question_snapshot.question_version??'未提供')],['录音次数',row.take_no],['来源',row.data_source],['记录版本',row.version]].map(([k,v])=>`<div><small>${k}</small>${e(v)}</div>`).join('')}</div>${view.html}<p class="legend">橙色：声调 · 红色：声韵母 · 蓝色：漏读 · 紫色：增读</p><div class="audio">标准 WAV<audio controls preload="none" src="/api/v1/admin/recordings/${encodeURIComponent(row.recording_id)}/audio"></audio><a href="/api/v1/admin/recordings/${encodeURIComponent(row.recording_id)}/audio?variant=original" download>下载原始录音</a></div><form data-form="note" class="stack"><label>核查备注<textarea name="note" maxlength="500" rows="3">${e(row.note)}</textarea></label><button class="primary" ${state.admin.role!=='admin'?'disabled':''}>保存核查备注</button></form>`
}

function editor(kind, row) {
  const q = kind === 'questions';
  return `<h2>${row?'编辑':'新增'}${q?'管理题目':'说话人'}</h2><p class="muted">此处维护管理端数据。${q?'命题发布请到命题工作区。':'上游学生账号的停用需学生服务支持。'}</p><form data-form="entity" class="stack"><label>${q?'题目':'说话人'}编号<input name="id" value="${e(row?.[q?'question_id':'speaker_id']??'')}" pattern="[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}" required ${row?'readonly':''}></label><label>等级<select name="level">${levels(row?.level??1,false)}</select></label>${q?`<label>题目文本<textarea name="text" required rows="2">${e(row?.display_text??'')}</textarea></label><label>逐字拼音（按汉字顺序，用空格分隔，如 wo3 ai4 ni3）<input name="pinyin" value="${e(row?.tokens?.map(t=>t.py).join(' ')??'')}" required></label><label>采集目标（留空表示未确认）<input type="number" min="0" name="target" value="${row?.target_recordings??''}"></label>`:`<label>国籍<input name="nationality" required value="${e(row?.nationality??'')}"></label><label>母语<input name="language" required value="${e(row?.language??'')}"></label>`}<button class="primary">保存</button></form>`
}
async function showDetail(index) {
  const row = state.rows[index],
    kind = state.page;
  state.selected = {
    row,
    kind
  };
  let html = kind === 'recordings' ? recordDetail(row) : `<h2>${e(row.speaker_id??row.question_id)}</h2><p>${e(row.display_text??`${row.nationality} / ${row.language}`)}</p><p>${row.level??row.question_snapshot?.level} 级 · v${row.version}</p>${state.admin.role==='admin'?button('编辑','edit'):''}`;
  html += `<div class="actions">${button('查看历史版本','versions')}${state.admin.role==='admin'?button(row.deleted?'恢复记录':'删除记录',row.deleted?'restore':'delete','danger'):''}</div><div id="versions"></div>`;
  modal(html)
}
async function history() {
  const r = await adminJson('actions?offset=' + state.offset + '&limit=20');
  state.total = r.total;
  return panel(`<h2>操作记录</h2><p class="muted">只有未被后续修改覆盖的操作可以撤销。恢复及撤销都会生成新的审计记录。</p><div class="scroll-table"><table><thead><tr><th>时间 / 操作者</th><th>对象</th><th>操作</th><th>处理</th></tr></thead><tbody>${r.items.map(x=>`<tr><td>${e(x.created_at)}<small>${e(x.actor)}</small></td><td>${e(x.entity_id)}</td><td>${e(({create:'创建',update:'修改',delete:'删除',restore:'恢复',undo:'撤销',diagnosis:'更新诊断'})[x.operation]??x.operation??x.kind)}</td><td><button data-action="undo" data-id="${x.id}" ${!x.can_undo||state.admin.role!=='admin'?'disabled':''}>${x.undone?'已撤销':'撤销'}</button></td></tr>`).join('')||'<tr><td colspan="4">暂无操作</td></tr>'}</tbody></table></div><div class="pagination"><button data-action="prev" ${state.offset===0?'disabled':''}>上一页</button><button data-action="next" ${state.offset+20>=r.total?'disabled':''}>下一页</button></div>`)
}
async function proposition() {
  const level = state.filter.level || 1;
  const r = await json('/gateway/proposition/api/questions?level=' + level);
  state.propRows = r.items ?? [];
  return `<div class="panel pad"><div class="row space"><div><h2>分级题库工作流</h2><p class="muted">校验题目、检查覆盖、按缺口补题，达标后发布。</p></div><label>当前等级<select id="prop-level">${levels(level,false)}</select></label>${button('切换等级','prop-filter')}</div><div class="pipeline">${['validate','stats','publish'].map((action,i)=>`<button data-action="pipeline" data-step="${action}" ${state.admin.role!=='admin'?'disabled':''}><b>${['题目校验','覆盖统计与缺口','发布题库'][i]}</b><small>${['检查字表、句长、重复与语法','查看覆盖指标及待补题内容','执行上游发布门禁，供学生抽题'][i]}</small></button>`).join('')}</div><div id="pipeline-result" role="status"></div><p class="muted">七至九级按命题端最新规则合并到第 7 级。题目新增、修改和补题目前由命题组流水线导入，网页编辑接口待该组交付。</p></div><div class="panel" style="margin-top:22px"><div class="toolbar row space"><span>${r.total??state.propRows.length} 道题目</span>${button('抽取已发布题目预览','draw')}${button('导出当前题库 JSON','bank-export')}</div><div class="scroll-table"><table><thead><tr><th>编号</th><th>文本与逐字拼音</th><th>状态</th><th>已录次数</th></tr></thead><tbody>${state.propRows.slice(state.offset,state.offset+20).map(q=>`<tr><td>${e(q.question_id??q.id)}</td><td>${e(q.display_text??q.text)}<small>${e(q.tokens?.map(t=>displayPinyin(t.display_py??t.py)).join(' '))}</small></td><td>${tag(q.status)}</td><td>${q.rec_count??'—'}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">该等级暂无题目，请联系命题组补齐题库</td></tr>'}</tbody></table></div><div class="pagination"><button data-action="prev" ${state.offset===0?'disabled':''}>上一页</button><span>${state.offset+1} / ${r.total??0}</span><button data-action="next" ${state.offset+20>=state.propRows.length?'disabled':''}>下一页</button></div></div>`
}
async function studentIdentity() {
  try {
    state.student = await json('/gateway/student/api/auth/me')
  } catch (err) {
    state.student = null;
    if (err.status !== 401) throw err
  }
}

function studentLogin() {
  return `<div class="grid">${panel(`<h2>学生登录 / Sign in</h2><form data-form="student-login" class="stack"><label>邮箱 / Email<input name="email" type="email" autocomplete="username" required></label><label>密码 / Password<input name="password" type="password" autocomplete="current-password" required></label><button class="primary">登录并开始采集 / Sign in</button></form><p>${button('重新发送验证邮件','resend')}</p><p class="auth-hint">首次使用请先注册并验证邮箱。未验证账号不能开始采集。</p>`)}${panel(`<h2>注册 / Create account</h2><form data-form="register" class="form-grid"><label class="wide">邮箱 / Email<input name="email" type="email" autocomplete="email" required></label><label class="wide">密码 / Password<input name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><label>国籍 / Nationality<input name="nationality" required maxlength="100"></label><label>母语 / First language<input name="native_language" required maxlength="100"></label><label>汉语等级 / Level<select name="chinese_level">${levels(1,false)}</select></label><label class="check wide"><input type="checkbox" name="consent" required><span>我已阅读录音用途说明，同意将录音及匿名背景用于本项目的发音研究与后续标注。/ I agree to the recording use described below.</span></label><p class="muted wide">本机联调仅使用测试账号。正式采集前需采用项目确认的隐私协议，明确保存期限、访问范围和撤回渠道。</p><button class="primary wide">注册并验证邮箱 / Register</button></form>`)}</div><div id="verification" style="margin-top:20px"></div>`
}

function student() {
  const q = state.question;
  return `<div class="toolbar row space"><span>Student · ${e(state.student.anonymous_id)}</span>${button('退出学生账号','logout-student')}<label>跟读等级 / Level<select id="student-level">${levels(state.student.chinese_level??1,false)}</select></label>${button('获取下一题 / Next','question','primary')}</div><div class="student-grid">${panel(`<h2>跟读练习 / Read aloud</h2><p class="muted">读出下面的内容，结束后试听。每次重录都会独立保留。</p><div class="reading">${q?reading(q):'<span class="muted">点击“获取下一题”开始 / Choose a question to begin</span>'}</div><div class="center"><button class="record-button" data-action="record" ${!q?'disabled':''}>开始录音 / Record</button><p id="record-state" role="status" class="muted">准备就绪 / Ready</p></div><audio id="playback" controls ${state.preview?'':'hidden'} src="${state.preview??''}"></audio><p class="muted">请先试听确认，再上传。没有麦克风时，可以选择自己的已授权录音。</p><label>选择录音文件 / Audio file<input id="audio-file" type="file" accept="audio/*" ${!q?'disabled':''}></label>`)}${panel(`<h2>上传与保存 / Upload</h2><p>录音先保存在当前浏览器，确认上传后进入补传队列。</p><p class="muted">断网后保留待上传录音；重新联网且登录同一账号时自动重试。请勿清除浏览器数据。</p><p>${button('上传本次录音 / Upload','save-take','primary')}</p><a href="#queue">查看我的上传记录 / My uploads</a><div id="take-status" role="status"></div><p class="muted">本期仅采集音频，不向学生展示诊断或评分。</p>`)}</div>`
}

function reading(q) {
  let i = 0;
  return [...(q.display_text ?? q.text ?? '')].map(c => han.test(c) ? `<ruby>${e(c)}<rt>${e(displayPinyin(q.tokens?.[i++]?.display_py??q.tokens?.[i-1]?.py??''))}</rt></ruby>` : e(c)).join('')
}
async function queuePage() {
  const rows = (await queueStore('getAll')).filter(x => x.owner === state.student.anonymous_id);
  state.queueRows = rows;
  return panel(`<div class="row space"><h2>我的上传 / My uploads</h2>${button('重试待上传录音','retry','primary')}</div><p class="muted">记录属于当前浏览器与当前账号。服务器完整历史列表待学生组提供。</p><div class="scroll-table"><table><thead><tr><th>题目 / 时间</th><th>上传状态</th><th>服务器录音编号</th><th>操作</th></tr></thead><tbody>${rows.sort((a,b)=>b.time.localeCompare(a.time)).map((r,i)=>`<tr><td>${e(r.question)}<small>${e(new Date(r.time).toLocaleString())}</small></td><td>${e({draft:'待确认上传',queued:'等待上传',failed:'上传失败',uploaded:'已上传'}[r.status])}<small>${e(r.error??'')}</small></td><td>${e(r.receipt?.recording_id??'—')}</td><td>${r.blob?`<button data-action="local-audio" data-id="${e(r.id)}">试听 / 保存本地</button>`:''}${r.status==='draft'?`<button data-action="queue-take" data-id="${e(r.id)}">确认上传</button>`:''}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">还没有录音记录</td></tr>'}</tbody></table></div>`)
}
async function retain(blob, duration, context = {
  question: state.question,
  owner: state.student?.anonymous_id
}) {
  if (!blob.size || blob.size > 20 * 1024 * 1024) throw new Error('录音为空或超过 20 MiB');
  const q = context.question;
  if (!q || !context.owner) throw new Error('请先登录并获取题目');
  const take = {
    id: crypto.randomUUID(),
    owner: context.owner,
    question: q.id ?? q.question_id,
    practice: q.practice_session_id,
    time: new Date().toISOString(),
    duration,
    device: {
      userAgent: navigator.userAgent
    },
    blob,
    status: 'draft'
  };
  await queueStore('put', take);
  state.take = take;
  if (state.preview) URL.revokeObjectURL(state.preview);
  state.preview = URL.createObjectURL(blob);
  if (!$('#playback')) return;
  $('#playback').src = state.preview;
  $('#playback').hidden = false;
  $('#record-state').textContent = '已保存在本机，请试听后上传 / Saved locally';
}
async function record() {
  if (state.recorder?.state === 'recording') {
    state.finalizing = true;
    state.recorder.stop();
    return
  }
  if (mediaBusy()) throw new Error('正在准备或保存录音，请稍候');
  if (!state.question || !state.student) throw new Error('请先登录并获取题目');
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('当前浏览器不支持录音，请使用 HTTPS 或 localhost，并允许麦克风');
  const context = {
    question: structuredClone(state.question),
    owner: state.student.anonymous_id
  };
  state.recordingPending = true;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: true
    });
    state.stream = stream;
    const type = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(t => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, type ? {
      mimeType: type
    } : {});
    state.recorder = rec;
    const chunks = [],
      started = Date.now();
    let failed = false;
    const release = () => {
      clearInterval(state.timer);
      stream.getTracks().forEach(t => t.stop());
    };
    rec.ondataavailable = x => {
      if (x.data.size) chunks.push(x.data)
    };
    rec.onstop = async () => {
      state.finalizing = true;
      release();
      const btn = $('[data-action="record"]');
      if (btn) {
        btn.textContent = '再次录音 / Record again';
        btn.classList.remove('recording')
      }
      try {
        if (!failed) await retain(new Blob(chunks, {
          type: rec.mimeType
        }), Date.now() - started, context)
      } catch (err) {
        failure(err)
      } finally {
        state.finalizing = false;
        state.recorder = null;
        state.stream = null;
      }
    };
    rec.onerror = () => {
      failed = true;
      release();
      toast('录音设备发生错误，请重新录音；未上传不完整音频')
    };
    rec.start(1000);
    $('[data-action="record"]').textContent = '结束录音 / Stop';
    $('[data-action="record"]').classList.add('recording');
    state.timer = setInterval(() => {
      const sec = Math.round((Date.now() - started) / 1000);
      $('#record-state').textContent = `正在录音 ${sec}s / Recording`;
      if (sec >= 120 && rec.state === 'recording') {
        state.finalizing = true;
        rec.stop()
      }
    }, 500);
  } catch (err) {
    stream?.getTracks().forEach(t => t.stop());
    throw new Error(err.name === 'NotAllowedError' ? '麦克风权限未开启。允许后重试，或选择已授权录音文件。' : err.message)
  } finally {
    state.recordingPending = false
  }
}
async function flush() {
  if (state.uploading || !state.student || !navigator.onLine) return;
  state.uploading = true;
  let changed=false;
  try {
    const rows = await queueStore('getAll');
    for (const take of rows.filter(x => x.owner === state.student.anonymous_id && ['queued', 'failed'].includes(x.status))) {
      try {
        const r = assertReceipt(await json('/gateway/student/api/recordings', {
          method: 'POST',
          body: uploadForm(take)
        }));
        take.receipt = r;
        take.status = 'uploaded';
        take.blob = null;
        take.error = '';
      } catch (err) {
        take.status = 'failed';
        take.error = err.message;
      }
      await queueStore('put', take);
      changed=true;
    }
  } finally {
    state.uploading = false
  }
  if (changed && state.page === 'queue') await render();
}
async function verification(result) {
  let html = `<p>${e(result.message??'请求已提交，请检查邮箱')}</p>`;
  if (result.dev_verify_url) {
    const u = new URL(result.dev_verify_url);
    const token = new URLSearchParams(u.hash.slice(1)).get('verify');
    if (token) {
      state.verifyToken = token;
      html += '<p class="notice">仅本机开发：邮件服务未配置，使用测试验证流程。</p>' + button('完成本机测试邮箱验证', 'verify', 'primary')
    }
  }
  $('#verification').innerHTML = panel(html)
}
async function submit(form) {
  if($('#dialog-error'))$('#dialog-error').hidden=true;
  const data = Object.fromEntries(new FormData(form)),
    name = form.dataset.form;
  if (name === 'admin-login') {
    state.admin = await api.login(data.token);
    form.reset();
    await render()
  }
  if (name === 'student-login') {
    await json('/gateway/student/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(data)
    });
    form.reset();
    await studentIdentity();
    state.page = 'student';
    location.hash = 'student';
    await render();
    await flush()
  }
  if (name === 'register') {
    data.chinese_level = Number(data.chinese_level);
    data.consent = data.consent === 'on';
    const result = await json('/gateway/student/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(data)
    });
    form.reset();
    await verification(result)
  }
  if (name === 'filter') {
    state.filter = Object.fromEntries(Object.entries(data).filter(([, v]) => v !== ''));
    state.offset = 0;
    await render()
  }
  if (name === 'note') {
    const row = state.selected.row;
    await adminJson('recordings/' + encodeURIComponent(row.recording_id), {
      method: 'PUT',
      body: {
        expected_version: row.version,
        note: data.note
      }
    });
    $('#detail').close();
    toast('核查备注已保存');
    await render()
  }
  if (name === 'entity') {
    const {
      kind,
      row
    } = state.selected;
    let value;
    if (kind === 'speakers') {
      value = {
        nationality: data.nationality,
        language: data.language,
        level: Number(data.level)
      };
      if (!row) value.speaker_id = data.id;
    } else {
      const chars = [...data.text].filter(c => han.test(c)),
        py = data.pinyin.trim().split(/\s+/);
      if (chars.length !== py.length) throw new Error('拼音数量必须与汉字数量一致，标点不计');
      value = {
        question_id: data.id,
        level: Number(data.level),
        display_text: data.text,
        tokens: chars.map((c, i) => ({
          c,
          py: py[i]
        })),
        status: row?.status ?? 'draft',
        source: row?.source ?? 'manual',
        grammar: row?.grammar ?? [],
        question_version: row?.question_version ?? null,
        target_recordings: data.target === '' ? null : Number(data.target)
      };
    }
    const body = row ? (kind === 'questions' ? {
      expected_version: row.version,
      question: value
    } : {
      expected_version: row.version,
      ...value
    }) : value;
    await adminJson(kind + (row ? '/' + encodeURIComponent(data.id) : ''), {
      method: row ? 'PUT' : 'POST',
      body
    });
    $('#detail').close();
    toast('已保存');
    await render();
  }
}
async function action(action, el) {
  if (action === 'close') {
    $('#detail').close();
    return
  }
  if (action === 'refresh') return render();
  if (action === 'login') {
    state.page = 'overview';
    location.hash = 'overview';
    return render()
  }
  if (action === 'logout-admin') {
    await api.request('/api/session', {
      method: 'DELETE'
    });
    state.admin = null;
    return render()
  }
  if (action === 'logout-student') {
    if (mediaBusy() || state.uploading) throw new Error('请先结束录音或等待上传完成');
    await json('/gateway/student/api/auth/logout', {
      method: 'POST'
    });
    state.student = null;
    state.question = null;
    state.take = null;
    return render()
  }
  if (action === 'prev' || action === 'next') {
    state.offset = Math.max(0, state.offset + (action === 'next' ? 20 : -20));
    return render()
  }
  if (action === 'clear-filter') {
    state.filter = {};
    state.offset = 0;
    return render()
  }
  if (action === 'overview-filter') {
    state.filter.level = $('#overview-level').value;
    return render()
  }
  if (action === 'export') {
    const blob = await api.exportData(state.filter.level || undefined);
    download(blob, 'management-export.zip');
    toast('数据包已导出');
    return
  }
  if (action === 'detail') return showDetail(Number(el.dataset.index));
  if (action === 'create') {
    state.selected = {
      kind: state.page,
      row: null
    };
    return modal(editor(state.page, null))
  }
  if (action === 'edit') return modal(editor(state.selected.kind, state.selected.row));
  if (action === 'versions') {
    const {
      kind,
      row
    } = state.selected;
    const r = await adminJson(kind + '/' + encodeURIComponent(row.recording_id ?? row.question_id ?? row.speaker_id) + '/history');
    $('#versions').innerHTML = `<h3>历史版本</h3>${r.items.map(x=>`<details><summary>v${x.version} · ${e(x.created_at)} ${x.deleted?'已删除':''}</summary><pre>${e(JSON.stringify(x,null,2))}</pre></details>`).join('')}`;
    return
  }
  if (['delete', 'restore'].includes(action)) {
    const {
      kind,
      row
    } = state.selected;
    if (action === 'delete' && !confirm('确认删除这条记录？删除后可恢复，关联关系不允许时会拒绝操作。')) return;
    await adminJson(kind + '/' + encodeURIComponent(row.recording_id ?? row.question_id ?? row.speaker_id) + (action === 'restore' ? '/restore' : ''), {
      method: action === 'delete' ? 'DELETE' : 'POST',
      body: {
        expected_version: row.version
      }
    });
    $('#detail').close();
    toast('操作已保存');
    return render()
  }
  if (action === 'undo') {
    await adminJson('actions/' + el.dataset.id + '/undo', {
      method: 'POST'
    });
    toast('已撤销');
    return render()
  }
  if (action === 'prop-filter') {
    state.filter.level = $('#prop-level').value;
    state.offset = 0;
    return render()
  }
  if (action === 'pipeline') {
    const step = el.dataset.step,
      level = Number($('#prop-level').value);
    if (step === 'publish' && !confirm('确认发布当前等级题库？系统将先执行上游质量门禁。')) return;
    const r = await json('/gateway/proposition/api/pipeline/' + step + (step === 'publish' ? '' : '?level=' + level), {
      method: 'POST',
      ...(step === 'publish' ? {
        body: JSON.stringify({
          level
        })
      } : {})
    });
    $('#pipeline-result').innerHTML = `<div class="notice">${e(r.message??(r.verdict==='pass'?'检查通过':'检查未通过，请查看具体缺口'))}</div><details open><summary>运行报告与缺口</summary><pre>${e(JSON.stringify(r,null,2))}</pre></details>`;
    return
  }
  if (action === 'draw') {
    const r = await json('/gateway/proposition/api/questions/recommend?level=' + ($('#prop-level').value) + '&n=1');
    return modal(`<h2>已发布题目抽取预览</h2><pre>${e(JSON.stringify(r,null,2))}</pre>`)
  }
  if (action === 'bank-export') return download(new Blob([JSON.stringify(state.propRows, null, 2)], {
    type: 'application/json'
  }), 'question-bank.json');
  if (action === 'question') {
    if (mediaBusy()) throw new Error('请先停止并保存当前录音');
    state.questionPending=true;
    try {
      const q = await json('/gateway/student/api/questions/next?level=' + $('#student-level').value);
      if (!q.practice_session_id) throw new Error('上游未返回练习编号，暂不能录音');
      state.question = q; state.take = null;
      if (state.preview) URL.revokeObjectURL(state.preview);
      state.preview = null;
      return await render();
    } finally {state.questionPending=false;}
  }
  if (action === 'record') return record();
  if (action === 'save-take') {
    if (!state.take) throw new Error('请先录音或选择音频文件');
    const saved = (await queueStore('getAll')).find(x => x.id === state.take.id);
    if (saved?.status === 'uploaded') {
      toast('这条录音已经上传');
      return
    }
    state.take.status = 'queued';
    await queueStore('put', state.take);
    await flush();
    if($('#take-status'))$('#take-status').textContent = '已保存到上传队列，请在“我的上传”查看服务器回执。';
    return
  }
  if (action === 'retry') return flush();
  if (action === 'queue-take') {
    const take = state.queueRows.find(x => x.id === el.dataset.id);
    take.status = 'queued';
    await queueStore('put', take);
    return flush()
  }
  if (action === 'local-audio') {
    const take = state.queueRows.find(x => x.id === el.dataset.id);
    const url = URL.createObjectURL(take.blob);
    modal(`<h2>本机录音</h2><audio controls src="${url}"></audio>`);
    $('#detail').addEventListener('close', () => URL.revokeObjectURL(url), {
      once: true
    });
    download(take.blob, 'recording-' + take.id + (take.blob.type.includes('mp4') ? '.mp4' : '.webm'));
    return
  }
  if (action === 'resend') {
    const f = $('[data-form="student-login"]');
    if (!f.reportValidity()) return;
    const r = await json('/gateway/student/api/auth/resend-verification', {
      method: 'POST',
      body: JSON.stringify(Object.fromEntries(new FormData(f)))
    });
    return verification(r)
  }
  if (action === 'verify') {
    await json('/gateway/student/api/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({
        token: state.verifyToken
      })
    });
    state.verifyToken = null;
    $('#verification').textContent = '验证完成，请登录 / Verified. Please sign in.';
    return
  }
}
document.addEventListener('submit', async ev => {
  const form = ev.target;
  if (!form.dataset.form) return;
  ev.preventDefault();
  const submitter = ev.submitter;
  if (submitter?.disabled) return;
  if (submitter) submitter.disabled = true;
  try {
    await submit(form)
  } catch (err) {
    failure(err)
  } finally {
    if (submitter) submitter.disabled = false
  }
});
document.addEventListener('click', async ev => {
  const el = ev.target.closest('[data-action]');
  if (!el || el.disabled) return;
  el.disabled = true;
  try {
    await action(el.dataset.action, el)
  } catch (err) {
    failure(err);
    if (el.dataset.action === 'pipeline' && $('#pipeline-result')) $('#pipeline-result').innerHTML = `<div class="error">${e(err.message)}</div>`
  } finally {
    el.disabled = false
  }
});
document.addEventListener('change', async ev => {
  if (ev.target.id === 'audio-file' && ev.target.files[0]) try {
    if (mediaBusy()) throw new Error('请先停止并保存当前录音');
    await retain(ev.target.files[0], 0)
  } catch (err) {
    failure(err)
  }
});
window.addEventListener('hashchange', navigate);
window.addEventListener('online', () => flush().catch(failure));
window.addEventListener('beforeunload', ev => {
  if (mediaBusy()) {
    ev.preventDefault();
    ev.returnValue = '';
  }
});

function setTheme(value) {
  const theme = value === 'senior' ? 'senior' : 'ours';
  document.body.dataset.theme = theme;
  $('#theme-choice').value = theme;
  const u = new URL(location.href);
  if (theme === 'senior') u.searchParams.set('theme', theme);
  else u.searchParams.delete('theme');
  window.history.replaceState(null, '', u);
}
$('#theme-choice').addEventListener('change', ev => setTheme(ev.target.value));
setTheme(new URL(location.href).searchParams.get('theme'));
async function boot() {
  try {
    state.config = await json('/api/portal/config');
    $('#connection').textContent = '管理服务已连接';
    try {
      state.admin = await json('/api/me')
    } catch {}
    const emailToken = new URLSearchParams(location.hash.slice(1)).get('verify');
    if (emailToken) {
      state.verifyToken = emailToken;
      window.history.replaceState(null, '', location.pathname + location.search + '#student')
    }
    await navigate();
    if (emailToken && $('#verification')) $('#verification').innerHTML = panel('<h2>邮箱验证 / Verify email</h2><p>点击下方按钮完成验证，然后登录开始采集。</p>' + button('验证邮箱 / Verify', 'verify', 'primary'));
    setInterval(() => flush().catch(() => {}), 30000);
  } catch (err) {
    $('#connection').textContent = '服务连接失败';
    $('#content').innerHTML = panel(`<p class="error">${e(err.message)}</p>${button('重试','refresh')}`)
  }
}
boot();
