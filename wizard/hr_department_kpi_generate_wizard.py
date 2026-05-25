from markupsafe import Markup

from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrDepartmentKpiGenerateWizard(models.TransientModel):
    _name = "hr.department.kpi.generate.wizard"
    _description = "Generate Department Performance Evaluations"

    department_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        string="Department KPI Template",
        required=True,
        default=lambda self: self.env.context.get("default_department_kpi_id"),
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="department_kpi_id.department_id",
        readonly=True,
    )
    kpi_template_id = fields.Many2one(
        "hr.kpi.template",
        string="Employee KPI Template",
        help="KPI template to use for generating individual employee evaluations.",
    )
    period_id = fields.Many2one(
        related="department_kpi_id.period_id",
        string="KPI Period",
        store=True,
        readonly=False,
    )
    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)
    deadline = fields.Date(string="Deadline", required=True)

    @api.onchange("department_kpi_id")
    def _onchange_department_kpi_id(self):
        if self.department_kpi_id and self.department_id and self.period_id:
            kpi = self.env["hr.kpi.template"].search(
                [
                    ("department_kpi_id", "=", self.department_kpi_id.id),
                    ("department_id", "=", self.department_id.id),
                    ("period_id", "=", self.period_id.id),
                ],
                limit=1,
            )
            if not kpi:
                kpi = self.env["hr.kpi.template"].search(
                    [
                        ("department_id", "=", self.department_id.id),
                        ("period_id", "=", self.period_id.id),
                    ],
                    limit=1,
                )
            self.kpi_template_id = kpi

    @api.onchange("period_id")
    def _onchange_period_set_dates(self):
        if not self.period_id:
            return
        self.start_date = self.period_id.date_start
        self.end_date = self.period_id.date_end
        self.deadline = self.period_id.date_end + relativedelta(days=5)

    @api.constrains("start_date", "end_date")
    def _check_date_range(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.start_date > rec.end_date:
                raise ValidationError(_("Start Date must be before or equal to End Date."))

    def _employee_matches_kpi(self, employee, kpi):
        if not kpi:
            return False
        if kpi.department_id:
            return bool(employee.department_id and employee.department_id == kpi.department_id)
        return False

    def action_generate(self):
        self.ensure_one()
        if not self.department_kpi_id:
            raise ValidationError(_("Please select a Department KPI Template."))
        if not self.department_id:
            raise ValidationError(
                _("The Department KPI Template must have a Department assigned.")
            )
        if self.kpi_template_id and self.kpi_template_id.period_id != self.period_id:
            raise ValidationError(
                _("The Employee KPI Template period must match the selected Department KPI period.")
            )

        employees = self.env["hr.employee"].search(
            [("active", "=", True), ("department_id", "=", self.department_id.id)]
        )
        if not employees:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Warning",
                    "message": _("No active employees found in this department."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        DeptEvaluation = self.env["hr.department.performance.evaluation"]
        exists_dept_eval = DeptEvaluation.search(
            [
                ("department_id", "=", self.department_id.id),
                ("department_kpi_id", "=", self.department_kpi_id.id),
                ("period_id", "=", self.period_id.id),
                ("start_date", "=", self.start_date),
                ("end_date", "=", self.end_date),
            ],
            limit=1,
        )
        if exists_dept_eval:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "No new data",
                    "message": _("A department performance evaluation already exists for this period."),
                    "type": "danger",
                    "sticky": False,
                },
            }

        report = self.env["hr.performance.report"].sudo().create(
            {
                "period_id": self.period_id.id,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "deadline": self.deadline,
                "department_id": self.department_id.id,
                "employee_id": [(6, 0, employees.ids)],
            }
        )

        scratch_dept = DeptEvaluation.new(
            {
                "department_kpi_id": self.department_kpi_id.id,
                "period_id": self.period_id.id,
            }
        )
        dept_line_cmds = scratch_dept._prepare_evaluation_line_commands_from_template(
            self.department_kpi_id
        )
        dept_eval = DeptEvaluation.create(
            {
                "department_id": self.department_id.id,
                "department_kpi_id": self.department_kpi_id.id,
                "period_id": self.period_id.id,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "deadline": self.deadline,
                "performance_report_id": report.id,
                "evaluation_line_ids": dept_line_cmds,
            }
        )
        dept_eval_line_by_template_line = {
            line.department_kpi_line_id.id: line.id
            for line in dept_eval.evaluation_line_ids
            if line.department_kpi_line_id
        }

        count = 0
        individual_evals = self.env["hr.performance.evaluation"]
        if self.kpi_template_id:
            Evaluation = self.env["hr.performance.evaluation"]
            valid_employees = self.env["hr.employee"]
            for emp in employees:
                if self._employee_matches_kpi(emp, self.kpi_template_id):
                    exists = Evaluation.search(
                        [
                            ("employee_id", "=", emp.id),
                            ("kpi_id", "=", self.kpi_template_id.id),
                            ("period_id", "=", self.kpi_template_id.period_id.id),
                            ("start_date", "=", self.start_date),
                            ("end_date", "=", self.end_date),
                        ],
                        limit=1,
                    )
                    if not exists:
                        valid_employees |= emp

            for emp in valid_employees:
                scratch = Evaluation.new(
                    {
                        "kpi_id": self.kpi_template_id.id,
                        "period_id": self.kpi_template_id.period_id.id,
                    }
                )
                line_cmds = scratch._prepare_evaluation_line_commands_from_template(
                    self.kpi_template_id,
                    dept_eval_line_by_template_line=dept_eval_line_by_template_line,
                )
                evaluation = Evaluation.create(
                    {
                        "employee_id": emp.id,
                        "kpi_id": self.kpi_template_id.id,
                        "period_id": self.kpi_template_id.period_id.id,
                        "start_date": self.start_date,
                        "end_date": self.end_date,
                        "deadline": self.deadline,
                        "evaluation_line_ids": line_cmds,
                        "performance_report_id": report.id,
                        "dept_evaluation_id": dept_eval.id,
                    }
                )
                self.send_notification(emp, evaluation)
                individual_evals |= evaluation
                count += 1

        if individual_evals:
            individual_evals._compute_final_score()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Thành công",
                "message": _(
                    "Created 1 Department Evaluation and %(count)s Individual Evaluations for the %(period)s period."
                )
                % {"count": count, "period": self.period_id.name},
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def send_notification(self, emp, evaluation):
        if emp.user_id and emp.user_id.partner_id:
            period_str = self.period_id.name if self.period_id else ""
            start_str = self.start_date.strftime("%d/%m/%Y")
            end_str = self.end_date.strftime("%d/%m/%Y")
            base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
            record_url = (
                f"{base_url}/web#id={evaluation.id}&model=hr.performance.evaluation&view_type=form"
            )
            msg_body = _(
                """
                <div style="margin: 0; padding: 0;">
                    <p>Hello <b>%s</b>,</p>
                    <p>A new KPI evaluation has been created for you in the system.</p>
                    <ul>
                        <li><b>Evaluation Period:</b> %s</li>
                        <li><b>Standard Time:</b> From %s to %s</li>
                    </ul>
                    <p>Please click the button below to view details and complete your self-assessment (if applicable).</p>

                    <div style="margin-top: 20px; margin-bottom: 20px;">
                        <a href="%s" 
                           style="background-color: #714B67; padding: 10px 20px; color: #FFFFFF; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            View Evaluation
                        </a>
                    </div>
                </div>
                """
            ) % (emp.name, period_str, start_str, end_str, record_url)

            emp.message_post(
                body=Markup(msg_body),
                subject=_("[Notification] You have a new KPI evaluation"),
                partner_ids=[emp.user_id.partner_id.id],
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
