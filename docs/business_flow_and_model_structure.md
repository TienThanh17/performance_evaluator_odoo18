# Business Flow and Model Structure - custom_adecsol_hr_performance_evaluator

## Scope
This document summarizes the business flow and key models for the module. It is intended for developers to understand the internal mechanics, scoring logic, and data relationships.

## Business Flow (End-to-End)
1. **Setup**: HR/Admin configures KPI thresholds (Excellent/Pass) and system parameters (Late Grace Minutes, Deadline Reminders) in Settings.
2. **Template Definition**: HR/Manager defines KPI templates for employees (`hr.kpi`) and departments (`hr.department.kpi`). 
   - Employee templates are targeted by Department/Job Position and Period.
   - Department templates use $\alpha$ (Department KPI) and $\beta$ (Average Individual) weights.
3. **Batch Generation**: HR creates a `hr.performance.report` record, selecting the period and target employees/department.
4. **Initialization**: Clicking "Generate" (or via automated wizards) creates `hr.performance.evaluation` (employee) and `hr.department.performance.evaluation` (department) records. Evaluation lines are copied from templates.
5. **Auto-Computation**: The system runs `hr.kpi.engine` to fetch "Actual" values from Odoo data sources (Tasks, Attendance, Leaves).
6. **Self-Evaluation**: Employees fill in manual ratings and comments. During this phase, employee ratings are mirrored to manager ratings to provide real-time score feedback.
7. **Manager Evaluation**: Managers review, override ratings if necessary, and add feedback.
8. **Finalization**: HR approves the evaluations. Scores are finalized and pushed to the `hr.employee` and `hr.department` profiles.
9. **Dashboard**: Users can view performance analytics via the "Performance Dashboard" (JS/OWL component) which pulls data from these models.

---

## Core Models (Employee Performance)

### `hr.kpi` (Employee Template)
- **Purpose**: Master template for employee KPIs.
- **Key Fields**:
    - `name`: Template name.
    - `period`: monthly, quarterly, half_yearly, yearly.
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
    - `performance_score`: Weighted average of all line `final_rating`s.
    - `performance_level`: excellent, pass, fail (computed based on thresholds).
- **Methods**: `action_compute_auto_kpi()`, `get_dashboard_data()`.

### `hr.performance.evaluation.line` (Evaluation Line)
- **Scoring Logic**:
    - **Quantitative**: 
        - `higher_better`: `(actual / target) * 10`
        - `lower_better`: `(target / actual) * 10`
    - **Special - Late Days**: `10.0 - (late_days * 1.0)`, min 0.
    - **Special - Attendance Full**: 10 points if 0 unpaid leave, decreasing points for more leave days, 0 points if any unpaid leave exists.
- **Behavior**: While in `self_evaluation`, employee inputs are mirrored to manager fields so `final_rating` updates live.

---

## Department Performance Models

### `hr.department.kpi` (Department Template)
- **Purpose**: Defines how a department is evaluated.
- **Weights**: 
    - `alpha` ($\alpha$): Weight for department-specific KPI lines.
    - `beta` ($\beta$): Weight for the average performance of employees in the department.
    - **Constraint**: $\alpha + \beta = 1.0$.

### `hr.department.performance.evaluation` (Dept Evaluation)
- **Calculation**:
    - `dept_kpi_score`: Weighted average of `hr.department.evaluation.line` scores.
    - `avg_individual_score`: Average `performance_score` of all `completed` employee evaluations in that department/period.
    - `department_score`: $(\alpha \times \text{dept\_kpi\_score}) + (\beta \times \text{avg\_individual\_score})$.

---

## KPI Engine (`hr.kpi.engine`)

The engine is an `AbstractModel` providing centralized computation logic:

### Employee Sources:
1. **`done_task`**: Count of tasks with `stage_id.is_done_stage=True` and `date_deadline` in range.
2. **`task_on_time`**: % of done tasks where `done_date` <= `date_deadline`.
3. **`late_days`**: Counts days where the first check-in is after the calendar start time (considering `late_grace_minutes`).
4. **`attendance_full`**: Complex calculation of Expected Work Days (from calendar, minus public holidays) vs Worked Days vs Approved Leave vs Unpaid Leave.

### Department Sources (Extension):
1. **`dept_task_completion`**: Aggregate on-time completion rate for all tasks assigned to department employees.
2. **`dept_attendance_rate`**: Average attendance rate across all department employees.
3. **`dept_avg_individual`**: Average of all completed employee performance scores within the department for the period.

---

## Global Configuration (`res.config.settings`)
- `kpi_threshold_excellent`: Default 9.0.
- `kpi_threshold_pass`: Default 5.0.
- `late_grace_minutes`: Buffer for check-in.
- `deadline_reminder_days`: For automated email/chatter reminders.

---

## Data Aggregation (`hr.performance.report`)
- **Batching**: Links multiple employee/department evaluations together for a single period.
- **Reporting**: Provides `get_report_dashboard_data()` for cross-employee comparisons and "Done Task" vs "Late" vs "Attendance" summaries.
- **Reminders**: Cron job `_cron_send_deadline_reminder` sends notifications to employees.

---

## Wizards & Automation

### `hr.kpi.generate.wizard`
- **Purpose**: Batch creates employee evaluations from a single `hr.kpi` template.
- **Logic**:
    - Filters active employees by Department.
    - Prevents duplicate evaluations for the same employee/period.
    - Automatically calculates `start_date`, `end_date`, and `deadline` based on the selected period (Monthly, Quarterly, etc.).
    - Sends an inbox/email notification with a direct link to each generated evaluation.

### `hr.department.kpi.generate.wizard`
- **Purpose**: A comprehensive generator that creates one `hr.department.performance.evaluation` and multiple `hr.performance.evaluation` records for all employees in that department.
- **Logic**: 
    - Maps `hr.department.kpi` periods to `hr.kpi` periods.
    - Links all generated records to a central `hr.performance.report`.
    - Ensures consistency across the department's evaluation cycle.

---

## UI Components & Dashboards

The module features a rich interactive layer built with OWL (Odoo Web Library) and Chart.js.

### 1. Individual Dashboard (`kpi_individual_dashboard`)
- **Accessibility**: Available via the "Dashboard" menu under KPI Employee.
- **Features**:
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
- **`hr.employee`**: Stored `performance_score` from the latest evaluation (if deadline hasn't passed).
- **`hr.department`**: Stored `department_score` and `level` from the latest approved evaluation.

