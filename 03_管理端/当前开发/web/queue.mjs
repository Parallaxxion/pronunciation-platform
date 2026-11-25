// Durable, account-scoped outbox; a successful server receipt is required before releasing audio.
export function openQueue() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open('shengcai-outbox-v1', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('takes', {
      keyPath: 'id'
    });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
export async function queueStore(method, value) {
  const db = await openQueue();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('takes', method === 'getAll' ? 'readonly' : 'readwrite');
    const r = tx.objectStore('takes')[method](value);
    let result;
    r.onsuccess = () => {
      result = r.result
    };
    tx.oncomplete = () => {
      db.close();
      resolve(result)
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error)
    };
    tx.onabort = () => {
      db.close();
      reject(tx.error)
    };
  });
}
export function uploadForm(take) {
  const form = new FormData();
  form.append('audio', take.blob, 'recording.' + (take.blob.type.includes('wav') ? 'wav' : take.blob.type.includes('mp4') ? 'mp4' : 'webm'));
  form.append('practice_session_id', take.practice);
  form.append('client_recording_id', take.id);
  form.append('recorded_at', take.time);
  form.append('duration_ms', take.duration);
  form.append('device_info', JSON.stringify(take.device));
  return form;
}
export function assertReceipt(receipt) {
  if (!receipt?.recording_id || receipt.status !== 'uploaded') throw new Error('服务器没有返回上传成功凭据，录音继续保存在本机');
  return receipt;
}
