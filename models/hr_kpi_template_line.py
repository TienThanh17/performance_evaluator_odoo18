from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .kpi_type_utils import (
    KPI_TYPE_SELECTION,
    MANUAL_SCORING_TYPE_SELECTION,
    NORMALIZED_3P_PILLAR_CODES,
    P3_PILLAR_CODES,
    get_manual_scoring_type_required_message,
)

WEIGHT_TOLERANCE = 0.0001
SEQUENCE_STEP = 10


class HrKpiTemplateLine(models.Model):
    _name = "hr.kpi.template.line"
    _description = "Employee KPI Template Line"
    _order = "sequence, id"
    _rec_name = "key_performance_area"

    key_performance_area = fields.Char(
        string="Key Performance Area",
        required=True,
    )
    kpi_type = fields.Selection(
        KPI_TYPE_SELECTION,
        string="KPI Type",
        default="auto",
        required=True,
    )
    manual_scoring_type = fields.Selection(
        MANUAL_SCORING_TYPE_SELECTION,
        string="Manual Scoring Type",
    )
    target = fields.Float(string="Target", default=0.0)
    target_display = fields.Char(string="Target", compute="_compute_display")
    unit = fields.Many2one(
        "hr.kpi.unit",
        string="Unit",
        ondelete="restrict",
    )
    weight = fields.Float(string="Weight", default=10.0)
    kpi_id = fields.Many2one(
        "hr.kpi.template",
        string="KPI Template",
        required=True,
        ondelete="cascade",
    )
    parent_dept_kpi_id = fields.Many2one(
        "hr.department.kpi.template",
        string="Parent Department KPI Template",
        related="kpi_id.department_kpi_id",
        store=False,
    )
    parent_dept_line_id = fields.Many2one(
        "hr.department.kpi.template.line",
        string="Parent Department KPI",
        help="Department KPI template line linked to this employee KPI line.",
    )
    pillar_id = fields.Many2one(
        "hr.evaluation.pillar",
        string="Pillar",
        ondelete="restrict",
    )
    pillar_code = fields.Selection(
        related="pillar_id.code",
        string="Pillar Code",
        store=True,
        readonly=True,
    )
    parent_line_id = fields.Many2one(
        "hr.kpi.template.line",
        string="Parent Line",
        ondelete="set null",
        index=True,
        domain="[('kpi_id', '=', kpi_id), ('pillar_id', '=', pillar_id), ('id', '!=', id), ('is_section', '=', True)]",
    )
    child_line_ids = fields.One2many(
        "hr.kpi.template.line",
        "parent_line_id",
        string="Child Lines",
    )
    score_scale_base_override = fields.Float(
        string="Score Scale Base Override",
        help="Optional native score scale for this line, for example 100, 10, or 5. Leave empty to use the global KPI score scale.",
    )
    score_max_display = fields.Char(
        string="Max Score",
        compute="_compute_score_max_display",
        store=False,
    )
    description = fields.Html(string="Description", sanitize=True)
    data_source_id = fields.Many2one(
        "hr.kpi.data.source",
        string="Data Source",
        ondelete="set null",
    )
    scoring_formula_id = fields.Many2one(
        "hr.kpi.scoring.formula",
        string="Scoring Formula",
        ondelete="restrict",
        help="Scoring formula applied to this KPI line.",
    )
    scoring_formula_type = fields.Selection(
        related="scoring_formula_id.formula_type",
        string="Scoring Formula Type",
        store=False,
        readonly=True,
    )
    violation_threshold = fields.Integer(
        string="Violation Threshold",
        default=0,
        help="For P3 KPI lines, a violation count above this threshold triggers wipeout for the whole branch.",
    )
    is_auto = fields.Boolean(
        string="Auto Compute",
        compute="_compute_auto",
        store=True,
    )
    is_special_scoring = fields.Boolean(
        string="Special Scoring",
        compute="_compute_is_special_scoring",
        store=False,
    )
    is_section = fields.Boolean(default=False)
    display_type = fields.Selection(
        [
            ("line_section", "Section"),
            ("line_note", "Note"),
        ],
        default=False,
        compute="_compute_display_type",
        store=True,
        readonly=False,
    )
    sequence = fields.Integer(default=10)

    # Resolve the pillar configured by the current tab context.
    def _get_default_pillar_from_context(self):
        pillar_code = (
            (self.env.context.get("default_pillar_code") or "").strip().lower()
        )
        if not pillar_code:
            return self.env["hr.evaluation.pillar"]
        return self.env["hr.evaluation.pillar"].search(
            [("code", "=", pillar_code)],
            limit=1,
        )

    # Prefill pillar_id so popup and inline creation inherit the tab pillar.
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if defaults.get("pillar_id"):
            return defaults

        default_pillar = self._get_default_pillar_from_context()
        if default_pillar:
            defaults["pillar_id"] = default_pillar.id
        return defaults

    # Compute whether the template line can auto-fill its actual value from a data source.
    @api.depends("kpi_type", "data_source_id")
    def _compute_auto(self):
        for rec in self:
            rec.is_auto = bool(rec.kpi_type == "auto" and rec.data_source_id)

    # Compute the score scale hint shown next to manual score inputs.
    @api.depends("kpi_type", "manual_scoring_type", "score_scale_base_override")
    def _compute_score_max_display(self):
        for rec in self:
            if (
                rec.kpi_type == "manual"
                and rec.manual_scoring_type == "score"
                and rec.score_scale_base_override > 0
            ):
                rec.score_max_display = f"/ {rec.score_scale_base_override:g} pts"
            else:
                rec.score_max_display = ""

    # Flag template lines that use non-linear auto scoring formulas.
    @api.depends("kpi_type", "scoring_formula_id", "scoring_formula_id.formula_type")
    def _compute_is_special_scoring(self):
        for rec in self:
            effective_formula_type = (
                rec.scoring_formula_id.formula_type if rec.scoring_formula_id else False
            )
            rec.is_special_scoring = bool(
                rec.kpi_type == "auto"
                and effective_formula_type
                and effective_formula_type != "linear"
            )

    # Resolve the default display unit from the selected data source.
    def _get_unit_by_code(self, code):
        return self.env["hr.kpi.unit"].search([("code", "=", code)], limit=1)

    # Use the unit code as the source of truth for percentage KPI lines.
    def _is_percent_unit(self):
        self.ensure_one()
        return (self.unit.code or "") == "percent" if self.unit else False

    # Reuse the data source unit mapping when the unit is not entered manually.
    def _get_default_unit(self):
        self.ensure_one()
        code = self.data_source_id.get_unit_id() if self.data_source_id else False
        return self._get_unit_by_code(code) if code else False

    # Refresh the unit when the data source changes.
    @api.onchange("data_source_id")
    def _onchange_unit(self):
        for rec in self:
            if rec.data_source_id:
                rec.unit = rec._get_default_unit()

    # Return the formula configured on the template line.
    def get_effective_formula(self):
        self.ensure_one()
        return self.scoring_formula_id or False

    # Format the target preview only for auto KPI lines.
    @api.depends("target", "kpi_type", "unit", "unit.code", "unit.name", "is_section")
    def _compute_display(self):
        for rec in self:
            if rec.display_type or rec.is_section or rec.kpi_type != "auto":
                rec.target_display = ""
                continue
            if rec._is_percent_unit():
                rec.target_display = f"{(rec.target or 0.0):g}%"
            else:
                target = f"{(rec.target or 0.0):g}"
                unit_name = rec.unit.name if rec.unit else ""
                rec.target_display = f"{target} {unit_name}" if unit_name else target

    # Keep the technical display type aligned with the section flag.
    @api.depends("is_section")
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = "line_section" if rec.is_section else False

    # Build the hierarchy scope key so resequencing stays inside one template pillar tab.
    def _get_sequence_scope_key(self):
        self.ensure_one()
        return (self.kpi_id.id or False, self.pillar_id.id or False)

    # Convert a scope key back into the domain used to fetch the flat tree scope.
    @api.model
    def _get_sequence_scope_domain_from_key(self, scope_key):
        kpi_id, pillar_id = scope_key or (False, False)
        if not kpi_id:
            return [("id", "=", False)]
        return [
            ("kpi_id", "=", kpi_id),
            ("pillar_id", "=", pillar_id or False),
        ]

    # Collect the current scope keys for every line in the recordset.
    def _get_sequence_scope_keys(self):
        scope_keys = []
        for rec in self:
            # Skip incomplete in-memory rows that do not belong to a template yet.
            if not rec.kpi_id:
                continue
            scope_keys.append(rec._get_sequence_scope_key())
        return scope_keys

    # Fetch every line that belongs to the same hierarchy scope as the current line.
    def _get_sequence_scope_lines(self):
        self.ensure_one()
        return self.search(
            self._get_sequence_scope_domain_from_key(self._get_sequence_scope_key()),
            order="sequence, id",
        )

    # Group scope lines by direct parent so preorder traversal stays deterministic.
    def _get_children_map(self, scope_lines):
        children_map = {}
        for line in scope_lines.sorted(lambda rec: (rec.sequence or 0, rec.id or 0)):
            # Keep children grouped by their direct parent id for sibling-only reordering.
            parent_id = line.parent_line_id.id or False
            children_map.setdefault(parent_id, []).append(line)
        return children_map

    # Return the whole subtree of the current line in preorder inside its own scope.
    def _get_subtree_lines(self, scope_lines=None):
        self.ensure_one()
        scope_lines = scope_lines or self._get_sequence_scope_lines()
        if not scope_lines or self not in scope_lines:
            return self.browse()

        # Reuse the scope child map so descendants stay in visible preorder.
        children_map = self._get_children_map(scope_lines)
        ordered_ids = []

        def _visit(line):
            # Add the current line before its children to preserve preorder.
            ordered_ids.append(line.id)
            for child in children_map.get(line.id, []):
                _visit(child)

        _visit(self)
        return self.browse(ordered_ids)

    # Return all direct siblings that share the same direct parent inside the scope.
    def _get_same_parent_siblings(self, scope_lines=None):
        self.ensure_one()
        scope_lines = scope_lines or self._get_sequence_scope_lines()
        parent_id = self.parent_line_id.id or False
        return scope_lines.filtered(
            lambda line: (line.parent_line_id.id or False) == parent_id
        ).sorted(lambda line: (line.sequence or 0, line.id or 0))

    # Return the flat hierarchy order for one scope using sibling sequence as the source of truth.
    def _get_hierarchy_ordered_lines(self, scope_lines=None):
        self.ensure_one()
        scope_lines = scope_lines or self._get_sequence_scope_lines()
        if not scope_lines:
            return self.browse()

        # Identify visible roots inside the current scope, including orphaned legacy rows.
        scope_ids = set(scope_lines.ids)
        ordered_scope_lines = scope_lines.sorted(
            lambda rec: (rec.sequence or 0, rec.id or 0)
        )
        root_lines = [
            line
            for line in ordered_scope_lines
            if not line.parent_line_id or line.parent_line_id.id not in scope_ids
        ]

        # Walk every root subtree in sibling order to rebuild the flat preorder tree.
        children_map = self._get_children_map(scope_lines)
        ordered_ids = []

        def _visit(line):
            ordered_ids.append(line.id)
            for child in children_map.get(line.id, []):
                _visit(child)

        for root_line in root_lines:
            _visit(root_line)

        # Keep any unexpected dangling rows at the end instead of dropping them.
        seen_ids = set(ordered_ids)
        ordered_ids.extend(
            line.id for line in ordered_scope_lines if line.id not in seen_ids
        )
        return self.browse(ordered_ids)

    # Rewrite the flat preorder sequence for one scope using fixed increments.
    def _normalize_hierarchy_sequence(self, scope_lines=None, ordered_lines=None):
        self.ensure_one()
        scope_lines = scope_lines or self._get_sequence_scope_lines()
        if not scope_lines:
            return

        # Default to the computed preorder when callers do not provide one explicitly.
        ordered_lines = ordered_lines or self._get_hierarchy_ordered_lines(
            scope_lines=scope_lines
        )
        for index, line in enumerate(ordered_lines, start=1):
            new_sequence = index * SEQUENCE_STEP
            if line.sequence == new_sequence:
                continue

            # Bypass recursive resequencing because this write is the canonical normalization pass.
            line.with_context(
                skip_hierarchy_sequence_sync=True,
                skip_normalized_3p_weight_validation=True,
            ).write({"sequence": new_sequence})

    # Normalize every affected scope once after create/write operations.
    def _normalize_hierarchy_scopes(self, scope_keys):
        unique_scope_keys = []
        for scope_key in scope_keys:
            if not scope_key or not scope_key[0] or scope_key in unique_scope_keys:
                continue
            unique_scope_keys.append(scope_key)

        for scope_key in unique_scope_keys:
            # Search by scope key so old and new scopes are both cleaned after reparenting.
            scope_lines = self.search(
                self._get_sequence_scope_domain_from_key(scope_key),
                order="sequence, id",
            )
            if not scope_lines:
                continue
            scope_lines[:1]._normalize_hierarchy_sequence(scope_lines=scope_lines)

    # Move the current subtree to the end of its new parent block or to the end of the root block.
    def _move_subtree_to_parent_end(self, scope_lines=None):
        self.ensure_one()
        scope_lines = scope_lines or self._get_sequence_scope_lines()
        if not scope_lines:
            return

        # Rebuild the visible flat tree before relocating the subtree block.
        ordered_lines = self._get_hierarchy_ordered_lines(scope_lines=scope_lines)
        subtree_lines = self._get_subtree_lines(scope_lines=scope_lines)
        if not ordered_lines or not subtree_lines:
            return

        subtree_ids = set(subtree_lines.ids)
        remaining_lines = ordered_lines.filtered(
            lambda line: line.id not in subtree_ids
        )

        # Insert children after the last descendant of the parent subtree.
        if self.parent_line_id and self.parent_line_id in scope_lines:
            remaining_scope_lines = scope_lines.filtered(
                lambda line: line.id not in subtree_ids
            )
            parent_subtree = self.parent_line_id._get_subtree_lines(
                scope_lines=remaining_scope_lines
            )
            # Compute the anchor from the remaining tree so a brand-new first child
            # lands right after its parent instead of falling to the scope tail.
            anchor_id = (
                parent_subtree.ids[-1] if parent_subtree else self.parent_line_id.id
            )
            anchor_index = (
                remaining_lines.ids.index(anchor_id) + 1
                if anchor_id and anchor_id in remaining_lines.ids
                else len(remaining_lines)
            )
            ordered_ids = (
                remaining_lines.ids[:anchor_index]
                + subtree_lines.ids
                + remaining_lines.ids[anchor_index:]
            )
        else:
            # Root lines always append after the last root subtree in the same tab scope.
            ordered_ids = remaining_lines.ids + subtree_lines.ids

        self._normalize_hierarchy_sequence(
            scope_lines=scope_lines,
            ordered_lines=self.browse(ordered_ids),
        )

    # Validate the target only for auto KPI lines that use numeric goals.
    @api.constrains("kpi_type", "target")
    def _check_numeric_target(self):
        for rec in self:
            if rec.display_type or rec.is_section:
                continue
            if rec.kpi_type == "auto" and (rec.target or 0.0) < 0.0:
                raise ValidationError(
                    _("For Auto KPI type, Target must be greater than or equal to 0.")
                )

    # Keep manual subtype required for manual lines and empty for auto lines.
    @api.constrains("kpi_type", "manual_scoring_type")
    def _check_manual_scoring_type(self):
        for rec in self:
            if rec.display_type or rec.is_section:
                continue
            if rec.kpi_type == "manual" and not rec.manual_scoring_type:
                raise ValidationError(get_manual_scoring_type_required_message())
            if rec.kpi_type == "auto" and rec.manual_scoring_type:
                raise ValidationError(
                    _("Manual scoring type must be empty for auto KPI lines.")
                )

    # Require a formula on normalized P3 auto leaf lines.
    @api.constrains("kpi_type", "pillar_id", "is_section", "scoring_formula_id")
    def _check_p3_scoring_formula(self):
        for rec in self:
            if rec.is_section or rec.pillar_code not in P3_PILLAR_CODES:
                continue
            if rec.kpi_type == "auto" and not rec.scoring_formula_id:
                raise ValidationError(
                    _(
                        "Please select a scoring formula for normalized P3 auto KPI lines."
                    )
                )

    # Keep the wipeout threshold non-negative.
    @api.constrains("violation_threshold")
    def _check_violation_threshold(self):
        for rec in self:
            if rec.violation_threshold < 0:
                raise ValidationError(
                    _("Violation Threshold must be greater than or equal to 0.")
                )

    # Validate the optional department KPI link used for bottom-up mapping.
    @api.constrains("parent_dept_line_id", "kpi_id", "is_section")
    def _check_parent_dept_line(self):
        self._validate_parent_dept_line_consistency()

    # Keep parent-child relations inside the same employee KPI template.
    @api.constrains("parent_line_id", "kpi_id", "pillar_id")
    def _check_parent_line(self):
        for rec in self:
            parent = rec.parent_line_id
            if not parent:
                continue
            if parent == rec:
                raise ValidationError(_("A KPI line cannot be its own parent."))
            if parent.kpi_id != rec.kpi_id:
                raise ValidationError(
                    _("The parent KPI line must belong to the same KPI template.")
                )
            if parent.pillar_id != rec.pillar_id:
                raise ValidationError(
                    _("The parent KPI line must belong to the same pillar.")
                )

            # Walk the full ancestry chain so deep recursive trees are blocked as well.
            ancestor = parent
            while ancestor:
                if ancestor == rec:
                    raise ValidationError(
                        _("Recursive KPI line hierarchy is not allowed.")
                    )
                ancestor = ancestor.parent_line_id

    # Validate that the employee line links to a real scorable department template line.
    def _validate_parent_dept_line_consistency(self, parent_kpi=None):
        for rec in self:
            parent_line = rec.parent_dept_line_id
            if not parent_line:
                continue
            if rec.is_section:
                raise ValidationError(
                    _("Section lines cannot be linked to department KPI lines.")
                )
            if parent_line.is_section:
                raise ValidationError(
                    _("Please select a KPI item, not a department section.")
                )

            parent_dept_kpi = parent_kpi or rec.kpi_id.department_kpi_id
            if not parent_dept_kpi:
                raise ValidationError(
                    _(
                        "Please select a parent Department KPI Template before linking department KPI lines."
                    )
                )
            if parent_line.department_kpi_id != parent_dept_kpi:
                raise ValidationError(
                    _(
                        "The selected department KPI line must belong to the parent Department KPI Template."
                    )
                )

    # Validate normalized 3P weights after user-driven create/write operations.
    def _validate_normalized_3p_weight_structure(self):
        if self.env.context.get("install_mode") or self.env.context.get(
            "skip_normalized_3p_weight_validation"
        ):
            return

        templates = self.mapped("kpi_id")
        for template in templates:
            for pillar_code in NORMALIZED_3P_PILLAR_CODES:
                lines = template.kpi_line_ids.filtered(
                    lambda line: line.pillar_code == pillar_code
                )
                if not lines:
                    continue

                negative_weight_line = lines.filtered(lambda line: line.weight < 0.0)[
                    :1
                ]
                if negative_weight_line:
                    raise ValidationError(
                        _("Weight cannot be negative for normalized 3P KPI lines.")
                    )

                root_lines = lines.filtered(lambda line: not line.parent_line_id)
                root_total = sum(root_lines.mapped("weight"))
                if root_lines and abs(root_total - 100.0) > WEIGHT_TOLERANCE:
                    raise ValidationError(
                        _(
                            "The total weight of root lines in pillar %(pillar)s must be exactly 100. Current total: %(total)s."
                        )
                        % {
                            "pillar": pillar_code,
                            "total": f"{root_total:g}",
                        }
                    )

                for parent in lines.filtered(lambda line: line.child_line_ids):
                    child_lines = parent.child_line_ids.filtered(
                        lambda line: line.pillar_code == parent.pillar_code
                    )
                    if not child_lines:
                        continue
                    child_total = sum(child_lines.mapped("weight"))
                    if abs(child_total - parent.weight) > WEIGHT_TOLERANCE:
                        raise ValidationError(
                            _(
                                "The total weight of child lines under '%(line)s' must equal the parent weight %(parent_weight)s. Current total: %(child_total)s."
                            )
                            % {
                                "line": parent.key_performance_area,
                                "parent_weight": f"{parent.weight:g}",
                                "child_total": f"{child_total:g}",
                            }
                        )

    # Keep section rows technically consistent and validate normalized 3P trees after edits.
    def write(self, vals):
        vals = dict(vals or {})
        if vals.get("display_type") and "is_section" not in vals:
            vals["is_section"] = True
        if vals.get("is_section") or vals.get("kpi_type") == "auto":
            vals["manual_scoring_type"] = False

        # Skip recursive hierarchy syncing for internal normalization writes.
        if self.env.context.get("skip_hierarchy_sequence_sync"):
            return super().write(vals)

        affected_scope_fields = {"sequence", "parent_line_id", "pillar_id", "kpi_id"}
        old_scope_keys = self._get_sequence_scope_keys()
        res = super().write(vals)

        if affected_scope_fields.intersection(vals):
            if "parent_line_id" in vals and "sequence" not in vals:
                for rec in self:
                    # Reparenting without an explicit drag sequence should append to the new parent block.
                    rec._move_subtree_to_parent_end()

            # Normalize both previous and current scopes so moved subtrees remain contiguous.
            self._normalize_hierarchy_scopes(
                old_scope_keys + self._get_sequence_scope_keys()
            )
        self._validate_normalized_3p_weight_structure()
        return res

    # Enforce the tab pillar and normalized 3P validation as a backend fallback.
    @api.model_create_multi
    def create(self, vals_list):
        default_pillar = self._get_default_pillar_from_context()
        normalized_vals_list = []
        for vals in vals_list:
            normalized_vals = dict(vals)
            if (
                normalized_vals.get("display_type")
                and "is_section" not in normalized_vals
            ):
                normalized_vals["is_section"] = True
            if (
                normalized_vals.get("is_section")
                or normalized_vals.get("kpi_type") == "auto"
            ):
                normalized_vals["manual_scoring_type"] = False
            if default_pillar and not normalized_vals.get("pillar_id"):
                normalized_vals["pillar_id"] = default_pillar.id
            normalized_vals_list.append(normalized_vals)

        records = super().create(normalized_vals_list)
        for rec, normalized_vals in zip(records, normalized_vals_list):
            if "sequence" in normalized_vals:
                continue

            # Auto-place new lines at the end of their root or parent subtree block.
            rec._move_subtree_to_parent_end()
        records._validate_normalized_3p_weight_structure()
        return records

    # Open the popup form used by the custom one2many widget.
    def action_open_popup(self):
        self.ensure_one()
        return {
            "name": _("Edit KPI Line"),
            "type": "ir.actions.act_window",
            "res_model": "hr.kpi.template.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_adecsol_hr_performance_evaluator.view_hr_kpi_line_form_popup"
            ).id,
            "target": "new",
        }
