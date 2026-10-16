# 幸运橱窗券抵扣消费契约

IronsBot 从自己的 SeerAPI 发布数据库读取正式抵扣规则，不根据道具 ID、名称或描述在运行时猜测金额。

必需表：

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

发布校验要求规则表及四个字段存在。旧数据库缺表或字段时明确拒绝加载，不兼容双读旧 schema。**External gate：必须先构建并发布包含新表的新 SeerAPI 数据，然后才能部署本消费者版本。** 本地 SQL fixture 和契约测试不代表远端数据已发布或生产已同步。

不需要修改 TOML、环境变量或 Unraid 配置。生产方负责从正式道具说明中提取幸运橱窗适用范围、抵扣额及来源证据，消费者只使用其发布结果。
