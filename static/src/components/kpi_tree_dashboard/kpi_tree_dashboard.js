/** @odoo-module **/
/**
 * kpi_tree_dashboard.js — KPI Tree Dashboard (3-level tree: Company → Dept → Employee)
 *
 * Registered as client action tag: "kpi_tree_dashboard"
 * Template: static/src/components/kpi_tree_dashboard/kpi_tree_dashboard.xml
 */

import { Component, useState, onMounted, useRef, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

// ─────────────────────────────────────────────────────────────────────────────
// Thresholds: thang 0-10 từ res.config.settings
// final_score, performance_score: thang 0-10
// Khi hiển thị trên UI nhân 10 để ra thang 0-100 dạng %
// ─────────────────────────────────────────────────────────────────────────────

export class KpiTreeDashboard extends Component {
    static template = "performance_evaluator.KpiTreeDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.d3Container = useRef("d3_container");

        this.state = useState({
            loading: true,
            data: null, // response từ get_kpi_tree_data()
            selectedNode: null, // { type: 'company'|'dept'|'emp', id, data }
            expandedDepts: new Set(), // Set of department id — MỞ HẾT khi load
            metric: "final", // 'final' | 'perf' | 'dept'
            selectedPeriod: null, // { start, end, label }
        });

        onMounted(async () => {
            // Khuyên dùng: Tải file d3.js về thư mục static/lib của module
            // await loadJS("/custom_adecsol_hr_performance_evaluator/static/lib/d3.v7.min.js");
            await loadJS("https://d3js.org/d3.v7.min.js");
            this.loadData(); // Giữ nguyên logic gọi RPC của bạn
        });

        onPatched(() => {
            if (!this.state.loading && this.state.data && this.d3Container.el) {
                this.renderD3Tree();
            }
        });
    }

    // ── Getters ───────────────────────────────────────────────────────────────

    /**
     * Tính điểm để hiển thị trên node (thang 0-100 cho %)
     * Vì backend trả final_score / performance_score theo thang 0-10
     */
    nodeScore(nodeData, type) {
        const d = this.state.data;
        console.log("d", d);
        if (!d) return 0;
        // debugger
        // Company node
        if (type === "company") {
            console.log("d.company", d.company);
            return Math.round((d.company.dept_kpi_score || 0) * 10 * 10) / 10;
        }

        // Dept node
        if (type === "dept") {
            const s =
                this.state.metric === "dept"
                    ? nodeData.dept_kpi_score || 0
                    : nodeData.dept_kpi_score || 0;
            return Math.round(s * 10 * 10) / 10;
        }
        // Emp node
        if (type === "emp") {
            const s =
                this.state.metric === "perf"
                    ? nodeData.performance_score || 0
                    : this.state.metric === "dept"
                      ? nodeData.dept_kpi_score || 0
                      : nodeData.final_score || 0;
            // scale 10
            return Math.round(s * 10 * 10) / 10;
        }
        return 0;
    }

    /**
     * levelColor dựa trên score đã nhân ×10 (thang 0-100) và threshold ×10
     */
    levelColor(score) {
        const t = this.state.data?.thresholds;
        if (!t) return "#B4B2A9";
        const exc = t.excellent * 10;
        const pass = t.pass * 10;
        if (score >= exc) return "#1D9E75";
        if (score >= pass) return "#378ADD";
        if (score <= 0) return "#B4B2A9";
        return "#E24B4A";
    }

    levelBg(score) {
        const t = this.state.data?.thresholds;
        if (!t) return "#F1EFE8";
        const exc = t.excellent * 10;
        const pass = t.pass * 10;
        if (score >= exc) return "#E1F5EE";
        if (score >= pass) return "#E6F1FB";
        if (score <= 0) return "#F1EFE8";
        return "#FCEBEB";
    }

    levelBadgeClass(level) {
        const map = {
            excellent: "badge-excellent",
            pass: "badge-pass",
            fail: "badge-fail",
        };
        return "kpi-badge " + (map[level] || "badge-fail");
    }

    stateBadgeLabel(state) {
        const map = {
            self_evaluation: "Tự đánh giá",
            manager_evaluating: "Quản lý đánh giá",
            completed: "Hoàn thành",
            cancel: "Hủy",
        };
        return map[state] || state;
    }

    stateBadgeClass(state) {
        const map = {
            self_evaluation: "state-self",
            manager_evaluating: "state-manager",
            completed: "state-done",
            cancel: "state-cancel",
        };
        return "kpi-state-badge " + (map[state] || "");
    }

    // ── SVG layout ────────────────────────────────────────────────────────────

    get svgWidth() {
        const data = this.state.data;
        if (!data || !data.departments) return 640;
        const slots = data.departments.reduce((sum, dept) => {
            const isExp = this.state.expandedDepts.has(dept.id);
            return sum + (isExp ? Math.max(1, dept.employees.length) : 1);
        }, 0);
        const NODE_W = 120;
        const PADDING = 80;
        return Math.max(640, slots * NODE_W + PADDING);
    }

    get svgHeight() {
        return 380;
    }

    /**
     * Tính tọa độ x cho từng dept và employee node trong SVG
     */
    computeLayout() {
        const data = this.state.data;
        if (!data || !data.departments)
            return { company: null, depts: [], emps: [] };

        const W = this.svgWidth;
        const NODE_W = 120;

        // Company node — top center
        const company = {
            cx: W / 2,
            cy: 60,
            data: { _type: "company", ...data.company },
        };

        // Dept nodes: compute slots
        const depts = [];
        const empRows = [];

        // Tính số slot cần thiết
        let slotStart = 0;
        const PADDING = 40;
        const totalSlots = data.departments.reduce((sum, dept) => {
            const isExp = this.state.expandedDepts.has(dept.id);
            return sum + (isExp ? Math.max(1, dept.employees.length) : 1);
        }, 0);

        // Tổng chiều rộng employee layer
        const totalW = totalSlots * NODE_W;
        const startX = (W - totalW) / 2 + NODE_W / 2;

        for (const dept of data.departments) {
            const isExp = this.state.expandedDepts.has(dept.id);
            const empCount = isExp ? Math.max(1, dept.employees.length) : 1;
            const deptSlotCenter = slotStart + empCount / 2;
            const deptCx = startX + deptSlotCenter * NODE_W - NODE_W / 2;

            depts.push({
                cx: deptCx,
                cy: 190,
                isExpanded: isExp,
                data: { _type: "dept", ...dept },
            });

            if (isExp) {
                dept.employees.forEach((emp, idx) => {
                    const empCx = startX + (slotStart + idx) * NODE_W;
                    empRows.push({
                        cx: empCx,
                        cy: 320,
                        deptCx: deptCx,
                        data: { _type: "emp", ...emp },
                    });
                });
            }

            slotStart += empCount;
        }

        return { company, depts, emps: empRows };
    }

    // ── Data loading ──────────────────────────────────────────────────────────

    async loadData(periodStart = null, periodEnd = null) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "hr.performance.evaluation",
                "get_kpi_tree_data",
                [],
                { period_start: periodStart, period_end: periodEnd },
            );
            this.state.data = data;

            // Mở hết tất cả phòng ban mặc định
            if (data && data.departments) {
                this.state.expandedDepts = new Set(
                    data.departments.map((d) => d.id),
                );
            }

            // Set kỳ đang chọn
            if (!this.state.selectedPeriod && data?.period?.start) {
                this.state.selectedPeriod = data.period;
            }
        } catch (e) {
            console.error("KpiTreeDashboard: loadData error", e);
            this.state.data = null;
        } finally {
            this.state.loading = false;
        }
    }

    // ── Event handlers (arrow class fields — this always bound to component) ──

    onPeriodChange = async (ev) => {
        const idx = parseInt(ev.target.value, 10);
        if (isNaN(idx)) return;
        const period = this.state.data?.available_periods?.[idx];
        if (!period) return;
        this.state.selectedPeriod = period;
        await this.loadData(period.start, period.end);
    };

    /**
     * node = { cx, cy, data: { _type, ... } }
     * Dùng arrow class field để this luôn trỏ đúng component
     * (OWL compile t-on-click arrow wrappers gọi hàm không qua this)
     */
    onNodeClick = (node) => {
        this.state.selectedNode = {
            type: node.data._type,
            id: node.data.id || node.data.employee_id || 0,
            data: node.data,
        };
    };

    selectCompanyNode = () => {
        const data = this.state.data;
        if (!data) return;
        this.state.selectedNode = {
            type: "company",
            id: 0,
            data: { _type: "company", ...data.company },
        };
    };

    toggleDept = (deptId) => {
        const s = new Set(this.state.expandedDepts);
        if (s.has(deptId)) {
            s.delete(deptId);
        } else {
            s.add(deptId);
        }
        this.state.expandedDepts = s;
    };

    onMetricChange = (ev) => {
        this.state.metric = ev.target.value;
    };

    closePanel = () => {
        this.state.selectedNode = null;
    };

    // ── Template helpers ──────────────────────────────────────────────────────

    formatScore(val) {
        if (val == null) return "—";
        return (val * 10).toFixed(1);
    }

    formatPct(val) {
        if (val == null) return "—";
        return (val * 100).toFixed(1) + "%";
    }

    formatPassRate(val) {
        if (val == null) return "—";
        return val.toFixed(1) + "%";
    }

    get metricLabel() {
        return (
            {
                final: "Điểm cuối (Final)",
                perf: "KPI cá nhân",
                dept: "KPI phòng ban",
            }[this.state.metric] || "Điểm cuối"
        );
    }

    get layout() {
        return this.computeLayout();
    }

    // Sparkline hardcode (6 điểm mẫu cho detail panel)
    get sparklinePoints() {
        return [4.5, 5.0, 6.2, 5.8, 7.1, 6.5];
    }

    sparklinePath(points) {
        const w = 120,
            h = 40;
        const max = Math.max(...points, 10);
        const min = Math.min(...points, 0);
        const range = max - min || 1;
        const coords = points.map((v, i) => {
            const x = (i / (points.length - 1)) * w;
            const y = h - ((v - min) / range) * h;
            return `${x},${y}`;
        });
        return `M ${coords.join(" L ")}`;
    }

    // Initials từ tên nhân viên (cho fallback avatar)
    initials(name) {
        if (!name) return "?";
        const parts = name.trim().split(" ");
        if (parts.length >= 2)
            return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        return parts[0][0].toUpperCase();
    }

    // ── BIẾN ĐỔI DỮ LIỆU THÀNH DẠNG HIERARCHY CHO D3 ──
    prepareD3Data() {
        const d = this.state.data;
        if (!d) return null;

        const rootNode = {
            id: "company",
            name: "Công ty",
            _type: "company",
            rawData: d.company,
            children: [],
        };

        d.departments.forEach((dept) => {
            const deptNode = {
                id: `dept_${dept.id}`,
                name: dept.name,
                _type: "dept",
                rawData: dept,
                children: [],
            };

            // Dựa vào expandedDepts để sinh node con
            if (this.state.expandedDepts.has(dept.id)) {
                dept.employees.forEach((emp) => {
                    deptNode.children.push({
                        id: `emp_${emp.employee_id}`,
                        name: emp.name,
                        _type: "emp",
                        rawData: emp,
                    });
                });
            } else if (dept.employees && dept.employees.length > 0) {
                deptNode._hasHiddenChildren = true;
            }
            rootNode.children.push(deptNode);
        });

        return rootNode;
    }

    // ── LOGIC VẼ D3.JS CHÍNH ──
    renderD3Tree() {
        const container = this.d3Container.el;
        container.innerHTML = ""; // Xóa SVG cũ khi vẽ lại

        const treeData = this.prepareD3Data();
        console.log("treeData", treeData);
        if (!treeData) return;

        // Khởi tạo kích thước layout
        const root = d3.hierarchy(treeData);

        // Hàm tính card width — nhận d object (dùng chung cho cả nodeSize lẫn vẽ node)
        const ORG_PAD = 10;
        const ORG_ICON_W = 44;
        const getOrgCardWidth = (d) => {
            const name = d.data
                ? d.data.name || d.data.rawData?.name || ""
                : d || "";
            return Math.max(
                160,
                Math.min(260, name.length * 7 + ORG_ICON_W + ORG_PAD * 2 + 16),
            );
        };

        const AVT = 32,
            PAD = 10,
            GAP = 8;
        const getEmpCardWidth = (d) => {
            const name = d.data
                ? d.data.rawData?.name || d.data.name || ""
                : d || "";
            return Math.max(
                140,
                Math.min(220, name.length * 6.5 + AVT + GAP + PAD * 2 + 20),
            );
        };

        // Tính max width để nodeSize không bị chật
        // Tính max emp card width để nodeSize vừa đủ cho emp layer
        let maxEmpW = 140;
        root.each((d) => {
            if (d.data._type === "emp") {
                maxEmpW = Math.max(maxEmpW, getEmpCardWidth(d));
            }
        });

        const empSlotW = maxEmpW + 20; // khoảng cách tâm-tâm giữa các emp
        const nodeHeight = 150;
        const MIN_NODE_GAP = 24;
        const DEPT_GROUP_GAP = 36;
        const getNodeCardWidth = (d) =>
            d.data._type === "emp" ? getEmpCardWidth(d) : getOrgCardWidth(d);
        const getMinSeparation = (a, b, gap = MIN_NODE_GAP) =>
            (getNodeCardWidth(a) / 2 + getNodeCardWidth(b) / 2 + gap) /
            empSlotW;

        const treeLayout = d3
            .tree()
            .nodeSize([empSlotW, nodeHeight])
            .separation((a, b) => {
                // Emp cùng dept: 1 slot; emp khác dept chỉ nới vừa đủ theo width card.
                if (a.data._type === "emp" && b.data._type === "emp") {
                    const base = a.parent === b.parent ? 1 : 1.2;
                    return Math.max(
                        base,
                        getMinSeparation(
                            a,
                            b,
                            a.parent === b.parent ? MIN_NODE_GAP : DEPT_GROUP_GAP,
                        ),
                    );
                }
                if (a.data._type === "dept" && b.data._type === "dept") {
                    const bothExpanded = Boolean(a.children && b.children);
                    return Math.max(
                        bothExpanded ? 1.15 : 1,
                        getMinSeparation(
                            a,
                            b,
                            bothExpanded ? DEPT_GROUP_GAP : MIN_NODE_GAP,
                        ),
                    );
                }
                return Math.max(1, getMinSeparation(a, b));
            });
        treeLayout(root);

        // Tính toán bounding box để canvas luôn fit hoặc scroll
        let x0 = Infinity,
            x1 = -x0,
            y1 = -x0;
        root.each((d) => {
            if (d.x > x1) x1 = d.x;
            if (d.x < x0) x0 = d.x;
            if (d.y > y1) y1 = d.y;
        });

        const svg = d3
            .select(container)
            .append("svg")
            .attr("width", x1 - x0 + empSlotW * 2)
            .attr("height", y1 + nodeHeight * 2)
            .append("g")
            .attr("transform", `translate(${-(x0 - empSlotW)}, 60)`);

        // 1. Vẽ Link (Đường nối)
        const link = svg
            .append("g")
            .attr("fill", "none")
            .attr("stroke-opacity", 0.5)
            .attr("stroke-width", 1.5)
            .selectAll("path")
            .data(root.links())
            .join("path")
            .attr("stroke", (d) =>
                this.levelColor(this.nodeScore(d.target.data.rawData)),
            )
            .attr("stroke-dasharray", (d) =>
                d.target.data._type === "emp" ? "3 2" : "4 2",
            )
            .attr(
                "d",
                d3
                    .linkVertical()
                    .x((d) => d.x)
                    .y((d) => d.y),
            );

        // 2. Vẽ Node
        const node = svg
            .append("g")
            .selectAll("g")
            .data(root.descendants())
            .join("g")
            .attr("transform", (d) => `translate(${d.x},${d.y})`)
            .attr("class", "kpi-d3-node")
            .style("cursor", "pointer")
            .on("click", (event, d) => {
                this.onNodeClick({
                    data: {
                        _type: d.data._type,
                        ...d.data.rawData, // Trải phẳng dữ liệu Odoo gốc ra để panel bên phải đọc được
                    },
                });
            });

        // 3. Render nội dung thẻ Node (Rect + Text)
        // === COMPANY & DEPT NODES ===
        const orgNodes = node.filter((d) => d.data._type !== "emp");

        // Card rect (company/dept)
        // Dynamic width cho dept/company theo tên
        // const ORG_PAD = 10;
        // const ORG_ICON_W = 44; // vùng icon bên trái (circle + gap)
        // const getOrgCardWidth = (d) => {
        //     const name = d.data.name || d.data.rawData?.name || "";
        //     return Math.max(
        //         160,
        //         Math.min(260, name.length * 7 + ORG_ICON_W + ORG_PAD * 2 + 16),
        //     );
        // };
        const orgCardH = 72;

        // Card rect (company/dept)
        orgNodes
            .append("rect")
            .attr("class", "kpi-card-rect")
            .attr("x", (d) => -getOrgCardWidth(d) / 2)
            .attr("y", -orgCardH / 2)
            .attr("width", (d) => getOrgCardWidth(d))
            .attr("height", orgCardH)
            .attr("rx", 10)
            .attr("fill", (d) =>
                this.levelBg(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .attr("stroke", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .attr("stroke-width", 1.5);

        // Icon background circle (left side)
        orgNodes
            .append("circle")
            .attr("cx", (d) => -getOrgCardWidth(d) / 2 + ORG_PAD + 18)
            .attr("cy", 0)
            .attr("r", 18)
            .attr("fill", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .attr("opacity", 0.12);

        // Icon symbol
        orgNodes
            .append("text")
            .attr("x", (d) => -getOrgCardWidth(d) / 2 + ORG_PAD + 18)
            .attr("dy", "0.35em")
            .attr("text-anchor", "middle")
            .attr("font-family", "FontAwesome")
            .attr("font-size", "16px")
            .attr("fill", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .text((d) => (d.data._type === "company" ? "\uf0ac" : "\uf1ad"));

        // Tên node (trên, bên phải icon)
        const orgTextX = (d) => -getOrgCardWidth(d) / 2 + ORG_PAD + ORG_ICON_W;
        orgNodes
            .append("text")
            .attr("class", "kpi-name-text")
            .attr("x", orgTextX)
            .attr("y", -10)
            .attr("text-anchor", "start")
            .attr("font-size", "14px")
            .attr("font-weight", 600)
            .attr("fill", "#6b7280")
            .text((d) => {
                const name = d.data.name || d.data.rawData?.name || "—";
                // Tính max chars dựa trên width thực tế của text area
                const textAreaW = getOrgCardWidth(d) - ORG_ICON_W - ORG_PAD * 2;
                const maxChars = Math.floor(textAreaW / 7);
                return name.length > maxChars
                    ? name.slice(0, maxChars) + "…"
                    : name;
            });

        // Điểm (dưới, bên phải icon)
        orgNodes
            .append("text")
            .attr("class", "kpi-score-text")
            .attr("x", orgTextX)
            .attr("y", 14)
            .attr("text-anchor", "start")
            .attr("font-size", "18px")
            .attr("font-weight", 800)
            .attr("fill", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .text((d) => {
                const score = this.nodeScore(d.data.rawData, d.data._type);
                return score != null ? `${score}%` : "—";
            });

        // === EMPLOYEE NODES ===
        const empNodes = node.filter((d) => d.data._type === "emp");

        // Layout: avatar trái (32px) + padding + text phải
        // Card width động theo tên
        // const AVT = 32; // avatar size
        // const PAD = 10; // padding trong card
        // const GAP = 8; // khoảng cách avatar - text
        // const getEmpCardWidth = (d) => {
        //     const name = d.data.rawData?.name || d.data.name || "";
        //     return Math.max(
        //         140,
        //         Math.min(220, name.length * 6.5 + AVT + GAP + PAD * 2 + 20),
        //     );
        // };
        const cardH = 60;

        // Card rect
        empNodes
            .append("rect")
            .attr("class", "kpi-card-rect")
            .attr("x", (d) => -getEmpCardWidth(d) / 2)
            .attr("y", -cardH / 2)
            .attr("width", (d) => getEmpCardWidth(d))
            .attr("height", cardH)
            .attr("rx", 10)
            .attr("fill", (d) =>
                this.levelBg(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .attr("stroke", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .attr("stroke-width", 1.5);

        // Avatar — dùng foreignObject để border-radius hoạt động, không cần clipPath
        empNodes
            .append("foreignObject")
            .attr("x", (d) => -getEmpCardWidth(d) / 2 + PAD)
            .attr("y", -AVT / 2)
            .attr("width", AVT)
            .attr("height", AVT)
            .append("xhtml:div")
            .style("width", AVT + "px")
            .style("height", AVT + "px")
            .style("border-radius", "6px")
            .style("overflow", "hidden")
            .style(
                "background",
                (d) =>
                    this.levelColor(
                        this.nodeScore(d.data.rawData, d.data._type),
                    ) + "22",
            )
            .style("display", "flex")
            .style("align-items", "center")
            .style("justify-content", "center")
            .style("font-size", "10px")
            .style("font-weight", "700")
            .style("color", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .each(function (d) {
                const avatarUrl = d.data.rawData?.avatar_url;
                const name = d.data.rawData?.name || d.data.name || "?";
                const initials = name
                    .trim()
                    .split(" ")
                    .map((p) => p[0])
                    .slice(0, 2)
                    .join("")
                    .toUpperCase();
                const div = d3.select(this);
                if (avatarUrl) {
                    div.append("xhtml:img")
                        .attr("src", avatarUrl)
                        .style("width", AVT + "px")
                        .style("height", AVT + "px")
                        .style("object-fit", "cover")
                        .style("display", "block");
                } else {
                    div.text(initials);
                }
            });

        // Text x bắt đầu từ: -cardWidth/2 + PAD + AVT + GAP
        const textX = (d) => -getEmpCardWidth(d) / 2 + PAD + AVT + GAP;

        // Tên nhân viên (trên)
        empNodes
            .append("text")
            .attr("class", "kpi-name-text")
            .attr("x", textX)
            .attr("y", -7)
            .attr("text-anchor", "start")
            .attr("font-size", "14px")
            .attr("font-weight", 600)
            .attr("fill", "#4b5563")
            .text((d) => {
                const name = d.data.rawData?.name || d.data.name || "—";
                return name.length > 18 ? name.slice(0, 18) + "…" : name;
            });

        // Điểm (dưới tên)
        empNodes
            .append("text")
            .attr("class", "kpi-score-text")
            .attr("x", textX)
            .attr("y", 12)
            .attr("text-anchor", "start")
            .attr("font-size", "15px")
            .attr("font-weight", 800)
            .attr("fill", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            )
            .text((d) => {
                const score = this.nodeScore(d.data.rawData, d.data._type);
                return score != null ? `${score}%` : "—";
            });

        // ── 4. Vẽ icon Toggle (+/-) cho Department Node ──────────────────────
        const deptNodes = node.filter(
            (d) =>
                d.data._type === "dept" &&
                (d.children || d.data._hasHiddenChildren),
        );

        const toggleBtn = deptNodes
            .append("g")
            .attr("class", "kpi-toggle-btn")
            .attr(
                "transform",
                (d) =>
                    `translate(${getOrgCardWidth(d) / 2 - 2}, ${-orgCardH / 2 + 8})`,
            )
            .on("click", (event, d) => {
                event.stopPropagation();
                this.toggleDept(d.data.rawData.id);
            });

        toggleBtn
            .append("circle")
            .attr("r", 9)
            .attr("fill", (d) =>
                this.levelColor(this.nodeScore(d.data.rawData, d.data._type)),
            );

        toggleBtn
            .append("text")
            .attr("dy", "0.35em")
            .attr("text-anchor", "middle")
            .attr("fill", "white")
            .attr("font-size", 13)
            .attr("font-weight", 700)
            .text((d) => (d.children ? "−" : "+"));
    }
}

registry.category("actions").add("kpi_tree_dashboard", KpiTreeDashboard);
