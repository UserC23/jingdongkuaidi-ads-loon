# jdkdads-loon

京东快递 App（`jdlogistic`）去广告 Loon 插件。

- 适用 App 版本：`1.7.7`（iOS，抓包基线）
- 需要：**开启 MITM + 安装证书 + 在「证书信任设置」里打开完全信任**
- 当前版本：**v2**
- 抓包分析：[docs/analysis.md](docs/analysis.md) ｜ 安装调试：[docs/mitm-guide.md](docs/mitm-guide.md)

---

## 这个插件能去掉什么

抓包基线两次：**常驻使用 674 条请求 / 34 域名**（未装插件）+ **冷启动 1001 条请求 / 44 域名**（已装 v1）。
核心发现是 —— **京东快递没有用第三方广告 SDK**，请求全部落在 `jd.com` / `jdl.com` / `360buyimg.com`
自有域名下，没有 1RTB、穿山甲、TanX。所以这个插件几乎不写域名规则，全部在响应体里改字段。

| 广告位 | 实际情况 | 处置 | 默认 |
|---|---|---|---|
| 开屏广告 | 不是独立接口，是 `//decision` 的一个场景（`sceneKey=jdl_splash_screen`） | `data` 置空 | ✅ |
| 启动「新人弹窗」 | 冷启动第 4 个请求就返回一整屏「新人弹窗-快运-8折」图片 | `contentDTO` 置 null | ✅ |
| 首页「为您推荐」瀑布流 | 60 张卡里 **46 张**是「权益免费领」（腾讯视频 8.3 折这类第三方联合会员），2 张是跳京东商城的商品导购 | 按卡片子对象名删除 | ✅ |
| 投放决策通道 | `//decision`（5 场景）、`smartmp/querySmartDecision`（10 场景） | `data` 置空 | ✅ |
| 首页运营位 | `homeBanner`（轮播图）、`homeYingxiao`（营销位） | 清空 | ✅ |
| 我的页推广入口 | 我的公益 / 包裹的旅行 / 秒送商家入驻 / POP商家入驻 | 清空 | ❌ |
| 京彩 tab banner | 拼团助力失败 banner、积分夺宝 | 清空 | ❌ |
| 秒杀列表 | 0.01 元快递券 | 清空 | ❌ |
| 第三方联合会员权益 | 腾讯视频 / 爱奇艺 整页（33 条） | 清空 | ❌ |
| 服务加购推荐流 | 空调维修 / 加氟 / 冰箱检测 | 清空 | ❌ |
| 到家竞价店 | `storeList[*].commonSrvMap.isAd` | 过滤 | ❌ |
| 京彩 tab 红点气泡 | 「免费领」「上新」 | 按 contentCode 置空文案 | ❌ |
| 首页模块开关 | banner / 券包 / 秒杀卡 / 积分商城 / 京豆 / 活动区 | 强制 false | ❌ |
| 试用福袋 | 1 分钱奶粉 / 避孕套（京东商城导购） | 清空 | ❌ |
| 年卡售卖页 | 8 个付费产品 | 清空 | ❌ |

默认开启的五项，实测效果：

```
开屏决策      557B → 85B     data[1] → data[]（那条 555KB 的双11 开屏大图不再下发）
新人弹窗      840B → 193B    contentDTO → null
首页推荐流   60 张卡 → 12 张  响应体 24976B → 4373B
```

留下的 12 张是快递券包 / 年卡 / E卡 / 亲情卡 —— 京东快递自家的付费产品，不是第三方广告，删了属于误伤。
想连券包一起删，把插件里 D12 那行放开，`12 张 → 4 张`。

**开屏怎么确认真的没了**：装上插件后清一次缓存、杀进程重开，抓包跑 `--scenes`：
`jdl_splash_screen` 那行的 `data` 应该是 `[]`；同时 `riskimg.360buyimg.com`（广告图 CDN）应该一次都不出现。

---

## 安装

### 1. 先开 MITM（不做这步，插件一行都不执行）

Loon → 设置 → **MitM** → 打开开关
→ **证书管理** → 生成并安装证书
→ 系统「设置 → 通用 → VPN与设备管理」安装描述文件
→ **系统「设置 → 通用 → 关于本机 → 证书信任设置」打开 Loon 证书的完全信任**

> 最后一步最容易漏。只在「VPN与设备管理」里看到证书**不算信任**，
> 此时 Loon 只能看到域名、拿不到响应体，所有 `response-body-json-jq` 全部失效 ——
> 表现就是「装了跟没装一样」。

### 2. 添加插件

