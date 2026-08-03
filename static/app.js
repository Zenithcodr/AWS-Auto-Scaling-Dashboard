const state = {
  charts: {},
  dashboardRequestInFlight: false,
  controlRequestInFlight: false,
  controlPageRequestInFlight: false,
};

const AUTO_REFRESH_SECONDS = 10;

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function hasMetricValue(value) {
  return value !== null && value !== undefined && value !== "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function choosePrecision(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  if (Math.abs(numeric % 1) < 0.001) return 0;
  return Math.abs(numeric) < 10 ? 2 : 1;
}

function formatNumeric(value, { suffix = "", maximumFractionDigits } = {}) {
  if (!hasMetricValue(value)) return "N/A";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);

  return `${numeric.toLocaleString(undefined, {
    maximumFractionDigits:
      maximumFractionDigits !== undefined ? maximumFractionDigits : choosePrecision(numeric),
  })}${suffix}`;
}

function easeOutCubic(progress) {
  return 1 - Math.pow(1 - progress, 3);
}

function pulseElement(element) {
  if (!element || prefersReducedMotion.matches) return;
  element.classList.remove("pulse-update");
  void element.offsetWidth;
  element.classList.add("pulse-update");
}

function animateNumericTextByIds(elementIds, value, options = {}) {
  elementIds.forEach((elementId) => {
    animateNumericText(document.getElementById(elementId), value, options);
  });
}

function animateNumericText(element, value, options = {}) {
  if (!element) return;
  if (!hasMetricValue(value) || !Number.isFinite(Number(value))) {
    element.textContent = formatNumeric(value, options);
    return;
  }

  const targetValue = Number(value);
  const currentValue = Number(element.dataset.value || 0);
  const duration = prefersReducedMotion.matches ? 0 : 850;

  if (duration === 0 || currentValue === targetValue) {
    element.textContent = formatNumeric(targetValue, options);
    element.dataset.value = String(targetValue);
    return;
  }

  const startTime = performance.now();

  const tick = (timestamp) => {
    const elapsed = timestamp - startTime;
    const progress = Math.min(1, elapsed / duration);
    const eased = easeOutCubic(progress);
    const nextValue = currentValue + (targetValue - currentValue) * eased;
    element.textContent = formatNumeric(nextValue, options);

    if (progress < 1) {
      window.requestAnimationFrame(tick);
      return;
    }

    element.textContent = formatNumeric(targetValue, options);
    element.dataset.value = String(targetValue);
    pulseElement(element);
  };

  window.requestAnimationFrame(tick);
}

function setText(elementId, text) {
  const element = document.getElementById(elementId);
  if (element) element.textContent = text;
}

function applyTone(element, tone, label) {
  if (!element) return;
  element.dataset.tone = tone;
  element.textContent = label;
}

