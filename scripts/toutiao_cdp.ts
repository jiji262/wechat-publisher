#!/usr/bin/env bun
/**
 * 头条发文的浏览器侧执行器。
 *
 * 为什么需要浏览器:mp.toutiao.com 的发布接口强制 msToken/a_bogus 签名,
 * 由页面里的字节风控 SDK(bdms.js)劫持 window.fetch 现算。实测对照:
 *   页面 fetch(自动签名) → code 0 保存成功
 *   iframe 原生 fetch(无签名) → code 7050 保存失败
 *
 * 为什么不需要浏览器扩展:CDP 的 Runtime.evaluate 默认就在 MAIN world,
 * 直接就能用页面的签名能力。wechatsync 必须做成扩展,是因为扩展的
 * content script 在 isolated world,只能绕道 chrome.scripting.executeScript。
 *
 * 零依赖:只用 bun/Node 内建模块。
 *
 * 用法(JSON 走 stdin/stdout,日志走 stderr):
 *   echo '{}'        | bun toutiao_cdp.ts check
 *   echo '{images…}' | bun toutiao_cdp.ts upload
 *   echo '{title…}'  | bun toutiao_cdp.ts publish
 */
import fs from 'node:fs'

import { Session, log, type Evaluate } from './toutiao_cdp_client.ts'

// ---------------------------------------------------------------- 命令

/** 把本地图片经 /spice/image 上传到头条 CDN。body 与 cover 用不同的 upload_source。 */
// 图片是 base64 内联进 Runtime.evaluate 的表达式里走 CDP WebSocket 的,
// 单条消息有上限(bun 默认 16MB)。超了会报成"CDP 连接断开"那种看不懂的错,
// 所以先自己拦一道,给人话。base64 膨胀约 4/3,留出余量取 9MB。
const MAX_IMAGE_BYTES = 9 * 1024 * 1024

async function uploadImage(ev: Evaluate, filePath: string, kind: 'body' | 'cover') {
  if (!fs.existsSync(filePath)) throw new Error(`图片不存在: ${filePath}`)
  const size = fs.statSync(filePath).size
  if (size > MAX_IMAGE_BYTES) {
    throw new Error(
      `图片过大(${(size / 1024 / 1024).toFixed(1)}MB > ${MAX_IMAGE_BYTES / 1024 / 1024}MB): ` +
      `${filePath}。请先压缩后重试。`)
  }
  const b64 = fs.readFileSync(filePath).toString('base64')
  const query = kind === 'cover'
    ? 'upload_source=20020003&aid=1231&device_platform=web&need_cover_url=1'
    : 'upload_source=20020002&aid=1231&device_platform=web'
  return ev<any>(`(async () => {
    const bin = atob(${JSON.stringify(b64)});
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const fd = new FormData();
    fd.append('image', new Blob([buf]), 'image.jpg');
    const r = await fetch('https://mp.toutiao.com/spice/image?${query}',
      {method:'POST', credentials:'include', body: fd});
    const j = await r.json();
    if (j.code !== 0 || !j.data || !j.data.image_uri) {
      throw new Error('图片上传失败: ' + (j.message || j.code));
    }
    return j.data;
  })()`)
}

async function cmdUpload(ev: Evaluate, input: any) {
  const images: Record<string, any> = {}
  const list: { key: string; path: string }[] = input.images || []
  for (let i = 0; i < list.length; i++) {
    log(`上传正文图 ${i + 1}/${list.length}`)
    images[list[i].key] = await uploadImage(ev, list[i].path, 'body')
  }
  let cover = null
  if (input.cover) {
    log('上传封面')
    cover = await uploadImage(ev, input.cover, 'cover')
  }
  return { images, cover }
}

/** 写草稿。save=0 存草稿,不直接发布 —— 与本 skill 微信侧的约定一致。 */
async function cmdPublish(ev: Evaluate, input: any) {
  const covers = input.cover ? [{
    url: input.cover.image_url, uri: input.cover.image_uri, web_uri: input.cover.image_uri,
    ic_uri: '', width: input.cover.image_width, height: input.cover.image_height,
    thumb_width: input.cover.image_width, thumb_height: input.cover.image_height, id: 0, pos: 0,
  }] : []
  const payload = {
    title: input.title, content: input.content,
    covers: JSON.stringify(covers),
    coverType: input.cover ? 1 : 3,
  }
  const res = await ev<any>(`(async () => {
    const P = ${JSON.stringify(payload)};
    const fields = {
      pgc_id: '0', source: '29', content: P.content, title: P.title,
      search_creation_info: '{"searchTopOne":0,"abstract":"","clue_id":""}',
      title_id: Date.now() + '_' + Math.floor(Math.random() * 1e16),
      mp_editor_stat: '{}', is_refute_rumor: '0',
      save: '0', timer_status: '0', timer_time: '', educluecard: '',
      draft_form_data: JSON.stringify({coverType: P.coverType}),
      pgc_feed_covers: P.covers,
      article_ad_type: '3', is_fans_article: '0', govern_forward: '0', praise: '0',
      disable_praise: '0', tree_plan_article: '0', activity_tag: '0',
      trends_writing_tag: '0', claim_exclusive: '0',
      extra: JSON.stringify({content_source: 100000000402, content_word_cnt: P.content.length,
        is_multi_title: 0, sub_titles: [],
        gd_ext: {entrance:'', from_page:'publisher_mp', enter_from:'PC',
                 device_platform:'mp', is_message: 0}}),
    };
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(fields)) p.set(k, v);
    const r = await fetch('https://mp.toutiao.com/mp/agw/article/publish?source=mp&type=article&aid=1231&mp_publish_ab_val=0',
      {method:'POST', credentials:'include',
       headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: p.toString()});
    const j = await r.json();
    return {code: j.code, msg: j.message || j.reason, pgc_id: j.data && j.data.pgc_id};
  })()`)
  if (res.code !== 0 || !res.pgc_id) {
    throw new Error(`头条拒绝保存: [${res.code}] ${res.msg || '未知错误'}`)
  }
  return {
    pgc_id: String(res.pgc_id),
    draft_url: `https://mp.toutiao.com/profile_v4/graphic/publish?pgc_id=${res.pgc_id}`,
  }
}

// ---------------------------------------------------------------- main

async function readStdin(): Promise<any> {
  const chunks: Buffer[] = []
  for await (const c of process.stdin) chunks.push(c as Buffer)
  const text = Buffer.concat(chunks).toString('utf-8').trim()
  return text ? JSON.parse(text) : {}
}

async function main() {
  const cmd = process.argv[2]
  if (!['check', 'upload', 'publish'].includes(cmd || '')) {
    console.error('用法: bun toutiao_cdp.ts <check|upload|publish>   (JSON 走 stdin)')
    process.exit(2)
  }
  const input = await readStdin()
  let session: Session | null = null
  try {
    session = await Session.open()
    const user = await session.waitLogin()
    log(`已登录: ${user.name} (${user.id})`)
    await session.waitSigningReady()

    let data: any = { user }
    if (cmd === 'upload') data = { user, ...(await cmdUpload(session.evaluate, input)) }
    if (cmd === 'publish') data = { user, ...(await cmdPublish(session.evaluate, input)) }

    console.log(JSON.stringify({ ok: true, ...data }))
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: (e as Error).message }))
    process.exitCode = 1
  } finally {
    await session?.close()
  }
}

main()
