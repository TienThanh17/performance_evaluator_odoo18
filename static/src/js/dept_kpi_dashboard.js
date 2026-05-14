/** @odoo-module **/
import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount, useEffect } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

// ─────────────────────────────────────────────────────────────────────────────
// Colour palette — mirrors SCSS $dept-primary / $dept-green etc.
// ─────────────────────────────────────────────────────────────────────────────
const C_BLUE = "#0367b0";
const C_GREEN = "#119a45";
const C_AMBER = "#e6a817";
const C_RED = "#e03c3c";
const C_PURPLE = "#7c3aed";
const C_TEAL = "#0891b2";

// Per-employee point colours for Chart C & D
const POINT_COLORS = [
    "#0367b0", "#119a45", "#e6a817", "#7c3aed",
    "#0891b2", "#e03c3c", "#f97316", "#84cc16",
    "#ec4899", "#14b8a6",
];

/** Chart A — stacked bar: total vs done tasks per employee */
function buildChartAData(employeeStats) {
    const names = employeeStats.map((e) => e.name);
    const total = employeeStats.map((e) => e.total);
    const done = employeeStats.map((e) => e.done);
    const pending = employeeStats.map((e) => e.pending);
    return { names, total, done, pending };
}

/** Chart B — bar: project completion % */
function buildChartBData(projectProgress) {
    // projectProgress = [{name, progress_pct, total_tasks, done_tasks}, ...]
    const projects = projectProgress.map((p) => p.name);
    const pct = projectProgress.map((p) => p.progress_pct);
    const totals = projectProgress.map((p) => p.total_tasks);
    const done = projectProgress.map((p) => p.done_tasks);
    return { projects, pct, totals, done };
}

/** Chart C — line: attendance count per employee */
function buildChartCData(attendanceData) {
    // attendanceData = [{employee_id, name, attendance_count}, ...]
    return attendanceData.map((e, i) => ({
        name: e.name,
        count: e.attendance_count,
        color: POINT_COLORS[i % POINT_COLORS.length],
    }));
}

/** Chart D — line: bug count per employee */
function buildChartDData(bugData) {
    // bugData = [{employee_id, name, bug_count}, ...]
    return bugData.map((e, i) => ({
        name: e.name,
        bugs: e.bug_count,
        color: POINT_COLORS[i % POINT_COLORS.length],
    }));
}

/** Chart E — line: score over timeline (one line per employee) */
function buildChartEData(employees) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const datasets = employees.map((e, i) => {
        const color = POINT_COLORS[i % POINT_COLORS.length];
        return {
            label: e.name,
            // data: months.map(() => parseFloat((4 + Math.random() * 6).toFixed(2))),
            data: null,
            borderColor: color,
            backgroundColor: color + "22",
            pointBackgroundColor: color,
            pointRadius: 4,
            tension: 0.35,
            fill: false,
        };
    });
    return { labels: months, datasets };
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart.js CDN loader (reuse pattern from kpi_dashboard_page.js)
// ─────────────────────────────────────────────────────────────────────────────
let _chartJsPromise = null;
function loadChartJs() {
    if (typeof window.Chart !== "undefined") return Promise.resolve();
    if (_chartJsPromise) return _chartJsPromise;
    _chartJsPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
    });
    return _chartJsPromise;
}

// ─────────────────────────────────────────────────────────────────────────────
// Default chart options helpers
// ─────────────────────────────────────────────────────────────────────────────
function baseBarOpts(yLabel = "") {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        },
        scales: {
            x: { ticks: { font: { size: 11 }, maxRotation: 30 }, grid: { display: false } },
            y: {
                title: { display: !!yLabel, text: yLabel, font: { size: 11 } },
                grid: { color: "rgba(0,0,0,0.05)" },
                ticks: { font: { size: 10 } },
            },
        },
    };
}

