#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
京东快递 App HAR 抓包分析工具

用途：从 Loon / Stream / Charles 导出的 HAR 里定位广告位，并验证插件里的
jq 改写规则在真实响应上到底做了什么。

用法：
    python analyze_har.py <file.har>                 # 总览
    python analyze_har.py <file.har> --check         # 先看 MITM 有没有生效
    python analyze_har.py <file.har> --hosts         # 请求域名排行
    python analyze_har.py <file.har> --map           # lop-proxy 接口地图（解码请求体）
    python analyze_har.py <file.har> --feeds         # 首页「为您推荐」卡片类型统计
    python analyze_har.py <file.har> --scenes        # 投广决策接口的 sceneKey（开屏在哪）
    python analyze_har.py <file.har> --scan-ads      # 遍历 JSON 定位广告字段
    python analyze_har.py <file.har> --verify [插件] # 跑插件里的 jq 规则，输出前后对比
    python analyze_har.py <file.har> --all           # 全部（不含 --verify）

关于 --verify：
    直接解析 .plugin 文件里的 `^正则 response-body-json-jq '表达式'` 行，
    对抓包里命中的响应逐条执行，打印响应体字节数与卡片数量的变化。
    这是唯一能证明「规则确实能跑通」的办法 —— 光看语法对不对没用，
    要拿真实响应喂进去。依赖 `pip install jq`。

核心知识点：
    1. 京东快递的业务接口全部走 lop-proxy.jd.com，一个网关装下了首页、
       我的、京彩、会员、任务所有 JSON。所以 [MITM] 只需要这一个域名。
    2. 请求体是 base64(JSON)，响应体是明文 JSON（个别接口是加密串，见
       ENCRYPTED_HINT，那种改不了）。
    3. 这套接口统一外面包一层 {"code":1,"content":{...},"success":true}。
       整包 reject 掉会返回 {}，App 会走进错误分支。只能改字段。
    4. 广告不在域名层。抓包里没有第三方广告 SDK，别按域名去找。