function apiFetch(url, options = {}) {
  return fetch(url, options).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}`);
    }
    return payload;
  });
}

function setRefreshButtonState(isLoading) {
  const button = document.getElementById("refreshDashboardBtn");
  if (!button) return;
  button.disabled = isLoading;
  button.textContent = isLoading ? "Refreshing..." : "Refresh Now";
}

function getAutoRefreshSeconds() {
  const configured = Number(window.APP_BOOTSTRAP?.pollIntervalSeconds || AUTO_REFRESH_SECONDS);
  if (!Number.isFinite(configured) || configured <= 0) return AUTO_REFRESH_SECONDS;
  return Math.min(configured, AUTO_REFRESH_SECONDS);
}

function buildLabels(history) {
  return history.map((row) =>
    new Date(row.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}

function buildSeriesLabels(series) {
  return (series || []).map((point) =>
    new Date(point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}

function dedupeSeriesByTimestamp(series) {
  const seriesMap = new Map();
  (series || []).forEach((point) => {
    if (!point?.timestamp) return;
    seriesMap.set(point.timestamp, {
      timestamp: point.timestamp,
      value: hasMetricValue(point.value) && !Number.isNaN(Number(point.value))
        ? Number(point.value)
        : point.value,
    });
  });

  return Array.from(seriesMap.values()).sort(
    (left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime()
  );
}

function dedupeHistoryRows(history) {
  const rowMap = new Map();
  (history || []).forEach((row) => {
    if (!row?.timestamp) return;
    rowMap.set(row.timestamp, row);
  });

  return Array.from(rowMap.values()).sort(
    (left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime()
  );
}

function buildHistorySeries(history, fieldName) {
  return dedupeHistoryRows(history)
    .filter((row) => row.timestamp && hasMetricValue(row[fieldName]) && !Number.isNaN(Number(row[fieldName])))
    .map((row) => ({
      timestamp: row.timestamp,
      value: Number(row[fieldName]),
    }));
}

function buildGradient(ctx, topColor, bottomColor) {
  const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height || 260);
  gradient.addColorStop(0, topColor);
  gradient.addColorStop(1, bottomColor);
  return gradient;
}

function buildLineDataset(ctx, dataset) {
  const shouldFill = dataset.fill !== undefined ? dataset.fill : true;
  return {
    label: dataset.label,
    data: dataset.data,
    borderColor: dataset.borderColor,
    backgroundColor:
      shouldFill && dataset.fillTop && dataset.fillBottom
        ? buildGradient(ctx, dataset.fillTop, dataset.fillBottom)
        : dataset.backgroundColor || "transparent",
    fill: shouldFill,
    borderWidth: dataset.borderWidth ?? 2,
    borderDash: dataset.borderDash || [],
    pointRadius: dataset.pointRadius ?? 0,
    pointHoverRadius: dataset.pointHoverRadius ?? 3,
    pointHoverBackgroundColor: dataset.pointHoverBackgroundColor || "#f7fff2",
    tension: dataset.tension ?? 0.38,
  };
}

function upsertLineChart({
  canvasId,
  label,
  labels,
  data,
  borderColor,
  fillTop,
  fillBottom,
  datasets,
  yMax,
  yTickSuffix = "",
  legendDisplay = false,
}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const normalizedDatasets = (datasets && datasets.length
    ? datasets
    : [
        {
          label,
          data,
          borderColor,
          fillTop,
          fillBottom,
        },
      ]
  ).map((dataset) => buildLineDataset(ctx, dataset));
  const existing = state.charts[canvasId];

  if (existing) {
    existing.data.labels = labels;
    existing.data.datasets = normalizedDatasets;
    existing.options.plugins.legend.display = legendDisplay;
    existing.options.scales.y.max = yMax;
    existing.options.scales.y.ticks.callback = (value) =>
      formatNumeric(value, { suffix: yTickSuffix });
    existing.options.plugins.tooltip.callbacks = {
      label: (tooltipItem) =>
        `${tooltipItem.dataset.label}: ${formatNumeric(tooltipItem.parsed.y, {
          suffix: yTickSuffix,
        })}`,
    };
    existing.update();
    return;
  }

  state.charts[canvasId] = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: normalizedDatasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: prefersReducedMotion.matches ? 0 : 900,
        easing: "easeOutCubic",
      },
      interaction: {
        intersect: false,
        mode: "index",
      },
      plugins: {
        legend: {
          display: legendDisplay,
          labels: {
            color: "rgba(240, 244, 235, 0.72)",
            boxWidth: 14,
            boxHeight: 14,
            usePointStyle: true,
            pointStyle: "line",
            padding: 16,
          },
        },
        tooltip: {
          backgroundColor: "rgba(11, 14, 12, 0.94)",
          borderColor: "rgba(214, 230, 202, 0.18)",
          borderWidth: 1,
          titleColor: "#f7fff2",
          bodyColor: "rgba(247, 255, 242, 0.88)",
          displayColors: false,
          padding: 12,
          callbacks: {
            label: (tooltipItem) =>
              `${tooltipItem.dataset.label}: ${formatNumeric(tooltipItem.parsed.y, {
                suffix: yTickSuffix,
              })}`,
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          max: yMax,
          grid: {
            color: "rgba(240, 244, 235, 0.08)",
            drawBorder: false,
          },
          ticks: {
            color: "rgba(240, 244, 235, 0.58)",
            callback: (value) => formatNumeric(value, { suffix: yTickSuffix }),
          },
        },
        x: {
          grid: { display: false, drawBorder: false },
          ticks: {
            color: "rgba(240, 244, 235, 0.44)",
            maxTicksLimit: 8,
          },
        },
      },
    },
  });
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "unknown time";
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return String(timestamp);
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function extractCpuFromMessage(message) {
  const match = String(message || "").match(/Average CPU\s+([0-9]+(?:\.[0-9]+)?)%/i);
  if (!match) return null;
  return Number(match[1]);
}

function getLatestSubmittedScalingEvent(events) {
  const candidates = (events || []).filter((event) => {
    const action = String(event.action || "").toLowerCase();
    const source = String(event.event_source || "").toLowerCase();
    const result = String(event.result || "").toLowerCase();
    return source === "controller" && result === "submitted" && ["scale_out", "scale_in"].includes(action);
  });

  if (!candidates.length) return null;

  return candidates.reduce((latest, event) => {
    if (!latest) return event;
    return new Date(event.timestamp).getTime() > new Date(latest.timestamp).getTime() ? event : latest;
  }, null);
}

function toneForResult(result) {
  const normalized = String(result || "").toLowerCase();
  if (normalized.includes("error") || normalized.includes("failed")) return "danger";
  if (normalized.includes("success") || normalized.includes("submitted")) return "healthy";
  if (normalized.includes("pending") || normalized.includes("progress")) return "warn";
  return "neutral";
}

function toneForInstanceState(instance) {
  const stateName = String(instance.state || "").toLowerCase();
  const healthName = String(instance.health_status || "").toLowerCase();
  if (stateName === "running" && (healthName === "healthy" || healthName === "unknown")) {
    return "healthy";
  }
  if (stateName === "stopped" || healthName === "unhealthy") return "danger";
  if (stateName === "pending" || healthName === "initializing") return "warn";
  return "neutral";
}

function renderEvents(events) {
  const container = document.getElementById("eventsList");
  if (!container) return;

  if (!events.length) {
    container.innerHTML = '<div class="event-item">No events recorded yet.</div>';
    return;
  }

  container.innerHTML = events
    .map((event) => {
      const action = escapeHtml(event.action || event.event_type || "event");
      const message = escapeHtml(event.message || "No message provided.");
      const source = escapeHtml(event.event_source || "unknown source");
      const result = escapeHtml(event.result || "n/a");
      const timestamp = escapeHtml(formatTimestamp(event.timestamp));
      const details = event.details ? `<div class="event-meta">${escapeHtml(event.details)}</div>` : "";

      return `
        <article class="event-item">
          <div class="event-item-top">
            <strong>${action}</strong>
            <span class="event-badge" data-tone="${toneForResult(result)}">${result}</span>
          </div>
          <p>${message}</p>
          <div class="event-meta">${timestamp} | ${source}</div>
          ${details}
        </article>
      `;
    })
    .join("");
}

function renderInstances(instances) {
  const body = document.getElementById("instancesTableBody");
  if (!body) return;

  if (!instances.length) {
    body.innerHTML = '<tr><td colspan="7">No instances matched the configured filters.</td></tr>';
    return;
  }

  body.innerHTML = instances
    .map((instance) => {
      const tone = toneForInstanceState(instance);
      return `
        <tr>
          <td>${escapeHtml(instance.instance_id)}</td>
          <td><span class="table-badge" data-tone="${tone}">${escapeHtml(instance.state || "unknown")}</span></td>
          <td>${escapeHtml(instance.health_status || "unknown")}</td>
          <td>${escapeHtml(instance.lifecycle_state || "standalone")}</td>
          <td>${escapeHtml(instance.availability_zone || "N/A")}</td>
          <td>${escapeHtml(instance.private_ip || "N/A")}</td>
          <td>${escapeHtml(instance.instance_type || "N/A")}</td>
        </tr>
      `;
    })
    .join("");
}

function summarizeInstances(instances, desiredCapacity) {
  const lifecycleCounts = new Map();
  let protectedCount = 0;

  instances.forEach((instance) => {
    const lifecycle = instance.lifecycle_state || instance.state || "unknown";
    lifecycleCounts.set(lifecycle, (lifecycleCounts.get(lifecycle) || 0) + 1);
    if (instance.protected_from_scale_in) {
      protectedCount += 1;
    }
  });

  const actualCount = instances.filter((instance) =>
    ["running", "pending"].includes(String(instance.state || "").toLowerCase())
  ).length;
  const safeDesired = Number(desiredCapacity || 0);
  const scalingGap = actualCount - safeDesired;

  const summary = [
    {
      label: "Convergence",
      value:
        scalingGap === 0
          ? `Desired and actual both at ${formatNumeric(actualCount)}`
          : scalingGap > 0
            ? `${formatNumeric(actualCount)} active while desired is ${formatNumeric(safeDesired)}`
            : `${formatNumeric(safeDesired)} desired while ${formatNumeric(actualCount)} are active`,
      tone: scalingGap === 0 ? "healthy" : "warn",
    },
  ];

  Array.from(lifecycleCounts.entries())
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .forEach(([lifecycle, count]) => {
      const normalized = String(lifecycle).toLowerCase();
      const tone =
        normalized.includes("service") || normalized === "running"
          ? "healthy"
          : normalized.includes("pending") || normalized.includes("terminating")
            ? "warn"
            : "neutral";

      summary.push({
        label: lifecycle,
        value: `${formatNumeric(count)} instance${count === 1 ? "" : "s"}`,
        tone,
      });
    });

  if (protectedCount > 0) {
    summary.push({
      label: "Scale-In Protected",
      value: `${formatNumeric(protectedCount)} protected instance${protectedCount === 1 ? "" : "s"}`,
      tone: "danger",
    });
  }

  return summary;
}

function renderInstanceStateSummary(instances, desiredCapacity) {
  const container = document.getElementById("instanceStateSummary");
  if (!container) return;

  if (!instances.length) {
    container.innerHTML = `
      <article class="state-pill" data-tone="neutral">
        <span class="state-pill__label">Fleet Summary</span>
        <strong>No instances matched the current filters.</strong>
      </article>
    `;
    return;
  }

  container.innerHTML = summarizeInstances(instances, desiredCapacity)
    .map(
      (item) => `
        <article class="state-pill" data-tone="${escapeHtml(item.tone)}">
          <span class="state-pill__label">${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
        </article>
      `
    )
    .join("");
}

function renderControllerSummary(controllerState, controllerResult, events) {
  const container = document.getElementById("controllerSummary");
  if (!container) return;

  const lastSubmittedScalingEvent = getLatestSubmittedScalingEvent(events);
  const triggerCpu = extractCpuFromMessage(lastSubmittedScalingEvent?.message);
  const triggerSummary = lastSubmittedScalingEvent
    ? `${String(lastSubmittedScalingEvent.action || "").replaceAll("_", " ")} at ${formatTimestamp(
        lastSubmittedScalingEvent.timestamp
      )}${hasMetricValue(triggerCpu) ? ` on ${formatNumeric(triggerCpu, { suffix: "%" })} CPU` : ""}`
    : "No submitted scale action in the current event window.";

  const summaryItems = [
    {
      label: "Mode",
      value: controllerState.mode || "unknown",
    },
    {
      label: "Active Control",
      value: controllerState.active_control ? "Enabled" : "Monitoring only",
    },
    {
      label: "Thresholds",
      value: `Out ${formatNumeric(controllerState.scale_out_cpu_threshold, { suffix: "%" })} / In ${formatNumeric(controllerState.scale_in_cpu_threshold, { suffix: "%" })}`,
    },
    {
      label: "Bounds",
      value: `Min ${controllerState.min_instances ?? "N/A"} / Max ${controllerState.max_instances ?? "N/A"}`,
    },
    {
      label: "Cooldown",
      value: `${formatNumeric(controllerState.cooldown_seconds)}s`,
    },
    {
      label: "Last Trigger",
      value: triggerSummary,
    },
    {
      label: "Latest Result",
      value: controllerResult.reason || controllerState.last_reason || "No recent controller output.",
    },
  ];

  container.innerHTML = summaryItems
    .map(
      (item) => `
        <article class="summary-item">
          <span>${escapeHtml(item.label)}</span>
          <strong>${escapeHtml(item.value)}</strong>
        </article>
      `
    )
    .join("");
}

function renderRecommendations(payload, derived) {
  const container = document.getElementById("recommendationsList");
  if (!container) return;

  const controllerState = payload.controller_state || {};
  const targetHealth = payload.target_health || {};
  const targetHealthCounts = targetHealth.counts || {};
  const recommendations = [];

  if (hasMetricValue(derived.cpu) && hasMetricValue(controllerState.scale_out_cpu_threshold)) {
    if (Number(derived.cpu) >= Number(controllerState.scale_out_cpu_threshold) - 5) {
      recommendations.push({
        title: "CPU is nearing scale-out threshold",
        body: `Average CPU is ${formatNumeric(derived.cpu, { suffix: "%" })}, close to the ${formatNumeric(
          controllerState.scale_out_cpu_threshold,
          { suffix: "%" }
        )} scale-out boundary.`,
        accent: true,
      });
    }
  }

  if (Number(targetHealthCounts.unhealthy || 0) > 0) {
    const unhealthyReasons = (targetHealth.targets || [])
      .filter((target) => String(target.state || "").toLowerCase() === "unhealthy")
      .map((target) => target.reason || target.description)
      .filter(Boolean)
      .slice(0, 2);

    recommendations.push({
      title: "ALB target group reports unhealthy targets",
      body:
        unhealthyReasons.length > 0
          ? unhealthyReasons.join(" | ")
          : `${formatNumeric(targetHealthCounts.unhealthy)} targets are currently unhealthy. Check target group port, health path, and security-group access to the app port.`,
    });
  }

  if (
    hasMetricValue(derived.healthyHosts) &&
    hasMetricValue(derived.desiredCapacity) &&
    Number(derived.healthyHosts) < Number(derived.desiredCapacity)
  ) {
    recommendations.push({
      title: "Target health is below desired capacity",
      body: `${formatNumeric(derived.healthyHosts)} healthy targets are serving traffic while desired capacity is ${formatNumeric(
        derived.desiredCapacity
      )}. Check target registration and startup times.`,
    });
  }

  if (controllerState.mode !== "custom") {
    recommendations.push({
      title: "Controller is in monitoring mode",
      body: "Switch to custom mode only if you want this app to submit scaling decisions automatically.",
    });
  } else if (!controllerState.active_control) {
    recommendations.push({
      title: "Active control is disabled",
      body: "Telemetry is live, but the app will not submit automatic scaling actions until active control is enabled.",
    });
  }

  if (!recommendations.length) {
    recommendations.push({
      title: "System is operating within its configured envelope",
      body: "Current metrics, capacity bounds, and controller state look stable. Keep monitoring the next refresh cycle for drift.",
      accent: true,
    });
  }

  recommendations.push({
    title: `${formatNumeric(derived.headroom)} headroom remaining`,
    body: `Desired capacity is ${formatNumeric(derived.desiredCapacity)} out of a configured maximum of ${formatNumeric(
      controllerState.max_instances
    )}.`,
  });

  container.innerHTML = recommendations
    .slice(0, 3)
    .map(
      (recommendation) => `
        <article class="recommendation-card${recommendation.accent ? " recommendation-card--accent" : ""}">
          <strong>${escapeHtml(recommendation.title)}</strong>
          <p>${escapeHtml(recommendation.body)}</p>
        </article>
      `
    )
    .join("");
}

function renderActivityStrip(series) {
  const container = document.getElementById("activityHeatmap");
  if (!container) return;

  if (!series.length) {
    container.innerHTML = "";
    return;
  }

  const recentPoints = series.slice(-72);
  const values = recentPoints.map((point) => Number(point.value || 0));
  const maxValue = Math.max(...values, 1);

  container.innerHTML = recentPoints
    .map((point, index) => {
      const intensity = Math.max(0.12, Number(point.value || 0) / maxValue);
      return `<span class="activity-dot" style="--intensity:${intensity.toFixed(3)}; --delay:${index * 40}ms" title="${escapeHtml(
        `${formatNumeric(point.value)} at ${formatTimestamp(point.timestamp)}`
      )}"></span>`;
    })
    .join("");
}

