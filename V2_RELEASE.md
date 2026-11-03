# V2.0

版本号 `2.0.0`。计算仍然只使用已经入库的公开观测。

局部投影带有滞后控制和 HAC 95% 区间，期限为 1、3、5、10、21、42、63 日。标签保持约化式。方差贡献可以指定两个加总为 1 的非负权重，并给出 Ledoit-Wolf 收缩份额。ΔCoVaR 是条件分位数的描述性差值。回放截面、持仓和修订差都按光标日过滤；终值发布日晚于光标日时标为事后信息。

工作台由 `/api/workbench` 一次返回。新鲜度是 as_of 与最后可见观测日的间隔。`QUANTRISKLAB_DB` 只在目标文件已经存在，或可以从内置快照复制出来时生效。这次部署没有挂载空卷，也没有执行 `railway config apply`。`railway.toml` 仍用来选择 Dockerfile。Config as Code 的替换期限是 2026-12-01。

`scripts/extend_v11.py` 会尝试补公司债 OAS、分段的 UNRATE vintage、2018 年起的 CFTC 压缩包，以及对 `GOLDPMGBD228NLBM` 的一次请求。没有返回的序列保持缺口。