function baseLineOpts(yLabel = "", xLabel = "") {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        },
        scales: {
            x: {
                title: { display: !!xLabel, text: xLabel, font: { size: 11 } },
                ticks: { font: { size: 11 } },
                grid: { display: false },
            },
            y: {
                title: { display: !!yLabel, text: yLabel, font: { size: 11 } },
                grid: { color: "rgba(0,0,0,0.05)" },
                ticks: { font: { size: 10 } },
            },
        },
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// OWL Component
// ─────────────────────────────────────────────────────────────────────────────
export class DeptKpiDashboard extends Component {
    static template = "performance_evaluator.DeptKpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");

        // Canvas refs
        this.refA = useRef("chartA");
        this.refB = useRef("chartB");
        this.refC = useRef("chartC");
        this.refD = useRef("chartD");
        this.refE = useRef("chartE");

        this.state = useState({
            phase: "loading",           // "loading" | "done" | "empty" | "error"
            errorMsg: "",
            departments: [],
            selectedDepartmentId: null,
            evaluations: [],
            selectedEvaluationId: null,
            data: null,
        });

        this._charts = {};

        onWillStart(async () => {
            await loadChartJs();
            await this._loadDepartments();
        });

        onMounted(async () => {
            if (this.state.phase === "done") {
                await this._renderAllCharts();
            }
        });

        onWillUnmount(() => {
            this._destroyCharts();
        });

        useEffect(
            () => {
                if (this.state.phase === "done" && this.state.data) {
                    this._renderAllCharts();
                }
            },
            () => [this.state.phase, this.state.data] // Chạy lại effect này nếu phase hoặc data thay đổi
        );
    }

    // ── Getters ───────────────────────────────────────────────────────────────
    formatScore(val) {
        return val != null ? Number(val).toFixed(2) : "—";
    }

    levelLabel(lvl) {
        return { excellent: "⭐ Excellent", pass: "✓ Pass", fail: "✗ Fail" }[lvl] || "—";
    }

    // ── Data loaders ─────────────────────────────────────────────────────────
    async _loadDepartments() {
        try {
            const depts = await this.orm.searchRead(
                "hr.department",
                [["active", "=", true]],
                ["id", "name", "manager_id"],
                { order: "name asc" }
            );
            this.state.departments = depts;

            if (depts.length) {
                this.state.selectedDepartmentId = depts[0].id;
                await this._loadEvaluations(depts[0].id);
            } else {
                this.state.phase = "empty";
            }
        } catch (e) {
            this.state.errorMsg = "Failed to load departments.";
            this.state.phase = "error";
        }
    }

    async _loadEvaluations(departmentId) {
        this.state.phase = "loading";
        this._destroyCharts();
        try {
            const evals = await this.orm.searchRead(
                "hr.department.performance.evaluation",
                [["department_id", "=", departmentId]],
                ["id", "name", "department_id", "start_date", "end_date",
                    "department_score", "department_level", "state"],
                { order: "start_date desc", limit: 24 }
            );
            this.state.evaluations = evals;

            if (evals.length) {
                this.state.selectedEvaluationId = evals[0].id;
                await this._loadDashboardData(departmentId, evals[0]);
            } else {
                this.state.data = null;
                this.state.phase = "empty";
            }
        } catch (e) {
            this.state.errorMsg = "Failed to load evaluations.";
            this.state.phase = "error";
        }
    }

    async _loadDashboardData(departmentId, evaluation) {
        this.state.phase = "loading";
        this._destroyCharts();
        try {
            const data = await this.orm.call(
                "hr.department.performance.evaluation",
                "get_dashboard_data",
                [evaluation.id],
            );

            this.state.data = data;
            this.state.phase = "done";

            await new Promise((r) => requestAnimationFrame(r));
            await this._renderAllCharts();
        } catch (e) {
            console.error("DeptKpiDashboard: _loadDashboardData", e);
            this.state.errorMsg = "Failed to load dashboard data.";
            this.state.phase = "error";
        }
    }


    // ── Event handlers ───────────────────────────────────────────────────────
    async onSelectDepartment(ev) {
        const id = parseInt(ev.target.value, 10) || null;
        this.state.selectedDepartmentId = id;
        this.state.evaluations = [];
        this.state.selectedEvaluationId = null;
        if (id) {
            await this._loadEvaluations(id);
        } else {
            this.state.phase = "empty";
        }
    }

    async onSelectEvaluation(ev) {
        const id = parseInt(ev.target.value, 10) || null;
        this.state.selectedEvaluationId = id;
        const ev_obj = this.state.evaluations.find((e) => e.id === id);
        if (ev_obj && this.state.selectedDepartmentId) {
            await this._loadDashboardData(this.state.selectedDepartmentId, ev_obj);
        }
    }

    // ── Chart rendering ───────────────────────────────────────────────────────
    async _renderAllCharts() {
        const d = this.state.data;
        if (!d) return;
        const employees = d.employees || [];

        this._renderChartA(d.task_summary_by_employee || []);
        this._renderChartB(d.project_progress || []);
        this._renderChartC(d.attendance_count || []);
        this._renderChartD(d.bug_count_by_employee || []);
        this._renderChartE(employees);
    }

    _renderChartA(employeeStats) {
        const el = this.refA.el;
        if (!el) return;
        const source = employeeStats;
        const { names, done, pending, total } = buildChartAData(source);
        this._charts.A = new Chart(el, {
            type: "bar",
            data: {
                labels: names,
                datasets: [
                    {
                        label: "Completed",
                        data: done,
                        backgroundColor: C_GREEN + "cc",
                        borderColor: C_GREEN,
                        borderWidth: 1,
                        stack: "tasks",
                    },
                    {
                        label: "Pending",
                        data: pending,
                        backgroundColor: C_AMBER + "99",
                        borderColor: C_AMBER,
                        borderWidth: 1,
                        stack: "tasks",
                    },
                    // Annotation lines: total & completed threshold
                    {
                        label: "Total (line)",
                        data: total,
                        type: "line",
                        borderColor: C_BLUE,
                        borderWidth: 2,
                        borderDash: [5, 4],
                        pointRadius: 3,
                        pointBackgroundColor: C_BLUE,
                        fill: false,
                        tension: 0,
                        stack: undefined,
                        order: -1,
                    },
                ],
            },
            options: {
                ...baseBarOpts("Number of Tasks"),
                plugins: {
                    ...baseBarOpts().plugins,
                    tooltip: {
                        callbacks: {
                            afterBody: (items) => {
                                const idx = items[0].dataIndex;
                                return [`Total: ${total[idx]}`];
                            },
                        },
                    },
                },
            },
        });
    }

    _renderChartB(projectProgress) {
        const el = this.refB.el;
        if (!el) return;

        const source = projectProgress;
        const { projects, pct, totals, done } = buildChartBData(source);

        this._charts.B = new Chart(el, {
            type: "bar",
            data: {
                labels: projects,
                datasets: [{
                    label: "Completion (%)",
                    data: pct,
                    backgroundColor: pct.map((v) =>
                        v >= 80 ? C_GREEN + "cc" :
                            v >= 50 ? C_BLUE + "cc" : C_AMBER + "cc"
                    ),
                    borderColor: pct.map((v) =>
                        v >= 80 ? C_GREEN :
                            v >= 50 ? C_BLUE : C_AMBER
                    ),
                    borderWidth: 1,
                    borderRadius: 5,
                }],
            },
            options: {
                ...baseBarOpts("Progress (%)"),
                scales: {
                    ...baseBarOpts().scales,
                    y: {
                        min: 0, max: 100,
                        title: { display: true, text: "Progress (%)", font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { callback: (v) => v + "%", font: { size: 10 } },
                    },
                },
                plugins: {
                    ...baseBarOpts().plugins,
                    tooltip: {
                        callbacks: {
                            label: (c) => {
                                const i = c.dataIndex;
                                return [
                                    `Progress: ${pct[i]}%`,
                                    `Done: ${done[i]} / ${totals[i]} tasks`,
                                ];
                            },
                        },
                    },
                },
            },
        });
    }

    _renderChartC(attendanceData) {
        const el = this.refC.el;
        if (!el) return;
        const source = attendanceData;
        const data = buildChartCData(source);
        this._charts.C = new Chart(el, {
            type: "line",
            data: {
                labels: data.map((d) => d.name),
                datasets: [{
                    label: "Attendance Count",
                    data: data.map((d) => d.count),
                    borderColor: C_TEAL,
                    backgroundColor: C_TEAL + "22",
                    pointBackgroundColor: data.map((d) => d.color),
                    pointBorderColor: data.map((d) => d.color),
                    pointRadius: 8,
                    pointHoverRadius: 10,
                    tension: 0.25,
                    fill: true,
                }],
            },
            options: {
                ...baseLineOpts("Số lần chấm công", "Nhân viên"),
                scales: {
                    x: {
                        title: { display: true, text: "Nhân viên", font: { size: 11 } },
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: "Số lần chấm công", font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: 1, font: { size: 10 } },
                    },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed.y} lần`,
                        },
                    },
                },
            },
        });
    }

    _renderChartD(bugData) {
        const el = this.refD.el;
        if (!el) return;
        const source = bugData;
        const data = buildChartDData(source);
        this._charts.D = new Chart(el, {
            type: "line",
            data: {
                labels: data.map((d) => d.name),
                datasets: [{
                    label: "Bug Count",
                    data: data.map((d) => d.bugs),
                    borderColor: C_AMBER,
                    backgroundColor: C_AMBER + "22",
                    pointBackgroundColor: data.map((d) => d.color),
                    pointBorderColor: data.map((d) => d.color),
                    pointRadius: 8,
                    pointHoverRadius: 10,
                    tension: 0.25,
                    fill: true,
                }],
            },
            options: {
                ...baseLineOpts("Number of Bugs", "Employee"),
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.label}: ${c.parsed.y} bugs`,
                        },
                    },
                },
                scales: {
                    ...baseLineOpts().scales,
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: "Bug Count", font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: 1, font: { size: 10 } },
                    },
                },
            },
        });
    }

    _renderChartE(employees) {
        const el = this.refE.el;
        if (!el) return;
        const empList = employees.slice(0, 6);
        const { labels, datasets } = buildChartEData(empList);
        this._charts.E = new Chart(el, {
            type: "line",
            data: { labels, datasets },
            options: {
                ...baseLineOpts("Score (0-10)", "Month"),
                scales: {
                    x: {
                        title: { display: true, text: "Month", font: { size: 11 } },
                        grid: { display: false },
                        ticks: { font: { size: 11 } },
                    },
                    y: {
                        min: 0, max: 10,
                        title: { display: true, text: "Score (0-10)", font: { size: 11 } },
                        grid: { color: "rgba(0,0,0,0.05)" },
                        ticks: { stepSize: 1, font: { size: 10 } },
                    },
                },
            },
        });
    }

    _destroyCharts() {
        for (const k of Object.keys(this._charts)) {
            try { this._charts[k].destroy(); } catch (_) { }
        }
        this._charts = {};
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Register as client action
// ─────────────────────────────────────────────────────────────────────────────
registry.category("actions").add("kpi_department_dashboard", DeptKpiDashboard);
