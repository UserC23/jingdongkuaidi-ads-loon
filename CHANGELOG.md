# 变更记录

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
