# kvspace

KV 树形存储的 Go 客户端 SDK。对应仓库 `github.com/array2d/kvspace-go`。

## KVSpace 接口

```go
type KVSpace interface {
    Get(keys []string) []XValue         // 批量读，缺失返回 null XValue
    Set(pairs []KVPair) error           // 批量写，维护目录索引；key 禁止尾斜杠
    List(prefix string) []string         // 列出直接子项
    Del(keys ...string) error           // 精确删除
    DelTree(prefix string) error        // 递归删除；prefix 本身是链接则只删链接

    Notify(key string, val XValue) error
    Watch(key string, timeout time.Duration) XValue  // 超时返回 null XValue

    Mount(target, linkpath string) error // 路径映射 linkpath → target
    Overlay(target, r, w string) error   // overlay：读 w/ → r/ 回退
    UnMount(linkpath string) error       // 删除映射

    Clear() error   // redis: FLUSHDB
    DisConn() error
}
```

**Get/Set** 统一批处理，单 key 操作传 `[]string{"k"}`。**Watch** 超时返回 kind=null 的 XValue。

## XValue 类型系统

```
TLV wire format: [1B kind_len][N B kind_name][4B raw_len LE][M B raw_value]
```

| kind | Go 构造 | Go 读取 | raw 格式 |
|------|---------|---------|----------|
| `int8`–`int64` | `Int8(v)`–`Int64(v)` | `v.Int64()` 宽容读 | LE |
| `uint8`–`uint64` | `Uint8(v)`–`Uint64(v)` | `v.Uint64()` 宽容读 | LE |
| `float32`/`float64` | `Float32(v)`/`Float64(v)` | `v.Float64()` | LE |
| `bool` | `Bool(v)` | `v.Bool()` | 1B |
| `string` | `Str(s)` / `String(s)` | `v.Str()` | UTF-8 |
| `bytes` | `Bytes(b)` | `v.Bytes()` | 原始 |
| `array1d` | `Array(elems)` | `v.Len()`, `v.Index(i)` | [4B count][elem TLV]… |
| `dict` | `Dict()` | — | 空，键族标记 |
| `time` | `Time(ns)` | `v.TimeNs()` | 8B LE UnixNano |
| 任意 | `Raw(kind, raw)` | `v.RawBytes()` | 原始 |

`Int64()`/`Uint64()`/`Float64()` 是宽容读取器：kind 对不齐时返回 0，不 panic。

## 路径模型

所有 key 以 `/` 开头。**尾斜杠 `/` 表示目录**，存储该目录的子项集合（Redis SET）。

```
/a          value（不以 / 结尾）
/a/         目录索引（/a 的子项集合：{b, c}）
/a/b        value
```

**约束**：`Set` 拒绝尾斜杠 key，value 键和目录键永不相交。

根目录 `/` 的索引键就是 `/` 本身。`dirKey(parent)` 处理此特例：

```go
func dirKey(parent string) string {
    if parent == kvspace.PathSep { return kvspace.PathSep }
    return parent + kvspace.DirIndexSuf
}
```

**JoinPath** 避免根路径拼接产生 `//`：

```go
func JoinPath(parent, child string) string {
    if parent == PathSep { return PathSep + child }
    return parent + PathSep + child
}
```

## 常量

```go
const (
    PathSep     = "/"   // 路径分隔符
    DirIndexSuf = "/"   // 目录索引后缀
    LinkSentinel    = "->" // mount 标记
    OverlaySentinel = "#>" // overlay 标记
)

// XValue kind
const (
    KindNull = "null"
    KindInt64 = "int64"  // + int8/16/32, uint8/16/32/64, float32/64
    KindString = "string"
    KindBytes  = "bytes"
    KindArray1d = "array1d"
    KindDict  = "dict"
    // ...
)
```

## Mount 系统

### 存储格式

```
Mount:   SET linkpath  "->target"          → 简单路径重定向
Overlay: SET target    "#>w_path\nr_path"  → 叠加层（先 w 后 r）
```

