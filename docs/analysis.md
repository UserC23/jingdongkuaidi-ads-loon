# 京东快递 App HAR 抓包分析（v2）

- 抓包设备：iPhone（`iPhone18,1`，iOS 27.0.1）
- App：京东快递 `jdlogistic` 1.7.7，appId 1372
- 抓包方式：Loon 全局代理导出 HAR
- 样本：
  - **A. 常驻使用，未装插件**：674 条请求 / 34 域名
  - **B. 冷启动，已装插件**：1001 条请求 / 44 域名
  - **C. 冷启动，未装插件**：1051 条请求 / 42 域名

三份拼起来才把「开屏」和「投放到底投了什么」看完整。原始 HAR 不入库（见 `.gitignore`），本文是分析结论。

| 样本 | 开屏 `jdl_splash_screen` | 投放决策命中条数 | 广告素材图下载 |
| --- | --- | --- | --- |
| A 未装插件 / 常驻 | **`data[1]` 557B** | 14 条 | 4 张（1.1MB） |
| B 已装插件 / 冷启动 | `data[]` | 0 | **0 张** |
| C 未装插件 / 冷启动 | `data[]` | **23 条** | 14 张 |

---

## 一、先回答最关心的那个问题：域名层有没有东西可拦？

**几乎没有。**

三份抓包全部落在这些域：

| 请求数（C 样本） | 域名 | 性质 |
| --- | --- | --- |
| 248 | `saturn.jd.com` | 埋点上报（`/log/sdk`） |
| 238 | `uranus.jd.com` | 埋点 |
| 201 | `lop-proxy.jd.com` | **业务接口网关** |
| 46 | `h5speed.m.jd.com` | 活动页埋点 |
| 40 | `jfe.s3-cache-accelerate...` | 静态资源（皮肤 / 活动页） |
| 26 | `sgm-m.jd.com` | 营销埋点（请求/响应都加密） |
| 20 | `arsenal.jdl.com` | 图标 CDN |
| 19 | `api.m.jd.com` | 京东主网关（到家门店页等） |
| 18 | `sgm-w.jd.com` | 营销埋点 |
| 14 | `riskimg.360buyimg.com` | **广告素材图** |
| 其余 | `*.jd.com` / `*.jdl.com` / `*.360buyimg.com` / `*.jdcloud-oss.com` | 图片、静态资源、登录、风控 |

**没有 1RTB、没有穿山甲/巨量、没有 TanX、没有汇川。** 京东快递的广告是自己家广告平台（京准通）通过业务网关下发的 JSON —— **广告和业务共用同一个域名**，按域名拦等于拦业务。

唯一例外是 `riskimg.360buyimg.com`：它只被广告接口引用（`//decision`、`querySmartDecision`、`thirdPartyRights`、`flashSaleList`、`getHomePageFeedCards`），没有一条业务图走它。首页 60 张卡的图床分得很干净：

| 卡片 | 图床 |
| --- | --- |
| `freeRightCard`（删） | `riskimg.360buyimg.com` |
| `retailProductCard`（删） | `img14.360buyimg.com` |
| `couponPackageCard`（留） | `wlimg10.360buyimg.com` |
| `saleCard`（留） | `jfe.s3.cn-north-1.jdcloud-oss.com` |

C 样本里它下了 14 张图（单张最大 533KB），B 样本（装了插件）0 张。插件里给了一条默认关闭的兜底规则 —— 不默认开是因为 D3 秒杀列表和 D4 权益页的图也在它上面，那两个页面默认还是可见的。

> 对比参考：菜鸟那边 `1rtb.net` / `pglstatp-toutiao.com` / `tanx.com` 都在，域名层有明确目标；京东快递基本没有。

---

## 二、开屏广告：它是投放决策接口的一个场景

这是 v2 最重要的发现。

开屏**没有独立接口**。冷启动时 App 打的是同一个 `//decision`，只是请求体里的 `sceneKey` 不同：

```json
POST https://lop-proxy.jd.com//decision
[{
  "sceneKey": "jdl_splash_screen",
  "latLongitude": {"longitude":0.0,"latitude":0.0,"ip":"0.0.0.0"},
  "deviceInfo": {"idfa":"","openudid":"856C5806-...","screen":"402x874",
                 "mobileModel":"iPhone18,1","os":"iOS","osVersion":"27.0.1"},
  "applicationInfo": {"version":"1.7.7","entry":"logistics"},
  "appId": "1372"
}]
```

### 开屏是「时投时不投」的

三份抓包里只有 A 样本真的投了：

