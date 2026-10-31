# 京东快递 App HAR 抓包分析（v1 基线）

- 抓包设备：iPhone（`iPhone18,1`，iOS 27.0.1）
- App：京东快递 `jdlogistic` 1.7.7，appId 1372
- 抓包方式：Loon 全局代理导出 HAR
- 样本：**674 条请求 / 34 个域名 / 246 条京东业务域**

原始 HAR 不入库（见 `.gitignore`），本文是分析结论。

---

## 一、先回答最关心的那个问题：域名层有没有东西可拦？

**没有。**

674 条请求全部落在这些域：

| 请求数 | 域名 | 性质 |
| --- | --- | --- |
| 203 | `saturn.jd.com` | 埋点上报（`/log/sdk`） |
| 159 | `lop-proxy.jd.com` | **业务接口网关** |
| 86 | `uranus.jd.com` | 埋点 |
| 41 | `h5speed.m.jd.com` | 活动页埋点 / 规则 |
| 22 | `api.m.jd.com` | 京东主网关（到家门店页等） |
| 19 | `arsenal.jdl.com` | 图标 CDN |
| 17 | `wmm.360buyimg.com` | 商品图 |
| 其余 | `*.jd.com` / `*.jdl.com` / `*.360buyimg.com` / `*.jdcloud-oss.com` | 登录、风控、静态资源 |

**没有 1RTB、没有穿山甲/巨量、没有 TanX、没有汇川。** 京东快递的广告是自己家广告平台（京准通）通过业务网关下发的 JSON —— 也就是说，**广告和业务共用同一个域名**，按域名拦等于拦业务。

这条结论直接决定了插件的形态：这个插件几乎不写 `[Rule]`，全部用 `response-body-json-jq` 在响应体里改字段。

> 对比参考：菜鸟那边 `1rtb.net` / `pglstatp-toutiao.com` / `tanx.com` 都在，域名层有明确目标；京东快递没有。

---

## 二、业务接口都挤在一个网关上

`lop-proxy.jd.com` 一个域名装下了首页、我的、京彩、会员、任务、订单所有 JSON。典型特征：

- 全部 POST
- 请求体是 **base64(JSON)**
- 响应体是**明文 JSON**，统一外壳：`{"code":1,"content":{...},"success":true}`
- 路径里会出现**双斜杠**：`https://lop-proxy.jd.com//decision`、`//moduleList`

最后这条很关键，写正则时 `^https?://lop-proxy\.jd\.com/+decision` 里的 `/+` 就是为了兼容单双斜杠。

### 接口地图（节选，完整用 `--map` 跑）

| 路径 | 大小 | 作用 |
| --- | --- | --- |
| `/getHomePageFeedCards` | 24.9KB | **首页「为您推荐」瀑布流，60 张卡** |
| `/getServicePlusFeed` | 6.5KB | 服务加购推荐流（空调维修/加氟…） |
| `/flashsale/flashSaleList` | 8.7KB | 秒杀列表（0.01 元券） |
| `/thirdPartyRights/rightsList` | 14.7KB | 第三方联合会员权益（腾讯视频…） |
| `/program/findTestBanners` | 1.3KB | 京彩 tab 活动 banner |
| `//queryHomeMainInfo` | 1.4KB | 首页运营位：`homeBanner` / `homeYingxiao` / `homeTeseji` |
| `//moduleList` | 6.6KB | 我的页：`minePromotion` 推广入口 |
| `queryMoreFeaturesSectionsNew` | 12.5KB | 特色寄件功能位（**不是广告，别删**） |
| `//decision` | 0.1~5.3KB | **投放决策**：`sceneKey=jdl_home_feed_fwj_card` |
| `/smartmp/querySmartDecision` | 0.6KB | **投放决策**：`sceneKey=h5_rece_card_banner` |
| `//queryHomePageOrders` | 92.7KB | 订单列表，**响应加密改不了** |
| `/order/searchOrderEnhance` | 0.1KB | 订单搜索，**响应加密改不了** |

---

## 三、真正的广告在哪：首页 60 张卡

`getHomePageFeedCards` 返回 `content.title = "为您推荐"`、`desc = "优惠好价天天享"`，一次 60 张卡：

| 数量 | 子对象 | 是什么 | 处置 |
| --- | --- | --- | --- |
| 46 | `freeRightCard` | 「权益免费领」—— 腾讯视频 8.3 折月卡这类第三方联合会员，跳 `jingcai-h5.jd.com#/receiveRights` | **删** |
| 8 | `couponPackageCard` | 「超值券包」付费券包推销（1.9 元抵 210 元） | 保留 |
| 4 | `saleCard` | 快递年卡·PLUS联名 / 寄件省钱卡 / 亲情卡 / E卡 | 保留 |
| 2 | `retailProductCard` | 「零售商品」—— 桌游、玩具，跳 `djg.jd.com` 京东商城 | **删** |

