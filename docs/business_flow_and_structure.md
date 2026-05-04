# Business Flow and Structure of `custom_adecsol_hr_performance_evaluator`

## 1. Introduction
This Odoo module (`custom_adecsol_hr_performance_evaluator`) is designed to manage employee performance evaluations. It calculates Key Performance Indicators (KPIs) dynamically or manually, facilitates the review process between employees and managers, tracks attendance/task metrics automatically, and provides reports and UI badges summarizing an employee's performance over selected periods.

## 2. Business Flow
1. **Creation of KPI Templates**: HR or Managers define general KPI Templates (`hr.kpi`) grouping various evaluation criteria (`hr.kpi.line`). A template is normally associated with a specific period (monthly, quarterly, etc.) and a target Department or Job Position.
2. **Launch Performance Report**: A Performance Report (`hr.performance.report`) is created for a specific period to define the start date, end date, and deadline. It triggers evaluations and can send notification emails/reminders.
3. **Generating Evaluation Records**: The system or user creates Performance Evaluation records (`hr.performance.evaluation`) for employees. Based on the selected `kpi_id`, evaluation lines (`hr.performance.evaluation.line`) are auto-populated.
4. **Auto-Computing Actuals**: A cron job or manual action runs the KPI Engine (`hr.kpi.engine`) on KPI lines configured with `is_auto = True`. It interrogates module data (like tasks or attendances) via data sources (e.g., `attendance_full`, `late_days`, `task_on_time`) to compute and fill in the "Actual" values.
5. **Self & Manager Evaluation**: 
    - **Draft State**: Employees fill in self-assessments (ratings, binary choices, scores). Manager fields automatically mirror employee entries in draft mode to simulate live evaluation results.
    - **Submitted State**: Employees submit the appraisal. The manager reviews, optionally modifies the manager inputs/comments, and visualizes the calculated `system_score`.
6. **Approval & Result**: The Manager approves the evaluation. The overall `performance_score` and `performance_level` (Excellent, Pass, Fail) are computed based on configured thresholds.
7. **Scoring Sync**: The `hr.employee` profile updates its `performance_score` based on the latest finalized/approved evaluations.

## 3. Structure of Each Model

### 3.1. `hr.kpi`
- **Purpose**: Defines templates containing multiple KPI criteria for a department or job position.
- **Key Fields**:
  - `name`, `period` (Monthly, Quarterly, etc.), `department_id`, `job_id`.
  - `kpi_line_ids`: `One2many` relation linking to `hr.kpi.line`.

### 3.2. `hr.kpi.line`
- **Purpose**: Defines an individual evaluation criterion or section header within a KPI Template.
- **Key Fields**:
  - `kpi_type`: 'quantitative', 'binary', 'rating', 'score'.
  - `target`, `target_type` (value/percentage), `direction` (higher/lower is better).
  - `weight`: Modifies the impact of this line on the total appraisal score.
  - `is_auto`, `data_source`: Indicates if the actual value should be retrieved programmatically (manual, task_on_time, late_days, attendance_full).
  - `is_section`: Visual grouping.

### 3.3. `hr.performance.evaluation`
- **Purpose**: Represents a specific appraisal event for an individual employee.
- **State Machine**: Draft -> Submitted -> Approved -> Cancel.
- **Key Fields**:
  - `employee_id`, `kpi_id`, `performance_report_id`.
  - `start_date`, `end_date`, `deadline`.
  - `evaluation_line_ids`: The individual scores, replicated from the KPI template.
  - `performance_score`: The aggregated weighted average score.
  - `performance_level`, `performance_badge_class`: Calculated classifications based on configuration thresholds.

### 3.4. `hr.performance.evaluation.line`
- **Purpose**: The live assessment entry connecting actual achievements to targets.
- **Calculations & Logic**:
  - Contains mirroring logic to copy `employee_rating` over to `manager_rating` while in Draft.
  - Controls access right constraints (e.g., manager cannot edit employee comments).
  - Evaluates `system_score` dynamically based on ratios (Actual vs. Target, penalty rules for late days/unpaid leave).
  - Generates the `final_rating` from manager ratings or the computed `system_score`.
- **Key Fields**:
  - `actual`, `system_score`, `final_rating`.
  - `employee_rating_*` & `manager_rating_*`: Separate inputs per assessment type.
  - Attendance specific metrics (`attendance_worked_days`, `attendance_unpaid_leave_days`, etc.) populated via KPI Engine.

### 3.5. `hr.kpi.engine` (AbstractModel)
- **Purpose**: Calculates metric formulas mapped to the `data_source` enum.
- **Capabilities**:
  - `_compute_task_on_time`: Calculates how many tasks were finished within the period minus deadlines.
  - `_compute_late_days`: Aggregates instances where the check-in time exceeds the expected start time defined in `resource.calendar`.
  - `_compute_attendance_full_with_metrics`: Advanced script computing raw expected vs worked shifts factoring in approved and unapproved leaves (with exact timezone compliance).

### 3.6. `hr.performance.report`
- **Purpose**: A centralized hub/report to batch create and manage evaluations, including sending alerts.
- **Key Capabilities**: 
  - Generates deadline notification reminders (`_cron_send_deadline_reminder`).
  - Capable of triggering an Excel report output detailing the scheduled tasks/calendar meetings by date (`action_export_excel_report`).

### 3.7. `hr.employee` (Extension)
- **Purpose**: Attaches the latest KPI scores directly onto the employee profile.
- **Key Fields**:
  - `performance_score`: Automatically computes based on the latest valid/active `hr.performance.evaluation` within deadlines.
