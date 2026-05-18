from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class KPIline(models.Model):
    _name = 'hr.kpi.line'
    _description = 'KPI Line for Job Position'
    _order = 'sequence, id'
    _rec_name = 'key_performance_area'

    key_performance_area = fields.Char(
        string="Key Performance Area",
        required=True,
        help="The KPI title (or the section header name if this is a Section).",
    )
    kpi_type = fields.Selection(
        selection=[
            ('quantitative', 'Quantitative'),
            ('binary', 'Binary'),
            ('rating', 'Rating'),
            ('score', 'Score'),
        ],
        string='KPI Type',
        default='quantitative',
        required=True,
        help="How this KPI is evaluated: Quantitative (Target vs Actual), Binary (Yes/No), Rating (0–5), or Score (0–10).",
    )

    target_type = fields.Selection(
        selection=[
            ('value', 'Value'),
            ('percentage', 'Percentage'),
        ],
        string='Target Type',
        required=False,
        default='value',
        help="Controls the unit for Target/Actual in evaluations. If Percentage, values are 0–100.",
    )
    direction = fields.Selection(
        selection=[
            ('higher_better', 'Higher is Better'),
            ('lower_better', 'Lower is Better'),
        ],
        string='Direction',
        default='higher_better',
        required=False,
        help="For Quantitative KPIs: choose whether a higher actual value is better or a lower actual value is better.",
    )
    target = fields.Float(
        string='Target',
        default=0.0,
        help="Target value to be achieved for Quantitative KPIs. Use the Target Type to indicate Value or Percentage.",
    )
    target_display = fields.Char(string="Target", compute="_compute_display", store=False)
    unit_label = fields.Char(
        string="Unit",
        default="",
        help="Display unit for Target/Actual, e.g. %, tasks, days, score.",
    )
    weight = fields.Float(
        string='Weight',
        default=10.0,
        help="Weight of this KPI in the overall evaluation (higher weight has more impact).",
    )
    kpi_id = fields.Many2one(
        'hr.kpi',
        string='KPI',
        required=True,
        ondelete='cascade',
    )
    parent_dept_kpi_id = fields.Many2one(
        'hr.department.kpi',
        string='Parent Department KPI Template',
        related='kpi_id.department_kpi_id',
        store=False,
    )
    # Thêm trường liên kết giữa Line Nhân viên và Line Phòng ban
    parent_dept_line_id = fields.Many2one(
        'hr.department.kpi.line',
        string='Thuộc chỉ tiêu Phòng ban',
        # Trường này sẽ được lọc trực tiếp trên giao diện XML bằng thuộc tính parent
    )
    description = fields.Html(
        string="Description",
        sanitize=True,
        help="Additional guidance for employees/managers about how this KPI should be evaluated.",
    )

    data_source = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('done_task', 'Done Task'),
            ('task_on_time', 'Task On Time'),
            ('late_days', 'Late Days'),
            ('attendance_full', 'Attendance Full'),
        ],
        string='Data Source',
        default='manual',
        required=False,
        help="Where the system gets the Actual value from when Auto Compute is enabled.",
    )
    is_auto = fields.Boolean(
        string='Auto Compute',
        default=False,
        compute='_compute_auto',
        store=True,
        help="Enable to let the system automatically compute Actual values from the selected Data Source.",
    )
    is_special_scoring = fields.Boolean(
        string="Special Scoring",
        compute="_compute_is_special_scoring",
        store=False,
        help="Technical flag: True when scoring uses a custom rule (not Target vs Actual ratio).",
    )

    is_section = fields.Boolean(default=False)
    display_type = fields.Selection(
        selection=[
            ('line_section', 'Section'),
            ('line_note', 'Note'),
        ],
        default=False,
        compute="_compute_display_type",
        store=True,
        readonly=False,
        help="Technical field for section/note lines. Derived from is_section.",
    )
    sequence = fields.Integer(default=10)

    @api.depends('kpi_type', 'data_source')
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(rec.kpi_type == 'quantitative' and rec.data_source != 'manual')

    @api.depends('kpi_type', 'data_source')
    def _compute_is_special_scoring(self):
        special_sources = {'late_days', 'attendance_full'}
        for rec in self:
            rec.is_special_scoring = bool(
                rec.kpi_type == 'quantitative' and (rec.data_source in special_sources)
            )

    def _get_default_unit_label(self):
        self.ensure_one()
        if self.target_type == 'percentage':
            return '%'
        return {
            'done_task': 'task',
            'task_on_time': '%',
            'late_days': 'ngày',
            'attendance_full': 'ngày',
        }.get(self.data_source or 'manual', '')

    @api.onchange('target_type', 'data_source')
    def _onchange_unit_label(self):
        for rec in self:
            rec.unit_label = rec._get_default_unit_label()

    @api.depends('target', 'target_type', 'kpi_type', 'unit_label')
    def _compute_display(self):
        for rec in self:
            if rec.display_type or rec.is_section:
                rec.target_display = ''
                continue
            if rec.kpi_type != 'quantitative':
                rec.target_display = ''
                continue

            if rec.target_type == 'percentage':
                # hiển thị 90% thay vì 90.0
                rec.target_display = f"{(rec.target or 0.0):g}%"
            else:
                target = f"{(rec.target or 0.0):g}"
                rec.target_display = f"{target} {rec.unit_label}" if rec.unit_label else target

    @api.depends('is_section')
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = 'line_section' if rec.is_section else False

    @api.constrains('kpi_type', 'target')
    def _check_numeric_target(self):
        for rec in self:
            if rec.display_type or rec.is_section:
                continue
            if rec.kpi_type == 'quantitative' and (rec.target or 0.0) < 0.0:
                raise ValidationError("For Quantitative KPI type, Target must be greater than or equal 0.")

    @api.constrains('parent_dept_line_id', 'parent_dept_kpi_id', 'is_section')
    def _check_parent_dept_line(self):
        for rec in self:
            parent_line = rec.parent_dept_line_id
            if not parent_line:
                continue
            if rec.is_section or rec.display_type:
                raise ValidationError(_("Section lines cannot be linked to department KPI lines."))
            if parent_line.is_section:
                raise ValidationError(_("Please select a KPI item, not a department section."))
            if not rec.parent_dept_kpi_id:
                raise ValidationError(_("Please select a parent Department KPI Template before linking department KPI lines."))
            if parent_line.department_kpi_id != rec.parent_dept_kpi_id:
                raise ValidationError(_("The selected department KPI line must belong to the parent Department KPI Template."))

    def write(self, vals):
        # Keep consistency for section rows on update.
        if vals.get('display_type') and 'is_section' not in vals:
            vals = dict(vals, is_section=True)
        return super().write(vals)

    def action_open_popup(self):
        self.ensure_one()
        return {
            'name': _('Edit KPI Line'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.kpi.line',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('custom_adecsol_hr_performance_evaluator.view_hr_kpi_line_form_popup').id,
            'target': 'new',
        }
