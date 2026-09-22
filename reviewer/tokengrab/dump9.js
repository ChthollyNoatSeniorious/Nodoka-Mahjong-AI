'use strict'
// 攔遊戲 oauth2Auth/requestConnection 幀的原始 hex,手工解析全部 protobuf 字段
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

// mini protobuf 解析:返回 [{field, wire, value}]
function parseProto(buf, depth) {
  const out = []
  let off = 0
  const readVarint = () => {
    let v = 0n, shift = 0n, b
    do {
      if (off >= buf.length) throw new Error('eof')
      b = buf[off++]
      v |= BigInt(b & 0x7f) << shift
      shift += 7n
    } while (b & 0x80)
    return v
  }
  while (off < buf.length) {
    const tag = Number(readVarint())
    const field = tag >> 3
    const wire = tag & 7
    if (wire === 0) {
      out.push({ field, wire, value: readVarint().toString() })
    } else if (wire === 2) {
      const len = Number(readVarint())
      if (off + len > buf.length) throw new Error('len overflow')
      const sub = buf.slice(off, off + len)
      off += len
      // 嘗試當 utf8(多數 string)
      let isText = true
      for (const c of sub) if (c < 32 && c !== 9 && c !== 10 && c !== 13) { isText = false; break }
      if (isText && sub.length) {
        out.push({ field, wire, value: '(str) ' + sub.toString('utf8') })
      } else if (depth > 0) {
        out.push({ field, wire, sub: parseProto(sub, depth - 1) })
      } else {
        out.push({ field, wire, value: 'hex ' + sub.toString('hex') })
      }
    } else if (wire === 1) {
      const v = buf.readBigUInt64LE(off); off += 8
      out.push({ field, wire, value: v.toString() })
    } else if (wire === 5) {
      const v = buf.readUInt32LE(off); off += 4
      out.push({ field, wire, value: String(v) })
    } else {
      throw new Error('wire ' + wire)
    }
  }
  return out
}

;(async () => {
  const sc = new ServerConfig({ mjsoul: { base: BASE, timeout: 20000 }, userAgent: 'Mozilla/5.0' })
  let scfg = null
  for (let i = 0; i < 8 && !scfg; i++) {
    try { scfg = await sc.getServerConfig(BASE, 20000) }
    catch (e) { console.error('cfg attempt', i + 1, 'failed:', e.message); await new Promise(r => setTimeout(r, 2500)) }
  }
  if (!scfg) throw new Error('no server config')
  const root = pb.Root.fromJSON(scfg.liqi)

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    userDataDir: PROFILE,
    args: ['--proxy-server=http://127.0.0.1:7897', '--disable-blink-features=AutomationControlled'],
  })
  const attach = async (page) => {
    try {
      const client = await page.createCDPSession()
      await client.send('Network.enable')
      client.on('Network.webSocketFrameSent', (e) => {
        const p = e.response && e.response.payloadData
        if (!p) return
        const buf = Buffer.from(p, 'base64')
        if (buf.length < 5 || buf[0] !== 2) return
        let wr
        try { wr = root.lookupType('Wrapper').decode(buf.slice(3)) } catch (err) { return }
        const name = wr.name || ''
        if (!/oauth2Auth|requestConnection|oauth2Check|oauth2Login/.test(name)) return
        console.log('=== SENT', name, 'index=', buf[1] | (buf[2] << 8))
        console.log('HEX:', buf.toString('hex'))
        try {
          const svc = root.lookup(name).toJSON()
          const reqType = root.lookupType(svc.requestType)
          const msg = reqType.decode(wr.data)
          console.log('KNOWN-FIELDS:', JSON.stringify(msg, (k, v) => (typeof v === 'bigint' ? v.toString() : v)))
          // protobufjs 未知字段
          if (msg.$unknownArray || msg.$unknown) console.log('UNKNOWN:', JSON.stringify(msg.$unknownArray || msg.$unknown))
        } catch (err) { console.log('decode err', err.message) }
        console.log('ALL-FIELDS:')
        try {
          console.log(JSON.stringify(parseProto(wr.data, 2), null, 1))
        } catch (err) { console.log('parse err', err.message) }
      })
    } catch (e) {}
  }
  browser.on('targetcreated', async (t) => { try { const p = await t.page(); if (p) attach(p) } catch (e) {} })
  const page = await browser.newPage()
  await attach(page)
  await page.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(() => {})
  await new Promise(r => setTimeout(r, 30000))
  console.log('SCAN DONE')
  await browser.close()
})().catch((e) => { console.error('FATAL', e); process.exit(1) })