```json
{"action": {
   "image": "https://riskimg.360buyimg.com/pop/jfs/t1/543849/15/13189/555886/6ae0b39aF61c44a10/06ed465984065a88.png",
   "url": "https://pro.m.jd.com/mall/active/JFGrF75PxmRfeQx53tAXFkV6DRZ/index.html?babelChannel=ttt39"
 },
 "nodeId": "2115086717886140417",
 "trackInfo": {"materialId":"...","sceneId":"2056971042542325760","source":1}}
```

一张 **555KB 的双 11 会场大图**，点击跳 `pro.m.jd.com/mall/active/...`。B 和 C 两次冷启动同一个场景都返回 `data[]`。

**所以不要把「某次没看到开屏」当成插件生效的证据。** 真正的证据是：

- 三份样本里 `//decision` 的所有响应被规则置空，无一例外
- C（未装）vs B（已装）对照：投放决策命中 23 条 payload → 0 条，广告素材图下载 14 张 → 0 张

### 15 个 sceneKey（三份抓包合并）

`//decision`（5 个）：

| sceneKey | 是什么 | C 样本投放 |
| --- | --- | --- |
| `jdl_splash_screen` | **开屏广告** | 否（A 样本投了） |
| `app_jdkd_tab_benefit_popup` | 底部「福利」tab 弹窗 | **是，1 条** |
| `app_jdkd_home_popup` | 首页弹窗 | 否 |
| `jdl_home_feed_card` | 首页推荐流插卡 | **是，6 条** |
| `jdl_home_feed_fwj_card` | 首页推荐流「服务加」卡片 | 否 |

`smartmp/querySmartDecision`（10 个，全是搜索 / 寄件 / 详情页的广告位）：

| sceneKey | 是什么 | C 样本投放 |
| --- | --- | --- |
| `jdl_detail_banner` | 运单详情页 banner | **是，4 条** |
| `jdl_detail_bubble` | 运单详情页气泡 | **是，1 条** |
| `jdl_search_bubble` | 搜索框气泡 | 是，1 条 |
| `jdl_search_textbanner` | 搜索页文字链 | 是，1 条 |
| `jdl_search_follow_banner` | 搜索结果关注 banner | 是，1 条 |
| `jdl_search_follow_bubble` | 搜索结果关注气泡 | 是，1 条 |
| `jdl_search_receive_banner` | 收件搜索结果 banner | 是，1 条 |
| `jdl_search_receive_bubble` | 收件搜索结果气泡 | 是，1 条 |
| `h5_send_card_banner` | 寄件页卡片 banner | 否 |
| `h5_rece_card_banner` | 收件页卡片 banner | 否 |

### C 样本实际投了 23 条，内容是这样

`jdl_home_feed_card` 6 条（5081B）—— 全部是京东商城导购，混进「为您推荐」里：

| 跳转 | 性质 |
| --- | --- |
| `pro.m.jd.com/mall/active/3BRUbAnH8KTdyiC3nnFy3i7gBJ9J/...` | 双 11 会场 |
| `pro.m.jd.com/mall/active/JFGrF75PxmRfeQx53tAXFkV6DRZ/...` | 双 11 会场 |
| `pro.m.jd.com/mall/active/4QHTYLhwsyTjTCBVaFV2vGgY86mS/...` | 双 11 会场 |
| `pro.m.jd.com/mall/active/2c3kejRsEQVxB1gkM3YfmV5csYgm/...` | 双 11 会场 |
| `wj-dongjian.jd.com/q/6ab344b2cb89820057501621` | 问卷 |
| `item.jd.com/100284198070.html` | 商品详情 |

**这 6 条根本不在 `getHomePageFeedCards` 里** —— 光删接口里的 60 张卡，它们照样会插进推荐流。必须在 A 级一起清。

`jdl_detail_banner` 单次 4 条（1964B）—— 运单详情页底部。样本里这个页面进了两次，所以记了 8 条，
按响应去重是 4 条：

- `jingcai-h5.jd.com/index.html?source=yunxiangBanner_FD#/` 京彩商城首页
- `wj-dongjian.jd.com/q/6addd2019f5f6100395e93f7` 问卷
- `jchd.jd.com/index.html#/reduceCarbon?test=ydxqybannerai` 减碳活动
- `jingcai-h5.jd.com/index.html?source=...#/mailCard` 明信片

### 为什么是「整条通道一起清空」

Loon 的规则只能匹配 **URL**，匹配不到请求体里的 `sceneKey`。所以「只杀开屏、留着别的」在客户端层面做不到。

好在这 15 个场景**无一例外都是商业投放**，没有一个是功能性的。整条通道置空，等于告诉 App「这次没有任何可投的」，外层 `code/message` 完整保留，不会触发错误分支。