function updateCapacityMeter(headroomPercent, desiredCapacity, maxInstances, actualCapacity) {
  const safePercent = Math.max(0, Math.min(100, Number(headroomPercent || 0)));
  const fill = document.getElementById("capacityMeterFill");
  if (fill) {
    fill.style.width = `${safePercent}%`;
  }

  setText("capacityMeterValue", `${Math.round(safePercent)}%`);
  const detailText = `Desired ${formatNumeric(desiredCapacity)} / Actual ${formatNumeric(actualCapacity)} / Max ${formatNumeric(maxInstances)}`;
  setText("desiredCapacityDetail", detailText);
  setText("capacityMeterDetail", detailText);
}

function refreshHeaderClock() {
  const now = new Date();
  const currentTime = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  setText("liveClock", currentTime);
  setText("headlineTime", currentTime);

  const dateLabel = now.toLocaleDateString([], { day: "numeric", month: "long" });
  const fullDateLabel = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });

  if (document.getElementById("headlineDate")) {
    setText("headlineDate", dateLabel);
  }
  if (document.getElementById("liveDate") && !document.body.dataset.latestSnapshotDate) {
    setText("liveDate", fullDateLabel);
  }
}

function setDashboardModeChips(controllerState) {
  const isCustom = controllerState.mode === "custom";
  const tone = isCustom ? (controllerState.active_control ? "custom" : "muted") : "passive";
  const label = isCustom
    ? controllerState.active_control
      ? "Custom Control Active"
      : "Custom Monitoring"
    : "AWS Managed";

  applyTone(document.getElementById("controlModeChip"), tone, label);
  applyTone(document.getElementById("operatingMode"), tone, controllerState.mode || "unknown");
}

