from odoo import models, fields, api


class HrDepartmentPerformanceEvaluation(models.Model):
    _name = 'hr.department.performance.evaluation'
    _description = 'Department Performance Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(compute='_compute_name', store=True)
    department_id = fields.Many2one('hr.department', required=True)
    department_kpi_id = fields.Many2one('hr.department.kpi', required=True)
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

    department_score = fields.Float(
        compute='_compute_department_score', store=True,
        help='α × dept_kpi_score + β × avg_individual_score'
    )
    
    department_level = fields.Selection([
        ('excellent', 'Excellent'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], compute='_compute_department_level', store=True)

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

    @api.depends('department_id', 'start_date', 'end_date')
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
        excellent = float(icp.get_param('custom_adecsol_hr_performance_evaluator.kpi_threshold_excellent', default='9') or 9.0)
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
