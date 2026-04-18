# HR Performance Evaluator (custom_adecsol_hr_performance_evaluator)

Purpose: document **business workflow** + **code flow** so another AI/dev can understand the module quickly.

Module path: `odoo_app_addons/custom_adecsol_hr_performance_evaluator`

---

## 0) Quick inventory

### Manifest
File: `__manifest__.py`

- Depends: `hr`, `mail`, `contacts`, `project`, `hr_attendance`, `project_task_done_date`
- Data/XML loaded:
  - `data/data.xml` (sequences, menus, etc.)
  - `data/kpi.xml`, `data/kpi_template_data.xml` (seed KPI templates/lines)
  - `data/ir_config_parameter_data.xml` (default KPI thresholds)
  - `data/email_template_evaluation_alert.xml`
  - `security/security.xml`, `security/ir.model.access.csv`
  - Views: `views/kpi_view.xml`, `views/performance_evaluation.xml`, `views/res_config_settings_views.xml`, …
- Backend assets:
  - `static/src/scss/performance_badges.scss`
  - `static/src/js/kpi_one2many.js`
  - `static/src/js/evaluation_one2many.js`

### Main models (Python)
- KPI template:
  - `models/kpi.py` → `hr.kpi`
  - `models/kpi_line.py` → `hr.kpi.line`
- Evaluation:
  - `models/performance_evaluation.py` → `hr.performance.evaluation`
  - `models/performance_evaluation_line.py` → `hr.performance.evaluation.line`
- Auto KPI engine:
  - `models/hr_kpi_engine.py` → `hr.kpi.engine` (AbstractModel)
- Settings:
  - `models/res_config_settings.py` → `res.config.settings` extension (thresholds)

### Main views (XML)
- KPI Template UI: `views/kpi_view.xml`
- Performance Evaluation UI: `views/performance_evaluation.xml`
- Threshold Settings UI: `views/res_config_settings_views.xml`

---

## 1) Business flow (end-user workflow)

### Actors & roles
- **Employee** (group: `group_employee`)
  - fills self assessment for non-quantitative manual KPIs
  - can edit `actual` only for manual quantitative KPIs (when allowed by view + backend write rules)
  - cannot approve
- **Manager** (group: `group_manager`)
  - reviews/edits manager rating fields
  - approves / cancels

Roles are enforced by:
- access rights: `security/ir.model.access.csv`
- record rules: `security/security.xml`
- UI readonly attrs + backend `write()` guards in `hr.performance.evaluation.line`

### Workflow states (evaluation)
Model: `hr.performance.evaluation.state`

- `draft` → employee can edit (self inputs)
- `submitted` → manager reviews (manager inputs)
- `approved` → completed
- `cancel` → locked

Transitions (buttons in `views/performance_evaluation.xml`, methods in `models/performance_evaluation.py`):
- Submit → `action_submit()`
- Approve → `action_approve()`
- Cancel → `action_cancel()`

### Typical business scenario
1. HR configures an **Evaluation Alert** (active evaluation window + period).
2. HR builds a **KPI Template** for a job/department.
3. Manager/HR creates a **Performance Evaluation** for an employee and selects a KPI template.
4. System generates evaluation lines from the template (including section headers).
5. Employee fills:
   - quantitative manual lines: `actual`
   - binary/rating/score manual lines: employee rating fields + comment
6. Employee submits:
   - validation ensures required self inputs are provided for non-quantitative manual lines
   - self values are auto-mirrored into manager values (for non-quantitative manual) to allow “default manager rating”
7. Manager adjusts manager rating if needed, adds feedback, and approves.
8. System computes summary score (`performance_score`) and derives result (`performance_level`) from settings thresholds.

---

## 2) KPI template flow (HR config)

### Model: `hr.kpi` (KPI Template)
File: `models/kpi.py`

- Holds the one2many list `kpi_line_ids`.
- Constraint: choose **either** `job_id` or `department_id`.

### Model: `hr.kpi.line` (KPI Template Line)
File: `models/kpi_line.py`

A template line can be either:
- a **Section row** (`is_section=True`)
- a **real KPI row** (`is_section=False`)

Ordering:
- `sequence` (drag handle)
- `_order = 'sequence, id'`

Key fields (for KPI rows):
- `key_performance_area`: display title
- `kpi_type`: `quantitative` | `binary` | `rating` | `score`
- quantitative-only:
  - `target_type`: `value` | `percentage`
  - `direction`: `higher_better` | `lower_better`
  - `target`
- weighting:
  - `weight`
- frequency flags: `is_monthly`, `is_quarterly`, `is_half_yearly`, `is_yearly`
- auto compute:
  - `is_auto`
  - `data_source`: `manual` | `task_on_time` | `late_days`