function renderCpuTelemetry(controllerState, cpuSeries, events) {
  const latestCpuPoint = cpuSeries.length ? cpuSeries.at(-1) : null;
  const lastSubmittedScalingEvent = getLatestSubmittedScalingEvent(events);
  const triggerCpu = extractCpuFromMessage(lastSubmittedScalingEvent?.message);

  setText(
    "cpuThresholdChip",
    `Out ${formatNumeric(controllerState.scale_out_cpu_threshold, { suffix: "%" })} / In ${formatNumeric(
      controllerState.scale_in_cpu_threshold,
      { suffix: "%" }
    )}`
  );

  setText(
    "cpuSampleChip",
    latestCpuPoint
      ? `${formatNumeric(latestCpuPoint.value, { suffix: "%" })} at ${formatTimestamp(latestCpuPoint.timestamp)}`
      : "CloudWatch sample not available yet."
  );

  setText(
    "lastScaleActionChip",
    lastSubmittedScalingEvent
      ? `${String(lastSubmittedScalingEvent.action || "").replaceAll("_", " ")} at ${formatTimestamp(
          lastSubmittedScalingEvent.timestamp
        )}${hasMetricValue(triggerCpu) ? ` on ${formatNumeric(triggerCpu, { suffix: "%" })} CPU` : ""}`
      : "No scaling action has been submitted yet."
  );
}

