lines = env["hr.department.kpi.template.line"].search(
    [("name", "=ilike", "TC1%")],
    order="id desc",
)
print("SECTION_COUNT", len(lines))
for line in lines:
    print(
        "SECTION",
        {
            "id": line.id,
            "name": line.name,
            "weight": line.weight,
            "template": line.department_kpi_id.name,
            "template_id": line.department_kpi_id.id,
            "pillar": line.pillar_code,
            "parent": line.parent_line_id.id if line.parent_line_id else False,
        },
    )
    children = line.child_line_ids.sorted(lambda rec: (rec.sequence or 0, rec.id or 0))
    print("CHILDREN_COUNT", len(children), "TOTAL", sum(children.mapped("weight")))
    for child in children:
        print(
            "CHILD",
            {
                "id": child.id,
                "name": child.name,
                "weight": child.weight,
                "sequence": child.sequence,
                "parent": child.parent_line_id.id if child.parent_line_id else False,
                "pillar": child.pillar_code,
            },
        )
    print("---")
