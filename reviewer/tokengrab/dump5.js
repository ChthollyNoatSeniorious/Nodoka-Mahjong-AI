'use strict'
// 頁內 hook WebSocket 捕獲【下行幀】(CDP 的 webSocketFrameReceived 攔不到)
if (!process.env.https_proxy && !process.env.HTTPS_PROXY) {
  process.env.https_proxy = 'http://127.0.0.1:7897'
}
const path = require('path')
const puppeteer = require('puppeteer-core')
const pb = require('protobufjs')
const ServerConfig = require(path.join(__dirname, '..', 'tensoul-main', 'server_config.js'))

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.join(__dirname, 'profile')
const BASE = 'https://game.mahjongsoul.com'
const PAGE = BASE + '/index.html'

const HOOK = `
window.__wsRecv = [];
const toBytes = (data) => {
  try {
    if (data instanceof ArrayBuffer) return new Uint8Array(data);
    if (data && data.buffer instanceof ArrayBuffer)
      return new Uint8Array(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
    if (typeof data === 'string') { const b = new Uint8Array(data.length); for (let i=0;i<data.length;i++) b[i]=data.charCodeAt(i)&0xff; return b; }
  } catch (e) {}
  return null;
};
const push = (data) => {
  const b = toBytes(data);
  if (b && b.length && b.length < 200000) {
    if (window.__wsRecv.length < 4000) window.__wsRecv.push(Array.from(b));
    else window.__wsRecv.push([]);
  }
};
const origDesc = Object.getOwnPropertyDescriptor(WebSocket.prototype, 'onmessage');
try {
  Object.defineProperty(WebSocket.prototype, 'onmessage', {
    configurable: true,
    get() { return origDesc.get.call(this); },
    set(fn) {
      origDesc.set.call(this, function (ev) { push(ev.data); return fn.apply(this, arguments); });
    },
  });
} catch (e) {}
const origAdd = WebSocket.prototype.addEventListener;
WebSocket.prototype.addEventListener = function (type, fn, ...rest) {
  if (type === 'message') {
    const wrapped = function (ev) { push(ev.data); return fn.apply(this, arguments); };
    return origAdd.call(this, type, wrapped, ...rest);
  }
  return origAdd.call(this, type, fn, ...rest);
};
`

;(async () => {
  const sc = new ServerConfig({ mjsoul: { base: BASE, timeout: 20000 }, userAgent: 'Mozilla/5.0' })
  let scfg = null
  for (let i = 0; i < 8 && !scfg; i++) {
    try { scfg = await sc.getServerConfig(BASE, 20000) }
    catch (e) { console.error('cfg attempt', i + 1, 'failed:', e.message); await new Promise(r => setTimeout(r, 2500)) }
  }
  if (!scfg) throw new Error('no server config')
  console.error('server version:', scfg.version)
  const root = pb.Root.fromJSON(scfg.liqi)

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    userDataDir: PROFILE,
    args: ['--proxy-server=http://127.0.0.1:7897', '--disable-blink-features=AutomationControlled'],
  })
  const page = await browser.newPage()
  await page.evaluateOnNewDocument(HOOK)
  await page.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(() => {})
  await new Promise(r => setTimeout(r, 50000))

  const frames = await page.evaluate(() => window.__wsRecv || [])
  console.log('RECV frames captured:', frames.length)
  let shown = 0
  for (const arr of frames) {
    const buf = Buffer.from(arr)
    if (!buf.length) continue
    let payload = null
    const tag = buf[0]
    if (tag === 1) payload = buf.slice(1)
    else if (tag === 3) payload = buf.slice(3)
    if (!payload) {
      console.log('RECV-ODD first=', tag, 'len=', buf.length, 'hex=', buf.toString('hex').slice(0, 60))
      continue
    }
    if (shown < 5) {
      shown++
      console.log('HEX-RECV tag=', tag, 'len=', buf.length, 'payload-hex=', payload.toString('hex').slice(0, 200))
    }
    let wr
    try { wr = root.lookupType('Wrapper').decode(payload) } catch (e) {
      console.log('RECV-UNDECODABLE first=', tag, 'len=', buf.length, 'hex=', buf.toString('hex').slice(0, 60))
      continue
    }
    const name = wr.name || '(empty)'
    console.log('FRAME', tag, name)
    if (!/oauth2|login|connection|heartbeat|prepare|notify/i.test(name)) continue
    console.log('=== RECV ' + name)
    try {
      const t = root.lookupType(name)
      const msg = t.decode(wr.data)
      console.log(JSON.stringify(msg, (k, v) => (typeof v === 'bigint' ? v.toString() : v), 1))
    } catch (e) {
      try {
        const svc = root.lookup(name).toJSON()
        const t = root.lookupType(svc.responseType)
        const msg = t.decode(wr.data)
        console.log(JSON.stringify(msg, (k, v) => (typeof v === 'bigint' ? v.toString() : v), 1))
      } catch (e2) {
        console.log('(decode failed:', e.message, '/', e2.message + ') hex=', buf.toString('hex').slice(0, 80))
      }
    }
  }
  console.log('SCAN DONE')
  await browser.close()
})().catch((e) => { console.error('FATAL', e); process.exit(1) })