function renderDashboard(payload) {
  const summary = payload.summary || {};
  const history = dedupeHistoryRows(payload.history || []);
  const events = payload.events || [];
  const controllerState = payload.controller_state || {};
  const controllerResult = payload.controller_result || {};
  const targetHealth = payload.target_health || {};
  const targetHealthCounts = targetHealth.counts || {};
  const historyCpuSeries = buildHistorySeries(history, "average_cpu");
  const historyRequestSeries = buildHistorySeries(history, "request_count");
  const historyDesiredCapacitySeries = buildHistorySeries(history, "desired_capacity");
  const historyInstanceCountSeries = buildHistorySeries(history, "instance_count");
  const historyHealthyHostSeries = buildHistorySeries(history, "healthy_host_count");
  const cpuSeries = dedupeSeriesByTimestamp(
    payload.raw_series?.cpu?.length ? payload.raw_series.cpu : historyCpuSeries
  );
  const requestSeries = dedupeSeriesByTimestamp(
    payload.raw_series?.request_count?.length
      ? payload.raw_series.request_count
      : historyRequestSeries
  );
  const desiredCapacitySeries = dedupeSeriesByTimestamp(
    payload.raw_series?.desired_capacity?.length
      ? payload.raw_series.desired_capacity
      : historyDesiredCapacitySeries
  );

  const latestHistoryCpu = historyCpuSeries.length ? historyCpuSeries.at(-1).value : null;
  const latestHistoryRequest = historyRequestSeries.length ? historyRequestSeries.at(-1).value : null;
  const latestHistoryDesiredCapacity = historyDesiredCapacitySeries.length
    ? historyDesiredCapacitySeries.at(-1).value
    : null;
  const latestHistoryInstanceCount = historyInstanceCountSeries.length
    ? historyInstanceCountSeries.at(-1).value
    : null;
  const latestHistoryHealthyHosts = historyHealthyHostSeries.length
    ? historyHealthyHostSeries.at(-1).value
    : null;

  const latestSummaryCpu = hasMetricValue(summary.average_cpu) ? summary.average_cpu : latestHistoryCpu;
  const latestRequestCount = hasMetricValue(summary.request_count)
    ? summary.request_count
    : latestHistoryRequest;
  const latestDesiredCapacity = hasMetricValue(summary.desired_capacity)
    ? summary.desired_capacity
    : latestHistoryDesiredCapacity;
  const latestInstanceCount = hasMetricValue(summary.instance_count)
    ? summary.instance_count
    : latestHistoryInstanceCount;
  const latestHealthyHosts = hasMetricValue(summary.healthy_host_count)
    ? summary.healthy_host_count
    : latestHistoryHealthyHosts;
  const maxInstances = Number(controllerState.max_instances || latestDesiredCapacity || 1);
  const desiredCapacity = Number(latestDesiredCapacity || 0);
  const actualCapacity = Number(latestInstanceCount || 0);
  const headroomPercent = maxInstances > 0 ? ((maxInstances - desiredCapacity) / maxInstances) * 100 : 0;
  const scalingGap = actualCapacity - desiredCapacity;
  const latestSampleTime = payload.collected_at ? new Date(payload.collected_at) : new Date();

  setDashboardModeChips(controllerState);

  const latestActionMessage =
    controllerResult.reason || controllerState.last_reason || "No controller message available.";
  setText("latestAction", latestActionMessage);
  setText(
    "lastUpdatedText",
    latestSampleTime.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
  );

  if (document.getElementById("liveDate")) {
    const snapshotLabel = latestSampleTime.toLocaleDateString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    document.body.dataset.latestSnapshotDate = snapshotLabel;
    setText("liveDate", snapshotLabel);
  }

  animateNumericTextByIds(["avgCpuCard"], latestSummaryCpu, { suffix: "%" });
  animateNumericTextByIds(["requestCard", "requestAccent"], latestRequestCount);
  animateNumericTextByIds(["instanceCountCard", "instanceCountAccent"], latestInstanceCount);
  animateNumericTextByIds(["desiredCapacityCard"], latestDesiredCapacity);
  animateNumericTextByIds(["actualCapacityCard"], latestInstanceCount);
  animateNumericTextByIds(["healthyHostCard", "healthyHostAccent"], latestHealthyHosts);

  const latestCpuPoint = cpuSeries.length ? cpuSeries.at(-1) : null;
  setText(
    "avgCpuDetail",
    latestCpuPoint
      ? `CloudWatch 1-minute average at ${formatTimestamp(latestCpuPoint.timestamp)}`
      : "CloudWatch CPUUtilization"
  );
  setText(
    "requestDetail",
    requestSeries.length
      ? `ALB RequestCount at ${formatTimestamp(requestSeries.at(-1).timestamp)}`
      : "ALB RequestCount"
  );

  setText(
    "instanceDetail",
    `Desired ${formatNumeric(latestDesiredCapacity)} / Actual ${formatNumeric(latestInstanceCount)} running and pending instances`
  );
  setText(
    "healthyHostDetail",
    hasMetricValue(targetHealthCounts.total)
      ? `Healthy targets ${formatNumeric(latestHealthyHosts)} of ${formatNumeric(targetHealthCounts.total)} registered targets`
      : `Healthy targets ${formatNumeric(latestHealthyHosts)} across ${formatNumeric(latestInstanceCount)} active instances`
  );
  setText(
    "scalingGapCard",
    scalingGap === 0
      ? "Aligned"
      : scalingGap > 0
        ? `+${formatNumeric(scalingGap)} active`
        : `${formatNumeric(Math.abs(scalingGap))} pending launch`
  );

  renderInstances(payload.instances || []);
  renderInstanceStateSummary(payload.instances || [], latestDesiredCapacity);
  renderEvents(events);
  renderControllerSummary(controllerState, controllerResult, events);
  renderCpuTelemetry(controllerState, cpuSeries, events);
  renderRecommendations(payload, {
    cpu: latestSummaryCpu,
    requestCount: latestRequestCount,
    desiredCapacity: latestDesiredCapacity,
    healthyHosts: latestHealthyHosts,
    headroom: headroomPercent,
  });
  renderActivityStrip(requestSeries.length ? requestSeries : cpuSeries);
  updateCapacityMeter(headroomPercent, latestDesiredCapacity, maxInstances, latestInstanceCount);

  upsertLineChart({
    canvasId: "cpuChart",
    labels: buildSeriesLabels(cpuSeries),
    legendDisplay: true,
    yMax: 100,
    yTickSuffix: "%",
    datasets: [
      {
        label: "Average CPU",
        data: cpuSeries.map((point) => Number(point.value || 0)),
        borderColor: "#e7f5dc",
        fillTop: "rgba(214, 230, 202, 0.32)",
        fillBottom: "rgba(214, 230, 202, 0.02)",
        tension: 0.2,
        pointRadius: 1.8,
        pointHoverRadius: 4,
      },
      {
        label: "Scale-Out Threshold",
        data: cpuSeries.map(() => Number(controllerState.scale_out_cpu_threshold || 0)),
        borderColor: "#f7be74",
        backgroundColor: "transparent",
        fill: false,
        borderDash: [8, 5],
        tension: 0,
        pointRadius: 0,
      },
      {
        label: "Scale-In Threshold",
        data: cpuSeries.map(() => Number(controllerState.scale_in_cpu_threshold || 0)),
        borderColor: "#ff8e89",
        backgroundColor: "transparent",
        fill: false,
        borderDash: [6, 6],
        tension: 0,
        pointRadius: 0,
      },
    ],
  });

  upsertLineChart({
    canvasId: "instanceChart",
    labels: history.length ? buildLabels(history) : buildSeriesLabels(desiredCapacitySeries),
    legendDisplay: true,
    datasets: [
      {
        label: "Desired Capacity",
        data: history.length
          ? history.map((row) => Number(row.desired_capacity || 0))
          : desiredCapacitySeries.map((point) => Number(point.value || 0)),
        borderColor: "#f7be74",
        fillTop: "rgba(247, 190, 116, 0.22)",
        fillBottom: "rgba(247, 190, 116, 0.03)",
        tension: 0.18,
      },
      {
        label: "Actual Active",
        data: history.length
          ? history.map((row) => Number(row.instance_count || 0))
          : desiredCapacitySeries.map(() => Number(latestInstanceCount || 0)),
        borderColor: "#b9f7cf",
        backgroundColor: "transparent",
        fill: false,
        borderDash: [7, 5],
        tension: 0.18,
      },
    ],
  });

  upsertLineChart({
    canvasId: "requestChart",
    label: "Request Count",
    labels: buildSeriesLabels(requestSeries),
    data: requestSeries.map((point) => Number(point.value || 0)),
    borderColor: "#b9f7cf",
    fillTop: "rgba(185, 247, 207, 0.18)",
    fillBottom: "rgba(185, 247, 207, 0.02)",
    legendDisplay: false,
    yMax: undefined,
  });
}

