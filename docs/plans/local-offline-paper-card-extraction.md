# 本地论文离线剥卡与 embedding 比对 Implementation Plan

> **For Hermes:** use this plan task-by-task. 先实现离线剥卡，再做 embedding 比对；以“多数成功、少数容错”为目标，不追求 100% 抽取完整。

**Goal:** 将本地 PDF 论文批量抽取成统一的 JSONL 卡片，字段包含 title / abstract / keywords / conclusion / text_for_embedding，可直接用于硅基流动 embedding 与 arXiv 论文比对。

**Architecture:**
- 抽取与比对分离：先做离线剥卡，再做在线比对。
- 卡片格式统一为 JSONL，一行一篇，允许字段缺失。
- 主干字段是 title + abstract；keywords / conclusion 是增强字段，缺失不影响整体可用性。
- 失败不是整篇失败，而是字段级失败；用状态字段和质量分数记录可用程度。

**Tech Stack:** Python, PyMuPDF, JSONL, OpenAI-compatible embeddings via SiliconFlow, existing project utils.

---

## 统一数据格式

建议输出到：
- `data/local_papers.jsonl`

每条记录建议字段：
```json
{
  "id": "sha256_or_stable_id",
  "path": "/abs/path/to/paper.pdf",
  "title": "...",
  "abstract": "...",
  "keywords": ["...", "..."],
  "conclusion": "...",
  "text_for_embedding": "Title: ...\n\nAbstract: ...\n\nKeywords: ...\n\nConclusion: ...",
  "status": {
    "title_ok": true,
    "abstract_ok": true,
    "keywords_ok": false,
    "conclusion_ok": true,
    "usable_for_embedding": true
  },
  "quality_score": 0.86,
  "source": "local_pdf",
  "extracted_at": "2026-06-10T12:00:00"
}
```

### 可用性判定
- **最低可比对条件**：`title_ok && abstract_ok`
- **增强条件**：`keywords_ok`、`conclusion_ok`
- **允许缺失**：keywords / conclusion / 部分元信息
- **不建议硬判失败**：缺一个字段就丢整篇

---

## Task 1: 先定义剥卡规则与字段优先级

**Objective:** 明确每个字段的提取优先级、兜底规则和失败处理方式，避免后面实现时反复改结构。

**Files:**
- Create: `docs/plans/local-offline-paper-card-extraction.md`
- Later modify: `src/zotero_arxiv_daily/ingest_pdfs.py`
- Later modify: `src/zotero_arxiv_daily/corpus/local_pdf.py`

**规则建议：**
- **title**：`PDF metadata.title -> 前导区多行拼接 -> 文件名兜底`
- **abstract**：`Abstract/ABSTRACT/摘要` 识别，找不到就标记缺失，不硬猜
- **keywords**：`Keywords/Index Terms/关键词`，找不到就空列表
- **conclusion**：`Conclusion/Conclusions/Discussion and Conclusions/Summary/Final Remarks`，找不到就空字符串
- **text_for_embedding**：按固定模板拼接，只拼有值的字段

**验收标准：**
- 规则写清楚且能覆盖常见论文格式。
- 明确“缺失字段不影响整篇可用”。

---

## Task 2: 设计离线剥卡脚本入口

**Objective:** 设计一个单独脚本，扫描本地 PDF 目录，生成 JSONL 卡片。

**Files:**
- Create: `scripts/extract_local_paper_cards.py`（或项目内对应入口文件）
- Later modify: `config/base.yaml` 或 `config/custom.yaml`

**输入建议：**
- `--input-root`：本地 PDF 根目录
- `--output-jsonl`：输出卡片文件
- `--recursive`：递归扫描
- `--max-pages`：抽全文页数上限
- `--limit`：只处理前 N 篇，便于调试

**输出建议：**
- 主输出：`data/local_papers.jsonl`
- 失败日志：`data/local_papers_failed.jsonl`
- 统计日志：`data/local_papers_summary.json`

**验收标准：**
- 能从一个目录批量扫描 PDF。
- 能稳定写出 JSONL。
- 出错时不会中断整个批处理。

---

## Task 3: 实现字段提取与容错

**Objective:** 在 PDF 文本层提取 title / abstract / keywords / conclusion，并确保少量失败不影响整体。

