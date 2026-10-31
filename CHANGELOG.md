# 变更记录

## v2 — 2026-10-31

补上开屏。新增第二次抓包作为对照：**冷启动 1001 条请求 / 44 域名**（已装 v1 插件），
和 v1 的基线样本（674 条 / 34 域名，未装插件）形成 A/B。

后续又补了一份 **冷启动 1051 条 / 42 域名（未装插件）**，三份样本互为对照：

| 样本 | 开屏 `jdl_splash_screen` | 投放决策命中 | 广告素材图下载 |
|---|---|---|---|
| A 未装 / 常驻 | `data[1]` 557B | 14 条 | 4 张（1.1MB） |
| B 已装 / 冷启动 | `data[]` | 0 条 | **0 张** |
| C 未装 / 冷启动 | `data[]` | **23 条** | 14 张 |

C 样本修正了 v2 初版一个不够严谨的判断：**开屏是「时投时不投」的**，
三次里只投中一次，所以「某次没看到开屏」不能当作插件生效的证据。
真正的证据是投放命中 23 条 payload → 0、素材图 14 张 → 0。

### 开屏的真相

开屏**没有独立接口**，它和首页推荐流插卡共用同一个投放决策接口，靠请求体里的 `sceneKey` 区分：

```
POST https://lop-proxy.jd.com//decision
[{"sceneKey":"jdl_splash_screen","deviceInfo":{...},"applicationInfo":{...}}]
```

C 样本里唯一投中的那次长这样：一张 555KB 的双 11 会场大图
（`riskimg.360buyimg.com`），点击跳 `pro.m.jd.com/mall/active/...`。

规则覆盖的是**整条通道**：15 个 `sceneKey` 全部置空。其中
`//decision` 5 个（开屏 / 福利 tab 弹窗 / 首页弹窗 / 推荐流插卡 / 推荐流服务加卡），
`smartmp/querySmartDecision` 10 个（搜索框气泡、搜索页 banner、寄件收件卡片 banner、运单详情页 banner 等）。
规则只能匹配 URL、匹配不到请求体，所以做不到「只杀开屏、留别的」—— 好在这 15 个场景全是商业投放。

C 样本实测：`//decision` 5081B → 85B（清掉 6 条商城导购卡），
`querySmartDecision` 1964B → 85B ×2（运单详情页 4 条 banner）。

### 补一条容易漏的：投放通道会往推荐流里塞卡

C 样本里 `jdl_home_feed_card` 塞了 6 条，**全部不在 `getHomePageFeedCards` 里**：
5 条京东商城双 11 会场、1 条问卷（`wj-dongjian.jd.com`）、1 条商品详情（`item.jd.com`）。
光删接口里那 60 张卡，这 6 条照样会插进「为您推荐」—— 必须靠 A 级一起清。

### 新增：A2 启动新人弹窗（默认开启）

v1 真正漏掉的是这条，不是开屏。冷启动第 4 个请求就返回一整屏「新人弹窗-快运-8折」图片，
点「领取」跳 `jingcai-h5` 领券页。它是独立接口，不走决策通道，所以 A 级规则管不到。

```
//home/queryNewPersonSceneDisplayContent → content.contentDTO 置 null
840B → 193B
```

保留 `businessLine` / `isNewPerson` / `couponDetail`，只挖掉渲染器依赖的那个节点。
少数版本若不保护 nil 导致空白弹窗，把该行注释掉即可。

### 规则健壮性

A 级的两个决策接口改成双分支：

```jq
if (.data|type)=="array" then .data=[] elif (.data|type)=="object" then .data={} else . end
```

v1 只处理数组。后端一旦把 `data` 改成对象，旧规则会静默失效 —— jq 不报错，你不会知道它没生效。

### 新增可选规则（D8–D12，默认关闭）

- D8 京彩 tab 红点气泡（`ContentApi/queryContentInfo`，按 `contentCode` 精准命中，不误伤同接口的分享卡片）
- D9 首页模块总开关（`MissionApi/queryHomePageConfig`，banner / 券包 / 秒杀卡 / 积分商城 / 京豆 / 活动区强制 false）
- D10 试用福袋（`getJDTrialList`，1 分钱奶粉 / 避孕套，京东商城导购）
- D11 年卡售卖页（`saleProductApiService/getProductListNew`，8 个付费产品）
- D12 推荐流连券包一起删（12 张 → 4 张，4373B → 1605B）

### 新增可选兜底：广告素材 CDN

`riskimg.360buyimg.com` 在三份抓包里只被广告接口引用，没有一条业务图走它。
首页卡片的图床分得很干净 —— 只有删掉的 `freeRightCard` 用它，
留着的 `couponPackageCard`（`wlimg10`）和 `saleCard`（`jfe.s3`）都不沾。
未装插件那次下了 14 张图（单张最大 533KB），装了插件 0 张。
`DOMAIN,riskimg.360buyimg.com,REJECT` 默认关闭，属防回归 —— 不默认开是因为
D3 秒杀列表和 D4 权益页的图也在它上面，那两个页面默认还看得见。

