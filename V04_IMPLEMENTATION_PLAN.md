# V0.4 实施记录

在 V0.3.1 上增加研究工作流，不改写已验收的 coexceedance、lift、相似聚类、CFTC 顺延和百分比回撤规则。

## 阶段

- A 历史回放：`/api/replay` 返回 as_of 之前的利率、VIX、价格收益和股油滚动相关。页面有时间轴、播放、暂停、速度和预设事件跳转。
- B 探索：`/api/explore` 只允许价格用简单收益、利率用差分、VIX 和 CPI 用水平。利差与国债收益率标成会计恒等式。
- C 尾部：`/api/tails` 调用原来的 `lower_tail_dependence`。可选 0.01、0.05、0.1，给出样本量、区间、事件日期和敏感性。收益率不能进入这个估计。
- D 对照：`/api/compare` 用原来的窗口函数比较预设危机。没有数据时状态是 missing。
- E 实验：`POST /api/experiments` 写到本机 `data/experiments`，该目录已忽略。页面可导出 Markdown、CSV、回放 PNG 和由真实点生成的 SVG。
- F 界面：新增回放、探索、尾部、对照、实验五个入口。旧的四个页面还在。
- G 验收：见另外两份记录。

没有做的：ECharts 按需拆包、1920px 单独版式、任意手填事件窗口、把实验做成可检索的数据库。