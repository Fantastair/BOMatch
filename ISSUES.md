# BOMatch Issues（2026-08-08 采购批量录入实测发现）

> 来源：2026-08-08 批量录入立创订单 SO26080812262 + 淘宝 telesky/欧贝顿 两订单（30 新料号 + 1 补库存）过程中的实际观察。
> 详情见 `local_dev/BOMatch_优化清单_2026-08-08.md`。
>
> 以下内容按 GitHub Issue 格式整理，可直接粘贴到仓库 Issues 页：<https://github.com/Fantastair/BOMatch/issues>

## 标签约定

- `bug`：功能异常 / 行为错误
- `enhancement`：体验 / 功能增强
- `priority: high` / `priority: medium` / `priority: low`
- `ux`：交互与提示类

---

## Issue 1 — bug · high · 立创编号同步失败且无任何错误提示

#### 现象

- 新建料号填 C 编号保存后，厂商 / 值 / 封装 / 容差 / 耐压 / 介质全部为空；
- 详情页「同步立创价格/参数」（POST `/parts/{id}/lcsc-sync`）返回 303 重定向但字段不填充，多次重试均失败，非偶发；
- 同步失败时页面静默重定向，无任何提示。

#### 根因（已定位）

- `app/services/lcsc.py::query_product` 用 `except Exception: pass` 吞掉所有异常，且无 pid 兜底时直接返回 `None`；
- `app/routers/parts.py::lcsc_sync` 拿到 `None` 后 `apply_product` 什么都不做，仍 303 跳转 → 静默失败。
- 实测 `https://list.szlcsc.com/substitute/simple/list?productCode=C21189` 返回 200 且含数据（2026-08-08 可通），说明失败主要是**部分编号在 substitute 接口无 mainProduct + 无 pid 兜底 + 异常被吞**，属偶发/接口盲区，需要显式暴露原因。

#### 期望

- [x] 同步失败时详情页给出明确错误提示（如「立创同步失败：<原因>」），不静默重定向
- [x] 保存流程改为「先同步、后跳转」，让用户看到同步结果
- [x] 提供 pid 兜底（方案B），加重试/降级提示

#### 验收

- 对一个不存在的 C 编号执行同步，详情页出现「同步失败：…」提示；
- 对有效编号同步成功时，详情页出现「同步成功」提示并回填字段。

---

## Issue 2 — bug · ux · high · 页面存在多个 form 且语义不清，导致按钮点击不稳定

#### 现象

- Playwright 对「保存」「同步」「入库」按钮的 click/scrollIntoView 每次都超时（element not stable），只能绕过用 `form.requestSubmit()` / `fetch`；
- 页面存在多个 `<form>`（顶栏「退出登录」按钮也是 `type=submit`），表单语义不清晰，干扰自动化定位。

#### 根因（已定位）

- 无全局 CSS 动画导致布局抖动（`style.css` 中无 transition/animation 影响布局）；
- 主要问题是各表单缺少 `id`/明确的 `action` 区分，自动化与可维护性差；导航栏 logout 表单与业务表单混在同一个选择器空间。

#### 期望

- [x] 给主要表单加明确 `id`（logout / part-form / lcsc-sync / batch-form / consume / delete / location）
- [x] 关键按钮加稳定 `id`/`name`
- [x] 破坏性操作（删除料号/批次、同步）确认逻辑清晰

---

## Issue 3 — enhancement · ux · medium · 保存后应跳转到新料号详情页，而非列表页

#### 现象

新建料号保存后直接回 `/parts` 列表页，新料号 ID 只能靠「列表第一行」猜。

#### 期望

- [x] 保存成功后跳转到 `/parts/{new_id}` 详情页，便于确认参数 + 顺手入库

---

## Issue 4 — bug · ux · medium · 入库缺少防重复 / 防误操作

#### 现象

同一来源重复提交入库（如两次各 +10）没有提示，库存变 20 才发现。

#### 期望

- [x] 入库时若 `source + note` 与最近批次相同，弹确认提示（服务端拦截 + 前端确认 + force 强制）
- [x] 删除批次、删除料号等破坏性操作加二次确认

---

## Issue 5 — enhancement · medium · 特殊件（X 类）等效组无「别名/等效」能力

#### 现象

连接器 / IC / LED / 开关等效组为 `X|料号`，必须完全同名才匹配；淘宝通用替代件只能被迫沿用 BOM 料号命名（如通用 8×8 开关命名为 `XKB8080-Z`）。

#### 期望

- [x] 为 X 类料号增加「等效别名」字段，允许多个 MPN 映射到同一等效组
- [x] 保存时自动合并同组料号到同一 `canonical_key`

---

## Issue 6 — enhancement · ux · low · 值/封装/容差/介质字段缺少输入规范提示

#### 现象

值要手写「22uF / 9.76kΩ」，容差填「10%」还是「J」，介质填「C0G」——格式全靠用户记忆，填错导致等效组不匹配（历史踩过 C0603 vs 0603 的坑）。

#### 期望

- [x] placeholder 增加格式示例
- [x] 输入校验（立创编号 `pattern`）防格式不一致

---

## Issue 7 — bug · low · 立创编号（lcsc_code）无唯一性校验

#### 现象

两个料号可填相同 C 编号，易造成重复料号。

#### 期望

- [x] 对 `lcsc_code` 加唯一约束（存量重复时自动跳过）+ 保存时重复提示

---

## 备注

- 本次批量录入 30 个新料号全部成功，库存 5744→6528（+784，与订单总量吻合），料号 150→180。
- 立创料号因同步失败改为从立创订单详情页手动填字段，`lcsc_code` 已保留在料号上，同步接口修复后可再点按钮补价格。
- 已更新的等效组测试经验：电阻 `R|值|封装|容差`、电容 `C|值|封装|耐压|介质`、电感 `L|值|封装`、特殊件 `X|料号`。
