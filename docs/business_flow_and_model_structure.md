# Business Flow and Model Structure - custom_adecsol_hr_performance_evaluator

## Scope
This document summarizes the business flow and key models for the module. It is intended for developers to understand the internal mechanics, scoring logic, and data relationships.

## Business Flow (End-to-End)
1. **Setup**: HR/Admin configures KPI thresholds (Excellent/Pass) and system parameters (Late Grace Minutes, Deadline Reminders) in Settings.
2. **Template Definition**: HR/Manager defines KPI templates for employees (`hr.kpi`) and departments (`hr.department.kpi`). 
   - Employee templates are targeted by Department/Job Position and Period.
   - Department templates use `dept_weight` to define how much the department score influences an individual's final result.
3. **Batch Generation**: HR creates a `hr.performance.report` record, selecting the period and target employees/department.
4. **Initialization**: Clicking "Generate" (or via automated wizards) creates `hr.performance.evaluation` (employee) and `hr.department.performance.evaluation` (department) records. Evaluation lines are copied from templates.
   - Individual evaluations are automatically linked to their respective department evaluation via `dept_evaluation_id`.
5. **Auto-Computation**: The system runs `hr.kpi.engine` to fetch "Actual" values from Odoo data sources (Tasks, Attendance, Leaves).
6. **Self-Evaluation**: Employees fill in manual ratings and comments. During this phase, employee ratings are mirrored to manager ratings to provide real-time score feedback.
7. **Manager Evaluation**: Managers review, override ratings if necessary, and add feedback.
8. **Finalization**: HR completes/approves the evaluations.
   - **Individual Level**: `final_score` is computed by blending the individual's `performance_score` with the department's `dept_kpi_score` using the configured `dept_weight`.
   - **Department Level**: The department's raw KPI score (`dept_kpi_score`) is stored and used to influence team members' scores.
9. **Analytics**: Users can view performance metrics via 4 distinct dashboards: Individual, Department, Report Hub, and the hierarchical KPI Tree.

---

## Core Models (Employee Performance)

### `hr.kpi` (Employee Template)
- **Purpose**: Master template for employee KPIs.
- **Key Fields**:
    - `period`: `monthly`, `quarterly`, `half_yearly`, `yearly`.
    - `department_id` / `job_id`: Target filters.
    - `department_kpi_id`: Link to parent Department KPI Template.
    - `kpi_line_ids`: O2M to `hr.kpi.line`.
- **Validation**: Total weight of non-section lines must equal 100% (with a `tolerance` of 0.1).

### `hr.kpi.line` (Template Line)
- **Purpose**: Defines a specific metric.
- **Types (`kpi_type`)**:
    - `quantitative`: Target vs Actual ratio.
    - `binary`: Yes/No (10 or 0 points).
    - `rating`: 0-5 stars (mapped to 0-10 scale).
    - `score`: 0-10 direct input.
- **Data Sources**: `manual`, `done_task`, `task_on_time`, `late_days`, `attendance_full`.

### `hr.performance.evaluation` (Employee Evaluation)
- **Purpose**: The actual evaluation instance for an employee.
- **States**: `self_evaluation`, `manager_evaluating`, `completed`, `cancel`.
- **Key Fields**:
    - `performance_score`: Weighted average of individual KPI lines.
    - `final_score`: The blended result: `(Dept Score × Dept Weight) + (Individual Score × Individual Weight)`.
    - `dept_evaluation_id`: Link to the department-level evaluation.
    - `performance_level` / `final_level`: `excellent`, `pass`, `fail` (derived from scores).
- **Methods**: `action_compute_auto_kpi()`, `_compute_final_score()`, `get_dashboard_data()`, `get_kpi_tree_data()`.

### `hr.performance.evaluation.line` (Evaluation Line)
- **Purpose**: Instance of a KPI for a specific employee and period.
- **Key Fields**:
    - `actual`: Collected value for quantitative KPIs.
    - `system_score`: Rule-based score (0-10) computed by the engine.
    - `final_rating`: Final score used in the summary (weighted by `weight`).

---

## Department Performance Models

### `hr.department.kpi` (Department Template)
- **Purpose**: Defines department-specific KPIs and blending weights.
- **Key Fields**:
    - `period`: `monthly`, `quarterly`, `biannual`, `annual`.
    - `dept_weight`: Contribution of department score (default 0.4).
    - `individual_weight`: Computed as `1.0 - dept_weight`.

