# Point-in-time 规范

旧接口仍用日期：`release_date <= as_of` 且 `observation_date <= as_of`。这是日级可得性，不是无前视的日内信息集。

新接口 `GET /api/availability` 列出信息时钟字段。`available_at_utc` 在不能逐条核实历史发布时间时留空，不编造时间戳。

- DFF：纽约联储下一营业日上午约 9:00 公布。库内日期仍是近似。
- H.15 收益率：现行惯例为美东 16:15，未逐日核实。
- T10Y2Y：会计恒等式，不早于两个分量。
- CPI：ALFRED 的 realtime_start 是发布日。
- CFTC：周五 15:30 惯例；周三至周五遇联邦假日则顺延。日期规则已与官方 2026 日历样本对齐。

`GET /api/snapshot` 给出数据库文件修改时间。`stale` 是建库时写入的，部署后的静态库不会自动更新。