### 工具

- 新增 `--scenes`：把 `//decision` 和 `querySmartDecision` 请求体里的 `sceneKey` 全挖出来，
  标出每个场景这次的 `data` 是否为空。开屏永远排第一行
- `--verify` 支持多轮回归：v2 的 5 条规则在三份样本上分别是 17 / 20 / 27 条命中，0 失败

### 冷启动里排掉的两个误判

- `/explore` 名字像「发现」，实际是**地址 POI 搜索**（返回酒店 / 小区 / 楼栋），寄件选地址要用 —— 不动
- `rightsmall/queryRightsListByMarketingPlacementId` 是**京豆兑券**活动，属于用户权益不是广告 —— 不做规则

---

## v1 — 2026-10-31

首个版本。基于京东快递 `1.7.7`（iOS 27.0.1）真机抓包，样本 674 条请求 / 34 个域名 / 246 条京东业务域。

### 抓包定下的三件事

| # | 结论 | 对插件的影响 |
|---|---|---|
| 1 | 没有第三方广告 SDK。674 条请求全在 `jd.com` / `jdl.com` / `360buyimg.com` 自有域名下，没有 1RTB / 穿山甲 / TanX | 域名层无目标，`[Rule]` 基本留空；这和菜鸟那边正好相反 |
| 2 | 广告在业务网关的 JSON 里。`lop-proxy.jd.com` 一个域名装下首页 / 我的 / 京彩 / 会员 / 订单所有接口 | 全部用 `response-body-json-jq` 改字段 |
| 3 | 接口外壳统一 `{"code":1,"content":{...},"success":true}`，整包 `reject` 返回 `{}` 会让 App 走错误分支 | **一条 `reject` 都不用**，包括 `reject-dict` |

### 广告位实测

`getHomePageFeedCards`（首页「为您推荐」）一次返回 60 张卡：

| 数量 | 子对象 | 性质 | v1 处置 |
|---|---|---|---|
| 46 | `freeRightCard` | 权益免费领，第三方联合会员（腾讯视频 8.3 折） | **删** |
| 8 | `couponPackageCard` | 超值券包推销 | 保留 |
| 4 | `saleCard` | 快递年卡 / 亲情卡 / E卡 | 保留 |
| 2 | `retailProductCard` | 零售商品，跳 `djg.jd.com` 京东商城 | **删** |

跳转域名也印证了这条流的性质：60 张卡里 57 张跳 `jingcai-h5.jd.com`（京彩活动），
2 张跳 `djg.jd.com`（商城），1 张跳 `jpay.jd.com` —— **没有一张跳寄件流程**。

结果：60 张 → 12 张，响应体 24976B → 4373B。

### 默认开启

- **A 级 投放决策**：`//decision`（`jdl_home_feed_fwj_card`）、`smartmp/querySmartDecision`（`h5_rece_card_banner`）的 `data` 置空
- **B 级 首页推荐流**：删 `freeRightCard` + `retailProductCard`
- **C 级 首页运营位**：`homeBanner` / `homeYingxiao` 清空

### 默认关闭（D 级，按需开）

- D1 我的页推广入口 `minePromotion`
- D2 京彩 banner `findTestBanners`
- D3 秒杀列表 `flashSaleList`
- D4 第三方联合会员 `thirdPartyRights/rightsList`
- D5 服务加购推荐流 `getServicePlusFeed`
- D6 首页推荐流整块清空（与 B 级二选一）
- D7 到家店铺竞价广告 `isAd`（样本里全是 0，预防性规则）

### 刻意没动

| 对象 | 原因 |
|---|---|
| `queryMoreFeaturesSectionsNew` / `homeTeseji` | 特色寄件**功能入口**（寄生鲜 / 寄港澳 / 寄国际），不是广告 |
| `//moduleList` 的 `myAssets` / `myWallet` | 我的页资产和钱包，删了看不到余额 |
| `queryHomePageOrders` / `searchOrderEnhance` | 响应是 AES 密文，Loon 改不了，也不该碰 |
| `jra.jd.com` / `sdkfp.jd.com` | 风控指纹，拦了有触发风控风险 |

### 工程细节

- 所有 jq 表达式都套了 `if <类型判断> then ... else . end`，接口改版时原样返回，不会把响应搞坏
- 正则用 `/+path` 兼容 `https://lop-proxy.jd.com//decision` 这种双斜杠路径
- `[MITM]` 只写 `lop-proxy.jd.com`，不写 `*.jd.com`（避免解密 `api.m.jd.com` 全站流量）
- 自带 `tools/analyze_har.py --verify`：直接解析插件里启用的规则，拿真实 HAR 响应跑一遍，输出字节数与卡片数变化。v1 的四条规则实测 16 条命中样本、0 失败

### 已知缺口

- **开屏广告未覆盖**：抓包时 App 已在后台，没有冷启动样本。需要补一次冷启动抓包再定位
- 到家 `isAd` 规则无实际样本验证（10 家店全是 `isAd=0`），属预防性规则