### `hr.department.kpi.line` (Dept Template Line)
- **Data Sources**: `manual`, `dept_task_completion`, `dept_attendance_rate`, `dept_avg_individual`.

### `hr.department.performance.evaluation` (Dept Evaluation)
- **Calculation**:
    - `dept_kpi_score`: Weighted average of department-specific KPI lines.
    - `get_dept_kpi_score()`: Public method for score blending.

---

## KPI Engine (`hr.kpi.engine`)

Centralized logic for computing "Actual" values:
1. **`done_task`**: Count of completed tasks within the deadline.
2. **`task_on_time`**: % of tasks where `done_date` <= `date_deadline`.
3. **`late_days`**: Score = `10.0 - (late_days * 1.0)`, minimum 0.
4. **`attendance_full`**: 
   - Unpaid leaves -> 0 score.
   - 0 leave days -> 10 points.
   - 1-5 leave days -> Graduated penalty (9, 8, 7, 6, 5 points).
   - >5 leave days -> 0 score.

---

## Global Configuration (`res.config.settings`)
- `kpi_threshold_excellent`: Default 9.0.
- `kpi_threshold_pass`: Default 5.0.
- `late_grace_minutes`: Default 30.
- `deadline_reminder_days`: Default 3.

---

## Data Aggregation (`hr.performance.report`)
- **Batching**: Links multiple employee and department evaluations together.
- **Infographic Hub**: Entry point for the Report Hub dashboard.

---

## Wizards & Automation

### `hr.department.kpi.generate.wizard`
- **Purpose**: Creates department and individual evaluations in a single batch.
- **Logic**: Creates the department record first, then links all employee evaluations to its ID.

### Automation
- **Cron Jobs**: Automated computation (`_cron_compute_auto_kpi`) and deadline reminders (`_cron_send_deadline_reminder`).

---

## UI Components & Dashboards

The module provides four distinct analytical views built with OWL, Chart.js, and D3.js.

### 1. Individual Dashboard (`kpi_individual_dashboard`)
- **Accessibility**: Available via the "Dashboard" menu under KPI Employee.
- **Features**:
    - **Final Score Breakdown**: Displays the blend of Individual KPI vs. Department KPI.
    - **Spider Chart**: Visualizes scores across different KPI categories.
    - **Check-in Log**: Line chart comparing actual check-in times vs. expected start time.
    - **Attendance Ring**: Doughnut chart showing present vs. absent days.
    - **Task Progress**: Line chart of daily task completion against the total target.
- **Permissions**: Managers can filter by Department and Employee to view their team's data.

### 2. Department Dashboard (`kpi_department_dashboard`)
- **Accessibility**: Available via the "Dashboard" menu under KPI Department.
- **Features**:
    - **Task Summary**: Stacked bar chart showing Completed vs. Pending tasks per employee.
    - **Project Progress**: Bar chart indicating completion percentages for various projects.
    - **Bug Tracking**: Line chart monitoring bug counts across the team.
    - **Performance Timeline**: Comparison of scores over the last 12 months.

### 3. Report Hub Dashboard (`performance_dashboard_form`)
- **Purpose**: An "Infographic" view embedded directly into the `hr.performance.report` form using a custom `js_class`.
- **Features**: 
    - High-level KPIs: Total Employees, Average Score, Pass Rate.
    - Aggregated charts for Tasks, Attendance, and Lateness across the entire batch.
    - A roster table for quick review of all evaluations in the report.

---

## View Structure & Enhancements

### Kanban Visuals
- **Circular Progress**: Custom widget showing `performance_score`.
- **Themed Sidebars**: Color-coded based on performance levels.

### Custom Form Widgets
- **`kpi_one2many`**: Optimized list view with mirrored editing (Self -> Manager).
- **`kpi_badge_class`**: Dynamic CSS classes for level badges.
- **`kpi_description_icon`**: Tooltips for KPI definitions.

---

## Technical Enhancements
- **Auto-Mirroring**: During self-evaluation, employee ratings are automatically copied to manager ratings.
- **Localization**: Full support for `_t()` translation.
- **Model Extensions**: 
    - `hr.employee`: Stores latest performance result.
    - `hr.department`: `avg_final_score` provides real-time team averages.
ults.