async function loadDashboard(forceRefresh = false) {
  if (state.dashboardRequestInFlight) return;
  state.dashboardRequestInFlight = true;
  setRefreshButtonState(true);

  try {
    const refreshSuffix = forceRefresh ? "?refresh=true" : "";
    const payload = await apiFetch(`/api/metrics${refreshSuffix}`);
    renderDashboard(payload);
  } catch (error) {
    renderEvents([
      {
        action: "dashboard_error",
        message: `Dashboard refresh failed: ${error.message}`,
        result: "error",
        event_source: "ui",
        timestamp: new Date().toISOString(),
      },
    ]);
  } finally {
    state.dashboardRequestInFlight = false;
    setRefreshButtonState(false);
  }
}

function getControlToken() {
  const tokenInput = document.getElementById("tokenField");
  return tokenInput ? tokenInput.value.trim() : "";
}

function populateControlForm(data) {
  const controllerState = data.controller_state || {};
  const limits = data.limits || {};

  const controlModeBadge = document.getElementById("controlModeBadge");
  const controlTone = controllerState.mode === "custom" ? "custom" : "passive";
  applyTone(controlModeBadge, controlTone, controllerState.mode || "unknown");

  setText("controlLastReason", controllerState.last_reason || "No message yet.");
  setText("controlStateMirror", controllerState.active_control ? "Enabled" : "Monitoring only");
  setText(
    "controlSyncHint",
    data.control_enabled
      ? data.control_allow_force
        ? "ASG bounds and cooldown can sync to AWS. Force actions are available."
        : "ASG bounds and cooldown can sync to AWS. Force actions are disabled."
      : "Control actions are disabled by configuration."
  );

  if (document.getElementById("modeField")) {
    document.getElementById("modeField").value = controllerState.mode || "custom";
    document.getElementById("scaleOutField").value = controllerState.scale_out_cpu_threshold ?? 30;
    document.getElementById("scaleInField").value = controllerState.scale_in_cpu_threshold ?? 10;
    document.getElementById("minField").value = controllerState.min_instances ?? 1;
    document.getElementById("maxField").value = controllerState.max_instances ?? 4;
    document.getElementById("cooldownField").value = controllerState.cooldown_seconds ?? 300;
    document.getElementById("activeControlField").checked = Boolean(controllerState.active_control);
  }

  if (document.getElementById("minField") && hasMetricValue(limits.hard_min_instances)) {
    document.getElementById("minField").min = String(limits.hard_min_instances);
  }
  if (document.getElementById("maxField") && hasMetricValue(limits.hard_max_instances)) {
    document.getElementById("maxField").max = String(limits.hard_max_instances);
  }
}

