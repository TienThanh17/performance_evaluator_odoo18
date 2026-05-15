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
   - **Department Level**: The department's raw KPI score is stored but no longer serves as a standalone "grade" for the department; instead, `avg_final_score` on the department profile provides a real-time summary of team performance.
9. **Dashboard**: Users can view performance analytics via the "Performance Dashboard" (JS/OWL component) which pulls data from these models.

---

## Core Models (Employee Performance)

### `hr.kpi` (Employee Template)
- **Purpose**: Master template for employee KPIs.
- **Key Fields**:
    - `name`: Template name.
    - `period`: monthly, quarterly, biannual, annual.
    - `department_id` / `job_id`: Target filters.
    - `kpi_line_ids`: O2M to `hr.kpi.line`.
- **Validation**: Total weight of non-section lines must be approximately 100% (tolerance 0.1).

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
- **States**: `self_evaluation` -> `manager_evaluating` -> `completed` -> `cancel`.
- **Key Fields**:
    - `employee_id`, `kpi_id`, `performance_report_id`.
    - `dept_evaluation_id`: Link to the department-level evaluation.
    - `performance_score`: Weighted average of individual KPI lines.
    - `final_score`: The blended final result. 
      - **Formula**: `dept_kpi_score × dept_weight + performance_score × (1 - dept_weight)`.
      - Falls back to `performance_score` if no department evaluation is linked or if it is cancelled.
    - `performance_level` / `final_level`: excellent, pass, fail (computed based on thresholds).
- **Methods**: `action_compute_auto_kpi()`, `_compute_final_score()`, `get_dashboard_data()`.

### `hr.performance.evaluation.line` (Evaluation Line)
- **Purpose**: Instance of a KPI for a specific employee and period.
- **Scoring**:
    - `performance_score`: Computed based on `actual` vs `target` or `manager_rating`.
    - `final_rating`: The rating used for the weighted average calculation of the parent evaluation.

---

## Department Performance Models

### `hr.department.kpi` (Department Template)
- **Purpose**: Defines how a department is evaluated and its weight in individual scores.
- **Fields**:
    - `dept_weight`: Contribution of the department score to an individual's final score (e.g., 0.4 = 40% Dept / 60% Individual).
    - `individual_weight`: Inverse of `dept_weight` (1.0 - `dept_weight`).
    - `alpha` / `beta`: **[DEPRECATED]** Old blending weights for a centralized department score.

### `hr.department.performance.evaluation` (Dept Evaluation)
- **Calculation**:
    - `dept_kpi_score`: Weighted average of department-specific KPI lines.
    - `get_dept_kpi_score()`: Public method to safely retrieve the score (returns 0.0 if cancelled).
    - `department_score` / `department_level` / `avg_individual_score`: **[DEPRECATED]** No longer used for the primary performance result.

---

## KPI Engine (`hr.kpi.engine`)

The engine is an `AbstractModel` providing centralized computation logic:

### Employee Sources:
1. **`done_task`**: Count of tasks with `stage_id.is_done_stage=True` and `date_deadline` in range.
2. **`task_on_time`**: % of done tasks where `done_date` <= `date_deadline`.
3. **`late_days`**: Counts days where the first check-in is after the calendar start time (considering `late_grace_minutes`).
4. **`attendance_full`**: Complex calculation of Expected Work Days vs Worked Days vs Approved Leave vs Unpaid Leave.

### Department Sources (Extension):
1. **`dept_task_completion`**: Aggregate on-time completion rate for all tasks assigned to department employees.
2. **`dept_attendance_rate`**: Average attendance rate across all department employees.
3. **`dept_avg_individual`**: Average of all individual performance scores within the department for the period.

---

## Global Configuration (`res.config.settings`)
- `kpi_threshold_excellent`: Default 9.0.
- `kpi_threshold_pass`: Default 5.0.
- `late_grace_minutes`: Buffer for check-in.
- `deadline_reminder_days`: For automated email/chatter reminders.

---

## Data Aggregation (`hr.performance.report`)
- **Batching**: Links multiple employee/department evaluations together for a single period.
- **Reminders**: Cron job `_cron_send_deadline_reminder` sends notifications to employees.

---

## Wizards & Automation

### `hr.department.kpi.generate.wizard`
- **Purpose**: Creates department and individual evaluations in one batch.
- **Refactored Logic**: 
    - Creates the `hr.department.performance.evaluation` record first.
    - Injects the `dept_evaluation_id` into each generated `hr.performance.evaluation`.
    - Explicitly triggers `_compute_final_score()` on all created records to ensure persistence.

---

## UI Components & Dashboards

The module features a rich interactive layer built with OWL (Odoo Web Library) and Chart.js.

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
Employee evaluations (`hr.performance.evaluation`) use a custom Kanban card layout:
- **Trophy Indicator**: A large circular progress bar representing the `performance_score`.
- **Themed Sidebars**: Color-coded based on performance level (Blue/Excellent, Green/Pass, Red/Fail).
- **Quick Info**: Displays job position, department, and period clearly.

### Custom Form Widgets
- **`kpi_one2many`**: Optimized list view for evaluation lines with section support and mirrored editing logic.
- **`kpi_description_icon`**: A tooltip/icon widget to show KPI descriptions without cluttering the list.
- **`priority_onchange`**: Enhances the standard priority (stars) widget to trigger immediate score recomputations.
- **`kpi_badge_class`**: Dynamic CSS classes applied to badges for visual consistency across forms and lists.

---

## Model Extensions
- **`hr.employee`**: Shows `performance_score` (and potentially `final_score`) from the latest evaluation.
- **`hr.department`**: 
    - `avg_final_score`: Real-time average of all `completed` individual `final_score`s in the department.
    - `department_score` / `department_level`: **[DEPRECATED]** Kept for historical data visibility in Debug Mode.
