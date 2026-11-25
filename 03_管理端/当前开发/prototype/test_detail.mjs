import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const code=readFileSync(new URL('./static/app.js',import.meta.url),'utf8').split("document.querySelectorAll('nav button').forEach(b=>b.onclick")[0];
const elements=new Map();
const context=vm.createContext({document:{querySelector:s=>{if(!elements.has(s))elements.set(s,{innerHTML:'',value:'',open:false,showModal(){this.open=true},close(){this.open=false}});return elements.get(s)},querySelectorAll:()=>[]},setTimeout,fetch:()=>{throw Error('unexpected fetch')}});
vm.runInContext(code,context);
const label=d=>vm.runInContext(`diagnosisLabel(${JSON.stringify(d)})`,context);
for(const [status,expected] of [['pending','等待检测'],['processing','检测中'],['failed','检测失败'],['unknown','诊断状态未知']])test(status,()=>assert.equal(label({status,errors:[]}),expected));
test('missing result differs from no errors',()=>{assert.equal(label(null),'暂无诊断结果');assert.equal(label({status:'completed',errors:[]}), '本次模型未检出偏误');assert.equal(label({status:'completed'}),'诊断数据不完整')});
function detail(extra={}){
 const record={id:'r1',speaker_id:'s1',question_id:'q1',attempt:1,recorded_at:'2026-11-23T00:00:00Z',device:'demo',audio:'demo.wav',note:'',text:'你好',pinyin:['nǐ','hǎo'],diagnosis:{status:'completed',errors:[]},...extra};
 vm.runInContext(`state={recordings:[${JSON.stringify(record)}]};showDetail('r1')`,context);
 return elements.get('#detailContent').innerHTML;
}
const snapshot={display_text:'你，好。',tokens:[{c:'你',display_py:'nǐ',display_start:0},{c:'好',display_py:'hǎo',display_start:2}]};
test('new API missing marker',()=>assert.match(detail({diagnosis_available:false,diagnosis:{status:'pending'}}),/暂无诊断结果/));
test('snapshot instead of current text',()=>{const html=detail({text:'错误当前题文',question_snapshot:snapshot});assert.match(html,/<h2>你，好。<\/h2>/);assert.doesNotMatch(html,/错误当前题文/)});
test('punctuation and first middle last insertions',()=>{const html=detail({question_snapshot:snapshot,diagnosis:{status:'completed',errors:[0,1,2].map((boundary_index)=>({type:'insertion',boundary_index,actual:`extra${boundary_index}`}))}});assert.ok(html.indexOf('extra0')<html.indexOf('<b>你</b>'));assert.ok(html.indexOf('extra1')<html.indexOf('<b>好</b>'));assert.ok(html.indexOf('extra2')>html.indexOf('<b>好</b>'));assert.ok(html.indexOf('extra2')<html.indexOf('<span>。</span>'))});
test('multiple errors on same character',()=>{const html=detail({question_snapshot:snapshot,diagnosis:{status:'completed',errors:[{type:'tone',char_index:1,expected:3,actual:2},{type:'substitution',char_index:1,expected:'hao',actual:'ao'}]}});assert.match(html,/声调偏误<br>预期 3/);assert.match(html,/声韵母误读<br>预期 hao/)});
test('pending errors hidden but audio kept',()=>{const html=detail({diagnosis:{status:'pending',errors:[{type:'tone',char_index:0,expected:'bad',actual:'bad'}]}});assert.doesNotMatch(html,/预期 bad/);assert.match(html,/<audio/)});
test('invalid position has fallback',()=>{assert.match(detail({question_snapshot:{...snapshot,tokens:[null]}}),/缺少有效逐字位置数据/)});
test('legacy first week compatible',()=>assert.match(detail(),/<b>你<\/b>/));
test('untrusted text escaped',()=>{const html=detail({note:'<script>bad()</script>',diagnosis:{status:'completed',errors:[{type:'insertion',boundary_index:0,actual:'<img src=x>'}]}});assert.doesNotMatch(html,/<script>|<img src=x>/);assert.match(html,/&lt;img src=x&gt;/)});
