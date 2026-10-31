# jdkdads-loon

京东快递 App（`jdlogistic`）去广告 Loon 插件。

- 适用 App 版本：`1.7.7`（iOS，抓包基线）
- 需要：**开启 MITM + 安装证书 + 在「证书信任设置」里打开完全信任**
- 当前版本：**v1**
- 抓包分析：[docs/analysis.md](docs/analysis.md) ｜ 安装调试：[docs/mitm-guide.md](docs/mitm-guide.md)

---

## 这个插件能去掉什么

抓包基线：**674 条请求 / 34 个域名**。核心发现是 —— **京东快递没有用第三方广告 SDK**，
674 条请求全部落在 `jd.com` / `jdl.com` / `360buyimg.com` 自有域名下，
没有 1RTB、穿山甲、TanX。所以这个插件几乎不写域名规则，全部在响应体里改字段。

| 广告位 | 实际情况 | 处置 | 默认 |
|---|---|---|---|
| 首页「为您推荐」瀑布流 | 60 张卡里 **46 张**是「权益免费领」（腾讯视频 8.3 折这类第三方联合会员），2 张是跳京东商城的商品导购 | 按卡片子对象名删除 | ✅ |
| 投放决策通道 | `//decision`、`smartmp/querySmartDecision` 两个 sceneKey 投放接口 | `data` 置空 | ✅ |
| 首页运营位 | `homeBanner`（轮播图）、`homeYingxiao`（营销位） | 清空 | ✅ |
| 我的页推广入口 | 我的公益 / 包裹的旅行 / 秒送商家入驻 / POP商家入驻 | 清空 | ❌ |
| 京彩 tab banner | 拼团助力失败 banner、积分夺宝 | 清空 | ❌ |
| 秒杀列表 | 0.01 元快递券 | 清空 | ❌ |
| 第三方联合会员权益 | 腾讯视频 / 爱奇艺 整页 | 清空 | ❌ |
| 服务加购推荐流 | 空调维修 / 加氟 / 冰箱检测 | 清空 | ❌ |
| 到家竞价店 | `storeList[*].commonSrvMap.isAd` | 过滤 | ❌ |

默认开启的三项，实测效果：

```
首页推荐流    60 张卡 → 12 张    响应体 24976B → 4373B
```

留下的 12 张是快递券包 / 年卡 / E卡 / 亲情卡 —— 京东快递自家的付费产品，不是第三方广告，删了属于误伤。

**没覆盖：开屏广告。** 本次抓包时 App 已在后台，没有冷启动样本。
如果实际还有开屏，按 [docs/mitm-guide.md 第三节](docs/mitm-guide.md#三还有广告怎么办) 补一次冷启动抓包。

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
https://fastly.jsdelivr.net/gh/UserC23/jdkdads-loon@main/JDKDAds.plugin
```

> 这个地址始终指向最新版，但 jsDelivr 对 `@main` 有缓存，推送后短时间内可能仍返回旧文件，
> `purge.jsdelivr.net` 也未必刷得掉（菜鸟那个仓库就踩过，卡了一个版本）。
> 想要确定版本，把 `@main` 换成具体 commit SHA —— 在仓库 Commits 页面复制 40 位完整哈希，
> 那个地址是内容寻址的，永远拿到确切版本。

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
python tools/analyze_har.py 抓包.har --scan-ads  # 哪些字段像广告位
python tools/analyze_har.py 抓包.har --verify    # 把插件里启用的 jq 规则跑一遍，看前后变化
```

`--verify` 直接解析 `JDKDAds.plugin` 里的 `response-body-json-jq` 行，输出：

```
--- 第 77 行  ^https?://lop-proxy\.jd\.com/getHomePageFeedCards
    ✓ /getHomePageFeedCards    24976B → 4373B (-20603)  卡片 60 → 12
```

`--check` 是前置条件：如果输出 `❌ 没有任何 HTTPS 请求`，说明 MITM 没生效，
此时任何分析都没有意义。

---

## 文件结构

```
JDKDAds.plugin                Loon 插件（主文件，直接装这个）
rules/JDKDAds-track.list      埋点域名列表（可选，不是去广告，是瘦身）
docs/analysis.md              抓包分析：674 条请求 / 34 域名 / 广告面清单
docs/mitm-guide.md            安装、验证、定位残留广告、排错表
tools/analyze_har.py          HAR 分析脚本（--check / --map / --feeds / --verify）
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
