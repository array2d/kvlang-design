# 008: while 条件不支持复合表达式

**严重程度**: 中 — 强制引入 flag 变量

**现象**: `while (i < n && !found)` 不支持，只能:
```
0 -> done
while (done == false) {
    i < n -> cond1
    cond1 == false -> at_end
    if (at_end) { true -> done }
    # ...
}
```

**建议**: 支持 `&&`/`||` 在 while 条件中。
