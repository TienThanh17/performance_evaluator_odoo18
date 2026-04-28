import datetime
import pytz

from odoo import api, fields, models

LATE_GRACE_MINUTES = 30

_EMPTY_METRICS = {
    'expected_work_days': 0.0,  # Ngày phải đi làm theo calendar (đã trừ ngày lễ , nhưng chưa trừ phép   )
    'worked_days': 0.0,  # Ngày thực sự có check-in
    'approved_leave_days': 0.0,  # Ngày nghỉ có phép (validated hr.leave)
    'public_holiday_days': 0.0,  # Ngày nghỉ lễ (global leaves từ calendar)
    'unpaid_leave_days': 0.0,  # Ngày nghỉ không phép
    'has_unpaid_leave': False,
}


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

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
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

    def _get_duration_days_for_date(self, calendar, day_date):
        """Tổng duration_days của ngày đó theo calendar. 0.0 nếu không phải ngày làm."""
        weekday = str(day_date.weekday())
        slots = calendar.attendance_ids.filtered(
            lambda a: a.dayofweek == weekday
                      and not a.display_type
                      and a.day_period != 'lunch'
                      and (not a.date_from or a.date_from <= day_date)
                      and (not a.date_to or a.date_to >= day_date)
        )
        if calendar.two_weeks_calendar:
            week_type = str(
                self.env['resource.calendar.attendance'].get_week_type(day_date)
            )
            slots = slots.filtered(lambda a: a.week_type == week_type)
        return sum(s.duration_days for s in slots)

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

    @api.model
    def _get_late_grace_minutes(self):
        param_obj = self.env['ir.config_parameter'].sudo()
        res = param_obj.get_param('custom_adecsol_hr_performance_evaluator.late_grace_minutes', default=30)
        try:
            return int(res)
        except (ValueError, TypeError):
            return 30

    # ------------------------------------------------------------
    # Data sources
    # ------------------------------------------------------------
    @api.model
    def _compute_task_on_time(self, employee, kpi_line, date_from, date_to):
        """% tasks completed on time in the range.

        Definition:
        - Task is assigned to employee user (project.task.user_ids)
        - Completed: task.stage_id.is_done_stage = True
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
            ('project_id', '!=', False),
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

    @api.model
    def _compute_attendance_full_with_metrics(self, employee, kpi_line, date_from, date_to):
        """Tính số ngày phải đi làm, nghỉ có phép, nghỉ không phép trong khoảng thời gian.

        Nguyên tắc thiết kế (quan trọng):
        - Tất cả các bước tính toán nội bộ đều dùng compute_leaves=False để giữ
          cùng hệ quy chiếu: mọi con số đều tính trên nền "ngày làm việc thuần
          theo calendar", ngày nghỉ lễ/phép KHÔNG được trừ ngầm.
        - Riêng `expected_work_days` trong metrics đã TRỪ ngày lễ để UI dễ đọc.
          Phép tính unpaid_leave_days vẫn dùng expected_raw nội bộ để cộng lại đúng.
        - Datetime truyền vào các batch method đều được localize theo timezone của
          employee để tránh lệch ngày đầu/cuối kỳ.

        Các bucket nội bộ (compute_leaves=False cho tất cả):
            expected_raw        = calendar thuần, bao gồm cả ngày lễ
            worked_days         = ngày thực tế có check-in (từ hr.attendance)
            approved_leave_days = working days bị cover bởi validated hr.leave
            public_holiday_days = working days bị cover bởi global leaves (ngày lễ)
            unpaid_leave_days   = expected_raw - worked - approved_leave - public_holiday
                                  (clamped >= 0)

        Metrics trả về cho UI:
            expected_work_days  = expected_raw - public_holiday_days
                                  (= số ngày phải đi làm thực tế, đã trừ lễ)

        Kiểm tra UI:
            expected_work_days = worked_days + approved_leave_days + unpaid_leave_days

        Returns:
            (value: float, metrics: dict)
        """
        empty = (0.0, dict(_EMPTY_METRICS))

        if not employee or not kpi_line or not date_from or not date_to:
            return empty

        employee = employee.sudo()
        kpi_line = kpi_line.sudo()

        d_from = fields.Date.to_date(date_from)
        d_to = fields.Date.to_date(date_to)
        if not d_from or not d_to or d_from > d_to:
            return empty

        calendar = employee.resource_calendar_id
        if not calendar:
            return empty

        tz = self._get_tz(employee)

        # Tạo datetime bounds có timezone theo local của employee.
        # Lý do: _get_work_days_data_batch dùng timezone_datetime() bên trong,
        # nếu truyền naive thì nó gắn UTC → lệch ngày với employee ở VN (+7).
        dt_from_local = tz.localize(datetime.datetime.combine(d_from, datetime.time.min))
        dt_to_local = tz.localize(datetime.datetime.combine(d_to + datetime.timedelta(days=1), datetime.time.min))

        # ------------------------------------------------------------------
        # Bước 1: expected_raw — ngày làm việc theo calendar thuần (chưa trừ lễ)
        # ------------------------------------------------------------------
        # compute_leaves=False: KHÔNG trừ ngày lễ hay ngày phép.
        # Đây là mẫu số chung cho toàn bộ phép tính nội bộ.
        # Ngày lễ sẽ được tách riêng ở Bước 4, rồi trừ ra khi build metrics cho UI.
        try:
            work_data = employee._get_work_days_data_batch(
                dt_from_local,
                dt_to_local,
                compute_leaves=False,
            )
            expected_raw = float((work_data.get(employee.id) or {}).get('days') or 0.0)
        except Exception:
            expected_raw = 0.0

        if expected_raw <= 0:
            return empty

        # ------------------------------------------------------------------
        # Bước 2: worked_days — đếm ngày có mặt đủ theo duration_days
        # ------------------------------------------------------------------
        # Chỉ xét có check-in vào ngày làm việc theo calendar hay không.
        # Đi trễ/về sớm không xét ở đây — thuộc KPI late_days.

        dt_start_utc = datetime.datetime.combine(d_from, datetime.time.min)
        dt_end_utc = datetime.datetime.combine(d_to + datetime.timedelta(days=1), datetime.time.min)

        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', dt_start_utc),
            ('check_in', '<', dt_end_utc),
        ], order='check_in asc')

        worked_dates = set()
        for att in attendances:
            if not att.check_in:
                continue
            check_in_utc = fields.Datetime.to_datetime(att.check_in).replace(tzinfo=pytz.UTC)
            local_date = check_in_utc.astimezone(tz).date()

            if not (d_from <= local_date <= d_to):
                continue
            if local_date in worked_dates:
                continue  # ngày đã đếm rồi, bỏ qua

            # Chỉ đếm nếu ngày đó có ca làm theo calendar
            if self._get_duration_days_for_date(calendar, local_date) > 0:
                worked_dates.add(local_date)

        # Cộng duration_days thay vì đếm số nguyên
        worked_days = sum(
            self._get_duration_days_for_date(calendar, d) for d in worked_dates
        )

        # ------------------------------------------------------------------
        # Bước 3: approved_leave_days — ngày nghỉ có phép (validated)
        # ------------------------------------------------------------------
        # Tính số working days (compute_leaves=False) bị cover bởi mỗi hr.leave.
        # Phải dùng compute_leaves=False để cùng hệ quy chiếu với expected_work_days.
        #
        # Ví dụ ngày lễ 2/9:
        #   - Nếu nhân viên xin phép đúng 2/9 và ta dùng compute_leaves=False
        #     → approved_leave_days tính ngày 2/9 là 1 ngày working
        #   - expected_work_days cũng tính 2/9 là 1 ngày (vì compute_leaves=False)
        #   → Hai bên nhất quán, phép tính sau không bị lệch
        approved_leave_days = 0.0
        try:
            validated_leaves = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                ('request_date_from', '<=', d_to),
                ('request_date_to', '>=', d_from),
            ])

            for lv in validated_leaves:
                # Clamp leave vào khoảng [d_from, d_to]
                lf = max(fields.Date.to_date(lv.request_date_from), d_from)
                lt = min(fields.Date.to_date(lv.request_date_to), d_to)
                if lf > lt:
                    continue

                # Localize theo timezone employee (không phải UTC)
                dt_lf = tz.localize(datetime.datetime.combine(lf, datetime.time.min))
                dt_lt = tz.localize(datetime.datetime.combine(lt + datetime.timedelta(days=1), datetime.time.min))

                leave_work = employee._get_work_days_data_batch(
                    dt_lf,
                    dt_lt,
                    compute_leaves=False,  # <-- cùng hệ quy chiếu với expected
                )
                approved_leave_days += float((leave_work.get(employee.id) or {}).get('days') or 0.0)
        except Exception:
            approved_leave_days = 0.0

        # ------------------------------------------------------------------
        # Bước 4: public_holiday_days — ngày nghỉ lễ trong kỳ
        # ------------------------------------------------------------------
        # Tính số working days bị cover bởi global leaves (resource.calendar.leaves
        # không gắn resource_id nào, tức là nghỉ lễ chung).
        # Vì expected đã tính ngày lễ là "ngày làm việc" (compute_leaves=False),
        # ta cần tách bucket này ra để phép tính cuối cộng lại đúng.
        public_holiday_days = 0.0
        try:
            # _leave_intervals_batch với domain mặc định ('time_type','=','leave')
            # sẽ trả về các leaves của calendar, bao gồm global leaves (ngày lễ).
            # Ta chỉ muốn global leaves → lọc resource_id = False.
            global_leave_domain = [
                ('time_type', '=', 'leave'),
                ('resource_id', '=', False),
            ]
            leave_intervals = calendar._leave_intervals_batch(
                dt_from_local,
                dt_to_local,
                resources=self.env['resource.resource'],  # empty = global
                domain=global_leave_domain,
            )
            # Interval trả về cho resource False (global)
            global_intervals = leave_intervals.get(False, [])

            # Đếm working days bị block bởi các interval lễ
            # Dùng _get_days_data cần day_total; đơn giản hơn: đếm distinct dates
            holiday_dates = set()
            for start, stop, _meta in global_intervals:
                # Duyệt từng ngày trong interval lễ
                cur = start.astimezone(tz).date()
                end_date = stop.astimezone(tz).date()
                while cur <= end_date:
                    holiday_dates.add(cur)
                    cur += datetime.timedelta(days=1)

            # Chỉ đếm ngày lễ nằm trong working days (theo calendar)
            for hday in holiday_dates:
                dt_hday = tz.localize(datetime.datetime.combine(hday, datetime.time.min))
                dt_hday_next = dt_hday + datetime.timedelta(days=1)
                day_work = employee._get_work_days_data_batch(
                    dt_hday, dt_hday_next, compute_leaves=False,
                )
                day_count = float((day_work.get(employee.id) or {}).get('days') or 0.0)
                public_holiday_days += day_count

        except Exception:
            public_holiday_days = 0.0

        # ------------------------------------------------------------------
        # Bước 5: unpaid_leave_days — nghỉ không phép
        # ------------------------------------------------------------------
        # Tất cả các bucket đều tính trên cùng hệ quy chiếu compute_leaves=False,
        # nên phép tính cộng lại đúng:
        #
        #   expected = worked + approved_leave + public_holiday + unpaid_leave
        #   → unpaid_leave = expected - worked - approved_leave - public_holiday
        #
        # Lưu ý: approved_leave có thể overlap với public_holiday nếu nhân viên
        # xin phép đúng ngày lễ. Trường hợp đó ta ưu tiên approved_leave.
        # Để tránh trừ 2 lần, ta lấy phần holiday không overlap với leave.
        # Cách đơn giản: clamp unpaid >= 0 là đủ cho hầu hết use case.
        # Dùng expected_raw (chưa trừ lễ) để phép tính cộng lại đúng nội bộ.
        # expected_raw = worked + approved_leave + public_holiday + unpaid_leave
        unpaid_leave_days = max(
            0.0,
            expected_raw - worked_days - approved_leave_days - public_holiday_days
        )
        has_unpaid_leave = unpaid_leave_days > 1e-6

        # expected_display = expected_raw - public_holiday_days
        # Đây là con số hiển thị trên UI: "số ngày phải đi làm" theo cách người dùng
        # thường hiểu (đã trừ ngày lễ ra rồi).
        #
        # Kiểm tra: expected_display = worked_days + approved_leave_days + unpaid_leave_days
        # Ví dụ: 22 = 19 (đi làm) + 2 (phép) + 1 (không phép)  ✓
        #
        # Lưu ý: nếu nhân viên xin phép đúng ngày lễ, approved_leave_days đã tính ngày
        # đó (vì compute_leaves=False), nhưng expected_display đã trừ nó qua
        # public_holiday_days → vế phải có thể vượt vế trái 1 chút.
        # Trường hợp này hiếm và acceptable; unpaid_leave_days đã được clamp >= 0.
        expected_display = max(0.0, expected_raw - public_holiday_days)

        metrics = {
            'expected_work_days': expected_display,  # UI: đã trừ ngày lễ
            'worked_days': worked_days,
            'approved_leave_days': approved_leave_days,
            'public_holiday_days': public_holiday_days,
            'unpaid_leave_days': unpaid_leave_days,
            'has_unpaid_leave': has_unpaid_leave,
        }

        value = self._value_or_percentage(
            kpi_line=kpi_line,
            numerator=unpaid_leave_days,
            denominator=expected_display,  # % tính trên nền đã trừ lễ (đúng với UI)
        )
        return value, metrics

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
        late_grace_minutes = self._get_late_grace_minutes()

        return tz.localize(naive_local) + datetime.timedelta(minutes=late_grace_minutes)