function formatControlResult(result) {
  if (!result) return "Action completed.";
  if (result.message) return result.message;

  if (result.status === "updated") {
    if (result.aws_sync?.status === "updated") {
      return `Settings saved and synchronized to ${result.aws_sync.asg_name}.`;
    }
    if (result.aws_sync?.status === "skipped") {
      return `Settings saved locally. ${result.aws_sync.reason}`;
    }
    return "Controller settings updated.";
  }

  return result.reason || result.status || "Action completed.";
}

async function loadControlPage() {
  if (state.controlPageRequestInFlight) return;
  state.controlPageRequestInFlight = true;

  try {
    const [controlPayload, eventsPayload] = await Promise.all([
      apiFetch("/api/control"),
      apiFetch("/api/events?limit=20"),
    ]);
    populateControlForm(controlPayload);
    renderEvents(eventsPayload.events || []);
  } catch (error) {
    setText("controlActionResult", error.message);
  } finally {
    state.controlPageRequestInFlight = false;
  }
}

async function submitControlAction(payload) {
  if (state.controlRequestInFlight) return;
  state.controlRequestInFlight = true;

  const token = getControlToken();
  if (token) {
    payload.control_token = token;
  }

  try {
    const result = await apiFetch("/api/control", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { "X-Control-Token": token } : {}),
      },
      body: JSON.stringify(payload),
    });

    setText("controlActionResult", formatControlResult(result.result));
    populateControlForm(result);
    renderEvents(result.events || []);
  } catch (error) {
    setText("controlActionResult", error.message);
  } finally {
    state.controlRequestInFlight = false;
  }
}

