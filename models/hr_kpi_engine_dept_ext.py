from odoo import models, fields, api

class HrKpiEngineDeptExt(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _inherit = 'hr.kpi.engine'

    @api.model
    def compute_for_department(self, department, dept_kpi_line, date_from, date_to):
        if not dept_kpi_line.is_auto or (dept_kpi_line.data_source or 'manual') == 'manual':
            return 0.0

        if dept_kpi_line.data_source == 'dept_task_completion':
            return self._compute_dept_task_completion(department, dept_kpi_line, date_from, date_to)
        if dept_kpi_line.data_source == 'dept_attendance_rate':
            return self._compute_dept_attendance_rate(department, dept_kpi_line, date_from, date_to)
        if dept_kpi_line.data_source == 'dept_avg_individual':
            return self._compute_dept_avg_individual(department, dept_kpi_line, date_from, date_to)

        return 0.0

    @api.model
    def _compute_dept_task_completion(self, department, dept_kpi_line, date_from, date_to):
        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', department.id), ('active', '=', True),
        ])
        user_ids = employees.mapped('user_id').ids
        if not user_ids:
            return 0.0

        Task = self.env['project.task'].sudo()
        domain = [
            ('user_ids', 'in', user_ids),
            ('stage_id.is_done_stage', '=', True),
            ('date_deadline', '>=', date_from),
            ('date_deadline', '<=', date_to),
            ('project_id', '!=', False),
        ]
        tasks = Task.search(domain)
        if not tasks:
            return 0.0

        on_time = 0
        for t in tasks:
            done_dt_utc = fields.Datetime.to_datetime(t.done_date) if t.done_date else False
            deadline_dt_utc = fields.Datetime.to_datetime(t.date_deadline) if t.date_deadline else False
            if not done_dt_utc or not deadline_dt_utc:
                continue
            done_local = fields.Datetime.context_timestamp(self, done_dt_utc)
            deadline_local = fields.Datetime.context_timestamp(self, deadline_dt_utc)
            if done_local <= deadline_local:
                on_time += 1

        return self._value_or_percentage(
            kpi_line=dept_kpi_line,
            numerator=on_time,
            denominator=len(tasks),
        )

    @api.model
    def _compute_dept_attendance_rate(self, department, dept_kpi_line, date_from, date_to):
        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', department.id),
            ('active', '=', True),
            ('resource_calendar_id', '!=', False),
        ])
        if not employees:
            return 0.0

        total_expected = 0.0
        total_worked = 0.0

        import datetime
        import pytz
        
        d_from = fields.Date.to_date(date_from)
        d_to = fields.Date.to_date(date_to)

        for emp in employees:
            tz = self._get_tz(emp)
            dt_from_local = tz.localize(datetime.datetime.combine(d_from, datetime.time.min))
            dt_to_local = tz.localize(datetime.datetime.combine(d_to + datetime.timedelta(days=1), datetime.time.min))

            # Expected raw
            try:
                work_data = emp._get_work_days_data_batch(dt_from_local, dt_to_local, compute_leaves=False)
                expected_raw = float((work_data.get(emp.id) or {}).get('days') or 0.0)
            except Exception:
                expected_raw = 0.0

            # Public holiday calculation to subtract from expected raw
            public_holiday_days = 0.0
            try:
                global_leave_domain = [('time_type', '=', 'leave'), ('resource_id', '=', False)]
                leave_intervals = emp.resource_calendar_id._leave_intervals_batch(
                    dt_from_local, dt_to_local, resources=self.env['resource.resource'], domain=global_leave_domain
                )
                global_intervals = leave_intervals.get(False, [])
                holiday_dates = set()
                for start, stop, _meta in global_intervals:
                    cur = start.astimezone(tz).date()
                    end_date = stop.astimezone(tz).date()
                    while cur <= end_date:
                        holiday_dates.add(cur)
                        cur += datetime.timedelta(days=1)

                for hday in holiday_dates:
                    dt_hday = tz.localize(datetime.datetime.combine(hday, datetime.time.min))
                    dt_hday_next = dt_hday + datetime.timedelta(days=1)
                    day_work = emp._get_work_days_data_batch(dt_hday, dt_hday_next, compute_leaves=False)
                    public_holiday_days += float((day_work.get(emp.id) or {}).get('days') or 0.0)
            except Exception:
                pass

            expected_display = max(0.0, expected_raw - public_holiday_days)
            if expected_display <= 0:
                continue

            dt_start_utc = datetime.datetime.combine(d_from, datetime.time.min)
            dt_end_utc = datetime.datetime.combine(d_to + datetime.timedelta(days=1), datetime.time.min)

            attendances = self.env['hr.attendance'].sudo().search([
                ('employee_id', '=', emp.id),
                ('check_in', '>=', dt_start_utc),
                ('check_in', '<', dt_end_utc),
            ], order='check_in asc')

            worked_dates = set()
            for att in attendances:
                if not att.check_in:
                    continue
                check_in_utc = fields.Datetime.to_datetime(att.check_in).replace(tzinfo=pytz.UTC)
                local_date = check_in_utc.astimezone(tz).date()

                if not (d_from <= local_date <= d_to): continue
                if local_date in worked_dates: continue
                if self._get_duration_days_for_date(emp.resource_calendar_id, local_date) > 0:
                    worked_dates.add(local_date)

            worked_days = sum(self._get_duration_days_for_date(emp.resource_calendar_id, d) for d in worked_dates)

            total_expected += expected_display
            total_worked += worked_days

        if total_expected <= 0:
            return 0.0

        avg_rate = total_worked / total_expected

        return self._value_or_percentage(
            kpi_line=dept_kpi_line,
            numerator=avg_rate * 100.0,
            denominator=100.0,
        )

    @api.model
    def _compute_dept_avg_individual(self, department, dept_kpi_line, date_from, date_to):
        evals = self.env['hr.performance.evaluation'].sudo().search([
            ('state', '=', 'approved'),
            ('employee_id.department_id', '=', department.id),
            ('start_date', '>=', date_from),
            ('end_date', '<=', date_to),
        ])
        if not evals:
            return 0.0

        scores = sum(evals.mapped('performance_score'))
        avg = scores / len(evals)

        return self._value_or_percentage(
            kpi_line=dept_kpi_line,
            numerator=avg,
            denominator=10.0,
        )

