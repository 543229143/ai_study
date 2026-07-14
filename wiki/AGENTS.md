# LLM 知识库工作规则

## 总体说明

这是一个个人 LLM 知识库。原始资料放在 `raw/` 里，编译后的 wiki 放在 `wiki/` 里。
你（AI）负责维护 wiki 内容；我负责决定方向，你负责执行整理、编译、维护和问答。

## 目录结构

- `raw/xurong/{lcs,lps,goa,ams,widek,zhangwu}/`：编码项目原始资料（源码在 `/Users/zhaoxin/code/inner/`）
- `raw/xurong/_shared/`：跨项目共享原始资料（涉及多个项目的需求、架构决策等）
- `raw/tech-learning/`：技术学习原始资料（papers/courses/experiments）
- `raw/personal/`：个人事务原始资料（finance/health）
- `wiki/_global-index.md`：全局索引，列出所有主题的索引页
- `wiki/log.md`：操作日志，只追加
- `wiki/{topic}/{subtopic}/`：编译后的知识库
  - `_index.md`：该子主题的索引
  - `concepts/`：概念页面
  - `entities/`：人物、组织、工具等实体页面
  - `sources/`：每个原始资料一篇摘要
  - `syntheses/`：跨资料综合分析
  - `notes/`：你自己写的学习总结/笔记（AI 不拆解，只建立 `[[wikilinks]]` 引用）
  - `outputs/`：问答结果归档

## 文件规范

- 文件名统一使用 kebab-case，全小写
- 每页顶部必须 YAML frontmatter：

```yaml
---
title: "页面标题"
date_created: 2026-06-12
date_modified: 2026-06-12
summary: "一句话说明"
tags: [标签1, 标签2]
type: concept | entity | source | synthesis | output | index
status: draft | review | final
---
```

- 内部交叉引用使用 `[[wikilinks]]`
- 关键术语第一次出现时加粗
- 内容以中文为主

## 操作规则

### INGEST（添加新原始资料时）

1. 读取 `raw/` 下新加的原始资料
2. 在对应 `wiki/{topic}/{subtopic}/sources/` 中创建摘要
3. 识别核心概念和实体
4. 在 `concepts/` 和 `entities/` 中创建或更新对应页面
5. 用 `[[wikilinks]]` 建立关联
6. 更新该子主题的 `_index.md`
7. 如果在多个主题间发现关联，更新 `_global-index.md`
8. 在 `wiki/log.md` 中追加操作记录

### QUERY（提问时）

1. 先读 `wiki/_global-index.md`，了解整体内容
2. 再读取相关子主题的 `_index.md` 和具体页面
3. 输出带 `[[wikilinks]]` 引用来源的综合答案
4. 把答案保存到对应主题的 `outputs/` 下
5. 更新 `_index.md` 和 `log.md`

### LINT（定期健康检查）

1. 找页面之间的冲突（用 ⚠️ 标出）
2. 找没有入链的孤儿页面
3. 找失效的 `[[wikilinks]]`
4. 检查 frontmatter 是否缺字段
5. 标记过期内容（来源超过 6 个月且没更新）
6. 找出频繁被提到但还没独立成页的概念
7. 能自动修的直接修，不能修的输出报告

## 什么时候该新建页面

- 某个概念或实体在 2 篇及以上资料中出现时，创建完整页面
- 只出现过 1 次，先创建 stub 页面（frontmatter + 一句定义 + 回来源的链接）
- 不允许存在指向空白页面的 `[[wikilink]]`

## 质量标准

- 摘要 200-500 字，综合提炼，不要照抄
- 概念文章 500-1500 字，开头要有清晰导语
- 所有判断要追溯到具体来源页
- 冲突内容用 ⚠️ 标出，双方观点都写清楚
- 如果不同来源打架，优先相信更新、更新的资料
