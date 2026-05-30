# Specification: Dynamic KPI-Driven Dashboard Charts

## Module: `custom_adecsol_hr_performance_evaluator` (Odoo 18)

---

## 1. Overview & Context

Currently, the **Individual KPI Dashboard** in the performance evaluation system displays three charts with hardcoded logic:
1. **Done Tasks Trend** (Line chart of task progress)
2. **Punctuality Log** (Line chart of check-in times)
3. **Attendance Overview** (Doughnut chart of presence/absence metrics)

This hardcoded design is rigid. The backend (`performance_evaluation.py`) hardcodes data generation, and the frontend (`kpi_dashboard_template.xml` and `kpi_dashboard_page.js`) hardcodes elements, `useRef` canvas bindings, and renderer calls. 

This specification defines the plan to refactor the dashboard charts into a **Fully Dynamic, KPI-Driven Architecture**. Charts will automatically render depending on the actual KPI lines configured in the employee's evaluation sheet.

### Core Architecture Concept
```
Evaluation Template ➔ Evaluation Line ➔ Data Source ➔ Chart Type (dynamic) ➔ JS Auto-render
```

### Invariant Rules & Decisions
*   **Dynamic Generation**: Charts will only be generated for quantitative KPI lines that use an automatic `data_source_id` having a `chart_type` other than `"none"`.
*   **Static Elements to Keep**: 
    *   **Spider Web (Competency Chart)**: Static, not tied to a data source (keeps `hasWidget('individual_radar')`).
    *   **Detailed Evaluation Log (Quantitative Table)**: Static (keeps `hasWidget('individual_quantitative_table')`).
    *   **Summary Cards**: Upper scorecard row remains intact.
*   **Widgets to Delete**: The static widget configurations for `individual_done_tasks`, `individual_punctuality`, and `individual_attendance` will be deleted using Odoo XML `<delete>` tags.
*   **Responsive Grid Layout**: Dynamic charts will render inside a modern CSS grid layout (`display: grid; grid-template-columns: repeat(auto-fill, minmax(45%, 1fr)); gap: 20px;`) so that:
    *   1 chart ➔ full width
    *   2 charts ➔ two columns
    *   3+ charts ➔ multi-row wrap
*   **Department Dashboard**: Explicitly **out of scope** for this phase. Keep changes focused on the Individual Dashboard only.
*   **Data Source Seed**: XML seed records in `data/hr_kpi_data_source_data.xml` are declared under `<data noupdate="0">` so modifications will upgrade cleanly.

---

## 2. Dynamic Architecture: Three-Layer Design

```
+--------------------------------------------------------------+
|                     Layer 1: Data Model                      |
|  - hr.kpi.data.source adds chart_type & data_method          |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
|                   Layer 2: Python Backend                    |
|  - Scan evaluation lines for active charts                   |
|  - Invoke engine methods dynamically                         |
|  - Output JSON: { "dynamic_charts": [...] }                  |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
|                   Layer 3: OWL JS & HTML                     |
|  - Template loops through dynamic_charts using t-foreach     |
|  - Canvas identified by data-chart-key                       |
|  - JS maps chart_type to specific renderer functions         |
+--------------------------------------------------------------+
```

---

## 3. Layer 1: Data Model Updates

### 3.1 `hr.kpi.data.source` Field Additions
File: `models/hr_kpi_data_source.py`

Add the following fields to the `HrKpiDataSource` class:

```python
chart_type = fields.Selection(
    [
        ("none", "Không hiện chart"),
        ("trend_line", "Đường xu hướng (Line chart)"),
        ("punctuality", "Punctuality Log (check-in theo ngày)"),
        ("doughnut", "Biểu đồ tròn (Doughnut)"),
        ("bar", "Biểu đồ cột (Bar chart)"),
    ],
    string="Dashboard Chart Type",
    default="none",
    required=True,
    help="Loại chart hiển thị trên dashboard cá nhân cho KPI dùng nguồn dữ liệu này.",
)

dashboard_data_method = fields.Char(
    string="Dashboard Data Method",
    help="Tên method trên hr.kpi.engine để lấy chart data. "
         "Ví dụ: 'get_task_progress_series'. "
         "Nếu trống, hệ thống sẽ fallback về method mặc định dựa trên chart_type.",
)
```

