# 套利监测看板

跨品种比价与价差看板，独立项目目录为 `D:\arbitrage-dashboard`。本地每日更新，并通过 GitHub `main` 自动触发 Cloudflare Pages 发布静态快照。

国内行情以 `xtdata` 为唯一主源；外部补充包括 LME/FCPO、新浪美股指数、中证指数估值、中美10年期国债收益率、Multpl 标普500市盈率和外管局汇率，均写入共享目录并接受完整性校验。

## 数据流程

1. `scripts/update_xtdata.py` 连接 `xtdata`，下载商品期货持仓量加权连续、商品与股指期货主力连续、具体月份和现货指数的全部可得日线历史。
2. xtdata 数据写入 `E:\data\market\futures_daily` 和 `E:\data\market\index_daily`。
3. 脚本更新 `catalog.sqlite`、`manifest.jsonl` 和完整性报告。
4. 34 组指标及常规期货组合成交量最大的 4 个共同合约月写入 `app/data/arbitrage.json`，网站从该文件渲染。
5. Windows 计划任务在周一至周五 20:10 检查新交易日数据；校验和静态页面测试通过后，只提交 `app/data/arbitrage.json` 并推送 `main`。节假日因数据日不变而自动跳过。

## 图表

- 分位总览：全部 34 个品种对的近 5 年分位横向排名，统一使用 0%–100% 量尺。
- 历史走势：IC/IF、IM/IF、科创50/上证50、创业板/沪深300、IM-IC价差、蛋白质价差、纯碱玻璃差。
- 历史窗口：最多 60 个自然月的月末值；当前月使用截至数据日的最新收盘。
- 图表数据：国内行情来自 xtdata；海外期货、海外指数、估值、国债收益率和汇率来自项目规则列明的已批准外部源。跨日合并只向后匹配已公布数据。

本机执行：

```powershell
D:\anaconda\python.exe scripts\update_xtdata.py
npm run build
node --test tests\rendered-html.test.mjs
```

## Cloudflare Pages

Cloudflare Pages 使用静态快照构建，不运行本机 xtdata 更新接口。项目设置如下：

- Production branch：`main`
- Build command：`npm run build:pages`
- Build output directory：`dist/client`
- Root directory：仓库根目录（留空）
- Node.js：遵守 `package.json` 中的 `>=22.13.0`

构建命令会先完成 Vinext 构建，再把服务器渲染的首页导出为 `dist/client/index.html`；`npm run test:pages` 可同时验证首页、客户端资源和原有看板测试。云端页面只展示提交时的 `app/data/arbitrage.json`，本机的“立即更新数据”功能在云端会自动显示为“云端数据快照”。

Cloudflare 连接的 Git 仓库必须包含当前代码；部署页面显示的提交号应与准备发布的提交一致。

`scripts/update-and-publish.ps1` 是唯一获准自动执行 `git push` 的入口。它要求本地 `main` 与 `origin/main` 完全同步、没有其他已跟踪文件修改、完整性报告通过且数据日更新；随后运行 `npm run test:pages`、仅提交 `app/data/arbitrage.json`、推送 `main`，最后等待线上页面出现新的数据日。任何一步失败都会停止发布并写入 `.runtime/cloud-publish-status.json`；计划任务会每 10 分钟重试，最多 3 次。

安装或刷新计划任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install-update-and-publish-task.ps1
```

无更新、无提交、无推送的安全演练：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\update-and-publish.ps1 -DryRun
```

## 口径

- 行情源：展示值、历史分位、手数和保证金均仅使用 `xtdata`。
- 默认合约：商品套利使用 `JQ00` 持仓量加权连续序列；股指期货套利继续使用 `00` 主力连续序列。商品 `00` 主连保留在月份展开区，可手动设为主要观察。
- IM期限套：展开显示 `(IM当月 − IM下季) × 12 / 月差 / 中证1000` 与 `(IM当月 − IM隔季) × 12 / 月差 / 中证1000`，月差按两张具体合约之间的自然月数计算（如 2608→2612 为 4）；主表、展开表和历史图统一按年化百分数呈现。下季、隔季分别取排在下月之后的第一、第二个季月合约；当月合约正常跟踪至到期，到期后才自然切换为次月。历史序列仅使用同日 xtdata 收盘价和预先可知的交易日历，不按未来成交量倒推合约。
- 月份展开：默认折叠；点击品种对前的 `+` 展开。展示共同合约月、当前值、两腿成交量、近 5 年分位和判断。
- 月份排序：按两腿当日成交量的较小值（可配对成交量）降序，取前 4 个共同月份。
- 当前值与前日值：最近两个共同交易日的收盘价计算结果。
- 全历史分位：`xtdata` 返回的全部可得日线历史。
- 近 5 年分位：最新数据日前滚动五年的日线历史。
- 判断：5% 以下为“极度偏低”，5%–15% 为“偏低”，85%–95% 为“偏高”，95% 以上为“极度偏高”，其余为“中性”。
- 平衡手数：价差组合固定为 1:1；比价组合遍历两腿各 1–20 手的整数组合，选择名义市值偏差最小的一组，偏差相同时优先总手数更少的组合。
- 保证金：使用脚本内配置的保证金比例估算；中金所股指期货组合按跨品种冲抵口径取两腿中较大的单边保证金，其他组合按两腿相加，不代表账户实际占用。
- 商品组合：蛋白质价差（豆粕减菜粕）、纯碱玻璃差、豆棕价差等均使用 xtdata `JQ00` 加权序列作为默认展示口径；科创50/上证50、创业板/沪深300使用 xtdata 现货指数，只作风格参考，因此不展示平衡手数、名义值和保证金。
- IM-IC价差：中证1000股指期货减中证500股指期货；卷螺价差：热卷减螺纹钢；螺矿比：螺纹钢除以铁矿石；焦炭焦煤比：焦炭除以焦煤；豆粕价差：豆粕减豆一；金银比：黄金价格乘 1000 后除以白银价格。
- 新增比价：燃料油/沥青、20号胶/BR橡胶、烧碱/玻璃、镍/不锈钢、玻璃/聚乙烯、玻璃/聚丙烯、猪肉/玉米均按左腿除以右腿计算。
- 风险溢价：沪深300风险溢价=`100/沪深300滚动市盈率−中国10年期国债收益率`；美股风险溢价=`100/标普500市盈率−美国10年期国债收益率`，页面按百分数显示。
- 海外相对指标：纳斯达克/标普500使用两只现货指数收盘价；马盘棕榈油与豆油比价=`FCPO（林吉特/吨）×人民币/林吉特÷国内豆油JQ00（人民币/吨）`，汇率用外管局中间价并以 BNM 最新值校对。

## 安全与失败处理

`xtdata` 凭证只从 `XTQUANT_TOKEN` 环境变量或本机 `E:\IM\config.py` 读取，不写入项目。若 xtdata 行情不可用、34 组数据不齐、批准的外部数据缺失或过期、交易日不一致或检测到未来数据，脚本保留上次有效网页数据并记录 `xtdata_unavailable`、`external_source_unavailable` 或校验错误，不发布异常结果。
