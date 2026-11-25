"""Management-owned change feed receiver; upstream agreement is still required."""
import hashlib
import json
from typing import Literal

from pydantic import Field
from contracts import Input, ID, Version, Speaker, Question, Recording, ContractError
from store import Conflict, Missing, encoded, now


class SyncEvent(Input):
    event_id: ID
    kind: Literal['speakers', 'questions', 'recordings']
    entity_id: ID
    source_version: Version = Field(le=9223372036854775807)
    operation: Literal['upsert', 'delete', 'restore'] = 'upsert'
    data: dict | None = None


class SyncBatch(Input):
    schema_version: Literal[1] = 1
    source_id: ID
    batch_id: ID
    cursor: str | None = Field(default=None, max_length=512)
    next_cursor: str = Field(min_length=1, max_length=512)
    events: list[SyncEvent] = Field(min_length=1, max_length=100)


SCHEMA = '''
CREATE TABLE IF NOT EXISTS sync_sources(source_id TEXT PRIMARY KEY, cursor TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_entities(kind TEXT, entity_id TEXT, source_id TEXT NOT NULL,
  source_version INTEGER NOT NULL, fingerprint TEXT NOT NULL, local_version INTEGER NOT NULL, PRIMARY KEY(kind,entity_id));
CREATE TABLE IF NOT EXISTS sync_events(source_id TEXT, event_id TEXT, fingerprint TEXT NOT NULL, PRIMARY KEY(source_id,event_id));
CREATE TABLE IF NOT EXISTS sync_batches(source_id TEXT, batch_id TEXT, fingerprint TEXT NOT NULL,
  receipt TEXT NOT NULL, PRIMARY KEY(source_id,batch_id));
'''


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def apply_batch(store, db, batch, actor):
    fingerprint = digest(batch.model_dump(mode='json'))
    saved = db.execute('SELECT * FROM sync_batches WHERE source_id=? AND batch_id=?',
                       (batch.source_id, batch.batch_id)).fetchone()
    if saved:
        if saved['fingerprint'] != fingerprint:
            raise Conflict('同步批次编号已用于不同内容')
        return {**json.loads(saved['receipt']), 'batch_replayed': True}
    source = db.execute('SELECT cursor FROM sync_sources WHERE source_id=?', (batch.source_id,)).fetchone()
    if (source['cursor'] if source else None) != batch.cursor:
        raise Conflict('同步游标已改变；请读取接收端状态后重试')
    if batch.cursor == batch.next_cursor:
        raise ContractError('非空批次必须推进游标')
    if len({e.event_id for e in batch.events}) != len(batch.events):
        raise ContractError('批次内事件编号重复')
    results = [apply_event(store, db, batch.source_id, event, actor) for event in batch.events]
    db.execute('INSERT INTO sync_sources VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET '
               'cursor=excluded.cursor,updated_at=excluded.updated_at', (batch.source_id, batch.next_cursor, now()))
    receipt = {'source_id': batch.source_id, 'batch_id': batch.batch_id, 'cursor': batch.next_cursor,
               'payload_sha256': fingerprint, 'batch_replayed': False, 'events': results}
    db.execute('INSERT INTO sync_batches VALUES(?,?,?,?)',
               (batch.source_id, batch.batch_id, fingerprint, encoded(receipt)))
    return receipt


