# Business Flow and Model Structure - custom_adecsol_hr_performance_evaluator

## Scope
This document summarizes the business flow and key models for the module. It is intended for another agent to continue development and maintenance.

## Business Flow (End-to-End)
1. HR/Manager defines KPI templates for employees (`hr.kpi`) and departments (`hr.department.kpi`).
2. HR generates evaluation batches from reports (`hr.performance.report`) or wizards.
3. Evaluation records are created with lines copied from templates.
4. Auto KPI lines compute `actual` via `hr.kpi.engine` (employee) or `compute_for_department` (department).
5. Managers fill in manual values and submit evaluations.
6. HR approves evaluations; employee or department scores are finalized.
7. Latest approved scores are surfaced on `hr.employee` and `hr.department`.

## Core Models (Employee KPI)

### `hr.kpi` (KPI Template)
- Purpose: Define KPI template for employees by period/department/job.
- Key fields: `name`, `period`, `department_id`, `job_id`, `kpi_line_ids`.
- Relations: One2many to `hr.kpi.line`.

### `hr.kpi.line` (Template Line)
- Purpose: Individual KPI criteria in a template.
- Key fields: `kpi_type`, `target`, `target_type`, `direction`, `weight`, `is_auto`, `data_source`, `is_section`.
- Behavior: Used to generate evaluation lines.

### `hr.performance.evaluation` (Employee Evaluation)
- Purpose: Store employee KPI evaluation for a time range.
- Key fields: `employee_id`, `kpi_id`, `start_date`, `end_date`, `performance_score`, `performance_level`, `state`.
- State: `draft` -> `submitted` -> `approved` -> `cancel`.

### `hr.performance.evaluation.line` (Employee Evaluation Line)
- Purpose: Score each KPI line in an evaluation.
- Key fields: `actual`, `system_score`, `final_rating`, rating fields, comments.
- Behavior: Computes scores per KPI type and supports manager override.

### `hr.performance.report` (Evaluation Hub)
- Purpose: Batch generator for evaluations, reminders, exports.
- Key fields: `department_id`, `period`, date range.

## Department KPI Models

### `hr.department.kpi` (Department KPI Template)
- Purpose: Template for department-level KPI.
- Key fields: `name`, `department_id`, `period`, `alpha`, `beta`, `kpi_line_ids`.
- Rules: `alpha + beta = 1.0` (validated).
- Relations: One2many to `hr.department.kpi.line`.

### `hr.department.kpi.line` (Department KPI Line)
- Purpose: KPI criteria for department templates.
- Key fields: `kpi_type`, `target`, `target_type`, `direction`, `weight`, `is_auto`, `data_source`, `is_section`.
- Data sources: `dept_task_completion`, `dept_attendance_rate`, `dept_avg_individual`, `manual`.

### `hr.department.performance.evaluation` (Department Evaluation)
- Purpose: Department KPI evaluation for a time range.
- Key fields: `department_id`, `department_kpi_id`, `start_date`, `end_date`, `deadline`, `state`.
- Computed fields: `dept_kpi_score`, `avg_individual_score`, `department_score`, `department_level`.
- Relations: One2many to `hr.department.evaluation.line`.
- State: `draft` -> `submitted` -> `approved` -> `cancel`.

### `hr.department.evaluation.line` (Department Evaluation Line)
- Purpose: KPI line instance for department evaluation.
- Key fields: `actual`, `system_score`, `final_score`, manager rating fields, comments.
- Behavior: Calculates scores per KPI type; supports manager input.

### `hr.department` (Extension)
- Purpose: Show latest approved department KPI score.
- Key fields: `department_score`, `department_level` (computed).

## Engine Extension

### `hr.kpi.engine` (Department extension)
- Entry: `compute_for_department(department, dept_kpi_line, date_from, date_to)`.
- Sources:
  - `dept_task_completion`: On-time completion rate for tasks assigned to department users.
  - `dept_attendance_rate`: Average attendance rate across department employees.
  - `dept_avg_individual`: Average approved individual scores in the period.
- Important: Use timezone-aware datetime and `compute_leaves=False` in work day calculations.

## Security Summary
- CRUD access via `security/ir.model.access.csv` for 4 groups: employee, manager, HR, admin.
- Record rules in `security/security.xml` for department KPI models:
  - Manager: only own department.
  - HR/Admin: full access.
- No custom rule for `hr.department` (use Odoo core rules).

## Known XML Dependency
- `action_hr_kpi_generate_wizard` must load before any view referencing it.

