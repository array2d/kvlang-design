# kvlang 数组与高维索引设计

> 基于 deepx 深度学习框架经验：数组节点有 `.shape` 子 key。
> 索引语法对标 C/Go/Rust/Python/JS：`a[i, j]`，逗号分隔维度。

---

## 一、语法

### 1.1 数组字面量

```
[1, 2, 3] -> a                      # 1D, shape = "3"
[[1, 2], [3, 4], [5, 6]] -> m       # 2D, shape = "3,2"
```

### 1.2 索引

```
a[0] -> x                           # 1D 读
x -> a[0]                           # 1D 写
m[0, 1] -> v                        # 2D 读
m[i, j] -> v                        # 2D 动态索引
t[0, 1, 2] -> v                     # 3D
```

对标 C 的 `a[i][j]`、Python 的 `a[i, j]`（NumPy 风格）。
逗号分隔 = 维度边界，与 shape 的逗号分隔一致。

### 1.3 遍历

```
for (elem in a) { print(elem) }     # 1D：逐个元素

for (row in m) {                    # 2D：外层
    for (col in row) {              # 内层（row 是子数组）
        print(col)
    }
}
```ß

---

## 二、Scanner / Parser

`[` `]` `,` 已有（`,` 已在 scanner 中）。`[` `]` 新增为 token。

Pratt parser 中 `[` 作为后缀索引：

```go
// 已解析 left = Leaf("a")
// peek = '['
case '[':
    advance() // consume [
    var indices []*Expr
    for peek != ']' {
        indices = append(indices, parseExpr(0))
        if !eat(',') { break }
    }
    expect(']')
    return IndexExpr(left, indices)
```

AST:
```go
type IndexExpr struct {
    Base    *Expr    // 被索引的数组
    Indices []*Expr  // 各维度索引表达式
}
```

---

## 三、Runtime

### 3.1 索引 → 路径构造

`a[i, j]` 的运行时行为等价于 `kv.at(kv.at(a, i), j)`。

```
a[0]      → kv.Get(frameRoot + "/a/0")
a[0, 1]   → kv.Get(frameRoot + "/a/0/1")
a[i, j]   → 运行时拼接: prefix + "/" + str(i) + "/" + str(j)
```

用户看到的语法是 `a[i, j]`，内部用 `/` 存储——**逗号是语法，`/` 是存储**。

### 3.2 数组字面量 lowering

```
[1, 2, 3] -> a
```
展开为：
```
newarray(3) -> a         # 写 /a/shape = "3"
1 -> a/0
2 -> a/1
3 -> a/2
```

```
[[1, 2], [3, 4]] -> m
```
展开为：
```
newarray(2, 2) -> m      # 写 /m/shape = "2,2"
1 -> m/0/0; 2 -> m/0/1
3 -> m/1/0; 4 -> m/1/1
```

### 3.3 `.shape` 子 key

```
/a/shape = "3,4"         ← 逗号分隔维度，与索引语法一致
```

| builtin | 语义 |
|---------|------|
| `newarray(d1, d2, ...)` | 创建数组 + 写 `.shape` |
| `len(a)` | 读 shape，返回总元素数（各维乘积） |
| `len(a, dim)` | 返回第 dim 维大小 |
| `shape(a)` | 返回 shape 字符串 |

---

## 四、与 5 种语言对比

| | C | Go | Rust | Python | JS | kvlang |
|--|---|---|------|--------|----|--------|
| 索引 | `a[0][1]` | `a[0][1]` | `a[0][1]` | `a[0,1]` | `a[0][1]` | `a[0,1]` |
| 形状 | 类型 | 类型 | 类型 | `.shape` | `.length` | **`/a/shape`** |
| 动态 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ + 随时加维 |

kvlang 继承 Python 的逗号分隔（NumPy 用户直觉），形状存储对标 deepx 做法（kvspace 子 key）。

---

## 五、热转（动态 reshape）

### 5.1 5 种语言对比

| | reshape 支持 | 机制 | 是否拷贝数据 |
|--|------------|------|------------|
| **C** | ❌ | 无 | — |
| **Go** | ❌（slice 可切割，不可改维） | — | — |
| **Rust** | ❌（`Vec` 可 grow，不可 reshape） | — | — |
| **JS** | ❌ | — | — |
| **Python (NumPy)** | ✅ `ndarray.reshape()` | 若 row-major 兼容则零拷贝（返回 view）；否则 `copy=False` 报错 | o(1) 或 o(n) |
| **kvlang** | ✅ `reshape(a, "2,3")` | 修改 `/a/shape`，**零拷贝、零移动** | **o(1)** |

kvlang 的独特优势：**元素独立寻址**（每个 `a/0`、`a/0/1` 是独立的 kvspace key），
没有"连续内存缓冲区"。shape 只是元数据，修改 shape 不需要移动任何数据。

NumPy 需要检查 row-major 兼容性（C-contiguous vs Fortran-contiguous），
kvlang 完全不需要——shape 改了就立即生效：
```
/a/shape = "6"            → a[0]..a[5] 是 1D 数组
reshape(/a, "2,3")        → a[0,0]..a[1,2] 即变为 2×3 矩阵，元素不变
reshape(/a, "3,2")        → 再转置，零开销
```

### 5.2 `reshape` 语义

```
reshape(a, "2,3")          → 修改 /a/shape，不移动元素
reshape(a, "3")            → 降维
reshape(a, "2,2,2")        → 升维（前提：总元素数 8 = 2×2×2）
```

约束：新 shape 的元素乘积必须等于旧 shape 的元素乘积（对标 NumPy）。

---

## 六、实现路线

| 阶段 | 内容 |
|------|------|
| P1 | Scanner 加 `[` `]` token |
| P2 | Parser 后缀索引 `a[i, j]` |
| P3 | lower: 索引 → 路径拼接；字面量 → newarray + 逐元素写入 |
| P4 | `newarray` / `len` / `shape` builtin |
| P5 | for 遍历器利用 shape 判定边界 |
