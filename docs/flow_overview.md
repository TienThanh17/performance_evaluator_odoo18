# HR Performance Evaluator – Current Logic Flow (Odoo 18)

This document describes the **current functional flow and main business logic** of the custom module `custom_adecsol_hr_performance_evaluator` (ADEC SOL HR Performance Evaluator).

> Goal: Help another developer quickly understand how KPI templates, evaluations, scoring, thresholds, and auto KPI computation work together.

---

## 1) High-level User Flow

### A. Configure evaluation cycle (Performance Report)
1. Admin configures an **Performance Report** (`hr.performance.report`) with:
   - `period` (monthly/quarterly/half_yearly/yearly)
   - `start_date`, `end_date`, `deadline`
   - `active = True`
2. This record acts as the **default evaluation window**.

### B. Create KPI Template
1. HR creates a **KPI Template** (`hr.kpi`) for either:
   - a **Job Position** (`job_id`) **or**
   - a **Department** (`department_id`)
2. Each template includes multiple **KPI Lines** (`hr.kpi.line`) that define:
   - KPI metadata: `key_performance_area`, `name`
   - KPI scoring inputs: `kpi_type`, `target_type`, `direction`, `target`, `weight`
   - evaluation frequency flags: `is_monthly`, `is_quarterly`, `is_half_yearly`, `is_yearly`
   - data collection mode: manual vs auto (`is_auto`, `data_source`)

### C. Create Performance Evaluation
1. Manager/HR creates an **Evaluation** (`hr.performance.evaluation`) and selects:
   - `employee_id`
   - `kpi_id` (KPI Template)
   - `period`
2. Default dates (`start_date`, `end_date`, `deadline`, `period`) are auto-filled from an active `hr.performance.report` via `default_get()`.
3. When the user selects `kpi_id`, the system auto-generates **Evaluation Lines** (`hr.performance.evaluation.line`) from matching KPI template lines (filtered by period flags).

### D. Fill actuals & compute score
- For **manual** KPIs: user enters `actual` directly.
- For **auto** KPIs: user clicks **Compute KPI** button to populate `actual`.
- The system computes:
  - line-level `system_score` (0–10)
  - line-level `final_rating` (depends on type; clamped to 0–10)
  - evaluation-level `performance_score` (weighted average)
  - evaluation-level `performance_level` (excellent/pass/fail) based on configurable thresholds

### E. Workflow states
Evaluation state transitions:
- `draft` → **Submit** → `submitted` → **Approve** → `approved`
- **Cancel** → `cancel`

---

## 2) Core Models & Responsibilities

### 2.1 `hr.performance.report`
**Purpose:** Defines the active evaluation window and default period.

Key behaviors:
- `hr.performance.evaluation.default_get()` fetches the first active alert and pre-fills:
- Constraint `_check_period_active` enforces that the selected period matches **at least one** active alert.

### 2.2 `hr.kpi` (KPI Template)
**Purpose:** Template grouping KPI lines to be evaluated.

Constraints:
- Must select **exactly one** of `job_id` or `department_id`.

Fields:
- `kpi_line_ids`: list of `hr.kpi.line`

### 2.3 `hr.kpi.line` (KPI Template Line)
**Purpose:** Defines one KPI item inside a template.

Key fields:
- `kpi_type`: `quantitative` / `binary` / `rating`
- `target_type`: `value` / `percentage`
- `direction`: `higher_better` / `lower_better`
- `target`, `weight`
- `is_auto` + `data_source`:
  - `manual`: no auto compute
  - `task_on_time`: compute from project tasks
  - `late_days`: compute from attendances

Helper:
- `serial_number` computed to display a stable row numbering within a template.

### 2.4 `hr.performance.evaluation`
**Purpose:** One evaluation for one employee for one period.

Important fields:
- `employee_id`, `kpi_id`, `period`
- `evaluation_alert_id`, `start_date`, `end_date`, `deadline`
- `evaluation_line_ids`: One2many to `hr.performance.evaluation.line`
- `performance_score`: computed weighted average
- `performance_level`: computed label (excellent/pass/fail)
- `state`: draft/submitted/approved

Thresholds:
- KPI thresholds are configured in **Settings** (`res.config.settings`) and stored in `ir.config_parameter`:
  - `custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent`
  - `custom_adecsol_hr_performance_evaluator.kpi_threshold_pass`

Key methods:

#### (1) `default_get()`
- Pulls the first active `hr.performance.report` and sets dates/period.

#### (2) `_onchange_kpi_id()` — generate evaluation lines
When `kpi_id` is selected:
1. Clear existing `evaluation_line_ids`
2. Filter KPI template lines based on `self.period`:
   - keep line if it has True on `is_{period}` (e.g., `is_monthly`)
3. For each selected KPI template line, create one evaluation line with copied fields:
   - `key_performance_area`, `description`
   - `kpi_type`, `target_type`, `direction`
   - `target`, `weight`
   - `is_auto`, `data_source`

Notes:
- Evaluation lines are **copied snapshots**. There is currently **no** `kpi_line_id` link back to the template line.
- For `kpi_type='quantitative'`, evaluation lines are treated as **auto-compute** by design (`is_auto=True`).

**Note:** Evaluation lines are copied snapshots. There is currently **no** `kpi_line_id` link to the template line.