"""

import argparse
import base64
import collections
import json
import os
import re
import sys
import urllib.parse

GATEWAY = "lop-proxy.jd.com"

# 业务主域：出现这些才说明抓到了京东快递的真实流量
BIZ_HOST_PATTERN = re.compile(r"(lop-proxy\.jd\.com|api\.m\.jd\.com|jdl\.com|360buyimg\.com)", re.I)

# 埋点/监控：可拦但不属于广告
TRACK_PATTERN = re.compile(
    r"(saturn\.jd\.com|cactus\.jd\.com|blackhole\.m\.jd\.com|sgm-w\.jd\.com|h5speed\.m\.jd\.com)", re.I
)

# 绝不该拦：风控指纹 / 登录
PROTECTED_PATTERN = re.compile(
    r"(jra\.jd\.com|sdkfp\.jd\.com|wlogin\.m\.jd\.com|un\.m\.jd\.com|wlmonitor\.m\.jd\.com)", re.I
)

# 响应是加密串、改不了的接口
ENCRYPTED_HINT = re.compile(r"(queryHomePageOrders|searchOrderEnhance|familyCard/getUserInfoEnhance)")

# JSON 里「像广告」的键名
AD_KEY_PATTERN = re.compile(
    r"^(ads?|adInfo|adData|adJson|adList|adItems|adMaterial|adZoneId|adExpInfo|adBanner"
    r"|banner|homeBanner|slideBanner|homeYingxiao|minePromotion|cpcInfo|isAd|trackInfo)$",
    re.I,
)

# 卡片类型标记
AD_VALUE_PATTERN = re.compile(r"^(ad|ads|advert|cpc|spm_ad)$", re.I)

# 像广告位的标题
AD_TITLE_PATTERN = re.compile(r"广告|推广|赞助|推荐|权益免费领|券包|秒杀|夺宝|助力")

# 首页 feed 里已知的卡片子对象 → 人类可读的名字
CARD_KIND = {
    "freeRightCard": "权益免费领（第三方联合会员）",
    "retailProductCard": "零售商品（跳京东商城导购）",
    "couponPackageCard": "超值券包（付费券包推销）",
    "saleCard": "快递卡券（年卡/亲情卡/E卡）",
}


# ── 基础工具 ──────────────────────────────────────────────────


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["log"]["entries"]


def host_of(url):
    try:
        return urllib.parse.urlsplit(url).netloc
    except Exception:
        return "?"


def path_of(url):
    try:
        return urllib.parse.urlsplit(url).path or "/"
    except Exception:
        return "/"


def _b64(text):
    if not text:
        return None
    s = text.strip()
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s)
    except Exception:
        return None


def resp_text(entry):
    """响应体文本，兼容 base64 编码。"""
    content = entry.get("response", {}).get("content") or {}
    text = content.get("text")
    if not text:
        return None
    if content.get("encoding") == "base64":
        raw = _b64(text)
        return raw.decode("utf-8", "replace") if raw else None
    return text


def req_text(entry):
    """请求体：京东这套是 base64(JSON)，解不开就返回原文。"""
    post = entry["request"].get("postData") or {}
    text = post.get("text")
    if not text:
        return ""
    raw = _b64(text)
    if raw:
        try:
            s = raw.decode("utf-8")
            if s.lstrip()[:1] in "[{":
                return s
        except Exception:
            pass
    try:
        return urllib.parse.unquote_plus(text)
    except Exception:
        return text


def try_json(entry):
    text = resp_text(entry)
    if not text or text.lstrip()[:1] not in "{[":
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def walk(node, path="$"):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


# ── 子命令 ────────────────────────────────────────────────────


def cmd_summary(entries):
    print(f"请求总数: {len(entries)}")
    print("协议:", dict(collections.Counter(e["request"]["url"].split(":", 1)[0] for e in entries)))
    print("响应状态:", dict(collections.Counter(e["response"]["status"] for e in entries)))
    hosts = collections.Counter(host_of(e["request"]["url"]) for e in entries)
    print(f"域名数: {len(hosts)}")


def cmd_check(entries):
    https = [e for e in entries if e["request"]["url"].startswith("https://")]
    biz = [e for e in https if BIZ_HOST_PATTERN.search(host_of(e["request"]["url"]))]
    gw = [e for e in https if host_of(e["request"]["url"]) == GATEWAY]

    print("\n=== MITM 自检 ===")
    print(f"  HTTPS 请求  {len(https)}")
    print(f"  京东业务域  {len(biz)}")
    print(f"  其中 lop-proxy 网关  {len(gw)}")

    if not https:
        print("\n❌ 没有任何 HTTPS 请求 —— MITM 完全没有解密。")
        print("   插件里的 [Rewrite] 一条都不会执行，此时分析广告字段没有意义。")
        return False
    if not gw:
        print("\n⚠️  抓到了京东流量，但没有一条落在 lop-proxy.jd.com。")
        print("   常见原因：[MITM] hostname 没覆盖这个网关，或者这次只开了别的页面。")
        return False

    print("\n✅ 解密正常。插件默认的 [MITM] 只需要 lop-proxy.jd.com，已覆盖。")
    return True


def cmd_hosts(entries):
    hosts = collections.Counter(host_of(e["request"]["url"]) for e in entries)
    print(f"\n=== 请求域名 {len(hosts)} 个 ===")
    for h, c in hosts.most_common():
        tag = ""
        if PROTECTED_PATTERN.search(h):
            tag = "  [风控/登录·勿拦]"
        elif TRACK_PATTERN.search(h):
            tag = "  [埋点]"
        print(f"{c:6d}  {h}{tag}")


def cmd_map(entries):
    rows = {}
    for e in entries:
        if host_of(e["request"]["url"]) != GATEWAY:
            continue
        key = path_of(e["request"]["url"])
        if key in rows:
            continue
        obj = try_json(e)
        size = len(resp_text(e) or "")
        if obj is None:
            shape = "加密串/非 JSON，改不了" if ENCRYPTED_HINT.search(key) else "非 JSON"
        elif isinstance(obj, dict):
            shape = ",".join(list(obj.keys())[:6])
            for v in obj.values():
                if isinstance(v, dict):
                    shape += " | " + ",".join(list(v.keys())[:8])
                    break
        else:
            shape = f"list[{len(obj)}]"
        rows[key] = (size, shape[:150], req_text(e)[:160])

    print(f"\n=== lop-proxy 接口地图 {len(rows)} 个 ===")
    for k in sorted(rows):
        size, shape, req = rows[k]
        print(f"\n  {k}   {size}B")
        print(f"    resp: {shape}")
        if req:
            print(f"    req : {req[:150]}")


def cmd_feeds(entries):
    hit = 0
    for e in entries:
        if "getHomePageFeedCards" not in e["request"]["url"]:
            continue
        obj = try_json(e)
        if not obj:
            continue
        content = obj.get("content") or {}
        cards = content.get("cardList") or []
        if not isinstance(cards, list):
            continue
        hit += 1
        kinds = collections.Counter()
        for c in cards:
            if not isinstance(c, dict):
                continue
            sub = [k for k in c if k.endswith("Card")]
            kinds[sub[0] if sub else "?"] += 1
        print(f"\n=== 首页「为您推荐」 {content.get('title')!r} / {content.get('desc')!r} ===")
        print(f"卡片 {len(cards)} 张，响应体 {len(resp_text(e) or '')}B")
        for k, n in kinds.most_common():
            print(f"  {n:4d}  {k:<20} {CARD_KIND.get(k, '')}")
        break
    if not hit:
        print("\n没抓到 getHomePageFeedCards。这个接口在首页「为您推荐」出现时才会打。")
    return hit


# 投放决策接口：广告（含开屏）下发的总闸。请求体里带 sceneKey。
DECISION_ENDPOINTS = {
    "/decision": "//decision",
    "querySmartDecision": "smartmp/querySmartDecision",
}

# sceneKey 的人类可读名（冷启动抓包实测到的 15 个）
SCENE_KIND = {
    "jdl_splash_screen": "开屏广告 ← 就是它",
    "app_jdkd_tab_benefit_popup": "底部「福利」tab 弹窗",
    "app_jdkd_home_popup": "首页弹窗",
    "jdl_home_feed_card": "首页推荐流插卡",
    "jdl_home_feed_fwj_card": "首页推荐流服务加卡片",
    "jdl_search_bubble": "搜索框气泡",
    "jdl_search_textbanner": "搜索页文字链",
    "jdl_search_follow_banner": "搜索结果关注 banner",
    "jdl_search_follow_bubble": "搜索结果关注气泡",
    "jdl_search_receive_banner": "收件搜索结果 banner",
    "jdl_search_receive_bubble": "收件搜索结果气泡",
    "h5_send_card_banner": "寄件页卡片 banner",
    "h5_rece_card_banner": "收件页卡片 banner",
    "jdl_detail_banner": "运单详情页 banner",
    "jdl_detail_bubble": "运单详情页气泡",
}


def cmd_scenes(entries):
    """把投放决策接口的 sceneKey 全部挖出来。

    规则没法匹配请求体，所以改不了「只杀开屏、留着别的」——
    但知道开屏叫 jdl_splash_screen，至少能确认它确实走这条通道、
    以及整体置空 data 是否真的覆盖到了它。
    """
    seen = {}
    for e in entries:
        url = e["request"]["url"]
        path = path_of(url)
        hit = next((label for k, label in DECISION_ENDPOINTS.items() if k in path), None)
        if not hit:
            continue
        body = req_text(e)
        if not body.lstrip().startswith(("[", "{")):
            continue
        try:
            payload = json.loads(body)
        except Exception:
            continue
        items = payload if isinstance(payload, list) else [payload]
        resp = try_json(e) or {}
        for it in items:
            if not isinstance(it, dict):
                continue
            key = it.get("sceneKey") or it.get("scene") or "?"
            data = resp.get("data")
            if isinstance(data, list):
                state = f"data=[]" if not data else f"data[{len(data)}]  ← 有投放"
            elif isinstance(data, dict):
                state = f"data={{}}" if not data else f"data{{{len(data)}}}  ← 有投放"
            else:
                state = f"data={data!r}"
            slot = seen.setdefault(key, {"n": 0, "ep": set(), "state": set()})
            slot["n"] += 1
            slot["ep"].add(hit)
            slot["state"].add(state)

    if not seen:
        print("\n没抓到 //decision 或 querySmartDecision。")
        print("这两个接口只在启动/进特定页面时打，抓包时要覆盖冷启动。")
        return 0

    print(f"\n=== 投放决策场景 {len(seen)} 个 ===")
    # 开屏永远排第一 —— 它是这份插件最初存在的理由
    for key in sorted(seen, key=lambda k: (k != "jdl_splash_screen", -seen[k]["n"], k)):
        slot = seen[key]
        kind = SCENE_KIND.get(key, "")
        print(f"\n  {key}   x{slot['n']}")
        if kind:
            print(f"     {kind}")
        print(f"     接口 {'、'.join(sorted(slot['ep']))}")
        print(f"     响应 {' / '.join(sorted(slot['state']))}")

    print("\n注意：规则只能匹配 URL，匹配不到请求体里的 sceneKey。")
    print("所以「只去开屏、留别的」做不到，A 级规则是整条通道一起置空。")
    print("上面显示 data 非空的场景，就是当前还在给你下发广告的。")
    return len(seen)


def cmd_scan_ads(entries):
    json_entries = [(e, try_json(e)) for e in entries]
    json_entries = [(e, o) for e, o in json_entries if o is not None]
    print(f"\n=== 可解析的 JSON 响应 {len(json_entries)} 条 ===")

    hits = 0
    for e, obj in json_entries:
        url = e["request"]["url"]
        found = []
        for path, val in walk(obj):
            key = path.rsplit(".", 1)[-1].split("[")[0]
            if AD_KEY_PATTERN.search(key):
                found.append((path, f"字段名 {key}"))
                continue
            if not isinstance(val, dict):
                continue
            tv = val.get("cardType") or val.get("bizType") or val.get("type")
            if isinstance(tv, str) and AD_VALUE_PATTERN.search(tv):
                found.append((f"{path}.cardType", f"类型 = {tv}"))
            for tk in ("title", "name", "contentTitle"):
                nv = val.get(tk)
                if isinstance(nv, str) and AD_TITLE_PATTERN.search(nv):
                    found.append((f"{path}.{tk}", f"标题 = {nv}"))
                    break
        if not found:
            continue
        hits += 1
        print(f"\n--- {host_of(url)}{path_of(url)[:70]}")
        seen = set()
        for path, why in found[:8]:
            if path in seen:
                continue
            seen.add(path)
            print(f"    {path}\n        ← {why}")

    if hits:
        print(f"\n命中 {hits} 条响应。改字段用 response-body-json-jq，不要整包 reject。")
    else:
        print("\n没有命中。京东这套的广告字段叫 freeRightCard / retailProductCard 这类")
        print("「渲染器字段」，不像传统广告那样带 ad 字样，用 --feeds 看更准。")


def cmd_verify(entries, plugin_path):
    try:
        import jq  # noqa: F401
    except ImportError:
        print("需要 jq 模块：python -m pip install jq", file=sys.stderr)
        return 2

    import jq as jqmod

    if not os.path.exists(plugin_path):
        print(f"插件不存在: {plugin_path}", file=sys.stderr)
        return 2

    rule_re = re.compile(r"^(\S+)\s+response-body-json-jq\s+'(.*)'\s*$")
    rules = []
    with open(plugin_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            m = rule_re.match(s)
            if m:
                rules.append((lineno, m.group(1), m.group(2)))

    if not rules:
        print("插件里没有启用的 response-body-json-jq 规则（可能都被注释了）。")
        return 0

    print(f"\n=== 校验 {len(rules)} 条启用的改写规则 ===")
    total_ok = total_miss = total_fail = 0

    for lineno, pattern, expr in rules:
        try:
            compiled = jqmod.compile(expr)
        except Exception as exc:
            print(f"\n✗ 第 {lineno} 行 表达式编译失败: {exc}")
            total_fail += 1
            continue

        try:
            regex = re.compile(pattern)
        except re.error as exc:
            print(f"\n✗ 第 {lineno} 行 正则编译失败: {exc}")
            total_fail += 1
            continue

        print(f"\n--- 第 {lineno} 行  {pattern}")
        matched = 0
        for e in entries:
            url = e["request"]["url"]
            if not regex.search(url):
                continue
            obj = try_json(e)
            if obj is None:
                continue
            matched += 1
            before = len(resp_text(e) or "")
            try:
                after_obj = jqmod.first(expr, obj)
            except Exception as exc:
                print(f"    ✗ {path_of(url)}  执行失败: {exc}")
                total_fail += 1
                continue
            # jq 输出是紧凑 JSON，这里也按紧凑算，否则字节数会被空格污染
            after = len(json.dumps(after_obj, ensure_ascii=False, separators=(",", ":")))
            delta = after - before
            extra = ""
            try:
                b = obj["content"]["cardList"]
                a = after_obj["content"]["cardList"]
                if isinstance(b, list) and isinstance(a, list):
                    extra = f"  卡片 {len(b)} → {len(a)}"
            except Exception:
                pass
            flag = "✓" if delta < 0 else "·"
            print(f"    {flag} {path_of(url):<40} {before:>7}B → {after:>7}B ({delta:+d}){extra}")
            total_ok += 1

        if matched == 0:
            print("    （本次抓包里没有命中样本，无法验证）")
            total_miss += 1

    print(f"\n命中样本 {total_ok} 条，无样本规则 {total_miss} 条，失败 {total_fail} 条。")
    return 0 if total_fail == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="京东快递 App HAR 抓包分析，辅助维护 Loon 去广告插件")
    ap.add_argument("har", help="HAR 文件路径")
    ap.add_argument("--check", action="store_true", help="检查 MITM 是否真的解密（先跑这个）")
    ap.add_argument("--hosts", action="store_true", help="请求域名排行")
    ap.add_argument("--map", action="store_true", help="lop-proxy 接口地图")
    ap.add_argument("--feeds", action="store_true", help="首页推荐流卡片类型统计")
    ap.add_argument("--scenes", action="store_true", help="投放决策接口的 sceneKey（开屏在哪）")
    ap.add_argument("--scan-ads", action="store_true", help="遍历 JSON 定位广告字段")
    ap.add_argument("--verify", nargs="?", const="JDKDAds.plugin", metavar="PLUGIN",
                    help="跑插件里的 jq 规则做前后对比（默认 JDKDAds.plugin）")
    ap.add_argument("--all", action="store_true", help="执行除 --verify 外的全部")
    args = ap.parse_args()

    try:
        entries = load(args.har)
    except FileNotFoundError:
        print(f"文件不存在: {args.har}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"HAR 解析失败: {exc}", file=sys.stderr)
        return 2

    flags = [args.check, args.hosts, args.map, args.feeds, args.scenes, args.scan_ads, args.all,
             args.verify is not None]
    if not any(flags):
        cmd_summary(entries)
        print("\n建议下一步：--check 确认 MITM 生效，--map 看接口，--feeds 看广告卡")
        return 0

    if args.all or args.check:
        cmd_check(entries)
    if args.all or args.hosts:
        cmd_hosts(entries)
    if args.all or args.map:
        cmd_map(entries)
    if args.all or args.feeds:
        cmd_feeds(entries)
    if args.all or args.scenes:
        cmd_scenes(entries)
    if args.all or args.scan_ads:
        cmd_scan_ads(entries)
    if args.verify is not None:
        return cmd_verify(entries, args.verify)
    return 0


if __name__ == "__main__":
    sys.exit(main())
