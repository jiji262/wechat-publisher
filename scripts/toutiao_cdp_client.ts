/**
 * 头条 CDP 传输层:WebSocket 协议封装 + Chrome 启动 + 会话/登录态。
 *
 * 和 toutiao_cdp.ts 的分工:这里只管"怎么连上一个能签名的页面",
 * 具体调哪些头条接口在 toutiao_cdp.ts。
 *
 * 零依赖:只用 bun/Node 内建模块。
 */
import { spawn, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

const PUBLISH_PAGE = 'https://mp.toutiao.com/profile_v4/graphic/publish?from=toutiao_pc'
const DEFAULT_PROFILE = path.join(
  os.homedir(), 'Library/Application Support/wechat-publisher/toutiao-profile')
const CHROME_CANDIDATES = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
]
const LOGIN_WAIT_MS = Number(process.env.TOUTIAO_LOGIN_TIMEOUT_MS || 180_000)

const log = (...a: unknown[]) => console.error('[toutiao]', ...a)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ------------------------------------------------------------------ CDP

class Cdp {
  private nextId = 0
  private pending = new Map<number, { resolve: Function; reject: Function; timer: Timer }>()

  private constructor(private ws: WebSocket) {
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(String(ev.data))
      if (!msg.id) return
      const p = this.pending.get(msg.id)
      if (!p) return
      this.pending.delete(msg.id)
      clearTimeout(p.timer)
      msg.error?.message ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result)
    })
    ws.addEventListener('close', () => {
      for (const [id, p] of this.pending) {
        this.pending.delete(id); clearTimeout(p.timer)
        p.reject(new Error('CDP 连接已关闭'))
      }
    })
  }

  static async connect(url: string): Promise<Cdp> {
    const ws = new WebSocket(url)
    await new Promise<void>((res, rej) => {
      const t = setTimeout(() => rej(new Error('CDP 连接超时')), 15_000)
      ws.addEventListener('open', () => { clearTimeout(t); res() })
      ws.addEventListener('error', () => { clearTimeout(t); rej(new Error('CDP 连接失败')) })
    })
    return new Cdp(ws)
  }

  send<T = any>(method: string, params?: object, sessionId?: string, timeoutMs = 60_000): Promise<T> {
    const id = ++this.nextId
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id); reject(new Error(`CDP 超时: ${method}`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      this.ws.send(JSON.stringify({ id, method, params, sessionId }))
    })
  }

  close() { try { this.ws.close() } catch { /* 已关闭 */ } }
}

// ------------------------------------------------------------ Chrome 启动

function findChrome(): string {
  const env = process.env.TOUTIAO_CHROME_PATH
  if (env) {
    if (!fs.existsSync(env)) throw new Error(`TOUTIAO_CHROME_PATH 指向的文件不存在: ${env}`)
    return env
  }
  const hit = CHROME_CANDIDATES.find((p) => fs.existsSync(p))
  if (!hit) throw new Error('找不到 Chrome。请安装 Chrome,或设置 TOUTIAO_CHROME_PATH 指向可执行文件。')
  return hit
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.on('error', reject)
    srv.listen(0, () => {
      const p = (srv.address() as net.AddressInfo).port
      srv.close(() => resolve(p))
    })
  })
}

