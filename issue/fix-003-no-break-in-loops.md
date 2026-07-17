# 003: while 循环内无法提前退出

**严重程度**: 高 — 所有搜索类算法被强制写成 flag 模式

**现象**: `break` 不存在，`return` 在循环内效果不确定。要提前退出循环只能:
```
0 -> done
while (done == false) {
    if (found) { true -> done }
    # 主逻辑...
}
```

这导致:
- 代码量翻倍
- 逻辑晦涩（`true -> done` 后再执行一轮才退出）
- `while (i < n && !found)` 这类复合条件也不支持

**建议**: 实现 `break` 关键字，或在 lower 阶段将 `return` 正确转换为退出循环。
