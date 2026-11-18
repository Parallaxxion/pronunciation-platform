'use strict';
function node(tag, text, cls) { const el=document.createElement(tag); if(text!==undefined)el.textContent=text; if(cls)el.className=cls;return el; }
function renderDiagnosis(container, question, diagnosis) {
 container.replaceChildren();
 if(diagnosis.status!=='completed'){container.append(node('p',({pending:'诊断等待中',processing:'诊断处理中',failed:'诊断失败'})[diagnosis.status]||'未知诊断状态'));return;}
 const names={tone:'声调偏误',substitution:'声韵母误读',omission:'漏读'};
 const errors=diagnosis.errors;
 if(!Array.isArray(errors))throw Error('已完成诊断缺少errors');
 for(let i=0;i<=question.tokens.length;i++){
  errors.filter(e=>e.type==='insertion'&&e.boundary_index===i).forEach(e=>container.append(node('span','增读 '+e.actual,'insertion')));
  if(i===question.tokens.length)break;
  const token=question.tokens[i],found=errors.filter(e=>e.char_index===i);
  const box=node('div',undefined,'char '+(found[0]?.type||''));
  box.append(node('small',token.display_py||token.py),node('b',token.c));
  found.forEach(e=>box.append(node('small',(names[e.type]||e.type)+' '+(e.actual||'未读出'))));container.append(box);
 }
}
fetch('preview-data.json').then(r=>{if(!r.ok)throw Error('样例读取失败');return r.json();}).then(data=>{
 document.getElementById('questionText').textContent=data.question.display_text;
 renderDiagnosis(document.getElementById('diagnosis'),data.question,data.diagnosis);
 document.getElementById('status').textContent='构造样例已加载；使用tokens索引，原题文中的标点不占偏误位置。';
}).catch(e=>{document.getElementById('status').textContent=e.message;});
