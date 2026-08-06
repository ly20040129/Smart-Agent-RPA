# models 目录

这里放所有数据表定义，一个class对应一张MySQL表。

## 文件说明

| 文件 | 内容 |
|------|------|
| base.py | 基类BaseModel和Column定义 |
| finance_models.py | 财务：微信账单、京东销售、天猫库存、日报 |
| business_models.py | 业务：销售、库存、运营、客户反馈 |
| task_models.py | 任务历史、下载记录 |
| user_models.py | 用户、部门（预留，目前用JSON） |

## 新增一张表

1. 打开对应文件（比如财务的打开 finance_models.py）
2. 复制一个class，改table_name和列：

```python
class MyTable(BaseModel):
    table_name = "my_table"
    id     = Column("id", "INT AUTO_INCREMENT PRIMARY KEY", "主键")
    date   = Column("date", "DATE", "日期")
    amount = Column("amount", "DECIMAL(15,2)", "金额")
```

3. 在 `__init__.py` 里加一行import
4. 用的时候传给MySQL.save就行，表不存在会自动建

## Column类型参考

| 类型 | 用途 |
|------|------|
| INT AUTO_INCREMENT PRIMARY KEY | 自增主键 |
| INT | 整数 |
| DECIMAL(15,2) | 金额 |
| VARCHAR(100) | 短文本 |
| VARCHAR(500) | 长文本 |
| DATE | 日期 |
| DATETIME | 日期时间 |
| TEXT | 超长文本 |