> 用 `python tools/analyze_har.py 抓包.har --scenes` 可以随时把当下的 sceneKey 全列出来，
> 哪个场景的 `data` 不是空的，哪个就是还在给你下发广告的。

### 规则实测（C 样本，真实命中）

```
//decision        jdl_home_feed_card    5081B → 85B    清掉 6 条商城导购卡
//decision        app_jdkd_tab_*          357B → 85B
querySmartDecision jdl_detail_banner    1964B → 85B    清掉运单详情页 4 条 banner
querySmartDecision jdl_search_*      597~634B → 85B    清掉搜索页气泡 / 文字链
```

---

## 三、启动时真正会弹出来的，是「新人弹窗」

冷启动第 4 个业务请求（比首页内容还早）就是它：

```json
POST https://lop-proxy.jd.com//home/queryNewPersonSceneDisplayContent
→ {"code":1,"content":{
     "businessLine": 2,
     "contentDTO": {
       "contentTitle": "新人弹窗-快运-8折",
       "resCode": "pos00075",
       "srcUrl": "https://jdl-cms-pro.s3-cache-accelerate.cn-north-1.jdcloud-oss.com/image-1750654981670.png",
       "link": "https://jingcai-h5.jd.com/#/newCoupon?promoterId=...&source=xiaogeAPPyingxiao",
       "extDisplayMap": {"kyDiscountRatio":"0.7","showUpNumber":"1","parentGroup":"1"}
     },
     "isNewPerson": true
   },
   "data": {"$ref": "$.content"}}
```

一整屏图片，点「领取」跳 `jingcai-h5` 领券页。三份抓包里内容一字不差（同一套素材），说明它不是偶发下发。它是**独立接口，不走决策通道**，所以 A 级规则管不到它 —— v1 漏掉的就是这一条。

处置：把 `content.contentDTO` 置 `null`，保留 `businessLine` / `isNewPerson` / `couponDetail`。App 拿到 nil 就不渲染，外层结构完整。

实测：`840B → 193B`。

> 注意 `data` 用的是 `{"$ref":"$.content"}` 这种 JSON 引用语法，App 侧会做解析。
> 所以不要删 `content` 本身，只挖掉里面那个渲染节点。

---

## 四、首页 60 张卡：广告主战场

`getHomePageFeedCards` 返回 `content.title = "为您推荐"`、`desc = "优惠好价天天享"`，一次 60 张卡：

| 数量 | 子对象 | 是什么 | 处置 |
| --- | --- | --- | --- |
| 46 | `freeRightCard` | 「权益免费领」—— 腾讯视频 8.3 折月卡这类第三方联合会员，跳 `jingcai-h5.jd.com#/receiveRights` | **删** |
| 8 | `couponPackageCard` | 「超值券包」付费券包推销（1.9 元抵 210 元） | 保留（想删用 D12） |
| 4 | `saleCard` | 快递年卡·PLUS联名 / 寄件省钱卡 / 亲情卡 / E卡 | 保留 |
| 2 | `retailProductCard` | 「零售商品」—— 桌游、玩具，跳 `djg.jd.com` 京东商城 | **删** |

60 张里 48 张是第三方导购/权益广告，占比 **80%**。

跳转域名统计也印证了：60 张卡里 57 张跳 `jingcai-h5.jd.com`（京彩），2 张跳 `djg.jd.com`（京东商城），1 张跳 `jpay.jd.com`。**没有一张跳自家的寄件流程** —— 这就是一条纯广告流。

### 为什么按子对象名删，而不是按 cardType 数字

```jq
.content.cardList |= map(select(((type=="object" and (has("retailProductCard") or has("freeRightCard")))|not)))
```

`cardType` 是后端排版的枚举，改版会重排；而 `retailProductCard` / `freeRightCard` 是**客户端渲染器认的字段名**，要改就必须同时改客户端，反而更稳定。

实测：`60 张 → 12 张`，`24976B → 4373B`。开了 D12（连券包一起删）是 `12 张 → 4 张`，`4373B → 1605B`。

---

## 五、冷启动里新发现的商业化接口

| 接口 | 大小 | 内容 | 级别 |
| --- | --- | --- | --- |
| `//home/queryNewPersonSceneDisplayContent` | 840B | 新人弹窗-快运-8折 | **A2，默认开** |
| `ContentApi/queryContentInfo` | 142B | 京彩 tab 红点气泡（`jingcai-home-tab-bubble`：免费领 / 上新） | D8 |
| `MissionApi/queryHomePageConfig` | 357B | 首页模块总开关（banner / 券包 / 秒杀卡 / 积分商城 / 京豆 / 活动区） | D9 |
| `getJDTrialList` | 880B | 试用福袋（1 分钱奶粉 / 避孕套），跳 `pro.m.jd.com` 京东商城活动页 | D10 |
| `saleProductApiService/getProductListNew` | 3.3KB | 年卡 / 亲情卡 / E 卡售卖，8 个付费产品 | D11 |
| `rightsmall/queryRightsListByMarketingPlacementId` | 3.6KB | 京豆兑券活动（**不算广告，没做规则**） | — |

