# Bottom-up Department KPI Scoring

## Summary

This document captures the business logic for calculating department KPI scores from employee KPI lines in a bottom-up flow.

The KPI structure has two levels:

- Department KPI evaluation: contains parent KPI lines. Each parent line has a department-level weight, and the total weight of all parent lines must be 100%.
- Employee KPI evaluation: contains child KPI lines. Each child line links directly to one department parent KPI line.
- Employee child KPI weights are absolute weights across the full employee KPI sheet. The total weight of all child lines must be 100%.

The scoring flow is:

1. Calculate each employee's score per parent KPI category by grouping that employee's child KPI lines by `parent_dept_line_id`.
2. Calculate each department parent KPI line score by averaging that category score across all employees in the department.
3. Calculate the final department score by multiplying each parent KPI line score by its department weight.

## Formula

### 1. Employee Category Score

For each employee and parent KPI category:

```text
Employee Category Score =
sum(Child KPI Score x Child KPI Weight) / sum(Child KPI Weights in that Category)
```

Because child KPI weights are absolute weights on the full employee sheet, the category score must use weighted average. This handles categories where child KPI weights are not equal.

### 2. Department Parent KPI Line Score

For each department parent KPI line:

```text
Department Parent KPI Line Score =
sum(Employee Category Scores) / Number of Employees in Department
```

This is a simple average across employees.

### 3. Final Department Score

After every department parent KPI line has a score:

```text
Final Department Score =
sum(Department Parent KPI Line Score x Parent KPI Weight / 100)
```

## Example Configuration

Parent KPI 1: Attendance Discipline, parent weight 10%

- Child KPI 1.1: On-time attendance, child weight 5%
- Child KPI 1.2: Full attendance, child weight 5%

Parent KPI 2: Work Completion Performance, parent weight 20%

- Child KPI 2.1: Completed tasks, child weight 20%

Parent KPI 3: Professional Quality, parent weight 35%

- Child KPI 3.1: Odoo development skill, child weight 20%
- Child KPI 3.2: Code quality and process compliance, child weight 15%

Parent KPI 4: Culture and Awareness, parent weight 35%

- Child KPI 4.1: Teamwork and peer support, child weight 15%
- Child KPI 4.2: Asset protection and cost awareness, child weight 10%
- Child KPI 4.3: Rule compliance, child weight 10%

## Manual Calculation Example

Assume a department has two employees: A and B. All scores are on a 100-point scale.

### Employee A

Parent KPI 1: Attendance Discipline

- On-time attendance: score 90, weight 5%
- Full attendance: score 80, weight 5%

```text
(90 x 5 + 80 x 5) / (5 + 5) = 85
```

Parent KPI 2: Work Completion Performance

- Completed tasks: score 75, weight 20%

```text
75
```

Parent KPI 3: Professional Quality

- Odoo development skill: score 88, weight 20%
- Code quality and process compliance: score 92, weight 15%

```text
(88 x 20 + 92 x 15) / (20 + 15)
= (1760 + 1380) / 35
= 89.71
```

Parent KPI 4: Culture and Awareness

- Teamwork and peer support: score 70, weight 15%
- Asset protection and cost awareness: score 85, weight 10%
- Rule compliance: score 95, weight 10%

```text
(70 x 15 + 85 x 10 + 95 x 10) / 35
= 2850 / 35
= 81.43
```

### Employee B

Parent KPI 1:

```text
(100 x 5 + 90 x 5) / 10 = 95
```

Parent KPI 2:

```text
85
```

Parent KPI 3:

```text
(80 x 20 + 78 x 15) / 35
= 2770 / 35
= 79.14
```

Parent KPI 4:

```text
(90 x 15 + 80 x 10 + 70 x 10) / 35
= 2850 / 35
= 81.43
```

## Roll Up To Department Parent KPI Lines

Parent KPI 1:

```text
(85 + 95) / 2 = 90
```

Parent KPI 2:

```text
(75 + 85) / 2 = 80
```

Parent KPI 3:

```text
(89.71 + 79.14) / 2 = 84.43
```

Parent KPI 4:

```text
(81.43 + 81.43) / 2 = 81.43
```

## Final Department Score

```text
90 x 10%
+ 80 x 20%
+ 84.43 x 35%
+ 81.43 x 35%

= 9
+ 16
+ 29.55
+ 28.50

= 83.05
```

Final Department Score: `83.05 / 100`.

## Key Interpretation

This logic means:

- Employee KPI child lines are the lowest scoring level.
- Child lines are grouped by their linked department parent KPI line.
- Each employee contributes one normalized category score per department parent KPI line.
- The department parent line score is the average of those employee category scores.
- The final department score is the weighted sum of all department parent line scores.
