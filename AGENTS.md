# AGENTS.md

## 项目范围

- 本项目目录固定为 `D:\arbitrage-dashboard`，本地服务使用 `http://localhost:3001/`。
- Cloudflare Pages 只发布 GitHub `main` 分支中的静态数据快照，不在云端连接或运行 xtdata。
- 除用户明确授权的自动发布及其实现变更外，不执行 `git push`，不调用 Sites 或其他发布工具；日常自动推送只能由 `scripts/update-and-publish.ps1` 执行。
- 自动发布只能提交 `app/data/arbitrage.json`；不得自动提交源代码、配置、凭证或其他工作区修改。

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
   - 本地验证：`npm run build` 和 `node --test tests\rendered-html.test.mjs`
   - Cloudflare 静态发布验证：`npm run test:pages`
4. `scripts/update-and-publish.ps1` 仅在数据日相对 `HEAD` 有更新、上述校验通过、当前分支为 `main`、本地与 `origin/main` 同步，且没有其他已跟踪文件修改时，才提交 `app/data/arbitrage.json` 并推送 `main`。
5. 更新、校验、提交或推送失败时保留上一版线上页面，写入 `.runtime` 日志和状态文件，不自动回滚或强推。

## 开发原则

- 优先使用中文，结论直接、可执行。
- 保留用户已有修改，不使用破坏性 Git 命令。
- 不使用强制推送，不自动拉取或覆盖用户修改，不调用 Sites 发布工具。