async function waitDebugger(port: number, timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`)
      if (r.ok) {
        const j = (await r.json()) as { webSocketDebuggerUrl?: string }
        if (j.webSocketDebuggerUrl) return j.webSocketDebuggerUrl
      }
    } catch { /* 还没起来 */ }
    await sleep(200)
  }
  throw new Error('Chrome 调试端口未就绪(30s 超时)')
}

/**
 * 关掉 Chrome:先 SIGTERM,等它自己退出,实在不退才 SIGKILL。
 *
 * 不能像原来那样固定 sleep 1.2s 就 SIGKILL —— 首次扫码那一轮 cookie 刚写进
 * profile,Chrome 的 SQLite 未必落盘完,被强杀会丢登录态,下次启动又要扫一次码。
 */
async function closeProcess(proc: ChildProcess, graceMs = 10_000): Promise<void> {
  if (proc.exitCode !== null || proc.signalCode !== null) return
  const exited = new Promise<'exited'>((resolve) => proc.once('exit', () => resolve('exited')))
  try {
    proc.kill('SIGTERM')
  } catch {
    return // 已经不在了
  }
  const timeout = new Promise<'timeout'>((r) => setTimeout(() => r('timeout'), graceMs))
  if ((await Promise.race([exited, timeout])) === 'timeout') {
    try { proc.kill('SIGKILL') } catch { /* 已退出 */ }
  }
}

// -------------------------------------------------------------- 会话封装

type Evaluate = <T>(expr: string, timeoutMs?: number) => Promise<T>

class Session {
  constructor(private cdp: Cdp, private sessionId: string, private proc: ChildProcess) {}

  static async open(): Promise<Session> {
    const profileDir = process.env.TOUTIAO_PROFILE_DIR || DEFAULT_PROFILE
    fs.mkdirSync(profileDir, { recursive: true })
    const port = await freePort()
    log(`启动 Chrome(profile: ${profileDir})`)
    const proc = spawn(findChrome(), [
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profileDir}`,
      '--no-first-run', '--no-default-browser-check', '--disable-popup-blocking',
      PUBLISH_PAGE,
    ], { stdio: 'ignore' })

    // spawn 之后任何一步失败都必须把 Chrome 收掉 —— 调用方拿不到 Session,
    // 也就没法在 finally 里 close(),否则会留下一个带调试端口的孤儿进程。
    try {
      const cdp = await Cdp.connect(await waitDebugger(port))
      try {
        const deadline = Date.now() + 30_000
        while (Date.now() < deadline) {
          const { targetInfos } = await cdp.send<any>('Target.getTargets')
          const t = targetInfos.find(
            (x: any) => x.type === 'page' && x.url.includes('mp.toutiao.com'))
          if (t) {
            const { sessionId } = await cdp.send<any>('Target.attachToTarget',
              { targetId: t.targetId, flatten: true })
            await cdp.send('Runtime.enable', {}, sessionId)
            return new Session(cdp, sessionId, proc)
          }
          await sleep(400)
        }
        throw new Error('没找到头条页面标签页(30s 超时)')
      } catch (e) {
        cdp.close()
        throw e
      }
    } catch (e) {
      await closeProcess(proc)
      throw e
    }
  }

  evaluate: Evaluate = async <T>(expr: string, timeoutMs = 120_000): Promise<T> => {
    const r = await this.cdp.send<any>('Runtime.evaluate',
      { expression: expr, awaitPromise: true, returnByValue: true }, this.sessionId, timeoutMs)
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.exception?.description || '页面内执行出错')
    }
    return r.result.value as T
  }

  private async probeUser(): Promise<{ id: number; name: string } | null> {
    return this.evaluate<any>(`(async () => {
      try {
        const r = await fetch('https://mp.toutiao.com/mp/agw/media/get_media_info', {credentials:'include'});
        const j = await r.json();
        return j && j.data && j.data.user ? {id:j.data.user.id, name:j.data.user.screen_name} : null;
      } catch (e) { return null }
    })()`, 30_000)
  }

  /**
   * 轮询等待登录。
   *
   * 头几次探针失败通常只是页面还没加载完,不是真的没登录 —— 所以先静默重试几次,
   * 确认确实没有登录态之后才提示扫码,免得每次都打一句吓人的"未登录"。
   */
  async waitLogin(): Promise<{ id: number; name: string }> {
    for (let i = 0; i < 4; i++) {
      const me = await this.probeUser()
      if (me) return me
      await sleep(2000)
    }

    log('未登录 —— 请在弹出的 Chrome 窗口里扫码登录头条号')
    const deadline = Date.now() + LOGIN_WAIT_MS
    while (Date.now() < deadline) {
      await sleep(3000)
      const me = await this.probeUser()
      if (me) return me
    }
    throw new Error(`登录等待超时(${Math.round(LOGIN_WAIT_MS / 1000)}s)。请重跑并及时扫码。`)
  }

  /**
   * 确保当前页是发文页,且页面的风控 SDK 已经劫持了 window.fetch。
   *
   * 这一步不能省:请求的 msToken/a_bogus 全靠这个劫持后的 fetch 自动挂上,
   * SDK 没加载完就发请求会拿到 7050 保存失败。用轮询而不是固定 sleep,
   * 因为加载耗时随网络波动。
   */
  async waitSigningReady(timeoutMs = 45_000): Promise<void> {
    const onPage = await this.evaluate<boolean>(
      `location.href.includes('graphic/publish')`)
    if (!onPage) {
      await this.evaluate(`(location.href = ${JSON.stringify(PUBLISH_PAGE)}, 1)`)
    }
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      const ready = await this.evaluate<boolean>(`(() => {
        try {
          return location.href.includes('graphic/publish')
            && !/\\[native code\\]/.test(window.fetch.toString());
        } catch (e) { return false }
      })()`).catch(() => false)
      if (ready) return
      await sleep(1000)
    }
    throw new Error(
      '页面的签名 SDK 未就绪(45s 超时)。可能是网络问题导致 bdms.js 没加载出来,请重试。')
  }

  async close() {
    this.cdp.close()
    await closeProcess(this.proc)
  }
}


export { Cdp, Session, log, sleep }
export type { Evaluate }