### 3.2 Form View Customization
File: `views/hr_kpi_data_source_views.xml` (or inline view definitions)

Add the two new fields `chart_type` and `dashboard_data_method` into the backend form view of `hr.kpi.data.source` to allow administrators to configure charts for custom data sources.

---

## 4. Layer 2: Python Backend Refactoring

File: [performance_evaluation.py](file:///d:/CODE/odoo18-work/odoo18/odoo_app_addons/custom_adecsol_hr_performance_evaluator/models/performance_evaluation.py)

### 4.1 Delete / Modify Methods
*   **DELETE**: `_get_dashboard_line(self, evaluation)`
*   **DELETE**: `_get_done_tasks_by_day_data(self, evaluation)`
*   **DELETE**: `_get_punctuality_log_data(self, evaluation)`
*   **DELETE**: `_get_attendance_overview_data(self, evaluation)`
*   **KEEP AS-IS**: `_get_spider_web_data(self, evaluation)`
*   **KEEP AS-IS**: `_get_quantitative_table_data(self, evaluation)`

### 4.2 Add `_get_chart_lines(self, evaluation)`
This method scans the current evaluation's lines and returns information on all active quantitative lines configured with an automatic data source that has an active chart representation.

```python
def _get_chart_lines(self, evaluation):
    """Scan evaluation_line_ids and extract lines that support dynamic charts."""
    results = []
    lines = evaluation.evaluation_line_ids.filtered(
        lambda l: (
            not l.is_section
            and l.kpi_type == "quantitative"
            and l.data_source_id
            and l.data_source_id.chart_type
            and l.data_source_id.chart_type != "none"
        )
    )
    for line in lines:
        ds = line.data_source_id
        results.append({
            "line": line,
            "data_source": ds,
            "chart_type": ds.chart_type,
            "data_method": ds.dashboard_data_method or False,
            "chart_key": f"chart_{ds.code}",  # Unique key for JS frontend and DOM identification
        })
    return results
```

### 4.3 Refactor `get_dashboard_data(self)`
Update the response dict returned by `get_dashboard_data()`. Remove the hardcoded chart keys and add the unified `dynamic_charts` list instead.

```python
# In get_dashboard_data():
result = {
    "evaluation_id": evaluation.id,
    "score_scale": score_scale,
    "widgets": widgets,
    "widget_map": {widget["code"]: widget for widget in widgets},
    "thresholds": {
        "excellent": threshold_excellent,
        "pass": threshold_pass,
    },
    "employee_name": evaluation.employee_id.name or "",
    "period_id": evaluation.period_id.id if evaluation.period_id else False,
    "period_name": evaluation.period_id.name if evaluation.period_id else "",
    "period_type": evaluation.period_type or "",
    "start_date": str(evaluation.start_date) if evaluation.start_date else "",
    "end_date": str(evaluation.end_date) if evaluation.end_date else "",
    "performance_score": round(float(evaluation.performance_score or 0.0), 2),
    "dept_kpi_score": round(float(dept_score), 2),
    "dept_weight": round(float(dept_weight), 4),
    "individual_weight": round(float(individual_weight), 4),
    "has_dept_evaluation": has_dept_evaluation,
    "final_score": round(float(evaluation.final_score or 0.0), 2),
    "final_level": final_key,
    "final_level_label": selection_dict.get(final_key, final_key),
    "performance_level": perf_key,
    "performance_level_label": perf_label,
    
    # ── Static Elements ───────────────────────────────────────
    "spider_web": self._get_spider_web_data(evaluation),
    "quantitative_table": self._get_quantitative_table_data(evaluation),
    
    # ── Dynamic Charts (NEW) ──────────────────────────────────
    "dynamic_charts": self._build_dynamic_charts(evaluation),
}
return result
```

### 4.4 Add `_build_dynamic_charts(self, evaluation)`
Implement dynamic dispatching to the `hr.kpi.engine` based on the configured chart types:

```python
def _build_dynamic_charts(self, evaluation):
    """Dispatch to hr.kpi.engine methods based on chart_type to build chart datasets."""
    charts = []
    engine = self.env["hr.kpi.engine"]
    
    for chart_info in self._get_chart_lines(evaluation):
        line = chart_info["line"]
        ds = chart_info["data_source"]
        chart_type = chart_info["chart_type"]
        method_name = chart_info["data_method"]
        
        data = None
        days = (evaluation.end_date - evaluation.start_date).days + 1
        labels = [f"Day {i+1}" for i in range(days)]
        
        # Dispatch logic
        if chart_type == "trend_line":
            fn = getattr(engine, method_name, None) if method_name else None
            if callable(fn):
                series_data = fn(evaluation.employee_id, evaluation.start_date, evaluation.end_date)
            else:
                series_data = engine.get_task_progress_series(
                    evaluation.employee_id, evaluation.start_date, evaluation.end_date
                )
            if series_data:
                data = {
                    "labels": labels,
                    "done_by_day": series_data.get("done_by_day", []),
                    "total": series_data.get("total", 0),
                }
                
        elif chart_type == "punctuality":
            fn = getattr(engine, method_name, None) if method_name else None
            per_day = fn(evaluation.employee_id, line, evaluation.start_date, evaluation.end_date) \
                      if callable(fn) else engine.get_first_checkin_series(
                          evaluation.employee_id, line, evaluation.start_date, evaluation.end_date
                      )
            data = {
                "labels": labels,
                "data": per_day,
                "expected_hour": engine.get_expected_start_hour(evaluation.employee_id),
                "grace_minutes": engine._get_late_grace_minutes(),
            }
            
        elif chart_type == "doughnut":
            metrics = engine.get_attendance_period_metrics(
                evaluation.employee_id, line, evaluation.start_date, evaluation.end_date
            )
            calendar_data = engine.get_attendance_worked_dates(
                evaluation.employee_id, evaluation.start_date, evaluation.end_date
            )
            summary = dict(metrics)
            summary["target"] = float(line.target or 0.0)
            summary["unit_code"] = line.unit.code if line.unit else ""
            data = {
                "summary": summary, 
                "calendar": calendar_data
            }
            
        elif chart_type == "bar":
            # Add basic bar chart support for aggregated values if required
            data = self._build_generic_bar_data(evaluation, line)
            
        if data:
            charts.append({
                "key": chart_info["chart_key"],
                "chart_type": chart_type,
                "title": ds.name,
                "kpi_name": line.key_performance_area or ds.name,
                "data": data,
            })
            
    return charts

def _build_generic_bar_data(self, evaluation, line):
    """Helper to build a simple dataset structure for custom bar charts."""
    # Example generic aggregator:
    actual_value = float(line.actual or 0.0)
    target_value = float(line.target or 0.0)
    return {
        "labels": ["Target", "Actual"],
        "datasets": [
            {
                "label": line.key_performance_area or line.name,
                "data": [target_value, actual_value],
            }
        ]
    }
```

---

## 5. Layer 3: OWL Frontend Refactoring

### 5.1 JS Component Refactoring
File: [kpi_dashboard_page.js](file:///d:/CODE/odoo18-work/odoo18/odoo_app_addons/custom_adecsol_hr_performance_evaluator/static/src/js/kpi_dashboard_page.js)

#### A. Remove Hardcoded Refs
Delete lines 68, 69, 70, 72 from `setup()`:
```javascript
// DELETE
this.doneTasksRef = useRef("doneTasksChart");
this.taskRef = useRef("taskChart");
this.puncRef = useRef("punctualityChart");
this.attendanceRef = useRef("attendanceChart");

// KEEP
this.radarRef = useRef("spiderChart");
```

#### B. Implement Renderer Registry and Loop
Add a static mapping of `chart_type` to renderer method names:

```javascript
static CHART_RENDERERS = {
    trend_line:  "_renderTrendLineChart",
    punctuality: "_renderPunctualityChart",
    doughnut:    "_renderDoughnutChart",
    bar:         "_renderBarChart",
};
```

Update `_renderCharts()` to dynamically iterate through the charts:

```javascript
_renderCharts() {
    const Chart = window.Chart;
    const d = this.state.data;
    if (!Chart || !d) return;
    this._destroyCharts();

    // 1. Render Competency Radar Chart (Static, keeps current logic)
    const radarEl = this.radarRef.el;
    if (radarEl && d.spider_web?.labels?.length) {
        this._renderSpiderChart(radarEl, d.spider_web);
    }

    // 2. Loop & Render Dynamic Charts
    for (const chartInfo of (d.dynamic_charts || [])) {
        const canvas = this.el?.querySelector(
            `canvas[data-chart-key="${chartInfo.key}"]`
        );
        if (!canvas) continue;
        
        const rendererName = this.constructor.CHART_RENDERERS[chartInfo.chart_type];
        if (rendererName && typeof this[rendererName] === "function") {
            const instance = this[rendererName](canvas, chartInfo.data);
            if (instance) {
                this._charts[chartInfo.key] = instance;
            }
        }
    }
}
```

#### C. Individual Chart Renderers
Extract the chart rendering definitions into clean, single-purpose functions that take `(canvas, data)` and return a `Chart` instance:

```javascript
_renderTrendLineChart(canvas, data) {
    const Chart = window.Chart;
    return new Chart(canvas, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: _t("Done Tasks"),
                    data: data.done_by_day,
                    borderColor: COLOR_GREEN,
                    backgroundColor: "rgba(34,197,94,0.12)",
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointBackgroundColor: COLOR_GREEN,
                    spanGaps: false,
                },
                {
                    label: _t("Total Tasks (target)"),
                    data: Array(data.labels.length).fill(data.total),
                    borderColor: COLOR_RED,
                    borderDash: [6, 4],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    tension: 0,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: true, position: "top" },
                tooltip: {
                    callbacks: {
                        label: (c) => {
                            if (c.datasetIndex === 1) {
                                return _t("Total in period: ") + data.total + _t(" tasks");
                            }
                            return _t("Done (Total): ") + c.parsed.y + _t(" tasks");
                        },
                    },
                },
            },
            scales: {
                x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1,
                        font: { size: 10 },
                        callback: (v) => (Number.isInteger(v) ? v : ""),
                    },
                    grid: { color: "rgba(0,0,0,0.05)" },
                    title: { display: true, text: _t("Tasks"), font: { size: 11 } },
                },
            },
        },
    });
}

_renderPunctualityChart(canvas, data) {
    const Chart = window.Chart;
    const expectedH = data.expected_hour || 8;
    const yMin = Math.max(0, Math.floor(expectedH) - 1);
    const yMax = Math.ceil(expectedH) + 1.5;
    
    return new Chart(canvas, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: _t("Check-in"),
                    data: data.data,
                    borderColor: COLOR_GREEN,
                    backgroundColor: "rgba(34,197,94,0.12)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 5,
                    spanGaps: true,
                },
                {
                    label: _t("Start time"),
                    data: Array(data.labels.length).fill(expectedH),
                    borderColor: COLOR_RED,
                    borderDash: [5, 4],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => {
                            const v = c.parsed.y;
                            return c.dataset.label + ": " + (v != null ? formatHour(v) : "--");
                        },
                    },
                },
            },
            scales: {
                x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
                y: {
                    min: yMin,
                    max: yMax,
                    ticks: {
                        stepSize: 0.25,
                        callback: (v) => formatHour(v),
                    },
                    grid: { color: "rgba(0,0,0,0.05)" },
                },
            },
        },
    });
}

_renderDoughnutChart(canvas, data) {
    const Chart = window.Chart;
    const worked = data.summary.worked_days;
    const expected = data.summary.expected_work_days;
    const absent = Math.max(expected - worked, 0);

    return new Chart(canvas, {
        type: "doughnut",
        data: {
            labels: [_t("Days Present"), _t("Days Absent")],
            datasets: [
                {
                    data: [worked, absent],
                    backgroundColor: [COLOR_BLUE, "#e2e8f0"],
                    borderWidth: 0,
                    hoverOffset: 4,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "75%",
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => c.label + ": " + c.parsed + _t(" days"),
                    },
                },
            },
        },
    });
}

_renderBarChart(canvas, data) {
    const Chart = window.Chart;
    return new Chart(canvas, {
        type: "bar",
        data: {
            labels: data.labels,
            datasets: data.datasets.map(ds => ({
                ...ds,
                backgroundColor: COLOR_BLUE,
                borderRadius: 4,
            })),
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true, grid: { color: "rgba(0,0,0,0.05)" } },
            },
        },
    });
}

_renderSpiderChart(canvas, data) {
    // Retain existing implementation for spider chart
    ...
}
```

#### D. Helper to Render Chart Icons dynamically
Add this helper method inside the JS class:

```javascript
chartIcon(chartType) {
    const icons = {
        trend_line:  "fa fa-line-chart",
        punctuality: "fa fa-clock-o",
        doughnut:    "fa fa-pie-chart",
        bar:         "fa fa-bar-chart",
    };
    return icons[chartType] || "fa fa-chart-area";
}
```

---

### 5.2 HTML OWL Template Refactoring
File: [kpi_dashboard_template.xml](file:///d:/CODE/odoo18-work/odoo18/odoo_app_addons/custom_adecsol_hr_performance_evaluator/static/src/xml/kpi_dashboard_template.xml)

#### A. Remove Obsolete Hardcoded Sections
Delete lines 166 to 220 entirely:
*   Row 1: Task Completion + Punctuality block (`t-if="hasWidget('individual_done_tasks') or hasWidget('individual_punctuality')"`).

Delete lines 260 to 293 entirely:
*   Attendance Overview card within Row 2 (`t-if="hasWidget('individual_attendance')"`).

Ensure Row 2's grid container is refactored. The Radar Competency chart will now span full-width inside Row 2, or wrap normally.

#### B. Add Unified `dynamic_charts` Section
Insert this dynamic layout loop right after the summary scorecard header (`class="o_kpi_header_cards"`):

```xml
<!-- Dynamic Charts Grid -->
<t t-if="state.data.dynamic_charts and state.data.dynamic_charts.length">
  <div class="o_kpi_row o_kpi_dynamic_grid">
    <t t-foreach="state.data.dynamic_charts" t-as="chart" t-key="chart.key">
      <div class="o_kpi_card o_kpi_chart_card">
        
        <div class="o_kpi_card_header">
          <span class="o_kpi_card_title">
            <i t-att-class="chartIcon(chart.chart_type)"/>
            <t t-esc="chart.title"/>
          </span>
          <span class="o_kpi_target_badge o_kpi_muted" t-esc="chart.kpi_name"/>
        </div>
        
        <div class="o_kpi_chart_container">
          <!-- Unique canvas target queried dynamically in JS -->
          <canvas t-att-data-chart-key="chart.key" height="160"/>
          
          <!-- Optional center overlay specific to Doughnut attendance -->
          <t t-if="chart.chart_type === 'doughnut'">
            <div class="o_kpi_doughnut_center">
              <div class="o_kpi_doughnut_val" t-esc="chart.data.summary.expected_work_days"/>
              <div class="o_kpi_doughnut_lbl">Total Days</div>
            </div>
          </t>
        </div>
        
        <!-- Optional Legends underneath charts -->
        <t t-if="chart.chart_type === 'doughnut'">
          <div class="o_kpi_attendance_legend" style="margin-top: 15px;">
            <div class="o_kpi_spider_legend_item" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <span class="o_kpi_spider_legend_label" style="display: flex; align-items: center;">
                <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #3b82f6; margin-right: 8px;"></span>
                Days Present
              </span>
              <span class="o_kpi_spider_legend_score" style="font-weight: bold;" t-esc="chart.data.summary.worked_days"/>
            </div>
            <div class="o_kpi_spider_legend_item" style="display: flex; justify-content: space-between; align-items: center;">
              <span class="o_kpi_spider_legend_label" style="display: flex; align-items: center;">
                <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #e2e8f0; margin-right: 8px;"></span>
                Days Absent
              </span>
              <span class="o_kpi_spider_legend_score" style="font-weight: bold;" t-esc="chart.data.summary.expected_work_days - chart.data.summary.worked_days"/>
            </div>
          </div>
        </t>
        
        <t t-if="chart.chart_type === 'punctuality'">
          <p class="o_kpi_chart_note">
            Giờ làm việc bắt đầu: <b t-esc="formatHour(chart.data.expected_hour)"/> (Grace period: <t t-esc="chart.data.grace_minutes"/>m)
          </p>
        </t>
        
      </div>
    </t>
  </div>
</t>
```

Modify Row 2's structure (where the Competency Radar is). Make it take full width or independent display since Attendance is now dynamic:

```xml
<!-- Row 2: Competency Spider Web -->
<div t-if="hasWidget('individual_radar') and state.data.spider_web.labels.length" class="o_kpi_row" style="margin-top: 20px;">
  <div class="o_kpi_card o_kpi_spider_card o_kpi_card_full">
    <div class="o_kpi_card_header">
      <span class="o_kpi_card_title"><i class="fa fa-bullseye"/> Competency Chart</span>
    </div>
    <div class="o_kpi_spider_body">
      <div class="o_kpi_chart_container o_kpi_chart_radar">
        <canvas t-ref="spiderChart"/>
      </div>
      <div class="o_kpi_spider_legend">
        <t t-foreach="state.data.spider_web.labels" t-as="label" t-key="label">
          <div class="o_kpi_spider_legend_item">
            <span class="o_kpi_spider_legend_label" t-esc="label"/>
            <span class="o_kpi_spider_legend_score" t-esc="formatScore(state.data.spider_web.scores[label_index])"/>
          </div>
        </t>
      </div>
    </div>
  </div>
</div>
```

---

### 5.3 CSS Refactoring (Vanilla CSS)
File: `static/src/css/kpi_dashboard.css` (or wherever CSS is stored in this addon)

Ensure the responsive grid CSS class is defined. Write rules that achieve a balanced 2-column layout that naturally scales to full width on mobile or when there's only one chart.

```css
.o_kpi_dynamic_grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(45%, 1fr));
    gap: 20px;
    width: 100%;
}

.o_kpi_chart_container {
    position: relative;
    width: 100%;
}

.o_kpi_doughnut_center {
    position: absolute;
    text-align: center;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
}

.o_kpi_doughnut_val {
    font-size: 24px;
    font-weight: bold;
    color: #1e293b;
    line-height: 1;
}

.o_kpi_doughnut_lbl {
    font-size: 10px;
    color: #64748b;
    text-transform: uppercase;
    margin-top: 2px;
}
```

---

## 6. Layer 4: Configuration & Seed Data Updates

### 6.1 Update Builtin Data Sources
File: [hr_kpi_data_source_data.xml](file:///d:/CODE/odoo18-work/odoo18/odoo_app_addons/custom_adecsol_hr_performance_evaluator/data/hr_kpi_data_source_data.xml)

Update the 5 core data source definitions (keeping `noupdate="0"` to ensure update execution on upgrade):

```xml
<record id="source_task_done_count" model="hr.kpi.data.source">
    <!-- Keep existing fields -->
    <field name="chart_type">trend_line</field>
    <field name="dashboard_data_method">get_task_progress_series</field>
</record>

<record id="source_task_on_time_rate" model="hr.kpi.data.source">
    <!-- Keep existing fields -->
    <field name="chart_type">none</field>
</record>

<record id="source_attendance_present_days" model="hr.kpi.data.source">
    <!-- Keep existing fields -->
    <field name="chart_type">doughnut</field>
    <field name="dashboard_data_method">get_attendance_period_metrics</field>
</record>

<record id="source_attendance_on_time_days" model="hr.kpi.data.source">
    <!-- Keep existing fields -->
    <field name="chart_type">none</field>
</record>

<record id="source_attendance_late_days" model="hr.kpi.data.source">
    <!-- Keep existing fields -->
    <field name="chart_type">punctuality</field>
    <field name="dashboard_data_method">get_first_checkin_series</field>
</record>
```

### 6.2 Widget Configuration Cleanup
File: [hr_kpi_dashboard_widget_data.xml](file:///d:/CODE/odoo18-work/odoo18/odoo_app_addons/custom_adecsol_hr_performance_evaluator/data/hr_kpi_dashboard_widget_data.xml)

Since charts are dynamic, the static widgets `individual_done_tasks`, `individual_punctuality`, and `individual_attendance` must be deleted. Add this clean `<delete>` tag block to the XML definition so they are safely purged on module upgrade:

```xml
<!-- Delete static widget records that are replaced by dynamic charts -->
<delete model="hr.kpi.dashboard.widget" search="[('code', 'in', ['individual_done_tasks', 'individual_punctuality', 'individual_attendance'])]"/>
```

*Ensure that `widget_individual_summary`, `widget_individual_radar`, and `widget_individual_quantitative_table` are left intact!*

---

## 7. Step-by-Step Codex Implementation Guide

To implement this dynamic refactoring, execute the tasks in this exact dependency order:

1.  **Model Configuration**:
    *   Add fields `chart_type` and `dashboard_data_method` in `models/hr_kpi_data_source.py`.
    *   Update `views/hr_kpi_data_source_views.xml` to present these fields in the Form view.
2.  **Built-in Data Source Upgrade**:
    *   Inject values into `data/hr_kpi_data_source_data.xml` for the 5 built-in records.
3.  **Python Backend Refactoring**:
    *   Delete the obsolete hardcoded data-generating methods in `models/performance_evaluation.py`.
    *   Write the new helper scanner `_get_chart_lines(self, evaluation)`.
    *   Implement `_build_dynamic_charts(self, evaluation)`.
    *   Inject `"dynamic_charts": self._build_dynamic_charts(evaluation)` inside `get_dashboard_data()`.
4.  **Static Widgets Purging**:
    *   Add the `<delete>` block in `data/hr_kpi_dashboard_widget_data.xml`.
5.  **OWL Template Refactoring**:
    *   Delete obsolete hardcoded rows in `static/src/xml/kpi_dashboard_template.xml`.
    *   Inject the unified dynamic charts loop mapping to dynamic canvas tags.
6.  **OWL JS Client Action Refactoring**:
    *   Remove hardcoded canvas references.
    *   Implement registry mapping `CHART_RENDERERS`.
    *   Refactor `_renderCharts()` to dynamically loop and instantiate chart types.
    *   Structure individual chart renderer methods.
7.  **CSS Integration**:
    *   Inject classes for the responsive grid `.o_kpi_dynamic_grid`.
8.  **Upgrade & Verify**:
    *   Upgrade the module with `-u custom_adecsol_hr_performance_evaluator` and verify logs.

---

## 8. Verification & Test Plan

Verify your refactoring using these core scenarios:

### Scenario A: Quantitative KPI with Automatic Data Source
*   **Action**: Open an evaluation sheet for an employee that has the "Số task hoàn thành" (`task_done_count`) KPI.
*   **Expectation**: The dashboard displays the dynamic **Line Chart** for tasks.

### Scenario B: Punctuality & Attendance
*   **Action**: Add "Số ngày đi muộn" (`attendance_late_days`) and "Số ngày đi làm thực tế" (`attendance_present_days`) to the evaluation sheet.
*   **Expectation**: The dashboard displays the **Punctuality Log** and **Attendance Overview (Doughnut)** in a clean multi-chart grid.

### Scenario C: Manual Scoring KPI (No Data Source)
*   **Action**: Create a quantitative or binary KPI that has **no data source** (manual entry only).
*   **Expectation**: No new chart card appears on the dashboard. The KPI values are correctly listed in the **Quantitative Table** and aggregated into the **Spider Web**, as designed.

### Scenario D: Multi-chart Grid Layout
*   **Action**: Configure 3 different active KPI lines with charts on one sheet.
*   **Expectation**: The 3 charts display in a responsive grid wrapping seamlessly (e.g. 2 charts on the first row, 1 chart taking full or partial width on the second row).

---

**End of Handoff Specification**
