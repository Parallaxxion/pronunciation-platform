/* 第一周样式兼容组件；接口齐全后接入统一 Web，不改变现有演示入口。
 * 详情展示责任：周佳怡。统计与导出责任：王阳。本次为自动化协助补齐，待复核。
 */
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const isHan = c => /[\u3400-\u9fff\u{20000}-\u{323af}]/u.test(c);
const names = {tone:'声调偏误',substitution:'声韵母误读',omission:'漏读',insertion:'增读'};

export function detailView(record) {
  const question = record.question_snapshot ?? {display_text:record.text, tokens:record.pinyin?.map((py,i)=>({c:[...(record.text??'')][i],py}))};
  const text = [...(question.display_text ?? '')], tokens = question.tokens ?? [];
  const diagnosis = record.diagnosis;
  const available = record.diagnosis_available ?? Boolean(diagnosis);
  const state = !available ? 'unavailable' : diagnosis?.status === 'done' ? 'completed' : diagnosis?.status;
  let message = {unavailable:'暂无诊断结果',pending:'等待检测',processing:'正在检测',failed:'检测失败，请稍后重试'}[state];
  const errors = state === 'completed' && Array.isArray(diagnosis?.errors) ? diagnosis.errors : [];
  let invalid = tokens.length !== text.filter(isHan).length || tokens.some((t,i)=>t.c !== text.filter(isHan)[i]);
  invalid ||= state === 'completed' && !Array.isArray(diagnosis?.errors);
  invalid ||= errors.some(e => !e || !Object.hasOwn(names,e.type) ||
    !Number.isInteger(e[e.type === 'insertion' ? 'boundary_index' : 'char_index']) ||
    e[e.type === 'insertion' ? 'boundary_index' : 'char_index'] < 0 ||
    e[e.type === 'insertion' ? 'boundary_index' : 'char_index'] >= tokens.length+(e.type === 'insertion'?1:0));
  if (!message) message = state === 'completed' ? (errors.length ? `检测到 ${errors.length} 处偏误` : '本次模型未检出偏误') : '诊断状态未知';
  if (invalid) message = '标注位置或题目快照不一致，请核查数据';
  const safeErrors = invalid ? [] : errors;
  let index=0, html='';
  const inserts = boundary => safeErrors.filter(e=>e.type==='insertion' && e.boundary_index===boundary)
    .map(e=>`<span class="insertion">增读<br>${escapeHtml(e.actual)}</span>`).join('');
  for (const char of text) {
    if (!isHan(char)) {html += `<span class="punctuation">${escapeHtml(char)}</span>`; continue;}
    html += inserts(index);
    const found = safeErrors.filter(e=>e.type!=='insertion' && e.char_index===index);
    html += `<div class="char ${found[0]?.type??''}"><small>${escapeHtml(tokens[index]?.display_py??tokens[index]?.py)}</small><b>${escapeHtml(char)}</b>${found.map(e=>`<small>${names[e.type]}<br>${escapeHtml(e.actual??'未读出')}</small>`).join('')}</div>`;
    index++;
  }
  html += inserts(index);
  return {state, invalid, message, html:`<p role="status">${escapeHtml(message)}</p><div class="phonetics">${html}</div>`};
}

export function statisticsView(stats, coverage=stats.coverage) {
  const metrics = [['已导入说话人', stats.known_active_speakers], ['学生注册总数', stats.registered_user_total ?? '待接通'],
    ['有效录音', stats.recording_count], ['采集总缺口', stats.total_gap ?? '目标待确认']];
  return {
    metrics:metrics.map(([label,value])=>`<div class="metric"><div class="label">${label}</div><strong>${escapeHtml(value)}</strong></div>`).join(''),
    coverage:`<div class="panel"><table><thead><tr><th>题目</th><th>录音 / 目标</th><th>独立说话人</th><th>缺口</th></tr></thead><tbody>${coverage.items.map(q=>`<tr><td>${escapeHtml(q.question_id)}</td><td>${q.recording_count} / ${q.target_recordings??'未确认'}</td><td>${q.unique_speaker_count}</td><td>${q.gap??'未确认'}</td></tr>`).join('')}</tbody></table></div>`
  };
}

export class ManagementClient {
  constructor(fetcher=(...args)=>globalThis.fetch(...args)) {this.fetcher=fetcher;}
  async request(path,{method='GET',body,token}={}) {
    const headers={};
    if (token) headers.Authorization=`Bearer ${token}`;
    if (body !== undefined) headers['Content-Type']='application/json';
    if (!['GET','HEAD'].includes(method) && path.startsWith('/api/v1/admin/')) headers['Idempotency-Key']=crypto.randomUUID();
    const response=await this.fetcher(path,{method,headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body)});
    if (!response.ok) {
      let data; try {data=await response.json();} catch {data={};}
      throw new Error(response.status===401?'登录已过期，请重新登录':response.status===403?'当前身份无此权限':data.error??data.detail??`请求失败 ${response.status}`);
    }
    return response;
  }
  async login(token) {return (await this.request('/api/session',{method:'POST',token})).json();}
  async list(kind,params={}) {
    if (!['speakers','questions','recordings'].includes(kind)) throw new Error('未知数据类型');
    return (await this.request(`/api/v1/admin/${kind}?${new URLSearchParams(params)}`)).json();
  }
  async statistics() {return (await this.request('/api/v1/admin/statistics')).json();}
  async exportData(level) {
    const response=await this.request('/api/v1/admin/export'+(level==null?'':`?level=${encodeURIComponent(level)}`));
    return response.blob();
  }
}