Display helpers:
- `target_display` computed to show `%` suffix when `target_type='percentage'`.

### KPI Template UI
File: `views/kpi_view.xml`

- `hr.kpi` form embeds `kpi_line_ids` with widget `kpi_one2many`.
- Mixed behavior:
  - **Add Section** → inline new row editable in list
  - **Add KPI** → opens popup form view `view_hr_kpi_line_form_popup`
- Drag & drop uses `sequence` with handle widget.

Widget file: `static/src/js/kpi_one2many.js`

---

## 3) Performance evaluation flow (runtime)

### Model: `hr.performance.evaluation`
File: `models/performance_evaluation.py`

Key fields:
- `employee_id`, `kpi_id`, `period`
- dates: `start_date`, `end_date`, `deadline` (defaulted from evaluation alert)
- `evaluation_line_ids`: one2many to `hr.performance.evaluation.line`
- `performance_score`: stored weighted average (digits 1 decimal)
- `performance_level`: derived label (excellent/pass/fail)
- `performance_badge_class`: UI helper class for summary coloring

#### Defaulting the evaluation window
- `default_get()` loads the first active `hr.performance.report` and sets:
  - `performance_report_id`, `start_date`, `end_date`, `deadline`, `period`

#### Mapping KPI template → evaluation lines
Triggered by: `@api.onchange('kpi_id')` → `_onchange_kpi_id()`

Algorithm (current code):
1. Guard: if `kpi_id` didn’t really change (same as `_origin.kpi_id`) → return
2. Clear `evaluation_line_ids`
3. Filter template lines by selected `period` flag:
   - keep if template line has `is_{period}` = True
4. Sort by `(sequence, origin id, id)` to keep stable order in onchanges
5. Create evaluation line (0,0,vals) per template line:
   - if template is a **section** → create evaluation section row (`is_section=True`, `display_type='line_section'`) with safe defaults
   - else create normal KPI row, copying:
     - `sequence`, `key_performance_area`, `description`
     - `kpi_type`, `target_type`, `direction`, `target`, `weight`
     - `is_auto`, `data_source`
     - `kpi_line_id` backlink to template line

#### Auto compute actuals
Button: **Compute KPI** → `action_compute_auto_kpi()`

- Iterates `evaluation_line_ids`
- For lines with `is_auto=True`:
  - calls `hr.kpi.engine.compute(employee, evaluation_line, start_date, end_date)`
  - writes return value into `line.actual`

#### Submit / Approve / Cancel
- `action_submit()`:
  - validates required employee self inputs for non-quantitative manual lines
  - mirrors employee values into manager fields (sudo write)
  - moves state to `submitted`
- `action_approve()`:
  - moves state to `approved`
- `action_cancel()`:
  - moves state to `cancel`

#### Summary score
- `performance_score` computed as weighted average:
  - sum(final_rating * weight) / sum(weight)
- Refresh button: `action_recompute_performance_score()`

---

## 4) Evaluation line scoring + rating flow

### Model: `hr.performance.evaluation.line`
File: `models/performance_evaluation_line.py`

This model supports:
- section rows (do not affect scoring)
- quantitative KPI (target vs actual)
- non-quantitative KPI (self vs manager inputs)

#### Section behaviour
Section row markers:
- `is_section=True` and `display_type='line_section'`

Rules:
- should not be used in computation/validation (handled mainly in UI + mapping)

#### Canonical quantitative inputs
- `target` (Float)
- `actual` (Float)
- `target_type` controls unit:
  - `value`: number
  - `percentage`: 0–100
- `target_display` / `actual_display` are computed strings for list UI

Constraint:
- if `target_type='percentage'`, enforce `0 <= actual <= 100`

#### Self vs manager rating fields (by kpi_type)
- `binary`: Selection values `yes` / `no` (plus False = unset)
  - employee: `employee_rating_binary`
  - manager: `manager_rating_binary`
- `rating`: Selection 0..5
  - employee: `employee_rating_selection`
  - manager: `manager_rating_selection`
- `score`: Integer 0..10
  - employee: `employee_rating_score`
  - manager: `manager_rating_score`

Comments (rich text)
- `employee_comment` (Html)
- `manager_comment` (Html)

#### How final rating is computed
Two-step:
1. `system_score` computed (`_compute_system_score`, store=True)
2. `final_rating` computed from `kpi_type` (`_compute_final_rating`, store=True)

