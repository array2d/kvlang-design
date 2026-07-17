# ISSUE: a[i] 作为嵌套表达式参数时 panic

`a[i]` 经过 Pratt 循环展开为 `at(a, i)` 调用后，若作为更大表达式的参数
（如 `target <= a[hi]`），lower 检测到 `at` 调用不是叶节点 → panic。

## 根因
Pratt 循环中将 `left = ast.Call("at", args...)` 内联进表达式树，
后续的比较/算术算子把 `at(a, i)` 当作直接参数，违反 `allArgsLeaf`。

## Workaround
手动展开：`a[hi] -> _tmp; target <= _tmp -> result`

## 影响题目
033, 034, 074 等需要 `a[mid]` 在比较表达式中的题目
