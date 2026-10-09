# CS50P Python 学习工作台

面向个人 Windows 本地学习的 CS50P 配套工作台，组织“视频 → 中文要点 → 示例 → 练习 → 错题复习”流程。项目通过17项产品设计选择和分阶段任务推进，采用 Codex AI 辅助开发。项目作者负责学习需求与产品取舍，代码与测试由 AI 协作实现。

## 已实现

- Week 0–9 与最终项目共11个单元，25个示例、30道原创练习、三级提示与折叠答案。
- React/TypeScript网页与CodeMirror编辑器；FastAPI运行服务、原生CPython代码执行与SQLite保存。
- 程序运行中逐行输入、EOF、停止、时限、输出上限和Windows进程树回收。
- 本地真实练习检查、错题复习、草稿/笔记自动保存；官方作业入口与完成情况手动记录。
- 多文件最终项目、pytest、结构核对、ZIP导出；文本和PNG/JPG附件下载/预览。
- JSON学习档案备份、压缩与校验、恢复前自动备份。

第一版使用固定中文讲解与分级提示，**没有在线AI导师或大模型问答**。AI用于开发协作，不属于已接入的运行时产品功能。

## 安装与启动

Windows 10/11 x64、原生CPython 3.12或更新版本、Node.js与pnpm均需加入PATH。请使用python.org等原生Python发行版；Microsoft Store激活代理会影响进程树回收。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\启动工作台.bat
```

也可双击 `首次安装.bat`，安装服务和学习虚拟环境、锁定前端依赖并构建网页；日常双击 `启动工作台.bat`。服务默认打开 `http://127.0.0.1:8765`，保留服务窗口，按Ctrl+C停止。

指定Python解释器：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -PythonPath "C:\Python312\python.exe"
```

端口冲突时运行 `scripts/run-server.ps1 -Port 8775`。运行时不自动安装第三方包；学习代码需要的依赖请安装到 `.venv-learning`。

## 测试与构建

```powershell
.\.venv-server\Scripts\python.exe -m pytest tests -q
Push-Location web
pnpm build
Pop-Location
```

开发机历史结果：65项自动化检查通过、TypeScript与Vite生产构建通过。覆盖30题参考解与错误解、输入/停止、进程回收、持久化、附件与备份恢复。页面资源和HTTP接口验证通过，**页面点击、视觉验收和实际视频播放尚未完整实测**。源码发布副本的复核记录见 [docs/validation.md](docs/validation.md)。

## 数据与使用边界

个人记录存储于 `local-data/workbench.sqlite3`，不随开源发布；恢复前备份当前记录，重要数据请主动导出。本仓库不含私人聊天、个人学习数据、视频、依赖环境或构建产物。

此工具只面向可信个人学习代码。子进程、临时目录和虚拟环境不构成恶意代码安全沙箱，请勿向公网开放或运行不可信代码。

本地练习检查不等于CS50P官方评分，项目也不代表作者已学完课程或获得证书。课程播放器受网络条件限制；可手动配置每周视频，B站分P与官方周次未自动核实。第一版不提供跨设备协同。

## 来源与许可

课程链接依据 [CS50P官方课程](https://cs50.harvard.edu/python/)，详见 [docs/course-sources.md](docs/course-sources.md)。导航摘要、中文辅助要点与练习为工作台原创内容，不复制完整官方讲义或官方作业答案，本工具不隶属哈佛大学。

本项目自身代码与原创辅助内容采用 [MIT](LICENSE)，第三方软件与外部课程保留各自许可，参见 [THIRD_PARTY.md](THIRD_PARTY.md)。
