// Self-check for api/feedback.js against an in-memory fake of the Upstash REST API. Run: node tools/test_feedback.js
const assert = require('assert');
process.env.KV_REST_API_URL = 'http://fake-redis';
process.env.KV_REST_API_TOKEN = 'tok';
process.env.FEEDBACK_ADMIN_KEY = 'correct horse battery staple';

const lists = {}, counters = {};
global.fetch = async (url, opt) => {
  assert.strictEqual(opt.headers.Authorization, 'Bearer tok');
  const [cmd, key, ...a] = JSON.parse(opt.body);
  let result = null;
  if (cmd === 'INCR') result = counters[key] = (counters[key] || 0) + 1;
  else if (cmd === 'EXPIRE') result = 1;
  else if (cmd === 'RPUSH') { (lists[key] = lists[key] || []).push(a[0]); result = lists[key].length; }
  else if (cmd === 'LTRIM') { lists[key] = lists[key].slice(a[0]); result = 'OK'; }
  else if (cmd === 'LRANGE') result = lists[key] || [];
  else if (cmd === 'DEL') { delete lists[key]; result = 1; }
  return { ok: true, json: async () => ({ result }) };
};

const handler = require('../api/feedback.js');
const call = async (method, { body, headers = {}, ip = '1.2.3.4' } = {}) => {
  const out = { status: 0, headers: {}, body: null };
  const res = { setHeader: (k, v) => { out.headers[k] = v; }, status(c) { out.status = c; return this; }, json(o) { out.body = o; return this; }, send(t) { out.body = t; return this; } };
  await handler({ method, body, headers: { 'x-forwarded-for': ip, ...headers }, socket: {} }, res);
  return out;
};
const admin = { authorization: 'Bearer ' + process.env.FEEDBACK_ADMIN_KEY };

(async () => {
  // validation
  assert.strictEqual((await call('POST', { body: { message: 'hi' } })).status, 400, 'too short is rejected');
  assert.strictEqual((await call('POST', { body: 'not json' })).status, 400, 'garbage body is rejected');
  // honeypot: reports success but stores nothing
  assert.strictEqual((await call('POST', { body: { message: 'buy pills now', website: 'http://spam' } })).status, 200);
  assert.strictEqual((lists['ericanav:feedback'] || []).length, 0, 'honeypot submission is not stored');
  // a real submission stores only id, time and message, whatever else the client sends
  const r = await call('POST', { body: { message: '  Add a dark mode, please  ', name: 'Kim', email: 'k@x.kr', contact: '010-1234', type: 'complaint' } });
  assert.strictEqual(r.status, 200);
  const row = JSON.parse(lists['ericanav:feedback'][0]);
  assert.deepStrictEqual(Object.keys(row).sort(), ['at', 'id', 'message'], 'nothing but id, time and message is kept');
  assert.strictEqual(row.message, 'Add a dark mode, please');
  assert.ok(!JSON.stringify(counters).includes('1.2.3.4'), 'raw IP never used as a key');
  // rate limit: 5 per hour per visitor, other visitors unaffected
  for (let i = 0; i < 4; i++) assert.strictEqual((await call('POST', { body: { message: 'message number ' + i } })).status, 200);
  assert.strictEqual((await call('POST', { body: { message: 'one too many' } })).status, 429, '6th submission in an hour is refused');
  assert.strictEqual((await call('POST', { body: { message: 'different visitor' }, ip: '9.9.9.9' })).status, 200);
  // length cap
  await call('POST', { body: { message: 'x'.repeat(5000) }, ip: '8.8.8.8' });
  assert.strictEqual(JSON.parse(lists['ericanav:feedback'].pop()).message.length, 2000, 'message capped at 2000');
  // admin: locked without the key, CSV with it
  assert.strictEqual((await call('GET')).status, 401);
  assert.strictEqual((await call('GET', { headers: { authorization: 'Bearer wrong' } })).status, 401);
  assert.strictEqual((await call('DELETE', { headers: { authorization: 'Bearer wrong' } })).status, 401);
  // CSV: BOM, quotes/newlines/Korean survive, spreadsheet formulas are defused
  lists['ericanav:feedback'] = [JSON.stringify({ id: 'a', at: '2026-09-25T00:00:00.000Z', message: '=HYPERLINK("http://evil")' }),
                                JSON.stringify({ id: 'b', at: '2026-09-25T00:01:00.000Z', message: '셔틀 시간이 "틀려요",\n두 줄' })];
  const g = await call('GET', { headers: admin });
  assert.strictEqual(g.status, 200);
  assert.ok(g.headers['Content-Type'].startsWith('text/csv') && /attachment/.test(g.headers['Content-Disposition']));
  assert.ok(g.body.startsWith('﻿id,received_at,message\r\n'), 'BOM + header');
  assert.ok(g.body.includes(`"'=HYPERLINK(""http://evil"")"`), 'formula defused and quotes doubled');
  assert.ok(g.body.includes('"셔틀 시간이 ""틀려요"",\n두 줄"'), 'Korean, quotes, comma and newline kept inside one cell');
  // delete all
  assert.strictEqual((await call('DELETE', { headers: admin })).status, 200);
  assert.strictEqual((await call('GET', { headers: admin })).body, '﻿id,received_at,message\r\n');
  // other methods; unconfigured store and unconfigured admin key
  assert.strictEqual((await call('PUT')).status, 405);
  delete process.env.FEEDBACK_ADMIN_KEY; assert.strictEqual((await call('GET', { headers: admin })).status, 503);
  delete process.env.KV_REST_API_URL; assert.strictEqual((await call('POST', { body: { message: 'hello there' } })).status, 503, 'store not connected -> 503, the app then offers email');
  console.log('feedback api: all checks passed');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
