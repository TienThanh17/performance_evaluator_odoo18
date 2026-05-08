from odoo import models, fields, api


class HrDepartmentPerformanceEvaluation(models.Model):
    _name = 'hr.department.performance.evaluation'
    _description = 'Department Performance Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(compute='_compute_name', store=True)
    department_id = fields.Many2one('hr.department', required=True)
    department_kpi_id = fields.Many2one('hr.department.kpi', required=True, string='Department KPI')
    performance_report_id = fields.Many2one('hr.performance.report', ondelete='cascade')

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    deadline = fields.Date()

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True)

    evaluation_line_ids = fields.One2many(
        'hr.department.evaluation.line', 'evaluation_id'
    )

    dept_kpi_score = fields.Float(
        compute='_compute_dept_kpi_score', store=True,
        help='Điểm từ KPI riêng phòng ban (trung bình có trọng số các line)'
    )
    avg_individual_score = fields.Float(
        compute='_compute_avg_individual_score', store=True,
        help='TB performance_score của nhân sự đã approved trong kỳ'
    )
    # avg_individual_score = fields.Float(
    #     related='performance_report_id.individual_score',
    #     help='TB performance_score của nhân sự đã approved trong kỳ',
    # )
    alpha = fields.Float(related='department_kpi_id.alpha')
    beta = fields.Float(related='department_kpi_id.beta')

    department_score = fields.Float(
        compute='_compute_department_score', store=True,
        help='α × dept_kpi_score + β × avg_individual_score'
    )

    department_level = fields.Selection([
        ('excellent', 'Excellent'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], compute='_compute_department_level', store=True)

    has_binary_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_rating_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)
    has_score_kpi = fields.Boolean(compute="_compute_kpi_types", store=False)

    @api.depends("evaluation_line_ids.kpi_type")
    def _compute_kpi_types(self):
        for rec in self:
            kpi_types = rec.evaluation_line_ids.mapped('kpi_type')
            rec.has_binary_kpi = 'binary' in kpi_types
            rec.has_rating_kpi = 'rating' in kpi_types
            rec.has_score_kpi = 'score' in kpi_types

    @api.depends('department_id', 'start_date', 'end_date')
    def _compute_name(self):
        for rec in self:
            if rec.department_id and rec.start_date and rec.end_date:
                rec.name = f"KPI-{rec.department_id.name} ({rec.start_date} to {rec.end_date})"
            else:
                rec.name = "New Dept KPI"

    @api.depends('evaluation_line_ids.final_score', 'evaluation_line_ids.weight')
    def _compute_dept_kpi_score(self):
        for rec in self:
            lines = rec.evaluation_line_ids.filtered(lambda l: not l.is_section)
            total_weight = sum(lines.mapped('weight'))
            if total_weight > 0:
                rec.dept_kpi_score = sum(l.final_score * l.weight for l in lines) / total_weight
            else:
                rec.dept_kpi_score = 0.0

    @api.depends('department_id', 'start_date', 'end_date', 'performance_report_id')
    def _compute_avg_individual_score(self):
        for rec in self:
            if not rec.department_id or not rec.start_date or not rec.end_date:
                rec.avg_individual_score = 0.0
                continue

            evals = self.env['hr.performance.evaluation'].search([
                ('state', '=', 'approved'),
                ('employee_id.department_id', '=', rec.department_id.id),
                ('start_date', '>=', rec.start_date),
                ('end_date', '<=', rec.end_date),
            ])
            if evals:
                rec.avg_individual_score = sum(evals.mapped('performance_score')) / len(evals)
            else:
                rec.avg_individual_score = 0.0

    @api.depends('dept_kpi_score', 'avg_individual_score', 'department_kpi_id.alpha', 'department_kpi_id.beta')
    def _compute_department_score(self):
        for rec in self:
            alpha = rec.department_kpi_id.alpha if rec.department_kpi_id else 0.5
            beta = rec.department_kpi_id.beta if rec.department_kpi_id else 0.5
            rec.department_score = (alpha * rec.dept_kpi_score) + (beta * rec.avg_individual_score)

    @api.depends('department_score')
    def _compute_department_level(self):
        # Giả sử thresholds 9 = Excellent, 5 = Pass giống như cá nhân
        icp = self.env['ir.config_parameter'].sudo()
        excellent = float(
            icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent', default='9') or 9.0)
        passed = float(icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_pass', default='5') or 5.0)

        for rec in self:
            if rec.department_score >= excellent:
                rec.department_level = 'excellent'
            elif rec.department_score >= passed:
                rec.department_level = 'pass'
            else:
                rec.department_level = 'fail'

    def action_compute_auto_kpi(self):
        engine = self.env['hr.kpi.engine']
        for evaluation in self:
            if not evaluation.department_id or not evaluation.department_kpi_id:
                continue
            for line in evaluation.evaluation_line_ids:
                if not line.is_auto or line.is_section:
                    continue
                actual = engine.compute_for_department(
                    evaluation.department_id,
                    line.department_kpi_line_id,
                    evaluation.start_date,
                    evaluation.end_date
                )
                line.actual = actual

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    @api.onchange("department_kpi_id")
    def _onchange_kpi_id(self):
        # if not self.kpi_id:
        #     return
        #
        #     # GUARD: Chỉ rebuild khi kpi_id thực sự được user thay đổi.
        #     # _origin.kpi_id là giá trị đang lưu trong DB.
        #     # Nếu bằng nhau → onchange đang fire spuriously (lúc save/reload) → bỏ qua.
        # if self._origin.kpi_id and self._origin.kpi_id.id == self.kpi_id.id:
        #     return

        if self.department_kpi_id:
            self.evaluation_line_ids = (
                self._prepare_evaluation_line_commands_from_template(
                    self.department_kpi_id
                )
            )

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _prepare_evaluation_line_commands_from_template(self, kpi):
        """Build one2many commands for evaluation_line_ids from KPI template lines.

        - Preserves ordering via sequence.
        - Preserves section/note lines.
        """
        self.ensure_one()
        if not kpi:
            return []

        template_lines = kpi.kpi_line_ids.sorted(lambda l: (l.sequence or 0, l._origin.id or 0, l.id or 0))

        # Sử dụng : list[tuple] để Type Checker không hiểu lầm là danh sách chỉ chứa tuple 3 số nguyên.
        # fields.Command.clear() tương đương với lệnh (5, 0, 0) để xóa sạch các dòng cũ trước khi thêm mới.
        commands: list[tuple] = [fields.Command.clear()]
        for line in template_lines:
            # Kiểm tra nếu dòng hiện tại là một Section (tiêu đề nhóm) dựa trên thuộc tính.
            is_section = bool(getattr(line, "is_section", False))
            if is_section:
                # fields.Command.create({...}) tương đương với lệnh (0, 0, {...}) để tạo mới một dòng.
                commands.append(
                    fields.Command.create(
                        {
                            "department_kpi_line_id": line.id,
                            # "sequence": line.sequence,
                            "is_section": True,
                            "name": line.name,
                            "description": False,
                            # Safe defaults for required KPI fields on section rows
                            "kpi_type": "quantitative",
                            "target_type": "value",
                            "direction": "higher_better",
                            "target": 0.0,
                            "weight": 0.0,
                            "is_auto": False,
                            "data_source": "manual",
                        }
                    )
                )
                continue

            commands.append(
                fields.Command.create(
                    {
                        "department_kpi_line_id": line.id,
                        # "sequence": line.sequence,
                        "name": line.name,
                        "description": getattr(line, "description", False),
                        "kpi_type": line.kpi_type,
                        "target_type": line.target_type,
                        "direction": line.direction,
                        "target": line.target,
                        "weight": line.weight,
                        "is_auto": bool(line.is_auto),
                        "data_source": line.data_source,
                    }
                )
            )
        return commands

    def get_dashboard_data(self):
        self.ensure_one()

        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', self.department_id.id),
            ('active', '=', True),
        ], order='name asc')

        result = {
            'department_name': self.department_id.name or '',
            'manager_name': (
                self.department_id.manager_id.name
                if self.department_id.manager_id else '—'
            ),
            'employee_count': len(employees),
            'department_score': round(float(self.department_score or 0.0), 2),
            'department_level': self.department_level or 'fail',
            'employees': [{'id': e.id, 'name': e.name} for e in employees],
            'task_summary_by_employee': self._dashboard_task_summary_by_employee(),
            'project_progress': self._dashboard_project_progress(),
            'attendance_count': self._dashboard_attendance_count(),
            'bug_count_by_employee': self._dashboard_bug_count_by_employee(),
        }
        return result

    def _dashboard_task_summary_by_employee(self):
        """
        Trả về task summary (total/done/pending) theo từng nhân viên
        trong cùng phòng ban, cùng kỳ đánh giá.

        Returns:
            list[dict]: [
                {
                    'employee_id': int,
                    'name': str,
                    'total': int,
                    'done': int,
                    'pending': int,
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        # Lấy tất cả nhân viên trong phòng ban
        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', self.department_id.id),
            ('active', '=', True),
        ])
        if not employees:
            return []

        user_ids = employees.mapped('user_id').ids
        if not user_ids:
            return []

        Task = self.env['project.task'].sudo()

        # Query tất cả tasks trong kỳ một lần (tránh N+1 queries)
        all_tasks = Task.search([
            ('user_ids', 'in', user_ids),
            ('date_deadline', '>=', self.start_date),
            ('date_deadline', '<=', self.end_date),
            ('project_id', '!=', False),
        ])

        # Group tasks by user_id
        # Một task có thể assign nhiều user → đếm cho từng user
        tasks_by_user = {}
        for task in all_tasks:
            for user in task.user_ids:
                if user.id not in tasks_by_user:
                    tasks_by_user[user.id] = {'total': [], 'done': []}
                tasks_by_user[user.id]['total'].append(task)
                if task.stage_id and task.stage_id.is_done_stage:
                    tasks_by_user[user.id]['done'].append(task)

        result = []
        for emp in employees:
            if not emp.user_id:
                continue
            uid = emp.user_id.id
            bucket = tasks_by_user.get(uid, {'total': [], 'done': []})
            total = len(bucket['total'])
            done = len(bucket['done'])
            result.append({
                'employee_id': emp.id,
                'name': emp.name,
                'total': total,
                'done': done,
                'pending': total - done,
            })

        # Sắp xếp theo tên
        result.sort(key=lambda x: x['name'])
        return result

    def _dashboard_project_progress(self):
        """
        Tính % tiến độ các dự án mà nhân viên trong phòng ban tham gia,
        trong kỳ đánh giá (dựa trên date_deadline của task).

        Returns:
            list[dict]: [
                {
                    'project_id': int,
                    'name': str,
                    'total_tasks': int,
                    'done_tasks': int,
                    'progress_pct': float,  # 0.0 - 100.0
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        # Lấy user_ids của nhân viên trong phòng ban
        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', self.department_id.id),
            ('active', '=', True),
        ])
        user_ids = employees.mapped('user_id').ids
        if not user_ids:
            return []

        # Lấy tất cả tasks trong kỳ có assign nhân viên phòng ban
        Task = self.env['project.task'].sudo()
        # NOTE: hiện tại đang lấy tất cả tasks có project_id khác False, sau đó sẽ lọc theo project_id và tính toán tiến độ.
        all_tasks = Task.search([
            # ('user_ids', 'in', user_ids),
            # ('date_deadline', '>=', self.start_date),
            # ('date_deadline', '<=', self.end_date),
            ('project_id', '!=', False),
        ])
        if not all_tasks:
            return []

        # Group theo project
        tasks_by_project = {}
        for task in all_tasks:
            pid = task.project_id.id
            pname = task.project_id.name
            if pid not in tasks_by_project:
                tasks_by_project[pid] = {'name': pname, 'total': 0, 'done': 0}
            tasks_by_project[pid]['total'] += 1
            if task.stage_id and task.stage_id.is_done_stage:
                tasks_by_project[pid]['done'] += 1

        result = []
        for pid, info in tasks_by_project.items():
            total = info['total']
            done = info['done']
            result.append({
                'project_id': pid,
                'name': info['name'],
                'total_tasks': total,
                'done_tasks': done,
                'progress_pct': round(done / total * 100, 1) if total > 0 else 0.0,
            })

        # Sắp xếp theo % giảm dần
        result.sort(key=lambda x: x['progress_pct'], reverse=True)
        return result

    def _dashboard_attendance_count(self):
        """
        Đếm số lần chấm công (số attendance record) theo từng nhân viên
        trong kỳ đánh giá.

        Returns:
            list[dict]: [
                {
                    'employee_id': int,
                    'name': str,
                    'attendance_count': int,
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', self.department_id.id),
            ('active', '=', True),
        ], order='name asc')
        if not employees:
            return []

        # Query tất cả attendance trong kỳ, 1 lần duy nhất
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_in', '>=', str(self.start_date) + ' 00:00:00'),
            ('check_in', '<=', str(self.end_date) + ' 23:59:59'),
        ])

        # Group by employee_id
        count_by_emp = {}
        for att in attendances:
            eid = att.employee_id.id
            count_by_emp[eid] = count_by_emp.get(eid, 0) + 1

        result = []
        for emp in employees:
            result.append({
                'employee_id': emp.id,
                'name': emp.name,
                'attendance_count': count_by_emp.get(emp.id, 0),
            })

        return result

    def _dashboard_bug_count_by_employee(self):
        """
        Đếm số task có task_type = 'bug' được assign cho từng nhân viên
        trong kỳ đánh giá.

        Returns:
            list[dict]: [
                {
                    'employee_id': int,
                    'name': str,
                    'bug_count': int,
                },
                ...
            ]
        """
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.department_id:
            return []

        employees = self.env['hr.employee'].sudo().search([
            ('department_id', '=', self.department_id.id),
            ('active', '=', True),
        ], order='name asc')
        if not employees:
            return []

        user_ids = employees.mapped('user_id').ids
        if not user_ids:
            return []

        # Query 1 lần tất cả bug tasks trong kỳ
        bug_tasks = self.env['project.task'].sudo().search([
            # ('task_type', '=', 'bug'),
            ('user_ids', 'in', user_ids),
            ('date_deadline', '>=', self.start_date),
            ('date_deadline', '<=', self.end_date),
            ('project_id', '!=', False),
        ])

        # Group by user_id — 1 task nhiều user → đếm cho từng user
        count_by_user = {}
        for task in bug_tasks:
            for user in task.user_ids:
                count_by_user[user.id] = count_by_user.get(user.id, 0) + 1

        result = []
        for emp in employees:
            if not emp.user_id:
                continue
            result.append({
                'employee_id': emp.id,
                'name': emp.name,
                'bug_count': count_by_user.get(emp.user_id.id, 0),
            })

        return result
