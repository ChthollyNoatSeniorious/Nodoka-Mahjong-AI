'use strict'
// 完整 dump 遊戲登入相關 WS 幀的所有字段(找 tensoul 缺的參數)
const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer-core')
const pb = require('protobufjs')

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.join(__dirname, 'profile')
const BASE = 'https://game.mahjongsoul.com/index.html'
const LIQI = path.join(__dirname, '..', 'tensoul-main', 'node_modules', 'mjsoul', 'liqi.json')
const root = pb.Root.fromJSON(JSON.parse(fs.readFileSync(LIQI, 'utf8')))

function dump(b64) {
  const buf = Buffer.from(b64, 'base64')
  if (!buf.length || buf[0] !== 2) return
  let wr
  try { wr = root.lookupType('Wrapper').decode(buf.slice(3)) } catch (e) { return }
  const name = wr.name || ''
  if (!/oauth2|login/i.test(name)) return
  try {
    const svc = root.lookup(name).toJSON()
    const reqType = root.lookupType(svc.requestType)
    const msg = reqType.decode(wr.data)
    console.log('=== ' + name)
    console.log(JSON.stringify(msg, (k, v) => typeof v === 'bigint' ? v.toString() : v, 1))
  } catch (e) { console.log('decode err', name, e.message) }
}

;(async () => {
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
        if (p) dump(p)
      })
    } catch (e) {}
  }
  browser.on('targetcreated', async (t) => { try { const p = await t.page(); if (p) attach(p) } catch (e) {} })
  const page = await browser.newPage()
  await attach(page)
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(e => console.log('goto warn:', e.message))
  await new Promise(r => setTimeout(r, 120000))
  console.log('SCAN DONE')
  await browser.close()
})().catch(e => { console.error('FATAL', e); process.exit(1) })