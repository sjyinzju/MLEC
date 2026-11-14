# 多来源冲突与版本核对

| 类别                                 |   对数 |
|:-------------------------------------|-------:|
| ROUNDING_ONLY                        |    626 |
| EXACT_MATCH                          |  13344 |
| VALUE_CONFLICT                       |    592 |
| DATED_PUBLICATION_VERSION_DIFFERENCE |    281 |
| SEMANTIC_ERROR                       |    268 |

同一可得时刻的已认证冲突记录数：0。全部配对证据见source_reconciliation.csv/parquet。没有用简单来源优先级覆盖冲突；舍入量子解释差异，原文值不改写。SEMANTIC_ERROR涉及候选定义不符，不当作普通统计修订。其他VALUE_CONFLICT仍需判断，保留在候选或版本层，不证明所有来源完全一致。