**Files:**
- Modify: `src/zotero_arxiv_daily/ingest_pdfs.py`
- Modify: `src/zotero_arxiv_daily/corpus/local_pdf.py`
- Optional later: `src/zotero_arxiv_daily/protocol.py`

**建议实现细节：**
1. **title 提取**
   - metadata 优先
   - 前导区多行组合候选标题
   - 排除 `Received/Accepted/DOI/IEEE/Springer/Elsevier/proof` 等元信息
2. **abstract 提取**
   - 先找 `Abstract` 区块
   - 找不到就留空
3. **keywords 提取**
   - 识别 `Keywords` / `Index Terms`
   - 没有就空列表
4. **conclusion 提取**
   - 支持多个结尾章节标题
   - 找不到就留空
5. **生成 quality_score**
   - title 和 abstract 权重大
   - keywords / conclusion 加分
   - 明显垃圾标题扣分

**验收标准：**
- 绝大多数正常论文能拿到 title + abstract。
- 少量论文缺 keywords / conclusion 不影响整体入库。
- 结果里能区分字段级成功和失败。

---

## Task 4: 生成统一的 text_for_embedding

**Objective:** 把不同来源、不同字段完整程度的论文统一成一个可直接送进 embedding 的文本。

**Files:**
- Modify: `src/zotero_arxiv_daily/reranker/base.py`
- Optional: 新增一个公共 helper 文件，例如 `src/zotero_arxiv_daily/utils/embedding_text.py`

**建议模板：**
```text
Title: ...

Abstract: ...

Keywords: ...

Conclusion: ...
```

**规则：**
- 只拼接存在的字段
- 不写空标签
- 保持与 arXiv 论文一致的模板

**验收标准：**
- 任意一篇卡片都能生成稳定的 `text_for_embedding`。
- 与 arXiv 文本格式一致，便于后续直接比对。

---

## Task 5: 做质量统计与抽样 QA

**Objective:** 验证“多数成功”的假设是否成立，并找出提取规则的薄弱点。

**Files:**
- New optional script: `scripts/qa_local_paper_cards.py`

**建议输出统计：**
- 总 PDF 数
- title 成功率
- abstract 成功率
- keywords 成功率
- conclusion 成功率
- usable_for_embedding 比例
- top 20 失败样例（文件名 + 原因）

**抽样 QA：**
- 随机抽 10~20 篇
- 人工看 title 是否错位、abstract 是否截断、conclusion 是否误抓
- 根据失败样例回调规则

**验收标准：**
- 能量化“多数成功”。
- 能明确知道哪些格式的 PDF 最容易失败。

---

## Task 6: 接入硅基流动 embedding 比对

**Objective:** 让离线卡片直接和 arXiv 论文用同一套 embedding 进行相似度计算。

**Files:**
- Modify: `src/zotero_arxiv_daily/reranker/api.py`
- Modify: `config/base.yaml` / `config/custom.yaml`
- Optional: 新增 `scripts/compare_local_cards_with_arxiv.py`

**建议策略：**
- 统一读 `text_for_embedding`
- 统一使用 `Qwen/Qwen3-Embedding-0.6B`
- 缺失 conclusion 不影响比对
- 先保证批量跑通，再调排序质量

**验收标准：**
- 离线卡片能和 arXiv 论文稳定做 similarity ranking。
- API 调用成功率高，少量失败可重试。

---

## Task 7: 最终验证与参数收敛

**Objective:** 通过几批真实 PDF 运行，确定默认参数和抽取阈值。

**建议检查：**
- `max_pages` 取值是否合适
- 标题截取是否太激进
- `conclusion` 是否常误抓摘要后半段
- 是否需要为个别出版社单独加规则

**验收标准：**
- 一个目录的 PDF 能稳定剥卡。
- 结果足够稳定，可以作为后续日常工作流使用。

---

## 总结：推荐的默认策略

**最小可用标准：**
- `title + abstract` 必须尽量保住
- `keywords + conclusion` 能提则提，不能提也不阻塞
- 少数失败允许存在，不影响整体流程

**最终目标：**
- 先把本地论文离线做成“标准卡片库”
- 再用同一套 embedding 模型和 arXiv 论文比对
- 把抽取与比对彻底解耦，后续维护更稳

---

## 下一步建议
如果开始实施，推荐顺序是：
1. 先做 `JSONL schema + 剥卡规则`
2. 再做 `批量抽取脚本`
3. 再做 `QA 统计`
4. 最后接入 `embedding 比对`
