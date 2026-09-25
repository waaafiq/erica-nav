// Anonymous suggestions & complaints for ERICA Nav: just the message text and when it arrived, nothing about who sent it.
//   POST   /api/feedback   public: stores one submission
//   GET    /api/feedback   admin (Authorization: Bearer <FEEDBACK_ADMIN_KEY>): all submissions as CSV
//   DELETE /api/feedback   admin: deletes every submission
//
// Storage is a private Upstash Redis database, added to the Vercel project from the Marketplace. That sets the
// KV_REST_API_* (or UPSTASH_REDIS_REST_*) variables read below. Set FEEDBACK_ADMIN_KEY yourself. Until the database
// is connected this returns 503 and the app offers to email the message instead.
const crypto = require('crypto');

const LIST = 'ericanav:feedback';
const MAX_ROWS = 5000;      // oldest submissions are dropped past this
const PER_HOUR = 5;         // submissions allowed per visitor per hour
const MAX_MESSAGE = 2000;

const redisUrl = () => process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const redisToken = () => process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;

async function redis(...cmd) {
  const r = await fetch(redisUrl(), {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + redisToken(), 'Content-Type': 'application/json' },
    body: JSON.stringify(cmd)
  });
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || 'redis HTTP ' + r.status);
  return j.result;
}

// A spreadsheet treats a cell starting with = + - @ as a formula, so defuse those; quote everything.
const cell = v => {
  v = String(v == null ? '' : v);
  if (/^[=+\-@\t\r]/.test(v)) v = "'" + v;
  return '"' + v.replace(/"/g, '""') + '"';
};

function toCsv(rows) {
  const lines = ['id,received_at,message'].concat(rows.map(r => [r.id, r.at, r.message].map(cell).join(',')));
  return '﻿' + lines.join('\r\n') + '\r\n'; // BOM so Excel reads Korean text correctly
}

const sha = s => crypto.createHash('sha256').update(String(s)).digest();
function isAdmin(req) {
  const key = process.env.FEEDBACK_ADMIN_KEY;
  const given = (req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  return !!key && crypto.timingSafeEqual(sha(given), sha(key));
}

async function submit(req, res) {
  let b = req.body;
  if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) { b = null; } }
  if (!b || typeof b !== 'object') return res.status(400).json({ error: 'bad_request' });
  if (b.website) return res.status(200).json({ ok: true }); // honeypot field: only bots fill it in; pretend it worked

  const message = String(b.message || '').trim().slice(0, MAX_MESSAGE);
  if (message.length < 5) return res.status(400).json({ error: 'too_short' });
  const row = { id: crypto.randomUUID(), at: new Date().toISOString(), message: message };

  // Rate limit per visitor. Only a keyed hash of the IP is used, it lives for one hour, and it is never stored with the message.
  const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || (req.socket && req.socket.remoteAddress) || '';
  const rl = 'ericanav:rl:' + crypto.createHmac('sha256', redisToken()).update(ip).digest('hex').slice(0, 32);
  const n = await redis('INCR', rl);
  if (n === 1) await redis('EXPIRE', rl, 3600);
  if (n > PER_HOUR) return res.status(429).json({ error: 'rate_limited' });

  await redis('RPUSH', LIST, JSON.stringify(row));
  await redis('LTRIM', LIST, -MAX_ROWS, -1);
  return res.status(200).json({ ok: true });
}

async function admin(req, res) {
  if (!process.env.FEEDBACK_ADMIN_KEY) return res.status(503).json({ error: 'admin_not_configured' });
  if (!isAdmin(req)) return res.status(401).json({ error: 'unauthorized' });
  if (req.method === 'DELETE') { await redis('DEL', LIST); return res.status(200).json({ ok: true }); }
  const rows = (await redis('LRANGE', LIST, 0, -1) || []).map(x => { try { return JSON.parse(x); } catch (e) { return null; } }).filter(Boolean);
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="ericanav-feedback.csv"');
  return res.status(200).send(toCsv(rows));
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (!redisUrl() || !redisToken()) return res.status(503).json({ error: 'not_configured' });
  try {
    if (req.method === 'POST') return await submit(req, res);
    if (req.method === 'GET' || req.method === 'DELETE') return await admin(req, res);
    res.setHeader('Allow', 'GET, POST, DELETE');
    return res.status(405).json({ error: 'method_not_allowed' });
  } catch (e) {
    console.error('[feedback]', e && e.message);
    return res.status(500).json({ error: 'server_error' });
  }
};
module.exports.toCsv = toCsv; // exported for the self-check below
