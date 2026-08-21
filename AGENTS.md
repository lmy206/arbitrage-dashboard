# AGENTS.md

## 项目范围

- 本项目目录固定为 `D:\arbitrage-dashboard`，本地服务使用 `http://localhost:3001/`。
- Cloudflare Pages 只发布 GitHub `main` 分支中的静态数据快照，不在云端连接或运行 xtdata。
- 用户已明确授权：本项目每次修改完成并通过相应校验后，都必须提交本次任务涉及的文件、推送到 GitHub `main`，并由 GitHub 推送触发 Cloudflare Pages 自动部署；不得只保留在本地。
- 每次推送后必须检查 Cloudflare 生产域名 `https://arbitrage-dashboard-588.pages.dev/` 是否已部署新版；若 GitHub 推送或 Cloudflare 部署失败，必须明确报告失败环节，不得宣称修改已经上线。
- 日常定时数据更新只能由 `scripts/update-and-publish.ps1` 执行；该自动任务只能提交 `app/data/arbitrage.json`，不得自动提交源代码、配置、凭证或其他工作区修改。
- 功能、样式、测试、文档和项目规则等人工修改，按本文件的“修改发布流程”提交，不得混入与当前任务无关的用户文件或未跟踪文件。

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

## 修改发布流程

1. 修改前检查 `git status`，保留并避开与当前任务无关的用户修改和未跟踪文件。
2. 完成本次修改后运行与改动相匹配的校验；涉及页面、样式、数据结构或渲染逻辑时，至少运行 `npm run build`、`node --test tests\rendered-html.test.mjs` 和 `npm run test:pages`。
3. 校验通过后，只暂存和提交本次任务涉及的文件，提交到当前 `main` 分支，并执行 `git push origin main`；不得使用强制推送。
4. GitHub 推送成功后检查 Cloudflare Pages 生产域名是否已切换到新版本；生产域名是 `https://arbitrage-dashboard-588.pages.dev/`，带随机前缀的部署预览地址不作为持续更新入口。
5. 只有 GitHub 推送成功且 Cloudflare 生产页验证通过，才可向用户报告“已上线”；任一环节失败都要保留可用的上一版并报告具体错误。

## 开发原则

- 优先使用中文，结论直接、可执行。
- 保留用户已有修改，不使用破坏性 Git 命令。
- 不使用强制推送，不自动拉取或覆盖用户修改，不调用 Sites 发布工具；Cloudflare Pages 由 GitHub `main` 自动部署。
