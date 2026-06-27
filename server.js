const http  = require('http');
const https = require('https');
const fs    = require('fs');
const url   = require('url');
const path  = require('path');

const PORT = 3000;
const ROOT = __dirname;

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml' };

http.createServer((req, res) => {
  const parsed = url.parse(req.url, true);

  /* ── /rss?url=ENCODED_FEED_URL ───────────────────────────── */
  if (parsed.pathname === '/rss') {
    const feedUrl = decodeURIComponent(parsed.query.url || '');
    if (!feedUrl.startsWith('http')) { res.writeHead(400); res.end('Bad URL'); return; }

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Content-Type', 'text/xml; charset=utf-8');

    const lib = feedUrl.startsWith('https') ? https : http;
    const reqOptions = { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; RSS-Reader/1.0 +https://github.com)' } };

    lib.get(feedUrl, reqOptions, feedRes => {
      if (feedRes.statusCode >= 300 && feedRes.statusCode < 400 && feedRes.headers.location) {
        // Follow one redirect
        const redirectLib = feedRes.headers.location.startsWith('https') ? https : http;
        redirectLib.get(feedRes.headers.location, reqOptions, r2 => r2.pipe(res)).on('error', () => { res.writeHead(502); res.end(); });
      } else {
        feedRes.pipe(res);
      }
    }).on('error', () => { res.writeHead(502); res.end('Fetch failed'); });
    return;
  }

  /* ── Static file serving ─────────────────────────────────── */
  const safePath = parsed.pathname.replace(/\\/g, '/').replace(/^(\.\.\/)+/, '');
  const filePath = path.join(ROOT, safePath === '/' || safePath === '' ? 'index.html' : safePath);

  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  });

}).listen(PORT, () => console.log(`Homepage running at http://localhost:${PORT}`));
