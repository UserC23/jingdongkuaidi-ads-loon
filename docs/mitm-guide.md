# 使用与调优指南

> 抓包结论见 [analysis.md](analysis.md)，版本变更见 [CHANGELOG.md](../CHANGELOG.md)。

---

## 零、先确认 MITM 真的在工作

这一步不做，插件一行都不会执行。

Loon → 设置 → **MitM**：

1. 打开 **MitM 开关**
2. **证书管理 → 生成证书 → 安装**，按系统提示装好描述文件
3. 装完**必须**再去这里打开开关：
   **设置 → 通用 → 关于本机 → 证书信任设置 → 找到 Loon 的证书 → 启用完全信任**

> 第 3 步是最常漏的一步。只在「VPN与设备管理」里看到证书**不算信任**。
> 没打开这个开关，Loon 只能看到域名（CONNECT），拿不到任何响应体，
> `response-body-json-jq` 全部失效 —— 表现就是「装了跟没装一样」。

### 30 秒验证

打开 Loon 的**请求日志**，然后进京东快递首页。

- 日志里应该出现 `https://lop-proxy.jd.com/getHomePageFeedCards` 这种**完整 URL**，点开能看响应体
- 如果只显示 `CONNECT`，或者压根没有 `lop-proxy` 的请求 → MITM 没生效，回第 3 步

已经抓了包的，直接用脚本判：

```bash
python tools/analyze_har.py 你的抓包.har --check
```

- `❌ 没有任何 HTTPS 请求` → MITM 没解密，插件一行没跑
- `⚠️ 没有一条落在 lop-proxy.jd.com` → 网关没进 MITM 范围，或者这次没开首页
- `✅ 解密正常` → 继续

---

## 一、安装

1. Loon → 配置 → 插件 → 右上角 `+` → 从 URL 添加：

```
https://fastly.jsdelivr.net/gh/UserC23/jingdongkuaidi-ads-loon@<commit-sha>/JDKDAds.plugin
```

2. 确认插件开关为**启用**
3. 确认 `[MITM]` 里的 `lop-proxy.jd.com` 已经进了 Loon 的 MITM 主机列表（插件会自动追加，但如果你手动改过 hostname 就要自己核对）
4. 京东快递 **上滑彻底杀掉**，重新打开

> **别用 `@main`。** jsDelivr 对 GitHub 仓库的 `@main` 有缓存，
> 推送后短时间可能仍拿到旧文件，`purge.jsdelivr.net` 也不一定刷得掉。
> 固定 commit SHA 是内容寻址的，永远拿到确切版本。
>
> 判断拿到的是不是新版：插件文件第二行 `#!desc=` 里的版本号和字节数，
> 和仓库里的一致就对了。

---

## 二、插件结构

| 层 | 手段 | 打什么 | 默认 |
|---|---|---|---|
| A | `response-body-json-jq` | 投放决策通道 `//decision`、`smartmp/querySmartDecision` 的 `data` 置空 | ✅ |
| B | `response-body-json-jq` | 首页「为您推荐」删 `freeRightCard` + `retailProductCard`（60 → 12 张） | ✅ |
| C | `response-body-json-jq` | 首页运营位 `homeBanner` / `homeYingxiao` 清空 | ✅ |
| D | `response-body-json-jq` | 我的页推广位、京彩 banner、秒杀、第三方权益、服务推荐流、到家竞价店 | ❌ |

### 为什么全是 jq，一条 `reject` 都没有

京东这套接口统一外壳：

```json
{"code":1,"content":{...},"success":true}
```

`reject` / `reject-dict` 返回的是 `{}` 或断连。App 拿到 `{}` 后 `content` 是 null，
会走进错误分支 —— 轻则弹「网络开小差」，重则该模块一直重试。

所以这里一律**保留外壳、只改字段**：

```jq
if (.content.cardList|type)=="array"
then .content.cardList |= map(select(...))
else . end
```

`if ... else . end` 这层壳是防御性的：万一接口改版、`content` 变成字符串，
表达式会原样返回，不会把响应搞坏。**所有规则都套了这一层。**

### 为什么 `[MITM]` 只有 lop-proxy.jd.com

京东快递的业务接口 159 条全在这一个网关上。不写 `*.jd.com` 是刻意的：

- `api.m.jd.com` 是京东全系主网关，解密它等于把京东 App 的流量全过一遍，耗电明显
- `img*.360buyimg.com` / `*.jdcloud-oss.com` 是图片和静态资源，解密纯浪费

只有一个例外：想用 D7「到家店铺广告」那条，才需要把 `api.m.jd.com` 加进去。

---

## 三、还有广告怎么办

别猜，用脚本定位。

### 1. 抓一段有效抓包

前提：`--check` 能过。抓的时候：

