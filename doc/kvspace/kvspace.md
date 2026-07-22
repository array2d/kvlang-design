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
    LinkSentinel = "->" // 链接标记
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

**Mount**：`Mount("/real", "/alias")` 写入 `->/real` 标记到 `/alias`。访问 `/alias/x` 透明解析为 `/real/x`，40 跳防环。

**Overlay**：`Overlay("/target", "/readonly", "/writable")` 创建叠加层。读 `/target/` 先查 `/writable/`，不存在则回退 `/readonly/`。写操作只落 `/writable/`。`UnMount` 删除 writable 层。

**UnMount**：删除 Mount 或 Overlay 的映射。

## Redis 实现

### 连接

```go
kv := kvspace.Conn("redis://host:port")  // 默认 poolSize=16
```

DSN scheme 注册机制：`init()` 中 `kvspace.Register("redis", ConnPool)`。

### 索引维护

`Set` 写入 key 时，沿路径每级 `SADD parent/ child` 维护目录索引。`Del` 删除 key 时，级联清理空目录（`delIndex`）。

### 链接

`Mount` 调用 `Link(target, linkpath)`：`SET linkpath "->target"` + 维护索引。`checkLink` 惰性缓存：首次 `Get` 时检查是否为链接，结果缓存在 `linkEntry{checked, target}` 中，后续访问不查 Redis。

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
