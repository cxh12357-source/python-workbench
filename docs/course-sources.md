# CS50P 课程资料来源

核查日期：2026年10月8日。结构化结果保存于 `data/course-index.json`。

## 官方依据

- [CS50P 首页](https://cs50.harvard.edu/python/)说明课程面向有或没有编程经验的学习者，包含十周内容和最终项目。
- [Weeks 目录](https://cs50.harvard.edu/python/weeks/)列出 Week 0–9 及其官方主题。
- [Problem Sets 目录](https://cs50.harvard.edu/python/psets/)列出 Problem Sets 0–8；Week 9 的任务入口指向最终项目。
- [Final Project](https://cs50.harvard.edu/python/project/)是独立项目说明页，要求 Python 程序、自定义函数、pytest 测试、依赖清单、说明文档和演示。

## 已核查入口

所有课程、Notes、Problem Set 及 CS50 Video Player 页面均通过网页工具打开核查；播放器标题与各周主题一致。YouTube 短链接从各周官方页面的真实链接提取，未另行验证播放。页面可读取不代表用户所在网络一定能播放视频，也不代表已完成官方提交或评分。

| 单元 | 主题 | 课程 | 讲义 | 作业 | 播放器 |
| --- | --- | --- | --- | --- | --- |
| Week 0 | 函数与变量 / Functions, Variables | [课程](https://cs50.harvard.edu/python/weeks/0/) | [Notes](https://cs50.harvard.edu/python/notes/0/) | [Problem Set 0](https://cs50.harvard.edu/python/psets/0/) | [CS50 Video Player](https://video.cs50.io/JP7ITIXGpHk) |
| Week 1 | 条件判断 / Conditionals | [课程](https://cs50.harvard.edu/python/weeks/1/) | [Notes](https://cs50.harvard.edu/python/notes/1/) | [Problem Set 1](https://cs50.harvard.edu/python/psets/1/) | [CS50 Video Player](https://video.cs50.io/_b6NgY_pMdw) |
| Week 2 | 循环 / Loops | [课程](https://cs50.harvard.edu/python/weeks/2/) | [Notes](https://cs50.harvard.edu/python/notes/2/) | [Problem Set 2](https://cs50.harvard.edu/python/psets/2/) | [CS50 Video Player](https://video.cs50.io/-7xg8pGcP6w) |
| Week 3 | 异常处理 / Exceptions | [课程](https://cs50.harvard.edu/python/weeks/3/) | [Notes](https://cs50.harvard.edu/python/notes/3/) | [Problem Set 3](https://cs50.harvard.edu/python/psets/3/) | [CS50 Video Player](https://video.cs50.io/LW7g1169v7w) |
| Week 4 | 库与模块 / Libraries | [课程](https://cs50.harvard.edu/python/weeks/4/) | [Notes](https://cs50.harvard.edu/python/notes/4/) | [Problem Set 4](https://cs50.harvard.edu/python/psets/4/) | [CS50 Video Player](https://video.cs50.io/MztLZWibctI) |
| Week 5 | 单元测试 / Unit Tests | [课程](https://cs50.harvard.edu/python/weeks/5/) | [Notes](https://cs50.harvard.edu/python/notes/5/) | [Problem Set 5](https://cs50.harvard.edu/python/psets/5/) | [CS50 Video Player](https://video.cs50.io/tIrcxwLqzjQ) |
| Week 6 | 文件读写 / File I/O | [课程](https://cs50.harvard.edu/python/weeks/6/) | [Notes](https://cs50.harvard.edu/python/notes/6/) | [Problem Set 6](https://cs50.harvard.edu/python/psets/6/) | [CS50 Video Player](https://video.cs50.io/KD-Yoel6EVQ) |
| Week 7 | 正则表达式 / Regular Expressions | [课程](https://cs50.harvard.edu/python/weeks/7/) | [Notes](https://cs50.harvard.edu/python/notes/7/) | [Problem Set 7](https://cs50.harvard.edu/python/psets/7/) | [CS50 Video Player](https://video.cs50.io/hy3sd9MOAcc) |
| Week 8 | 面向对象编程 / Object-Oriented Programming | [课程](https://cs50.harvard.edu/python/weeks/8/) | [Notes](https://cs50.harvard.edu/python/notes/8/) | [Problem Set 8](https://cs50.harvard.edu/python/psets/8/) | [CS50 Video Player](https://video.cs50.io/e4fwY9ZsxPw) |
| Week 9 | 更多 Python 特性 / Et Cetera | [课程](https://cs50.harvard.edu/python/weeks/9/) | [Notes](https://cs50.harvard.edu/python/notes/9/) | 不适用 | [CS50 Video Player](https://video.cs50.io/6pgodt1mezg) |
| Final Project | 最终项目 / Final Project | [课程](https://cs50.harvard.edu/python/project/) | 未列出 | 不适用 | 未列出 |

Week 9 没有配置 Problem Set 9。最终项目没有独立 Notes 或专属讲座视频入口：索引保留 `null`，并以 `not_applicable` 或 `not_listed` 说明原因。最终项目页要求的学习者演示视频不会被当成官方课程视频。

## 用户视频入口

用户指定的 [B 站课程入口（p=4）](https://www.bilibili.com/video/BV1fFyJBFE92/?p=4)保存在顶层 `userVideoEntry`。本次未读取 B 站正文、未核实分 P 标题及其与 Week 0–9 的对应关系，因此 `sourceVerified=false`、`status=unverified`、`weekMapping=null`。后续取得可核实的分集信息后再建立映射。

抖音视频的方法没有得到核实，本索引不声称已按该视频的方法设计。

## 内容与状态约定

- 中英文主题名称用于课程导航；中文简述由工作台编写，是课程主题的原创摘要。
- 索引不复制完整讲义，不包含官方题目的答案。原创中文辅助内容保存在 `data/learning-content.json`。
- 用户已确认每周三道原创练习，共 30 道，`independentPractice.exerciseCount=30`；各题标明 `source_type=original`。
- `sourceVerified` 表示链接及其课程归属有官方来源支持。资源 `status` 进一步区分网页已读取、播放器页面已读取、仅官方列出链接、不适用及未列出。
- 缺失资源保留 `url=null` 和说明。`absenceVerified` 表示核查了所引用页面没有列出该类入口，不表示断言互联网中完全不存在相关材料。
- 稳定条目 ID 为 `week-0` 至 `week-9` 和 `final-project`。排序为 0–10；用户学习记录应引用 ID，避免依赖可调整的中文名称。

## 本次检查

JSON 成功解析；共 11 个条目；ID 唯一；前十个条目按 Week 0–9 排列；最后一个是 Final Project；仅 Week 0–8 有 Problem Set URL；Week 9 与 Final Project 的 Problem Set URL 为 `null`；B 站周次映射为 `null`。
