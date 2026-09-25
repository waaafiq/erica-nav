// Who runs ERICA Nav. Fill these in ONCE; privacy.html and terms.html pick them up.
// Values still highlighted yellow on the pages are placeholders that need replacing.
const OP = {
  name: 'Wafiq',                     // person or company that operates the site
  email: 'hakeemwafiq04@gmail.com',  // contact for privacy requests and questions
  place: 'Ansan, South Korea',      // where the operator is based
  host: 'Vercel',                    // confirmed: erica-nav.vercel.app
  law: 'the Republic of Korea',      // governing law for the Terms; confirm it fits where you live
  updated: '2026-09-25'
};

document.querySelectorAll('[data-op]').forEach(el => {
  const v = OP[el.dataset.op];
  el.textContent = v;
  if (/^(YOUR|CITY|you@)/.test(v)) el.classList.add('todo');
  if (el.tagName === 'A') el.href = 'mailto:' + v;
});

// Language: follow the app's EN/한 choice, else the browser language. Without JS both languages show.
const root = document.documentElement;
function setLang(l) {
  root.dataset.l = l;
  root.lang = l;
  document.querySelectorAll('.langs button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.l === l)));
}
let saved = null;
try { saved = JSON.parse(localStorage.getItem('ericanav.v2') || 'null'); } catch (e) { /* ignore */ }
const pref = (saved && saved.primary) || ((navigator.language || '').toLowerCase().startsWith('ko') ? 'ko' : 'en');
setLang(pref === 'ko' ? 'ko' : 'en');
document.querySelectorAll('.langs button').forEach(b => b.addEventListener('click', () => setLang(b.dataset.l)));
// the language switch changes the page height, so re-jump to a #section link (e.g. privacy.html#feedback)
if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