function initRevealAnimations() {
  const targets = document.querySelectorAll(".reveal");
  if (!targets.length) return;
  if (prefersReducedMotion.matches) {
    targets.forEach((target) => target.classList.add("is-visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.18 }
  );

  targets.forEach((target) => observer.observe(target));
}

function wireDashboardPage() {
  const refreshSeconds = getAutoRefreshSeconds();
  document.getElementById("refreshDashboardBtn")?.addEventListener("click", () => loadDashboard(true));
  setText("refreshCycleValue", `${refreshSeconds} sec`);
  loadDashboard();
  window.setInterval(loadDashboard, refreshSeconds * 1000);
}

function wireControlPage() {
  const refreshSeconds = getAutoRefreshSeconds();
  const form = document.getElementById("controlForm");
  const refreshBtn = document.getElementById("refreshControlBtn");
  const manualButtons = document.querySelectorAll("[data-control-action]");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    submitControlAction({
      action: "update_settings",
      mode: formData.get("mode"),
      scale_out_cpu_threshold: Number(formData.get("scale_out_cpu_threshold")),
      scale_in_cpu_threshold: Number(formData.get("scale_in_cpu_threshold")),
      min_instances: Number(formData.get("min_instances")),
      max_instances: Number(formData.get("max_instances")),
      cooldown_seconds: Number(formData.get("cooldown_seconds")),
      active_control: document.getElementById("activeControlField").checked,
    });
  });

  refreshBtn?.addEventListener("click", loadControlPage);
  manualButtons.forEach((button) => {
    button.addEventListener("click", () => {
      submitControlAction({ action: button.dataset.controlAction });
    });
  });

  loadControlPage();
  window.setInterval(loadControlPage, refreshSeconds * 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  initRevealAnimations();
  refreshHeaderClock();
  window.setInterval(refreshHeaderClock, 1000);

  const page = document.body.dataset.page;
  if (page === "dashboard") wireDashboardPage();
  if (page === "control") wireControlPage();
});