`ContentApi/queryContentInfo` 一个接口供着多个 contentCode（还有 `jingcai-share-card-info` 分享卡片），所以 D8 那条规则按 `contentCode` 精准命中，只把气泡文案置空，别的内容原样放过。

---

## 六、投放决策的数据结构

C 样本里 `//decision` 的 `jdl_home_feed_card` 返回 6 条，能看到完整投放结构：

```json
{"code":0,"data":[
  {"action": {
     "image": "https://riskimg.360buyimg.com/pop/jfs/t1/541647/23/9614/...png",
     "materialDisplayTemplate": "1",
     "url": "https://pro.m.jd.com/mall/active/3BRUbAnH8KTdyiC3nnFy3i7gBJ9J/index.html?c=26shuang11appbanner"
   },
   "nodeId": "2111085587338366977",
   "strategyId": "2111085587338366978",
   "trackInfo": {"materialId":"...","sceneId":"2014324799207116800","source":1},
   "virtualHeat": 1446974.87}
]}
```

字段名直接就是投放术语：`strategyId`（策略）、`materialId`（素材）、`sceneId`（场景）、`virtualHeat`（虚拟热度）。

处置：`.data=[]`。比拦域名精准 —— 因为它是业务域名，拦了就断全站。

---

## 七、不改的东西（以及为什么）

| 接口 / 字段 | 看起来像 | 为什么不动 |
| --- | --- | --- |
| `queryMoreFeaturesSectionsNew` | 一堆 banner/卡片 | 是**特色寄件功能入口**（寄生鲜 / 寄港澳 / 寄国际 / 雪具寄），删了功能就没了 |
| `//queryHomeMainInfo` 的 `homeTeseji` / `homeGongneng` | 「特色寄机」运营位 | 同上，功能位 |
| `//queryHomeMainInfo` 的 `homeNotice` | 运营位 | 是公告，不是广告 |
| `//moduleList` 的 `myAssets` / `myWallet` | 我的页一堆入口 | 是资产和钱包，删了看不到余额 |
| `/explore` | 名字像「发现」 | 实际是**地址 POI 搜索**（返回酒店/小区/楼栋），寄件选地址要用 |
| `//home/queryHomeToDoInformationNew` | 名字像运营 | 是待办/运单提醒 |
| `jra.jd.com` / `sdkfp.jd.com` | 可疑上报 | 风控指纹，拦了有触发风控的风险 |
| `wlogin.m.jd.com` / `un.m.jd.com` | 跳转 | 登录链路 |

---

## 八、永远改不了的（别白费力气）

| 接口 | 大小 | 原因 |
| --- | --- | --- |
| `/order/searchOrderEnhance` | 321KB | 响应是 AES 密文 |
| `//queryHomePageOrders` | 92.7KB | 响应是 AES 密文 |
| `/familyCard/getUserInfoEnhance` | — | 加密 |
| `sgm-m.jd.com/ios` | — | 请求响应双加密（营销埋点，纯上报） |

Loon 的 jq 只处理明文 JSON。这几个接口哪怕里面真夹了广告卡，也动不了。

---

## 九、复现方式

```bash
python tools/analyze_har.py 抓包.har --check    # MITM 是否真在解密
python tools/analyze_har.py 抓包.har --map      # 接口地图（解码 base64 请求体）
python tools/analyze_har.py 抓包.har --feeds    # 首页卡片类型统计
python tools/analyze_har.py 抓包.har --scenes   # 投放决策的 sceneKey（开屏在哪）
python tools/analyze_har.py 抓包.har --verify   # 把插件规则跑一遍，看前后变化
```

`--verify` 是核心：它直接读 `JDKDAds.plugin` 里启用的 `response-body-json-jq` 行，对 HAR 里命中的响应逐条执行 jq，输出字节数和卡片数变化。**规则改完必须跑一遍**，光看语法对不对没用。三份样本实测：17 / 20 / 27 条命中，0 失败。

`--scenes` 是 v2 新加的：把 `//decision` 和 `querySmartDecision` 请求体里的 `sceneKey` 全挖出来，并标出每个场景这次的 `data` 是不是空的。开屏会排在第一行。
