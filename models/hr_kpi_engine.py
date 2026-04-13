import datetime
import pytz

from odoo import api, fields, models

LATE_GRACE_MINUTES = 5

class HrKpiEngine(models.AbstractModel):
    _name = 'hr.kpi.engine'
    _description = 'HR KPI Engine'

    @api.model
    def compute(self, employee, kpi_line, date_from, date_to):
        """Return computed KPI actual (float) for an employee in a date range.

        Backward compatible: for manual KPIs returns 0.0 (caller keeps existing actual).
        """
        employee = employee.sudo()
        kpi_line = kpi_line.sudo()
        if not employee or not kpi_line:
            return 0.0

        if not kpi_line.is_auto or (kpi_line.data_source or 'manual') == 'manual':
            return 0.0

        if kpi_line.data_source == 'task_on_time':
            return self._compute_task_on_time(employee, kpi_line, date_from, date_to)
        if kpi_line.data_source == 'late_days':
            return self._compute_late_days(employee, kpi_line, date_from, date_to)
        if kpi_line.data_source == 'attendance_full':
            return self._compute_attendance_full(employee, kpi_line, date_from, date_to)

        return 0.0

    @api.model
    def compute_with_metrics(self, employee, kpi_line, date_from, date_to):
        """Compute KPI actual and optionally return extra metrics.

        Why: context changes inside compute() are not observable by the caller because
        compute() only returns a float. For some data sources (attendance_full) we need
        intermediate metrics for scoring/debug.

        Returns:
            (value: float, metrics: dict|False)
        """
        kpi_line = kpi_line.sudo() if kpi_line else kpi_line
        if not kpi_line:
            return 0.0, False

        if (kpi_line.data_source or 'manual') == 'attendance_full':
            value, metrics = self._compute_attendance_full_with_metrics(employee, kpi_line, date_from, date_to)
            return value, metrics

        return self.compute(employee, kpi_line, date_from, date_to), False

    @api.model
    def _get_tz(self, employee):
        """Best-effort timezone used to bucket datetimes by local date."""
        tz_name = (
            employee.resource_calendar_id.tz
            or employee.tz
            or self.env.user.tz
            or 'UTC'
        )
        return pytz.timezone(tz_name)

    @api.model
    def _compute_attendance_full(self, employee, kpi_line, date_from, date_to):
        """Compute leave days (absent days) vs expected work days for the range.

        Worked days: distinct local dates with at least 1 check_in.
        Expected work days: employee._get_work_days_data_batch().days
        Leave days: expected_work_days - worked_days (clamped at 0)
        Approved leave days: rough day-count of validated leaves overlapping the range.

        Returns (Actual):
        - target_type='value'      -> leave_days
        - target_type='percentage' -> leave_days / expected_work_days * 100

        Side-channel: store metrics in context so caller can persist them on evaluation lines.
        """
        if not employee or not date_from or not date_to:
            return 0.0

        employee = employee.sudo()
        kpi_line = kpi_line.sudo()

        d_from = fields.Date.to_date(date_from)
        d_to = fields.Date.to_date(date_to)
        if not d_from or not d_to or d_from > d_to:
            return 0.0

        # Step 1: actual worked days from attendance (unique dates with check_in)
        tz = self._get_tz(employee)
        dt_start = fields.Datetime.to_datetime(date_from)
        dt_end_excl = fields.Datetime.to_datetime(fields.Date.add(date_to, days=1))

        Attendance = self.env['hr.attendance'].sudo()
        attendances = Attendance.search(
            [
                ('employee_id', '=', employee.id),
                ('check_in', '>=', dt_start),
                ('check_in', '<', dt_end_excl),
            ],
            order='check_in asc',
        )

        worked_dates = set()
        for att in attendances:
            if not att.check_in:
                continue
            check_in_utc = fields.Datetime.to_datetime(att.check_in)
            check_in_local = check_in_utc.replace(tzinfo=pytz.UTC).astimezone(tz)
            worked_dates.add(check_in_local.date())
        worked_days = float(len(worked_dates))

        # Step 2: expected work days from calendar
        expected_work_days = 0.0
        if employee.resource_calendar_id:
            try:
                # _get_work_days_data_batch expects datetimes (it normalizes timezone/UTC internally).
                # Provide full-day datetime bounds.
                dt_from = fields.Datetime.to_datetime(date_from)
                dt_to_excl = fields.Datetime.to_datetime(fields.Date.add(date_to, days=1))
                work_data = employee._get_work_days_data_batch(dt_from, dt_to_excl)
                expected_work_days = float((work_data.get(employee.id) or {}).get('days') or 0.0)
            except Exception:
                expected_work_days = 0.0

        # Step 3: leave_days (expected - worked) (can be negative due to extra attendances)
        leave_days = max(0.0, expected_work_days - worked_days)

        # Step 4: approved leave days within range (validated leaves)
        # NOTE: _get_leave_days_data_batch's `domain` targets resource.calendar.leaves,
        # so it cannot filter by hr.leave.state. We compute approved leave days by reading
        # validated hr.leave and converting them to calendar-accurate day quantities.
        approved_leave_days = 0.0
        if expected_work_days > 0 and employee.resource_calendar_id:
            try:
                Leave = self.env['hr.leave'].sudo()
                leaves = Leave.search([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'validate'),
                    ('request_date_from', '<=', d_to),
                    ('request_date_to', '>=', d_from),
                ])

                emp = self.env['hr.employee'].sudo().browse(employee.id)
                for lv in leaves:
                    lf = max(fields.Date.to_date(lv.request_date_from), d_from)
                    lt = min(fields.Date.to_date(lv.request_date_to), d_to)
                    if not lf or not lt or lf > lt:
                        continue

                    # Calendar-accurate working days for this leave interval
                    dt_lf = datetime.datetime.combine(lf, datetime.time.min).replace(tzinfo=pytz.UTC)
                    dt_lt_excl = datetime.datetime.combine(fields.Date.add(lt, days=1), datetime.time.min).replace(tzinfo=pytz.UTC)
                    leave_work = emp._get_work_days_data_batch(
                        dt_lf,
                        dt_lt_excl,
                        compute_leaves=False,
                    )
                    approved_leave_days += float((leave_work.get(emp.id) or {}).get('days') or 0.0)
            except Exception as e:
                approved_leave_days = 0.0

        has_unpaid_leave = bool(leave_days > approved_leave_days + 1e-6)

        # Return actual; pass metrics to caller via returned context.
        # Caller can read them as: engine.with_context(...).env.context.get('attendance_full_metrics')
        # To keep compatibility with existing call sites, we also return the plain float.
        metrics = {
            'worked_days': worked_days,
            'expected_work_days': expected_work_days,
            'leave_days': leave_days,
            'approved_leave_days': approved_leave_days,
            'has_unpaid_leave': has_unpaid_leave,
        }
        return self._value_or_percentage(
            kpi_line=kpi_line,
            numerator=leave_days,
            denominator=expected_work_days,
        )

    @api.model
    def _compute_attendance_full_with_metrics(self, employee, kpi_line, date_from, date_to):
        """Same as _compute_attendance_full but also returns metrics dict."""
        # Reuse the exact logic by computing here and returning both.
        if not employee or not kpi_line or not date_from or not date_to:
            return 0.0, {
                'worked_days': 0.0,
                'expected_work_days': 0.0,
                'leave_days': 0.0,
                'approved_leave_days': 0.0,
                'has_unpaid_leave': False,
            }

        employee = employee.sudo()
        kpi_line = kpi_line.sudo()

        d_from = fields.Date.to_date(date_from)
        d_to = fields.Date.to_date(date_to)
        if not d_from or not d_to or d_from > d_to:
            return 0.0, {
                'worked_days': 0.0,
                'expected_work_days': 0.0,
                'leave_days': 0.0,
                'approved_leave_days': 0.0,
                'has_unpaid_leave': False,
            }

        tz = self._get_tz(employee)
        dt_start = fields.Datetime.to_datetime(date_from)
        dt_end_excl = fields.Datetime.to_datetime(fields.Date.add(date_to, days=1))

        Attendance = self.env['hr.attendance'].sudo()
        attendances = Attendance.search(
            [
                ('employee_id', '=', employee.id),
                ('check_in', '>=', dt_start),
                ('check_in', '<', dt_end_excl),
            ],
            order='check_in asc',
        )

        worked_dates = set()
        for att in attendances:
            if not att.check_in:
                continue
            check_in_utc = fields.Datetime.to_datetime(att.check_in)
            check_in_local = check_in_utc.replace(tzinfo=pytz.UTC).astimezone(tz)
            worked_dates.add(check_in_local.date())
        worked_days = float(len(worked_dates))

        expected_work_days = 0.0
        if employee.resource_calendar_id:
            try:
                # _get_work_days_data_batch expects datetimes.
                dt_from = fields.Datetime.to_datetime(date_from)
                dt_to_excl = fields.Datetime.to_datetime(fields.Date.add(date_to, days=1))
                work_data = employee._get_work_days_data_batch(dt_from, dt_to_excl)
                expected_work_days = float((work_data.get(employee.id) or {}).get('days') or 0.0)
            except Exception:
                expected_work_days = 0.0

        leave_days = max(0.0, expected_work_days - worked_days)

        approved_leave_days = 0.0
        if expected_work_days > 0 and employee.resource_calendar_id:
            try:
                Leave = self.env['hr.leave'].sudo()
                leaves = Leave.search([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'validate'),
                    ('request_date_from', '<=', d_to),
                    ('request_date_to', '>=', d_from),
                ])

                emp = self.env['hr.employee'].sudo().browse(employee.id)
                for lv in leaves:
                    lf = max(fields.Date.to_date(lv.request_date_from), d_from)
                    lt = min(fields.Date.to_date(lv.request_date_to), d_to)
                    if not lf or not lt or lf > lt:
                        continue
                    dt_lf = datetime.datetime.combine(lf, datetime.time.min).replace(tzinfo=pytz.UTC)
                    dt_lt_excl = datetime.datetime.combine(fields.Date.add(lt, days=1), datetime.time.min).replace(tzinfo=pytz.UTC)
                    leave_work = emp._get_work_days_data_batch(
                        dt_lf,
                        dt_lt_excl,
                        compute_leaves=False,
                    )
                    approved_leave_days += float((leave_work.get(emp.id) or {}).get('days') or 0.0)
            except Exception as e:
                approved_leave_days = 0.0

        has_unpaid_leave = bool(leave_days > approved_leave_days + 1e-6)

        metrics = {
            'worked_days': worked_days,
            'expected_work_days': expected_work_days,
            'leave_days': leave_days,
            'approved_leave_days': approved_leave_days,
            'has_unpaid_leave': has_unpaid_leave,
        }
        value = self._value_or_percentage(kpi_line=kpi_line, numerator=leave_days, denominator=expected_work_days)
        return value, metrics

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    @api.model
    def _value_or_percentage(self, kpi_line, numerator, denominator):
        """Return either a raw value or a percentage-ratio, depending on target_type.

        This helper centralizes the unit policy so it can be reused by multiple
        data sources.

        - target_type = 'value'      -> return numerator (raw count/value)
        - target_type = 'percentage' -> return (numerator/denominator) * 100
        """
        kpi_line = kpi_line.sudo() if kpi_line else kpi_line
        numerator = float(numerator or 0.0)
        denominator = float(denominator or 0.0)

        if not kpi_line or (kpi_line.target_type or 'value') == 'value':
            return numerator

        # percentage (ratio)
        return (numerator / denominator) * 100 if denominator > 0 else 0.0

    # ------------------------------------------------------------
    # Data sources
    # ------------------------------------------------------------

    @api.model
    def _compute_task_on_time(self, employee, kpi_line, date_from, date_to):
        """% tasks completed on time in the range.

        Definition:
        - Task is assigned to employee user (project.task.user_ids)
        - Completed: task.stage_id.fold = True
        - Date range: use task.date_deadline within [date_from, date_to]
        - On time: done_date <= date_deadline

        Returns:
        - target_type='value'      -> number of on-time tasks
        - target_type='percentage' -> ratio on_time / total_tasks (0..1)
        """
        user = employee.user_id
        if not user or not date_from or not date_to:
            return 0.0

        Task = self.env['project.task'].sudo()
        domain = [
            ('user_ids', 'in', user.id),
            ('stage_id.is_done_stage', '=', True),
            ('date_deadline', '>=', date_from),
            ('date_deadline', '<=', date_to),
        ]
        tasks = Task.search(domain)
        if not tasks:
            return 0.0

        on_time = 0
        for t in tasks:
            done_dt_utc = fields.Datetime.to_datetime(t.done_date) if t.done_date else False
            deadline_dt_utc = fields.Datetime.to_datetime(t.date_deadline) if t.date_deadline else False
            if not deadline_dt_utc or not done_dt_utc:
                continue

            # Compare on the same timezone context.
            done_dt_local = fields.Datetime.context_timestamp(self, done_dt_utc)
            deadline_dt_local = fields.Datetime.context_timestamp(self, deadline_dt_utc)

            if done_dt_local <= deadline_dt_local:
                on_time += 1

        return self._value_or_percentage(kpi_line=kpi_line, numerator=on_time, denominator=len(tasks))

    @api.model
    def _compute_late_days(self, employee, kpi_line, date_from, date_to):
        """Compute number of late work days within [date_from, date_to].

        Business rule:
        - For each work day, compare the employee first check-in with expected start time,
          derived from the employee working schedule (resource_calendar_id).
        - If first check-in is after expected start -> late for that day.

        Return:
        - target_type='value'      -> late_days (count)
        - target_type='percentage' -> late_days / total_work_days * 100
        """
        if not employee or not date_from or not date_to:
            return 0.0

        calendar = employee.resource_calendar_id
        if not calendar:
            # Edge case: no calendar -> assume no late to avoid false penalties
            return 0.0

        dt_start = fields.Datetime.to_datetime(date_from)
        dt_end_excl = fields.Datetime.to_datetime(fields.Date.add(date_to, days=1))

        Attendance = self.env['hr.attendance'].sudo()
        attendances = Attendance.search(
            [
                ('employee_id', '=', employee.id),
                ('check_in', '>=', dt_start),
                ('check_in', '<', dt_end_excl),
            ],
            order='check_in asc',
        )

        # Build first check-in per local date
        first_check_in_by_date = {}
        for att in attendances:
            if not att.check_in:
                continue
            check_in_utc = fields.Datetime.to_datetime(att.check_in)
            check_in_local = fields.Datetime.context_timestamp(self, check_in_utc)
            day = check_in_local.date()
            if day not in first_check_in_by_date:
                first_check_in_by_date[day] = check_in_local

        # Iterate each day in range to count work days and late days
        d = fields.Date.to_date(date_from)
        d_end = fields.Date.to_date(date_to)
        late_days = 0
        total_work_days = 0

        while d and d_end and d <= d_end:
            # Determine expected start for that day from calendar
            expected_start_local = self._get_expected_start_local(employee, calendar, d)
            if expected_start_local:
                total_work_days += 1
                first_ci = first_check_in_by_date.get(d)
                if first_ci and first_ci > expected_start_local:
                    late_days += 1
            d = fields.Date.add(d, days=1)

        return self._value_or_percentage(kpi_line=kpi_line, numerator=late_days, denominator=total_work_days)

    # ------------------------------------------------------------
    # Calendar helpers
    # ------------------------------------------------------------

    @api.model
    def _get_expected_start_local(self, employee, calendar, day_date):
        if not calendar or not day_date:
            return False

        weekday = str(day_date.weekday())
        day_attendances = calendar.attendance_ids.filtered(
            lambda a: a.dayofweek == weekday and not a.display_type
        )
        if not day_attendances:
            return False

        hour_from = min(day_attendances.mapped('hour_from') or [0.0])
        hours = int(hour_from)
        minutes = int(round((hour_from - hours) * 60.0))

        # FIX: Tạo naive datetime rồi localize trực tiếp,
        # KHÔNG convert qua UTC trước
        tz_name = (
                calendar.tz
                or employee.tz
                or self.env.user.tz
                or 'UTC'
        )
        tz = pytz.timezone(tz_name)
        naive_local = datetime.datetime.combine(
            day_date, datetime.time(hour=hours, minute=minutes)
        )
        return  tz.localize(naive_local) + datetime.timedelta(minutes=5)
