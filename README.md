# 溪桥社区合唱节盲评服务

辅导老师从排练稿中冻结实际评阅节选。场务按固定组别签出匿名件，领评台可离线收讲评稿并发出正式页。收班后场务按领评台实际发出的首执核齐应办关系，指导老师按轮次读取冻结讲评册。

## 运行

使用 Python 3.11 标准库。以下命令从项目根目录执行。场务与领评各使用自己的数据库，重开时传回原路径即可继续。端口设为 0 可由操作系统分配，启动首行 JSON 给出实际端口。服务监听 127.0.0.1，供本机可信的场务与领评台使用。

```sh
python3 -B -m issue.office_http --db office.sqlite --port 8011
python3 -B -m desk.http --db desk.sqlite --port 8012
```

完整回归入口由运行平台生成。演示使用两份临时数据库，经 HTTP 显式提交样例，当业务断言失败时以非零状态退出。服务启动只补建缺失表，不会自行导入样例。

```sh
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t . -p 'test_*.py'
python3 -B -m tests.scenario
```

`samples/festival.json` 中的 P 使用 S1 [0,4)、S2 [4,8) 和请求窗 [2,6)。校样保留 [2,4)、[4,6) 的原段文字。B 的 [3,5) 讲评跨两段且完整受到覆盖。样例固定 P 为甲组、Q 为乙组，A/B/C 为甲/乙/丙组。作品按登记键分配匿名号，原轮应办 W01/B、W01/C、W02/A、W02/C。留到最后核回的 W02/C 会出现在缺页清单，补回后原轮可结成四页讲评册。

## JSON HTTP

POST 请求体和响应均为 UTF-8 JSON，对象参数使用表中的字段。表中每个 GET 查询键使用 URL 编码。成功响应为 200，非法 JSON 或查询串返回 400，实体不存在或查册尚未结时返回 404，业务状态冲突返回 409，字段或拍窗不合规返回 422。错误对象有 `error` 字段，缺页冲突另给出 `missing`。

| 台位 | 入口 | 请求参数与结果 |
| --- | --- | --- |
| 场务 | `POST /proof` | `revision_id`、`author`、`segments`、`window`。每个段有 `segment_id`、`window`、`text`。冻结后返回 `proof_id`、`revision_id`、`window` 和 `spans`。同一修订号只能登记同一作者和原序段内容。原修订同窗复取使用原校样号。 |
| 场务 | `GET /proof?proof_id=…` | 查询冻结校样及原段出处。 |
| 场务 | `POST /release` | `round_id`、`works`、`reviewers`。每个作品有 `work_id`、`group`、`proof_id`，每个评阅人有 `reviewer_id`、`group`。返回完整匿名发行件。相同名单重报取原发行，异名单重报冲突。 |
| 场务 | `GET /release?round_id=…` 或 `?release_id=…` | 取原匿名件。返回 `round_id`、`release_id`、`works`、`reviewers`、`eligible`。匿名作品条目有 `alias`、`proof_id`、`spans`，资格项有 `alias`、`reviewer_id`。 |
| 领评 | `POST /install` | 直接传完整匿名件，返回 `receipt_id` 和原 `bundle`。同发行号同内容复用原实收号，只忽略对象键顺序。同发行号异内容或同轮另一个发行号冲突。 |
| 领评 | `GET /install?round_id=…` | 取已装件和实收号。 |
| 领评 | `POST /comment` | `round_id`、`alias`、`reviewer_id`、`window`、`text`。按匿名关系冻结讲评稿，返回 `draft_id`、发行、校样及稿件内容。 |
| 领评 | `POST /page` | `round_id`、`alias`、`reviewer_id`、`draft_id`、`request_id`。按已装固定资格和稿件归属首次出页，返回 `page_id`、`draft_id`。同请求号同参复领，异参冲突。每条评阅关系最多一张正式页。 |
| 领评 | `GET /page?page_id=…` | 读取正式页的冻结内容。 |
| 领评 | `GET /receipt?request_id=…` 或 `GET /receipts?round_id=…` | 查已提交的首执。单条首执同时携带原请求号和正式页内容。轮次入口返回 `receipts` 列表。 |
| 场务 | `POST /reconcile` | `release_id` 和领评台返回的一条 `receipt`。核录后返回 `release_id`、`missing`。重复交回原首执继续报告当前缺页。 |
| 场务 | `GET /reconcile?release_id=…` | 按原发行读取当前缺页。 |
| 场务 | `POST /collection` 或 `GET /collection?round_id=…` | POST 传 `round_id`，核齐后冻册。GET 读原册。返回 `collection_id`、`round_id`、`release_id` 和按匿名号、评阅号排序的 `pages`。 |

拍窗写作 `[起拍, 止拍]`，含起拍且不含止拍。端点必须是整数且起拍小于止拍。稿段按原起拍排序，同起拍保留上报次序。原文以段级保存，交段只改变拍窗。仅接触端点不产出交段。稿窗必须落在节选交段的覆盖并集内。同组评阅人可以提交稿件，正式出页以发行时的固定资格为准。领评件不携带作者、原修订号及内部作品键，段号和原段文字随节选传递。

领评台在一个本地事务内固定正式页和首执，回复是否送达不影响已提交结果。场务核回时检查发行、轮次、关系、校样、拍窗和页身份。首执由本机可信的领评台导出，页号用于核对冻结内容。场务只有收到所有应办关系的有效首执才能结册，包括应办集合为空的情形。已冻讲评册保持原页内容和顺序。