Loon → 配置 → 插件 → 右上角 `+` → 从 URL 添加：

```
https://fastly.jsdelivr.net/gh/UserC23/jdkdads-loon@345d1610521ff079a746c4e4ff27f5129ad9ce6f/JDKDAds.plugin
```

> **请用上面这个固定 commit 地址，不要用 `@main`。**
> jsDelivr 对 GitHub 仓库的 `@main` 有缓存，推送后可能仍返回旧文件，
> `purge.jsdelivr.net` 也未必刷得掉（同作者的 cnads-loon 就永久卡在 v1 过）。
> 固定 SHA 是内容寻址的，永远拿到确切版本。
>
> 换成别的版本时，去仓库 Commits 页面复制对应提交的 40 位完整哈希替换即可。

### 3. 重启 App

京东快递 **上滑彻底杀掉**再重开。只切后台无效，响应有缓存。

---

## 规则长什么样

只有一种手段：`response-body-json-jq`。因为京东这套接口统一外壳
`{"code":1,"content":{...},"success":true}`，整包 `reject` 返回 `{}` 会让 App
走进错误分支（弹「网络开小差」或一直重试）。

删首页广告卡：

```jq
if (.content.cardList|type)=="array"
then .content.cardList |= map(select(((type=="object" and (has("retailProductCard") or has("freeRightCard")))|not)))
else . end
```

`if ... else . end` 这层壳是防御性的：接口改版、字段变字符串时原样返回，不把响应搞坏。

**为什么按子对象名删、不按 `cardType` 数字删**：`cardType` 是后端排版枚举，改版会重排；
`retailProductCard` / `freeRightCard` 是客户端渲染器认的字段名，要改必须同时改客户端，反而更稳。

---

## 验证 / 排查

仓库自带分析脚本，规则改完必须跑一遍 —— 光看语法对不对没用，要拿真实响应喂进去。

```bash
python -m pip install jq

python tools/analyze_har.py 抓包.har --check     # MITM 有没有真在解密（先跑这个）
python tools/analyze_har.py 抓包.har --map       # lop-proxy 接口地图（解码 base64 请求体）
python tools/analyze_har.py 抓包.har --feeds     # 首页卡片类型统计
python tools/analyze_har.py 抓包.har --scenes    # 投放决策的 sceneKey，开屏排第一
python tools/analyze_har.py 抓包.har --scan-ads  # 哪些字段像广告位
python tools/analyze_har.py 抓包.har --verify    # 把插件里启用的 jq 规则跑一遍，看前后变化
```

`--verify` 直接解析 `JDKDAds.plugin` 里的 `response-body-json-jq` 行，输出：

```
--- 第 145 行  ^https?://lop-proxy\.jd\.com/getHomePageFeedCards
    ✓ /getHomePageFeedCards    24976B → 4373B (-20603)  卡片 60 → 12
```

`--scenes` 是 v2 新加的，用来回答「开屏到底在哪」：

```
=== 投放决策场景 15 个 ===

  jdl_splash_screen   x1
     开屏广告 ← 就是它
     接口 //decision
     响应 data=[]          ← 空就是已经挡住了
```

`--check` 是前置条件：如果输出 `❌ 没有任何 HTTPS 请求`，说明 MITM 没生效，
此时任何分析都没有意义。

---

## 文件结构

```
JDKDAds.plugin                Loon 插件（主文件，直接装这个）
rules/JDKDAds-track.list      埋点域名列表（可选，不是去广告，是瘦身）
docs/analysis.md              抓包分析：两次样本 / 开屏 sceneKey / 广告面清单
docs/mitm-guide.md            安装、验证、定位残留广告、排错表
tools/analyze_har.py          HAR 分析脚本（--check / --map / --feeds / --scenes / --verify）
CHANGELOG.md                  版本记录
```

---

## 与其他 App 的差异

同一作者在菜鸟那边（[cnads-loon](https://github.com/UserC23/cnads-loon)）的做法完全不同：

| | 菜鸟 | 京东快递 |
|---|---|---|
| 第三方广告 SDK | 有（1RTB、穿山甲、TanX） | **没有** |
| 域名层能否拦 | 能，14 个域名 | 不能，广告和业务同域 |
| 主要手段 | `reject-dict` + 域名 REJECT | 纯 `response-body-json-jq` |
| MITM 范围 | `*.cainiao.com` + 3 个淘宝网关 | 只有 `lop-proxy.jd.com` |

---

## 免责

规则来自本项目对京东快递 1.7.7 的真机抓包分析，随 App 版本变化可能失效。
仅供个人学习自用，请自行评估风险。