60 张里 48 张是第三方导购/权益广告，占比 **80%**。

跳转域名统计也印证了：60 张卡里 57 张跳 `jingcai-h5.jd.com`（京彩），2 张跳 `djg.jd.com`（京东商城），1 张跳 `jpay.jd.com`。**没有一张跳自家的寄件流程** —— 这就是一条纯广告流。

### 为什么按子对象名删，而不是按 cardType 数字

```jq
.content.cardList |= map(select(((type=="object" and (has("retailProductCard") or has("freeRightCard")))|not)))
```

`cardType` 是后端排版的枚举，改版会重排；而 `retailProductCard` / `freeRightCard` 是**客户端渲染器认的字段名**，要改就必须同时改客户端，反而更稳定。

实测：`60 张 → 12 张`，响应体 `24976B → 4373B`。

---

## 四、投放决策：广告的总闸

```
POST https://lop-proxy.jd.com//decision
[{"sceneKey":"jdl_home_feed_fwj_card","latLongitude":{...},"deviceInfo":{...}}]
→ {"code":0,"data":[],"message":"SUCCESS","traceId":"..."}
```

```
POST https://lop-proxy.jd.com/smartmp/querySmartDecision
[{"sceneKey":"h5_rece_card_banner","extendParams":{"source":"JDLAPP"}}]
→ {"code":0,"data":[],"message":"SUCCESS","traceId":"..."}
```

本次抓包里这两条**返回的都是空 data**（用户没被投放命中），所以看不到广告 payload 长什么样。但接口本身是标准投放通道：设备信息（idfa / oaid / 屏幕 / 机型 / 网络）全在请求体里，只有广告平台才需要这么全的画像。

处置：`.data=[]`。比拦域名精准 —— 因为它是业务域名，拦了就断全站。

---

## 五、不改的东西（以及为什么）

| 接口 / 字段 | 看起来像 | 为什么不动 |
| --- | --- | --- |
| `queryMoreFeaturesSectionsNew` | 一堆 banner/卡片 | 是**特色寄件功能入口**（寄生鲜 / 寄港澳 / 寄国际 / 雪具寄），删了功能就没了 |
| `//queryHomeMainInfo` 的 `homeTeseji` | 「特色寄机」运营位 | 同上，功能位 |
| `//queryHomeMainInfo` 的 `homeNotice` | 营运位 | 是公告，不是广告 |
| `//moduleList` 的 `myAssets` / `myWallet` | 我的页一堆入口 | 是资产和钱包，删了看不到余额 |
| `jra.jd.com` / `sdkfp.jd.com` | 可疑上报 | 风控指纹，拦了有触发风控的风险 |
| `wlogin.m.jd.com` / `un.m.jd.com` | 跳转 | 登录链路 |

---

## 六、本次没覆盖到的

1. **开屏广告**：抓包时 App 已在后台，没有冷启动，所以没有开屏接口样本。如果实际使用中还有开屏，需要**杀掉 App 后立刻开始抓包**再走一遍冷启动，然后 `--map` 找新出现的接口。
2. **加密响应**：`queryHomePageOrders`、`searchOrderEnhance`、`familyCard/getUserInfoEnhance` 的响应是密文（AES），Loon 改不了，插件也不会去碰。
3. **到家店铺广告**：`api.m.jd.com/client.action?functionId=hours_pub_store_page` 的 `storeList[*].commonSrvMap.isAd` 是竞价广告标记，但本次样本里 **10 家店全是 `isAd=0`**，没有实际广告可验证。插件里给了预防性规则，默认关闭。

---

## 七、复现方式

```bash
python tools/analyze_har.py 抓包.har --check    # MITM 是否真在解密
python tools/analyze_har.py 抓包.har --map      # 接口地图（解码 base64 请求体）
python tools/analyze_har.py 抓包.har --feeds    # 首页卡片类型统计
python tools/analyze_har.py 抓包.har --verify   # 把插件规则跑一遍，看前后变化
```

`--verify` 是核心：它直接读 `JDKDAds.plugin` 里启用的 `response-body-json-jq` 行，对 HAR 里命中的响应逐条执行 jq，输出字节数和卡片数变化。**规则改完必须跑一遍**，光看语法对不对没用。
