# 套利监测看板

基于 `xtdata` 日线主力连续合约生成的跨品种比价与价差看板，每日 20:00（Asia/Shanghai）更新。

## 数据流程

1. `scripts/update_xtdata.py` 连接 `xtdata` 并下载全部可得日线历史。
2. 原始合约缓存写入 `E_SHARED_DATA_ROOT`，未设置时使用 `E:\data`。
3. 脚本更新 `catalog.sqlite`、`manifest.jsonl` 与完整性报告。
4. 15 组指标写入 `app/data/arbitrage.json`，网站从该文件渲染。
5. Codex 自动任务在每天 20:00 验证新交易日数据；仅更新本地数据与构建，不发布网站。

本机执行：

```powershell
D:\anaconda\python.exe scripts\update_xtdata.py
npm run build
node --test tests\rendered-html.test.mjs
```

## 口径

- 行情源：仅使用 `xtdata`。
- 合约：各品种 `00` 主力连续合约。
- 当前值与前日值：最近两个共同交易日的收盘价计算结果。
- 全历史分位：`xtdata` 返回的全部可得日线历史。
- 近 3 年分位：最新数据日前滚动三年的日线历史。
- 判断：近 3 年分位不低于 75% 为“偏高”，不高于 10% 为“极度偏低”，其余为“中性”。
- 平衡手数：按合约乘数和最新收盘价，在单边不超过 30 手的范围内逼近两腿等名义敞口。
- 保证金：使用脚本内配置的保证金比例估算，不代表账户实际占用。
- 螺卷差：热卷减螺纹钢；豆粕价差：豆粕减豆一；金银比：黄金价格乘 1000 后除以白银价格。

## 安全与失败处理

`xtdata` 凭证只从 `XTQUANT_TOKEN` 环境变量或本机 `E:\IM\config.py` 读取，不写入项目。若行情不可用、15 组数据不齐、交易日不一致或检测到未来数据，脚本保留上次有效网页数据并记录 `xtdata_unavailable` 或校验错误，不发布异常结果。
