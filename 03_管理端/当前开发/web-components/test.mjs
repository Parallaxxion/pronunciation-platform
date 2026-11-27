import test from 'node:test';
import assert from 'node:assert/strict';
import {detailView,statisticsView,ManagementClient} from './management.mjs';

const fixture={question_snapshot:{display_text:'我，学汉语。',tokens:[{c:'我',py:'wo3'},{c:'学',py:'xue2'},{c:'汉',py:'han4'},{c:'语',py:'yu3'}]},diagnosis_available:true};
test('详情参考读音、误读和增读使用调号，原始数据保持不变',()=>{
 const record={question_snapshot:{display_text:'我喜欢学习中文。',tokens:[
  {c:'我',py:'wo3'},{c:'喜',py:'xi3'},{c:'欢',py:'huan1'},
  {c:'学',py:'xue2'},{c:'习',py:'xi2'},{c:'中',py:'zhong1'},{c:'文',py:'wen2'}
 ]},diagnosis_available:true,diagnosis:{status:'completed',errors:[
  {type:'tone',char_index:1,expected:'xi3',actual:'xi1'},
  {type:'substitution',char_index:3,expected:'xue2',actual:'shue2'},
  {type:'omission',char_index:5,expected:'zhong1',actual:null},
  {type:'insertion',boundary_index:7,expected:null,actual:'a5'}
 ]}};
 const original=JSON.stringify(record);
 const result=detailView(record);
 assert.equal(result.invalid,false);
 for(const reading of ['wǒ','xǐ','huān','xué','xí','zhōng','wén']) {
  assert.ok(result.html.includes(`<small>${reading}</small>`),reading);
 }
 assert.ok(result.html.includes('声调偏误<br>xī'));
 assert.ok(result.html.includes('声韵母误读<br>shué'));
 assert.ok(result.html.includes('漏读<br>未读出'));
 assert.ok(result.html.includes('增读<br>a</span>'));
 assert.ok(!/\b(?:wo3|xi3|xi1|shue2|a5)\b/u.test(result.html));
 assert.equal(JSON.stringify(record),original);
});
test('详情优先使用展示拼音，并在非完成状态显示带调参考读音',()=>{
 const record={...fixture,question_snapshot:{display_text:'女。',tokens:[{c:'女',py:'nv3',display_py:'nü4'}]}};
 for(const status of ['pending','processing','failed','completed']) {
  const result=detailView({...record,diagnosis:{status,errors:[]}});
  assert.ok(result.html.includes('<small>nǜ</small>'));
  assert.ok(!result.html.includes('nǚ'));
 }
});
test('标点、多类偏误与首中尾增读',()=>{
 const result=detailView({...fixture,diagnosis:{status:'completed',errors:[
  ...[0,2,4].map(boundary_index=>({type:'insertion',boundary_index,actual:'a1'})),
  {type:'tone',char_index:1,actual:'xue3'},{type:'substitution',char_index:1,actual:'que2'},
  {type:'omission',char_index:3}]}});
 assert.equal(result.invalid,false); assert.equal((result.html.match(/class="insertion"/g)||[]).length,3);
 assert.ok(result.html.includes('，')); assert.ok(result.html.includes('。'));
 assert.ok(result.html.includes('声调偏误')); assert.ok(result.html.includes('声韵母误读'));
});
test('缺少、待处理、处理中和失败不能显示无偏误',()=>{
 for(const status of ['pending','processing','failed']) {
  const result=detailView({...fixture,diagnosis:{status,errors:[{type:'tone',char_index:0}]}});
  assert.ok(!result.html.includes('声调偏误')); assert.ok(!result.message.includes('未检出'));
 }
 assert.equal(detailView({...fixture,diagnosis_available:false}).state,'unavailable');
 assert.equal(detailView({...fixture,diagnosis:{status:'completed',errors:[]}}).message,'本次模型未检出偏误');
});
test('越界提示以及文本转义',()=>{
 assert.equal(detailView({...fixture,diagnosis:{status:'completed',errors:[{type:'tone',char_index:9}]}}).invalid,true);
 const result=detailView({...fixture,diagnosis:{status:'completed',errors:[{type:'insertion',boundary_index:0,actual:'<img onerror=x>'}]}});
 assert.ok(!result.html.includes('<img')); assert.ok(result.html.includes('&lt;img'));
});
test('旧的无标点原型可以兼容；目标未定不显示零缺口',()=>{
 assert.equal(detailView({text:'我你',pinyin:['wo3','ni3'],diagnosis:{status:'completed',errors:[]}}).invalid,false);
 const result=statisticsView({known_active_speakers:1,recording_count:2,total_gap:null}, {items:[{question_id:'Q1',recording_count:2,unique_speaker_count:1,target_recordings:null,gap:null}]});
 assert.ok(result.metrics.includes('目标待确认'));assert.ok(result.coverage.includes('未确认'));
});
test('权限错误必须显式处理',async()=>{
 const client=new ManagementClient(async()=>new Response('{}',{status:401}));
 await assert.rejects(()=>client.list('recordings'),/登录已过期/);
 await assert.rejects(()=>client.exportData(),/登录已过期/);
});
test('默认 fetch 必须保留浏览器 Window 接收者',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=function(){assert.equal(this,globalThis);return Promise.resolve(new Response('{"items":[],"total":0}'))};
 try{assert.equal((await new ManagementClient().list('recordings')).total,0)}
 finally{globalThis.fetch=original}
});
