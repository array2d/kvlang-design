# 006: `print("str:", val)` 解析冒号为数字字面量的一部分

**严重程度**: 低 — workaround 简单，但反直觉

**现象**:
```
print("121:", a)   → 报错 "invalid numeric literal '121:'"
print("121", a)    → 正常输出 "121 true"
```

**workaround**: 不在字符串值后面紧跟 `:`，改用空格: `print("121 :", a)`

**建议**: parser 在解析 `"121:"` 时不应把 `:` 当作数字的一部分。
