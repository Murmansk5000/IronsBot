# 幸运橱窗券抵扣消费契约

IronsBot 从自己的 SeerAPI 发布数据库读取正式抵扣规则，不根据道具 ID、名称或描述在运行时猜测金额。

SeerAPI 新发布数据必须提供下表；IronsBot 将它视为可独立缺失的价格能力，而非基础查询的加载条件：

```sql
CREATE TABLE skin_ticket_rule (
    ticket_id INTEGER PRIMARY KEY,
    diamonds_per_ticket INTEGER NOT NULL CHECK(diamonds_per_ticket > 0),
    source TEXT NOT NULL,
    source_text TEXT NOT NULL
);
```

`skin_store_price` 同时 LEFT JOIN `item` 和 `skin_ticket_rule`，单次批量查询取得名称和每张券的抵扣额。规则缺行映射为 `SkinStorePrice.ticket_diamonds = None`：仅展示券名、数量，不计算最低价。没有名称时展示道具 ID；不存在按名称识别风尚券或固定十钻的路径。

图片按四张卡实际使用的券 ID 去重加载，逐卡选择对应道具图标。只有有效报价及正式正数抵扣规则才展示付款图标行；未使用的券图标和钻石图标不会下载，也不会影响缓存。实际需要的素材缺失时局部降级，并跳过渲染缓存以便之后重试。保持当前默认布局。

缺少规则表、字段或对应规则行时，只展示报价、券名和数量，不计算抵扣额及最低价；精灵、技能、立绘等查询不受影响。基础数据的 schema 版本、声明表及指纹校验仍然有效，声明存在但实际丢失的表仍属于损坏数据，不能静默接受。

生产方必须先构建并发布包含新表的数据，再上线依赖该能力的程序。构建流程同时比较生成器源码指纹和外部数据指纹；即使外部数据未更新，生成器或模型改变也会重建。仅在发布下载校验成功后保存指纹，失败后下次继续构建。本地 SQL fixture 和契约测试不代表远端数据已发布或生产已同步。

不需要修改 TOML、环境变量或 Unraid 配置。生产方负责从正式道具说明中提取幸运橱窗适用范围、抵扣额及来源证据，消费者只使用其发布结果。