def apply_event(store, db, source_id, event, actor):
    fingerprint = digest(event.model_dump(mode='json'))
    previous = db.execute('SELECT fingerprint FROM sync_events WHERE source_id=? AND event_id=?',
                          (source_id, event.event_id)).fetchone()
    if previous:
        if previous['fingerprint'] != fingerprint:
            raise Conflict('同步事件编号已用于不同内容')
        return {'event_id': event.event_id, 'duplicate': True}
    owned = db.execute('SELECT * FROM sync_entities WHERE kind=? AND entity_id=?',
                       (event.kind, event.entity_id)).fetchone()
    content_hash = digest(event.model_dump(mode='json', exclude={'event_id'}))
    if owned:
        if owned['source_id'] != source_id:
            raise Conflict('该记录属于其他同步来源')
        if event.source_version < owned['source_version']:
            raise Conflict('拒绝旧来源版本覆盖新数据')
        if event.source_version == owned['source_version']:
            if content_hash != owned['fingerprint']:
                raise Conflict('同一来源版本包含不同内容')
            db.execute('INSERT INTO sync_events VALUES(?,?,?)', (source_id, event.event_id, fingerprint))
            return {'event_id': event.event_id, 'duplicate': True}
    try:
        old = store.get(db, event.kind, event.entity_id)
    except Missing:
        old = None
    if old and not owned:
        raise Conflict('编号已存在但未绑定该来源；需要人工核对，不能自动接管')
    if event.operation == 'upsert':
        model = {'speakers': Speaker, 'questions': Question, 'recordings': Recording}[event.kind]
        try:
            body = model.model_validate(event.data)
        except ValueError:
            raise ContractError('同步实体字段不符合管理端契约') from None
        data = body.model_dump(mode='json') if event.kind == 'speakers' else body.normalized()
        if (event.kind == 'recordings' and data['data_source'] != 'synthetic_fixture'
                and not data['question_snapshot'].get('question_version')):
            raise ContractError('真实来源录音必须包含录音时的题目版本')
        key = {'speakers': 'speaker_id', 'questions': 'question_id', 'recordings': 'recording_id'}[event.kind]
        if data[key] != event.entity_id:
            raise ContractError('事件实体编号与内容不一致')
        if old is None:
            result = store.create(db, event.kind, data, actor)
        else:
            if old['deleted']:
                raise Conflict('管理记录已删除；更新不能自动恢复')
            current = {k: v for k, v in old.items() if k not in ('version', 'deleted')}
            if event.kind == 'recordings':
                mutable = {'diagnosis', 'diagnosis_available', 'note'}
                if {k: v for k, v in current.items() if k not in mutable} != {k: v for k, v in data.items() if k not in mutable}:
                    raise Conflict('录音身份、音频及题目快照不可被同步改写')
                fields = {k: data[k] for k in ('diagnosis', 'diagnosis_available')}
                last_body = json.loads(db.execute('SELECT body FROM history WHERE kind=? AND entity_id=? AND version=?',
                    (event.kind, event.entity_id, owned['local_version'])).fetchone()[0])
                if any(current[k] != last_body[k] for k in fields):
                    raise Conflict('诊断已有管理端修改；需要人工确认冲突')
            else:
                if old['version'] != owned['local_version']:
                    raise Conflict('管理端已修改该实体；需要人工确认冲突')
                fields = data
            result = ({'item': old, 'duplicate': True} if all(current[k] == v for k, v in fields.items())
                      else store.update(db, event.kind, event.entity_id, old['version'], fields, actor, 'sync'))
    else:
        if event.data is not None or old is None:
            raise ContractError('删除/恢复事件必须引用已同步实体，且不附 data')
        if old['version'] != owned['local_version']:
            raise Conflict('管理端已修改该实体；删除或恢复需要人工确认')
        deleted = event.operation == 'delete'
        result = ({'item': old, 'duplicate': True} if old['deleted'] == deleted else
                  store.set_deleted(db, event.kind, event.entity_id, old['version'], deleted, actor))
    db.execute('INSERT INTO sync_entities VALUES(?,?,?,?,?,?) ON CONFLICT(kind,entity_id) DO UPDATE SET '
               'source_version=excluded.source_version,fingerprint=excluded.fingerprint,local_version=excluded.local_version',
               (event.kind, event.entity_id, source_id, event.source_version, content_hash, result['item']['version']))
    db.execute('INSERT INTO sync_events VALUES(?,?,?)', (source_id, event.event_id, fingerprint))
    return {'event_id': event.event_id, 'duplicate': result['duplicate'], 'version': result['item']['version']}
