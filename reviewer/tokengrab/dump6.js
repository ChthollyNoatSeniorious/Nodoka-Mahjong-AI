'use strict'
// 在真實 Chrome 中完整重放登入序列(排除 Node ws 環境因素)
if (!process.env.https_proxy && !process.env.HTTPS_PROXY) {
  process.env.https_proxy = 'http://127.0.0.1:7897'
}
const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer-core')
const ServerConfig = require(path.join(__dirname, '..', 'tensoul-main', 'server_config.js'))

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = 'https://game.mahjongsoul.com'
const PBDIST = path.join(__dirname, '..', 'tensoul-main', 'node_modules', 'protobufjs', 'dist', 'protobuf.min.js')

// 敏感值請從環境變數讀取(勿提交真實值):
//   $env:YOSTAR_OAUTH_TOKEN / $env:MJS_UID / $env:MJS_RANDOM_KEY
const YOSTAR_TOKEN = process.env.YOSTAR_OAUTH_TOKEN || ''
const UID = process.env.MJS_UID || ''
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/153.0.0.0 Safari/537.36'

;(async () => {
  const sc = new ServerConfig({ mjsoul: { base: BASE, timeout: 20000 }, userAgent: 'Mozilla/5.0' })
  let scfg = null
  for (let i = 0; i < 8 && !scfg; i++) {
    try { scfg = await sc.getServerConfig(BASE, 20000) }
    catch (e) { console.error('cfg attempt', i + 1, 'failed:', e.message); await new Promise(r => setTimeout(r, 2500)) }
  }
  if (!scfg) throw new Error('no server config')
  const gateways = sc.gatewayEndpoints(scfg.gateways || [])
  console.error('gateways:', gateways)
  const gateway = gateways[0]
  if (!gateway) throw new Error('no gateway')

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--proxy-server=http://127.0.0.1:7897', '--disable-blink-features=AutomationControlled'],
  })
  try {
    const page = await browser.newPage()
    await page.addScriptTag({ path: PBDIST })

    const result = await page.evaluate(async ({ liqi, gateway, token, uid, ua }) => {
      const protobuf = window.protobuf
      const root = protobuf.Root.fromJSON(liqi)
      const Wrapper = root.lookupType('Wrapper')
      let idx = Math.floor(Math.random() * 1000)
      const send = (ws, name, obj) => new Promise((resolve, reject) => {
        let svc
        try { svc = root.lookup(name).toJSON() } catch (e) { reject(new Error('no svc ' + name)); return }
        const reqType = root.lookupType(svc.requestType)
        const resType = root.lookupType(svc.responseType)
        const data = reqType.encode(reqType.create(obj)).finish()
        const body = Wrapper.encode(Wrapper.create({ name, data })).finish()
        const myIdx = idx
        idx = (idx + 1) % 60007
        const head = new Uint8Array([2, myIdx & 0xff, (myIdx >> 8) & 0xff])
        const buf = new Uint8Array(3 + body.length)
        buf.set(head); buf.set(body, 3)
        pending.set(myIdx, { resType, resolve, reject })
        setTimeout(() => { if (pending.has(myIdx)) { pending.delete(myIdx); reject(new Error('timeout ' + name)) } }, 20000)
        ws.send(buf)
      })
      const pending = new Map()
      const ws = new WebSocket(gateway)
      ws.binaryType = 'arraybuffer'
      await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('ws error')) })
      ws.onmessage = (ev) => {
        const data = new Uint8Array(ev.data)
        if (data.length < 3) return
        if (data[0] === 3) {
          const index = data[1] | (data[2] << 8)
          const p = pending.get(index)
          if (p) {
            pending.delete(index)
            try {
              const wrapper = Wrapper.decode(data.slice(3))
              p.resolve(p.resType.decode(wrapper.data))
            } catch (e) { p.reject(e) }
          }
        }
      }

      const out = {}
      try {
        out.requestConnection = await send(ws, '.lq.Route.requestConnection', {
          type: 1, route_id: 'jp-1', timestamp: String(Math.floor(Date.now() / 1000)),
        })
        out.heartbeat = await send(ws, '.lq.Route.heartbeat', { delay: 5000, platform: 11, network_quality: 5000 })
        out.oauth2Auth = await send(ws, '.lq.Lobby.oauth2Auth', {
          type: 21, code: token, uid, client_version_string: 'WebGL_2022-0.16.259',
        })
        const tok = out.oauth2Auth && out.oauth2Auth.access_token
        if (tok) {
          out.oauth2Check = await send(ws, '.lq.Lobby.oauth2Check', { type: 21, access_token: tok })
          out.oauth2Login = await send(ws, '.lq.Lobby.oauth2Login', {
            type: 21, access_token: tok, reconnect: false,
            device: {
              platform: 'pc', hardware: 'pc', os: 'windows', os_version: 'win10',
              is_browser: true, software: 'Chrome', sale_platform: 'web',
              screen_width: 800, screen_height: 600, user_agent: ua, screen_type: 1,
            },
            random_key: process.env.MJS_RANDOM_KEY || '',
            client_version: { resource: '0.16.259', package: '4.0.12' },
            currency_platforms: [1, 3, 5, 9, 12],
            client_version_string: 'WebGL_2022-0.16.259',
            tag: 'jp',
          })
        }
      } catch (e) {
        out.error = String(e && e.message || e)
      }
      try { ws.close() } catch (e) {}
      return out
    }, { liqi: scfg.liqi, gateway, token: YOSTAR_TOKEN, uid: UID, ua: UA })

    console.log('RESULT:', JSON.stringify(result, (k, v) => {
      if (v && typeof v === 'object' && 'low' in v && 'high' in v) return Number(v.toString ? v.toString() : v.low)
      return v
    }, 1))
  } finally {
    await browser.close()
  }
})().catch((e) => { console.error('FATAL', e); process.exit(1) })