两种类型通过首字节区分：`-` = mount，`#` = overlay。

### Mount

`Mount("/real", "/alias")` 写入 `->/real` 到 `/alias`。`ResolveCore` 在路径解析时透明替换 `/alias/x` → `/real/x`。最多 40 跳防环。

### Overlay 

`Overlay("/merged", "/readonly", "/writable")` 创建叠加层，写入 `#>\/writable\n/readonly` 到 `/merged`。

**读路径**：`Get("/merged/x")` → `resolveOL` 沿路径向上查找 overlay 祖先 → 返回 `(wPrefix, rPrefix)` → 先 `GET wPrefix`，miss 则 fallback `GET rPrefix`。

**写路径**：`Set("/merged/x", val)` → 发现 overlay → 直接写入 w 层（`/writable/x`）。r 层只读，绝不写入。

**List**：`List("/merged")` → 合并 `SMEMBERS dirKey(wPrefix)` + `SMEMBERS dirKey(rPrefix)`，w 的条目去重优先。

**UnMount**：删除 w 层全部数据及索引，再删除 overlay 标记本身。r 层不受影响。

## Redis 实现

### 连接注册

```go
kv := kvspace.Conn("redis://host:port")  // 默认 poolSize=16
```

DSN scheme 注册：`init()` 中 `kvspace.Register("redis", ConnPool)`。`ConnPool` 创建 go-redis 连接池（MinIdleConns、PoolTimeout、Read/WriteTimeout）。

### 索引维护

`Set` 写入 key 时，对路径的每级父目录 `SADD dirKey(parent) child` 维护索引。`Del` 删除 key 时，`delIndex` 级联清理空目录：若目录已无子项且自身无 value，则从祖父索引中 SREM 该目录名，沿祖先链向上重复。

### linkEntry 缓存

```go
type linkEntry struct {
    checked   bool
    target    string    // mount: 目标路径
    isOverlay bool
    w, r      string    // overlay: writable / readonly 层
}
```

`checkLinkEntry(path)`：惰性加载 + 全缓存。首次访问查 Redis，根据 sentinel（`->` 或 `#>`）解析为 mount 或 overlay。之后所有访问走内存缓存，零 Redis 查询。

`resolveOL(path)`：沿路径从深到浅逐级查 `checkLinkEntry`，返回最深层 overlay 祖先的 `(wPrefix, rPrefix)`。无 overlay 返回 `("", "", false)`。

### Get/Set/List 的 overlay 分支

- **Get**：`ResolveCore` 先解析普通 mount 链接，再 `resolveOL` 检测 overlay。无 overlay 走 pipeline 批量 GET。有 overlay 的 key 单独处理：先 GET w 路径，miss 则 GET r 路径。
- **Set**：`ResolveCore` → `resolveOL`，发现 overlay 则将 resolved key 替换为 w 层路径。写入只落 w。
- **List**：发现 overlay 则合并两层的 `SMEMBERS`，w 的 key 去重优先。

## Walk

```go
func Walk(kv KVSpace, prefix string, fn func(path string, v XValue))
```

深度优先递归遍历。节点无值时 fn 不被调用。遍历顺序：前缀序（等同于 `ls -R`）。

## CLI 工具

```bash
kvspace get /a /b /c           # 批量读取
kvspace set /k string:hello    # 单 key 写入
kvspace del /a /b              # 精确删除
kvspace deltree /prefix        # 递归删除
kvspace list /                 # 列出子项
kvspace tree /                 # 可视化树（含 [s0,s1] 二维表格打印）
kvspace dump /                 # 递归遍历，每行 key:value
kvspace watch --timeout 5s /k  # 阻塞等待通知
kvspace notify /k string:msg   # 推送通知
kvspace mount /real /alias     # 创建路径映射
kvspace unmount /alias         # 删除映射
kvspace clear                  # FLUSHDB
```

`--kvspace dsn` 指定后端地址，默认 `redis://127.0.0.1:6379`。环境变量 `KVLANG_KVSPACE` 覆盖。
