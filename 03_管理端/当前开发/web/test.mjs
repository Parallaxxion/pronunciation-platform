import test from 'node:test';
import assert from 'node:assert/strict';
import {
  uploadForm,
  assertReceipt
} from './queue.mjs';
import {
  displayPinyin
} from './pinyin.mjs';
import {levelOptions} from './options.mjs';
test('新增表单必须包含可提交的九个等级，筛选额外包含全部等级',()=>{
 const create=levelOptions(1,false);
 assert.equal((create.match(/<option /g)||[]).length,9);
 assert.ok(create.includes('<option value="1" selected>1 级</option>'));
 assert.ok(create.includes('<option value="9">9 级</option>'));
 assert.equal((levelOptions().match(/<option /g)||[]).length,10);
});
test('展示带调拼音，同时兼容轻声、ü、iu、ui 和已有带调值', () => {
  for (const [input, expected] of Object.entries({
      wo3: 'wǒ',
      ma5: 'ma',
      nv3: 'nǚ',
      'lu:4': 'lǜ',
      liu2: 'liú',
      gui4: 'guì',
      ou3: 'ǒu',
      xue2: 'xué',
      'nǐ': 'nǐ'
    })) assert.equal(displayPinyin(input), expected);
});
test('上传重试保持同一客户端录音编号和练习编号', () => {
  const take = {
    id: 'take-1',
    practice: 'practice-1',
    time: '2026-11-25T10:00:00Z',
    duration: 1200,
    device: {
      os: 'test'
    },
    blob: new Blob(['fixture'], {
      type: 'audio/webm'
    })
  };
  for (let i = 0; i < 2; i++) {
    const form = uploadForm(take);
    assert.equal(form.get('client_recording_id'), 'take-1');
    assert.equal(form.get('practice_session_id'), 'practice-1');
    assert.equal(form.get('audio').type, 'audio/webm');
    assert.equal(form.get('recorded_at'), take.time);
  }
});
test('没有持久化上传回执时不能释放本机录音', () => {
  for (const r of [{}, {
      recording_id: 'R1'
    }, {
      status: 'uploaded'
    }, {
      recording_id: 'R1',
      status: 'failed'
    }]) assert.throws(() => assertReceipt(r));
  assert.equal(assertReceipt({
    recording_id: 'R1',
    status: 'uploaded',
    duplicate: true
  }).recording_id, 'R1')
});
