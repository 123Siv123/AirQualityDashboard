/**
 * AQ Monitor — Live Analytics Engine
 * Connects Chart.js to /api/analytics with smooth animated updates.
 */
(function () {
    const chartColors = {
        cyan: "#22d3ee",
        blue: "#38bdf8",
        green: "#22c55e",
        amber: "#f59e0b",
        red: "#ef4444",
        purple: "#a78bfa",
    };

    let payload = {};
    let activePeriod = "today";

    function gasThresholds() {
        const t = payload.thresholds || {};
        return {
            safeMax: t.safe_max || 650,
            moderate: t.moderate || 651,
            moderateMax: t.moderate_max || 850,
            critical: t.critical || 851,
            poorMax: t.poor_max || 2000,
        };
    }

    function gasBarColor(value) {
        const th = gasThresholds();
        const v = Number(value) || 0;
        if (v >= th.critical) {
            return "rgba(239,68,68,0.85)";
        }
        if (v >= th.moderate) {
            return "rgba(245,158,11,0.85)";
        }
        return "rgba(34,211,238,0.85)";
    }
    let charts = {};
    let chartsReady = false;
    let lastUpdatedAt = null;

    function trendLabel(trend) {
        if (trend === "rising") return { text: "▲ Rising", cls: "up" };
        if (trend === "falling") return { text: "▼ Falling", cls: "down" };
        return { text: "■ Stable", cls: "stable" };
    }

    function setTrend(id, trend) {
        const el = document.getElementById(id);
        if (!el) return;
        const t = trendLabel(trend);
        el.textContent = t.text;
        el.className = "kpi-trend-mini " + t.cls;
    }

    function spectrumValues() {
        const kpis = payload.kpis || {};
        const dist = payload.distribution || { normal: 33, moderate: 33, poor: 34 };
        const gauge = payload.gauge || { percent: 50 };
        const avgGas = Number(kpis.avg_gas) || 0;
        const gasLoad = Math.min(100, (avgGas / 300) * 100);
        const tempVal = parseFloat(String(kpis.temperature || "0")) || 0;
        const humVal = parseFloat(String(kpis.humidity || "0")) || 0;
        const tempLoad = Math.min(100, Math.max(0, ((tempVal - 18) / 22) * 100));
        const humLoad = Math.min(100, Math.max(0, humVal));
        const alertLoad = Math.min(100, (dist.poor || 0) + (dist.moderate || 0) * 0.5);
        const stability = Math.min(100, gauge.percent || 50);
        return [gasLoad, tempLoad, humLoad, alertLoad, stability];
    }

    function updateRiskSpectrum() {
        if (!charts.spectrum) return;
        charts.spectrum.data.datasets[0].data = spectrumValues();
        charts.spectrum.update("none");
    }

    function updateStreamMeta() {
        const stream = payload.stream || {};
        const label = document.getElementById("streamLabel");
        const updated = document.getElementById("lastUpdated");
        const pill = document.getElementById("analyticsLivePill");

        if (label) {
            label.textContent = stream.label || "LIVE SENSOR STREAM";
        }
        if (pill) {
            pill.classList.toggle("stream-sim", !stream.live);
        }
        if (updated) {
            const sec = stream.updated_seconds_ago ?? 0;
            updated.textContent =
                sec <= 1 ? "Updated just now" : "Updated " + sec + " sec ago";
        }
    }

    function updateInsights() {
        const list = document.getElementById("insightsList");
        if (!list) return;
        const items = payload.insights || [];
        list.innerHTML = items
            .map(function (text) {
                return "<li>" + text + "</li>";
            })
            .join("");
    }

    function updateAlertBanner() {
        const box = document.getElementById("analyticsInsight");
        const title = document.getElementById("insightTitle");
        const msg = document.getElementById("insightMessage");
        if (!box) return;

        const severity = payload.severity || "safe";
        box.className = "analytics-insight insight--" + severity;

        if (severity === "critical") {
            title.textContent = "🔴 CRITICAL — Live stream elevated";
            msg.textContent =
                "Real-time analytics detected hazardous air quality. Check alerts immediately.";
        } else if (severity === "moderate") {
            title.textContent = "🟠 MODERATE — Trend under watch";
            msg.textContent =
                "Pollution index drifting upward. Monitor gas and humidity correlation.";
        } else {
            title.textContent = "🟢 SAFE — Real-time analytics active";
            msg.textContent =
                "Sensor stream stable. All metrics within expected industrial range.";
        }
    }

    function updateKpis() {
        const kpis = payload.kpis || {};
        const set = function (id, v) {
            const el = document.getElementById(id);
            if (el) el.textContent = v ?? "--";
        };

        set("kpiAvgGas", kpis.avg_gas);
        set("kpiPeakGas", kpis.peak_gas);
        set("kpiSafe", (kpis.safe_percent ?? "--") + (typeof kpis.safe_percent === "number" ? "%" : ""));
        set("kpiAlerts", kpis.alert_count);
        set("kpiTemp", kpis.temperature);
        set("kpiHumidity", kpis.humidity);
        set("heroAqi", payload.display_status || kpis.status);
        set("historyPoints", payload.history_points ?? 0);

        const trends = kpis.trends || {};
        setTrend("trendGas", trends.gas);
        setTrend("trendTemp", trends.temperature);
        setTrend("trendHum", trends.humidity);

        updateRiskSpectrum();
    }

    function chartAnimOptions(base) {
        return Object.assign({}, base, {
            animation: {
                duration: 750,
                easing: "easeOutQuart",
            },
        });
    }

    const CHART_TICK = { color: "#cbd5e1", font: { size: 13, weight: "600" } };
    const CHART_LEGEND = {
        labels: { color: "#e2e8f0", boxWidth: 14, font: { size: 13, weight: "600" } },
    };

    function commonOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: CHART_LEGEND,
                tooltip: {
                    backgroundColor: "rgba(15,23,42,0.95)",
                    borderColor: "rgba(56,189,248,0.3)",
                    borderWidth: 1,
                    titleFont: { size: 14, weight: "700" },
                    bodyFont: { size: 13 },
                },
            },
            scales: {
                x: {
                    ticks: { ...CHART_TICK, maxRotation: 0 },
                    grid: { color: "rgba(255,255,255,0.06)" },
                },
                y: {
                    ticks: CHART_TICK,
                    grid: { color: "rgba(255,255,255,0.06)" },
                },
            },
        };
    }

    function getDataset(period) {
        return (
            (payload.datasets && payload.datasets[period]) ||
            payload.datasets?.today || {
                labels: [],
                gas: [],
                temperature: [],
                humidity: [],
                pollution: [],
            }
        );
    }

    function hideSkeletons() {
        document.querySelectorAll(".chart-skeleton").forEach(function (el) {
            el.classList.add("hidden");
        });
        document.querySelectorAll(".chart-canvas-wrap canvas").forEach(function (c) {
            c.style.opacity = "1";
        });
    }

    function showSkeletons() {
        document.querySelectorAll(".chart-skeleton").forEach(function (el) {
            el.classList.remove("hidden");
        });
    }

    function initCharts() {
        const data = getDataset(activePeriod);
        const dist = payload.distribution || { normal: 70, moderate: 20, poor: 10 };

        charts.spectrum = new Chart(document.getElementById("riskSpectrumChart"), {
            type: "polarArea",
            data: {
                labels: ["Gas load", "Temperature", "Humidity", "Alert pressure", "Stability"],
                datasets: [{
                    label: "Risk factors",
                    data: spectrumValues(),
                    backgroundColor: [
                        "rgba(34,211,238,0.55)",
                        "rgba(56,189,248,0.5)",
                        "rgba(167,139,250,0.5)",
                        "rgba(245,158,11,0.55)",
                        "rgba(34,197,94,0.45)",
                    ],
                    borderColor: [
                        chartColors.cyan,
                        chartColors.blue,
                        chartColors.purple,
                        chartColors.amber,
                        chartColors.green,
                    ],
                    borderWidth: 2,
                }],
            },
            options: chartAnimOptions({
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                        ticks: { display: false },
                        grid: { color: "rgba(255,255,255,0.08)" },
                        pointLabels: {
                            color: "#e2e8f0",
                            font: { size: 13, weight: "700" },
                        },
                    },
                },
            }),
        });

        charts.gas = new Chart(document.getElementById("gasTrendChart"), {
            type: "line",
            data: {
                labels: data.labels,
                datasets: [{
                    label: "Gas Index (live)",
                    data: data.gas,
                    borderColor: chartColors.cyan,
                    backgroundColor: "rgba(34,211,238,0.14)",
                    borderWidth: 3,
                    tension: 0.45,
                    fill: true,
                    pointRadius: 3,
                }],
            },
            options: chartAnimOptions(commonOptions()),
        });

        charts.distribution = new Chart(document.getElementById("distributionChart"), {
            type: "doughnut",
            data: {
                labels: ["Normal", "Moderate", "Poor"],
                datasets: [{
                    data: [dist.normal, dist.moderate, dist.poor],
                    backgroundColor: [chartColors.green, chartColors.amber, chartColors.red],
                    borderWidth: 0,
                }],
            },
            options: chartAnimOptions({
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: { legend: { position: "bottom", labels: CHART_LEGEND.labels } },
            }),
        });

        charts.climate = new Chart(document.getElementById("climateChart"), {
            type: "line",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Temperature °C",
                        data: data.temperature,
                        borderColor: chartColors.blue,
                        tension: 0.4,
                        yAxisID: "y",
                    },
                    {
                        label: "Humidity %",
                        data: data.humidity,
                        borderColor: chartColors.purple,
                        tension: 0.4,
                        yAxisID: "y1",
                    },
                ],
            },
            options: chartAnimOptions({
                ...commonOptions(),
                scales: {
                    x: commonOptions().scales.x,
                    y: {
                        position: "left",
                        ticks: { color: chartColors.blue, font: { size: 13, weight: "600" } },
                        grid: { color: "rgba(255,255,255,0.06)" },
                    },
                    y1: {
                        position: "right",
                        grid: { drawOnChartArea: false },
                        ticks: { color: chartColors.purple, font: { size: 13, weight: "600" } },
                    },
                },
            }),
        });

        charts.indexBar = new Chart(document.getElementById("indexBarChart"), {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [{
                    label: "AQI / Gas Index",
                    data: data.gas,
                    backgroundColor: data.gas.map(gasBarColor),
                    borderRadius: 8,
                }],
            },
            options: chartAnimOptions(commonOptions()),
        });

        charts.radar = new Chart(document.getElementById("pollutionRadarChart"), {
            type: "radar",
            data: {
                labels: data.labels,
                datasets: [{
                    label: "Pollution activity",
                    data: data.pollution,
                    backgroundColor: "rgba(34,211,238,0.2)",
                    borderColor: chartColors.cyan,
                }],
            },
            options: chartAnimOptions({
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        pointLabels: { color: "#e2e8f0", font: { size: 12, weight: "600" } },
                        grid: { color: "rgba(255,255,255,0.1)" },
                        ticks: { color: "#cbd5e1", font: { size: 12, weight: "600" }, backdropColor: "transparent" },
                    },
                },
            }),
        });

        charts.alertMix = new Chart(document.getElementById("alertMixChart"), {
            type: "bar",
            data: {
                labels: ["Normal", "Moderate", "Critical"],
                datasets: [{
                    label: "Severity share",
                    data: [dist.normal, dist.moderate, dist.poor],
                    backgroundColor: [chartColors.green, chartColors.amber, chartColors.red],
                    borderRadius: 8,
                }],
            },
            options: chartAnimOptions({
                indexAxis: "y",
                ...commonOptions(),
                plugins: {
                    legend: { display: false },
                    tooltip: commonOptions().plugins.tooltip,
                },
            }),
        });

        chartsReady = true;
        hideSkeletons();
        resizeAllCharts();
    }

    function applyCharts(period) {
        activePeriod = period;
        const data = getDataset(period);
        const anim = { duration: 600, easing: "easeOutQuart" };

        charts.gas.data.labels = data.labels;
        charts.gas.data.datasets[0].data = data.gas;
        charts.gas.update("active");

        charts.climate.data.labels = data.labels;
        charts.climate.data.datasets[0].data = data.temperature;
        charts.climate.data.datasets[1].data = data.humidity;
        charts.climate.update("active");

        charts.indexBar.data.labels = data.labels;
        charts.indexBar.data.datasets[0].data = data.gas;
        charts.indexBar.data.datasets[0].backgroundColor = data.gas.map(gasBarColor);
        charts.indexBar.update("active");

        charts.radar.data.labels = data.labels;
        charts.radar.data.datasets[0].data = data.pollution;
        charts.radar.update("active");

        document.querySelectorAll(".filter-btn[data-period]").forEach(function (btn) {
            btn.classList.toggle("active", btn.dataset.period === period);
        });
    }

    function updateDistributionCharts() {
        const dist = payload.distribution;
        if (!dist) return;
        charts.distribution.data.datasets[0].data = [dist.normal, dist.moderate, dist.poor];
        charts.distribution.update("active");
        charts.alertMix.data.datasets[0].data = [dist.normal, dist.moderate, dist.poor];
        charts.alertMix.update("active");
    }

    async function refresh() {
        try {
            const res = await fetch("/api/analytics");
            if (!res.ok) return;
            payload = await res.json();
            lastUpdatedAt = Date.now();

            updateStreamMeta();
            updateKpis();
            updateInsights();
            updateAlertBanner();
            updateRiskSpectrum();

            if (!chartsReady) {
                initCharts();
            } else {
                applyCharts(activePeriod);
                updateDistributionCharts();
            }
        } catch (e) {
            console.warn("Analytics refresh failed", e);
        }
    }

    function bindUi() {
        document.querySelectorAll(".filter-btn[data-period]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                applyCharts(btn.dataset.period);
            });
        });
    }

    function resizeAllCharts() {
        Object.keys(charts).forEach(function (key) {
            if (charts[key] && typeof charts[key].resize === "function") {
                charts[key].resize();
            }
        });
    }

    window.AQAnalytics = {
        start: function (initialPayload) {
            if (initialPayload) payload = initialPayload;
            Chart.defaults.color = "#cbd5e1";
            Chart.defaults.borderColor = "rgba(255,255,255,0.08)";
            Chart.defaults.font.family = "Inter, sans-serif";
            Chart.defaults.font.size = 13;
            Chart.defaults.font.weight = "600";
            showSkeletons();
            bindUi();
            updateStreamMeta();
            updateKpis();
            updateInsights();
            updateAlertBanner();

            requestAnimationFrame(function () {
                initCharts();
                setInterval(refresh, 2000);
                refresh();
                window.addEventListener("resize", function () {
                    resizeAllCharts();
                });
            });
        },
    };
})();