Current implemented rules:
- quantitative → `system_score` = ratio scoring (0..10) → `final_rating = system_score`
- binary → manager yes/no → `system_score = final` (=10 or 0)
- rating 0..5 → `(manager_selection/5)*10`
- score 0..10 → `manager_rating_score`

#### Live mirror of employee → manager (draft)
Goal: employee can see “current result” without waiting for submit.

Mechanisms:
- onchange: `_onchange_employee_rating_autofill_manager()` mirrors in draft
- persistence: `write()` calls `_mirror_employee_to_manager_vals()` to prevent values reverting after save/reload

#### Row decoration (manager changed)
- `manager_edited` computed, stored
- tree view uses `decoration-danger="manager_edited"`

---

## 5) Auto KPI engine flow

### Abstract model: `hr.kpi.engine`
File: `models/hr_kpi_engine.py`

Entry point:
- `compute(employee, kpi_line, date_from, date_to)`

Rules:
- if `kpi_line.is_auto` is False or `data_source='manual'` → returns `0.0`

Helper for unit policy:
- `_value_or_percentage(kpi_line, numerator, denominator)`
  - target_type=value → return numerator
  - target_type=percentage → return (numerator/denominator) * 100

Data sources implemented:
- `task_on_time`
  - counts done tasks in window whose done_date <= date_deadline
  - returns count or percentage depending on target_type
- `late_days`
  - counts distinct late check-in dates

---

## 6) Settings: KPI thresholds (excellent/pass)

### Model: `res.config.settings`
File: `models/res_config_settings.py`

System parameters:
- `custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent`
- `custom_adecsol_hr_performance_evaluator.kpi_threshold_pass`

Used by:
- `hr.performance.evaluation._compute_performance_level()`
- `hr.performance.evaluation._compute_performance_badge_class()`
- `hr.performance.evaluation.line._compute_final_rating_badge_class()`

UI:
- `views/res_config_settings_views.xml`

---

## 7) UI widgets (OWL) and why they exist

### 7.1 KPI template one2many widget
File: `static/src/js/kpi_one2many.js`

Widget name: `kpi_one2many`

Behavior:
- Add Section → inline editable row
- Add KPI → popup form (`hr.kpi.line`), using `form_view_ref` from XML context
- Section rows:
  - bold style via renderer + `performance_badges.scss`
  - columns collapse to handle + title
  - Enter/Tab exits edit mode (no multiline)

### 7.2 Evaluation lines one2many widget
File: `static/src/js/evaluation_one2many.js`

Widget name: `evaluation_one2many`

Behavior:
- Add Section → inline editable row
- Add KPI → popup form (`hr.performance.evaluation.line`), using `form_view_ref` from XML context
- New KPI lines are hinted to appear at the end by default sequence

---

## 8) Security model (what controls what)

### Access rights
File: `security/ir.model.access.csv`

Highlights:
- KPI templates (`hr.kpi`, `hr.kpi.line`) are manager-only for create/write
- evaluations: employees can read/write their evaluations (not unlink), managers full
- evaluation lines: employees read/write limited by backend guards (and record rules)

### Record rules
File: `security/security.xml`

- Managers: can access evaluations where they are the manager (or creator)
- Employees: can access their own evaluations

### Field-level enforcement (backend)
File: `models/performance_evaluation_line.py` → `write()`

- blocks editing on canceled evaluations
- employees cannot modify manager fields (except mirrored values in draft when they edit employee fields)
- managers cannot modify employee self fields
- manager rating fields editable only in `submitted`

---

## 9) Where to change things (extension map)

### Add a new auto KPI data source
1. Add selection value to `data_source` on BOTH:
   - `hr.kpi.line.data_source`
   - `hr.performance.evaluation.line.data_source`
2. Implement new `_compute_xxx()` in `hr.kpi.engine`
3. Dispatch it inside `compute()`
4. Ensure it returns either raw value or % using `_value_or_percentage()`

### Change scoring
- Quantitative and non-quantitative scoring lives in:
  - `hr.performance.evaluation.line._compute_system_score()`
  - `hr.performance.evaluation.line._compute_final_rating()`

### Change performance thresholds
- Settings are stored in system parameters
- Used in `_get_thresholds()` methods

---

## 10) Known implementation details / gotchas

- `target_display` / `actual_display` are CHAR computed fields for list UI; canonical numeric fields remain `target` / `actual`.
- Section rows are created with safe defaults for required fields (e.g., `kpi_type='quantitative'`) to satisfy ORM constraints.
- Widget popup creation is used to keep KPI rows clean and avoid inline-edit complexity.
- Some view readonly rules rely on related `evaluation_state` field; in popup forms, ensure the evaluation is linked (`evaluation_id`) so readonly evaluates correctly.

