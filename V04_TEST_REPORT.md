# V0.4 测试

日期：2026-10-17。

第一次全量 `pytest -q` 因为输出被缓冲，进程在数分钟后被停掉，没有留下通过或失败的计数。

修复回放序列的空值类型后，重新运行 `pytest -q --tb=line`，退出码 0。收集到的测试共 27 项：

- test_api 1
- test_cftc_release 3
- test_manifest 2
- test_manifest_sha 2
- test_missing 1
- test_pit 3
- test_risk_metrics 1
- test_secrets 1
- test_structure 4
- test_v03_rules 5
- test_v04_studio 4

输出为 27 个点，退出码 0。另有 Starlette 使用 httpx 的弃用警告。

`npx tsc --noEmit` 通过。

`npm run build` 通过。产物 `frontend/dist/assets/index-DRrFzlui.js` 1,299.26 kB，gzip 426.43 kB。仍然是单个大包，没有按需拆开 ECharts。

`/api/replay?as_of=2012-01-03` 返回 502 个点，事件窗口为 0。健康检查版本 0.4.0。

日期快速切换脚本 `tests/e2e/date-switch.cjs` 在 V0.3.1 修复后已经通过。V0.4 页面截图另见发布验收。