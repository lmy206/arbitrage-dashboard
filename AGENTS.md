# AGENTS.md

## 项目范围

- 本项目是仅在本机运行的套利监测看板，目录固定为 `D:\arbitrage-dashboard`。
- 严禁发布、部署、推送远端或创建 Sites 版本。
- 本地服务使用 `http://localhost:3001/`，启动与健康检查脚本位于 `scripts/`。

## 数据规则

- 国内行情以 `xtdata` 为唯一主源，Python 优先使用 `D:\anaconda\python.exe`。
- 共享数据根目录优先遵守 `E_SHARED_DATA_ROOT`，否则使用 `E:\data`。
- 仅允许已经获用户批准的外部补充源：LME 铜、铝、锌三个月电子盘，以及国家外汇管理局美元兑人民币中间价。
- 外部补充数据写入共享数据目录；不得自行增加或替换为其他网页、AkShare 接口或行情源。
- 所有历史统计与回测必须检查未来数据风险。

## 更新与验证

1. 运行 `D:\anaconda\python.exe scripts\update_xtdata.py`。
2. 读取 `E:\data\reports\arbitrage_dashboard_integrity.json`。
3. 只有在 `status=ok`、`pairCount=expectedPairCount=30`、`futureDataDetected=false`、`hierarchySorted=true` 且 `externalSourcesComplete=true` 时，才运行：
   - `npm run build`
   - `node --test tests\rendered-html.test.mjs`
4. 更新失败时保留上次有效数据，并明确报告具体错误。

## 开发原则

- 优先使用中文，结论直接、可执行。
- 保留用户已有修改，不使用破坏性 Git 命令。
- 不执行 `git push`，不调用任何发布工具。