- 清空 Loon 日志 → 杀掉京东快递 → 重开
- 在**有广告的那个页面**停留 15~30 秒，瀑布流滑到底
- 导出 HAR

> 想抓开屏广告必须**先开抓包再冷启动 App**。开屏不是独立接口，它是
> `//decision` 的一个 `sceneKey`，`--scenes` 能直接把它指出来。
>
> 冷启动样本已经补齐了（v2）：开屏素材是 `riskimg.360buyimg.com` 上一张 555KB 的
> 双 11 会场大图。如果哪天换了个投放形式，重新抓一次冷启动再跑 `--scenes` 就能看到。

### 2. 先看接口地图

```bash
python tools/analyze_har.py 抓包.har --map
```

输出会解出每个接口的 base64 请求体和响应顶层结构，长这样：

```
  /getHomePageFeedCards   24976B
    resp: code,content,data,errorMsg,msg,success | cardList,desc,title
    req : [{"eid":"","pin":"","client":"apple",...}]
```

新出现的路径直接就是候选。

### 3. 再看归因

```bash
python tools/analyze_har.py 抓包.har --feeds      # 首页卡片都是什么类型
python tools/analyze_har.py 抓包.har --scenes     # 投放决策的 sceneKey，开屏排第一
python tools/analyze_har.py 抓包.har --scan-ads   # 哪些字段像广告位
```

`--scenes` 是给弹窗/开屏/插卡这类「看不见的投放」用的：

```
=== 投放决策场景 15 个 ===

  jdl_splash_screen   x1
     开屏广告 ← 就是它
     接口 //decision
     响应 data[1]  ← 有投放          ← 这个状态就说明它正在给你下发
```

`data` 非空的场景就是当前还在投的。反之 `data=[]` 说明已经被插件挡下来了。

`--feeds` 会把 `getHomePageFeedCards` 的卡片按子对象名分桶：

```
卡片 60 张，响应体 24976B
    46  freeRightCard        权益免费领（第三方联合会员）
     8  couponPackageCard    超值券包（付费券包推销）
```

比 `--scan-ads` 准 —— 京东的广告字段不叫 `ad`，叫 `freeRightCard`，
正则匹配不到这种命名。

### 4. 补规则并验证

按子对象名删卡：

```
^https?://lop-proxy\.jd\.com/getHomePageFeedCards response-body-json-jq 'if (.content.cardList|type)=="array" then .content.cardList |= map(select(((type=="object" and (has("freeRightCard")))|not))) else . end'
```

**改完必须跑 `--verify`**：

```bash
python tools/analyze_har.py 抓包.har --verify
```

它会解析插件里所有启用的 `response-body-json-jq` 行，拿真实响应跑一遍，
输出字节数变化：

```
--- 第 142 行  ^https?://lop-proxy\.jd\.com/getHomePageFeedCards
    ✓ /getHomePageFeedCards    24976B → 4373B (-20603)  卡片 60 → 12
```

看到 `✗ 执行失败` 就是 jq 表达式写错了（括号、引号、`has()` 用在非对象上）。
看到「本次抓包里没有命中样本」说明正则没匹配到，回头核对你抓的是不是那个接口。

---

## 四、排错表

| 现象 | 原因 | 处理 |
|---|---|---|
| 一点变化都没有 | MITM 没生效（最常见），或插件没启用 | 跑 `--check`；确认证书「完全信任」 |
| 日志里只有 CONNECT | 证书没在「证书信任设置」里打开 | 零、第 3 步 |
| 首页推荐流少了一半，但没有全空 | **正常** —— B 级就是删广告卡，留自家券包 | 想更干净开 D6 |
| 首页推荐流整块空白 | 开了 D6（整块清空） | 注释 D6，用 B 级 |
| 我的页少了一排入口 | 开了 D1 | 注释 D1 |
| 抢不到 0.01 元券了 | 开了 D3（秒杀列表被清空） | 注释 D3 |
| 弹「网络开小差」 | 有人把规则改成了 `reject` / jq 表达式抛错 | 改回 `response-body-json-jq`，并补 `if ... else . end` |
| 京东 App 变卡 | MITM hostname 写了 `*.jd.com` | 改回只有 `lop-proxy.jd.com` |
| 改完没反应 | jsDelivr 缓存 | 地址换成具体 commit SHA；或杀 App 重开 |
| 订单/物流页错乱 | 误删了 `queryMoreFeaturesSectionsNew` 等功能位 | 那是特色寄件入口，不是广告 |

---

## 五、声明

规则来自本项目对京东快递 1.7.7 真机抓包的分析，随 App 版本变化可能失效。
App 升级后如果广告复现，按第三节流程重新定位即可。

仅供个人学习自用，请自行评估风险。