#### (3) `action_compute_auto_kpi()` — Compute button
- For each evaluation line with `is_auto = True`:
  - calls KPI engine: `hr.kpi.engine.compute(employee, evaluation_line, date_from, date_to)`
  - writes returned value to `line.actual`

### 2.5 `hr.performance.evaluation.line`
**Purpose:** Stores actual results and scoring for one KPI line during evaluation.

Key fields:
- `kpi_type`, `target_type`, `direction`, `target`, `weight`
- `is_auto`, `data_source`
- `actual`: canonical value used for scoring
- employee self inputs:
  - `employee_rating_binary`, `employee_rating_selection`, `employee_rating_score`
- manager inputs:
  - `manager_rating_binary`, `manager_rating_selection`, `manager_rating_score`
- `system_score`: computed (0–10)
- `final_rating`: computed (clamped to 0–10)

UI helper fields (technical):
- `final_rating_badge_text`: Char formatted with 1 decimal (shows `0.0` instead of hiding 0)
- `final_rating_badge_class`: Used by the UI to color the badge (excellent/pass/fail)

Scoring rules (current code):

- **quantitative**:
  - if `target <= 0`: score = 0
  - `higher_better`: ratio = actual / target
  - `lower_better`: ratio = target / actual (if actual > 0 else 0)
  - `system_score = min(ratio * 10, 10)`
  - `final_rating = system_score`

- **binary**:
  - scoring follows manager decision:
  - `final_rating = 10` if `manager_rating_binary == 'yes'` else `0`

- **rating** (0..5):
  - scoring follows manager selection:
  - `final_rating = (manager_rating_selection / 5) * 10`

- **score** (0..10):
  - scoring follows manager integer `manager_rating_score` directly

Constraints:
- if `target_type = percentage` then `actual` must be within 0..100
- if `kpi_type = rating` then `actual` must be within 0..5
- `employee_rating` and `manager_rating` (if set) must be within 0..10

---

## 3) KPI Target Semantics (target_type)

The module supports two target meanings:

### Case A — target_type = value
- Example: “Close 30 tickets” → target = 30
- Actual is a raw value (count/amount).
- Quantitative scoring uses ratio vs target.

### Case B — target_type = percentage
- Intended meaning: Actual is 0..100.

**Implementation note (current code):** the KPI engine helper `_value_or_percentage()` returns:
- `target_type='value'`      → raw value
- `target_type='percentage'` → **percentage 0..100** (= numerator/denominator * 100)

---

## 4) Auto KPI Computation Engine

### Model: `hr.kpi.engine` (AbstractModel)
Entry point:
- `compute(employee, kpi_line, date_from, date_to)` → returns a float for `actual`

In this module, the `kpi_line` argument is effectively a **performance evaluation line** (`hr.performance.evaluation.line`) because the evaluation line carries `is_auto`, `data_source`, and `target_type`.

Dispatch rule:
- if `is_auto` is False or `data_source == 'manual'` → return 0.0
- else compute by `data_source`

Shared helper:
- `_value_or_percentage(kpi_line, numerator, denominator)` centralizes unit policy:
  - `target_type='value'` → return numerator
  - `target_type='percentage'` → return (numerator/denominator) * 100

### Data source: task_on_time
From `project.task`:
- filter tasks assigned to employee’s `user_id` (`project.task.user_ids` contains user)
- completed tasks only (`stage_id.is_done_stage = True`)
- within date range based on `date_deadline`
- compute `on_time` tasks where `done_date <= date_deadline` (compared in context timezone)
- return either value or ratio depending on `target_type` via `_value_or_percentage()`
  - value: number of on-time tasks
  - percentage: (on_time/total) * 100

### Data source: late_days
From `hr.attendance`:
- filter attendance in date range by `check_in`
- count distinct calendar dates where `check_in.hour > 8`
- returns count as float

---

## 5) Views / UX Touchpoints

- KPI Template form/list: maintain KPI lines, including `target_type`, `is_auto`, `data_source`.
- Evaluation form:
  - selecting `kpi_id` triggers `_onchange_kpi_id()` and fills lines
  - “Compute KPI” button triggers `action_compute_auto_kpi()`

UI improvements added:
- In the evaluation lines list, `final_rating` is shown as a **colored badge** based on KPI thresholds.
- Below the evaluation lines, the form shows an emphasized **performance summary** (`performance_score` + `performance_level`) colorized by thresholds.

---

## 6) Extension Points (adding new auto KPI data sources)

To add a new auto KPI type:
1. Add a new selection value to `data_source` (both on template line and evaluation line).
2. Extend `hr.kpi.engine.compute()` to dispatch to a new `_compute_xxx()`.
3. Ensure the returned value matches your chosen unit policy for `target_type`.

---

## 7) Quick Troubleshooting Map

- Evaluation lines not generated:
  - check KPI lines have correct period flags (`is_monthly`, etc.)
  - check `_onchange_kpi_id()` filter uses `self.period`

- Auto KPI compute does nothing:
  - ensure the evaluation line has `is_auto=True` and `data_source != manual`

- Score seems wrong:
  - verify the unit for percentage KPIs:
    - UI/constraints expect 0..100
    - auto compute returns 0..100
  - verify `target` is aligned with `actual` unit
  - direction lower_better requires `actual > 0` to avoid divide-by-zero

- Badge colors not updated:
  - upgrade module and hard-refresh browser assets (Ctrl+F5)

