from odoo import models, fields, api
from odoo.exceptions import ValidationError


class KPIline(models.Model):
    _name = 'hr.kpi.line'
    _description = 'KPI Line for Job Position'
    _order = 'sequence, id'

    # New simplified section flag (requested).
    is_section = fields.Boolean(
        string="Is Section",
        default=False,
        help="Enable this to make the line a Section header (used to group KPI lines). Sections do not affect scoring.",
    )

    # Backward-compatible technical field used by section_and_note_one2many.
    # We keep it so existing views/widgets can still work.
    display_type = fields.Selection(
        selection=[
            ('line_section', 'Section'),
            ('line_note', 'Note'),
        ],
        default=False,
        compute="_compute_display_type",
        # inverse="_inverse_display_type",
        store=True,
        readonly=False,
        help="Technical field for section/note lines. Derived from is_section.",
    )
    sequence = fields.Integer(
        default=10,
        help="Controls the order of lines in the KPI template (drag & drop).",
    )

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
    weight = fields.Float(
        string='Weight',
        default=10.0,
        help="Weight of this KPI in the overall evaluation (higher weight has more impact).",
    )
    kpi_id = fields.Many2one(
        'hr.kpi',
        string='KPI',
        required=True,
        help="The KPI template that this line belongs to.",
    )
    serial_number = fields.Char(
        "SN",
        compute='_compute_serial_number',
        store=True,
        help="Auto-generated row number for display (does not affect scoring).",
    )
    description = fields.Html(
        string="Description",
        sanitize=True,
        help="Additional guidance for employees/managers about how this KPI should be evaluated.",
    )

    data_source = fields.Selection(
        selection=[
            ('manual', 'Manual'),
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
        help="Enable to let the system automatically compute Actual values from the selected Data Source.",
    )
    is_special_scoring = fields.Boolean(
        string="Special Scoring",
        compute="_compute_is_special_scoring",
        store=False,
        help="Technical flag: True when scoring uses a custom rule (not Target vs Actual ratio).",
    )

    is_monthly = fields.Boolean(
        string="Monthly",
        default=True,
        help="Include this KPI line when generating Monthly evaluations.",
    )
    is_quarterly = fields.Boolean(
        string="Quarterly",
        default=False,
        help="Include this KPI line when generating Quarterly evaluations.",
    )
    is_half_yearly = fields.Boolean(
        string="Half-Yearly",
        default=False,
        help="Include this KPI line when generating Half-Yearly evaluations.",
    )
    is_yearly = fields.Boolean(
        string="Yearly",
        default=False,
        help="Include this KPI line when generating Yearly evaluations.",
    )

    @api.depends('kpi_type', 'data_source')
    def _compute_is_special_scoring(self):
        special_sources = {'late_days', 'attendance_full'}
        for rec in self:
            rec.is_special_scoring = bool(
                rec.kpi_type == 'quantitative' and (rec.data_source in special_sources)
            )

    @api.depends('target', 'target_type', 'kpi_type')
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
                rec.target_display = f"{(rec.target or 0.0):g}"

    @api.depends('kpi_id', 'kpi_id.kpi_line_ids')
    def _compute_serial_number(self):
        """Display a stable row number per KPI template.

        Odoo requires compute methods to exist; older versions might have tolerated
        missing compute targets in some situations, but Odoo 18 will fail hard.
        """
        for line in self:
            if not line.kpi_id:
                line.serial_number = False
                continue
            if line.display_type or line.is_section:
                line.serial_number = False
                continue

            # Order by sequence and a stable, comparable tiebreaker.
            # Note: during onchanges, records may be NewId() objects (unsaved) -> not comparable.
            ordered = line.kpi_id.kpi_line_ids.filtered(lambda l: not l.display_type and not l.is_section)
            ordered = ordered.sorted(lambda l: (l.sequence or 0, l._origin.id or 0, l.id or 0))

            # Find index by record identity (works for new records too)
            idx = 1
            for rec in ordered:
                if rec == line:
                    line.serial_number = str(idx)
                    break
                idx += 1
            else:
                line.serial_number = False

    @api.constrains('kpi_type', 'target')
    def _check_numeric_target(self):
        for rec in self:
            if rec.display_type or rec.is_section:
                continue
            if rec.kpi_type == 'quantitative' and (rec.target or 0.0) < 0.0:
                raise ValidationError("For Quantitative KPI type, Target must be greater than or equal 0.")

    @api.depends('is_section')
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = 'line_section' if rec.is_section else False

    @api.model_create_multi
    def create(self, vals_list):
        # Ensure section rows remain sections even if clients only send display_type.
        # Also append new lines to the end by setting sequence to max(sequence)+10
        # for the given KPI template when sequence is not explicitly provided.
        seq_step = 10

        # Pre-group by kpi_id to minimize queries
        kpi_ids = {vals.get('kpi_id') for vals in vals_list if vals.get('kpi_id')}
        max_seq_by_kpi = {}
        if kpi_ids:
            lines = self.search_read(
                [('kpi_id', 'in', list(kpi_ids))],
                ['kpi_id', 'sequence'],
                order='sequence desc',
            )
            for l in lines:
                kid = l['kpi_id'][0] if l.get('kpi_id') else False
                if kid and kid not in max_seq_by_kpi:
                    max_seq_by_kpi[kid] = l.get('sequence') or 0

        for vals in vals_list:
            if vals.get('display_type') and 'is_section' not in vals:
                vals['is_section'] = True

            kpi_id = vals.get('kpi_id')
            if kpi_id and not vals.get('sequence'):
                current_max = max_seq_by_kpi.get(kpi_id)
                if current_max is None:
                    current_max = 0
                vals['sequence'] = current_max + seq_step
                max_seq_by_kpi[kpi_id] = vals['sequence']

        return super().create(vals_list)

    def write(self, vals):
        # Keep consistency for section rows on update.
        if vals.get('display_type') and 'is_section' not in vals:
            vals = dict(vals, is_section=True)
        return super().write(vals)

    def _inverse_display_type(self):
        for rec in self:
            # Any display_type means it's a section/note
            rec.is_section = bool(rec.display_type)
