import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import { RefreshCw, TriangleAlert } from "lucide-react";
import "../lib/chartSetup";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import StatusBadge from "../components/StatusBadge";
import MetricComparison from "../components/MetricComparison";
import EvidentlyReport from "../components/EvidentlyReport";
import RelativeTime from "../components/RelativeTime";
import TrafficSimulator from "../components/TrafficSimulator";
import InputQuality from "../components/InputQuality";
import GroupMetrics from "../components/GroupMetrics";
import { DRIFT_FACTORS, STATUS_META } from "../lib/constants";
import { formatAbsoluteTime, formatNumber } from "../lib/format";
import { axisTime, dayBoundaries, primaryMetric, readHistory, RECENT_WINDOW } from "../lib/driftReading";

const LEVEL = { ok: 0, warning: 1, high: 2 };
const POINT_STYLE = { ok: "circle", warning: "triangle", high: "rectRot" };
const POINT_COLOR = { ok: "#059669", warning: "#F59E0B", high: "#DC2626" };
const STALE_THRESHOLD_MS = 2 * 60 * 60 * 1000;

function levelLabel(value) {
  return { 0: "ổn", 1: "cảnh báo", 2: "cao" }[value] ?? "";
}

// Draws a vertical rule wherever the calendar day changes, and (on the strip
// that carries the axis) writes the day above it. The x axis itself only
// shows the time, because repeating "20/9/26" under twenty points hides the
// one thing worth seeing: that two of the gaps are days wide and the rest
// are minutes. Registered per chart rather than globally so no other screen
// inherits it.
const dayDividers = {
  id: "dayDividers",
  afterDatasetsDraw(chart, _args, options) {
    const { boundaries = [], dayLabels = {}, showLabels = false } = options ?? {};
    const scale = chart.scales.x;
    const { top, bottom } = chart.chartArea;
    const context = chart.ctx;

    context.save();
    context.strokeStyle = "#CBD5E1";
    context.setLineDash([3, 3]);
    context.lineWidth = 1;
    boundaries.forEach((index) => {
      // Halfway between the two measurements the day changed across: the
      // boundary is a gap, not a point.
      const x = (scale.getPixelForValue(index - 1) + scale.getPixelForValue(index)) / 2;
      context.beginPath();
      context.moveTo(x, top);
      context.lineTo(x, bottom);
      context.stroke();
      if (showLabels) {
        context.setLineDash([]);
        context.fillStyle = "#64748B";
        context.font = "11px sans-serif";
        context.textAlign = "left";
        context.fillText(dayLabels[index] ?? "", x + 4, top + 11);
        context.setLineDash([3, 3]);
      }
    });
    if (showLabels && dayLabels[0]) {
      context.setLineDash([]);
      context.fillStyle = "#64748B";
      context.font = "11px sans-serif";
      context.textAlign = "left";
      context.fillText(dayLabels[0], scale.getPixelForValue(0), top + 11);
    }
    context.restore();
  },
};

/**
 * Draws one drift factor's history as its own strip.
 *
 * One strip per factor rather than three lines on one axis: three series
 * sharing three y values overlap almost everywhere, and the earlier version
 * drew all three in the same grey, so no line could be told from another.
 *
 * Args:
 *   factor: An entry of DRIFT_FACTORS — its key, label, hint and colour.
 *   chronological: Drift summaries oldest first.
 *   labels: Formatted timestamps, one per summary.
 *   dividers: Where the day changes, from dayBoundaries().
 *   showAxis: Whether to draw the x axis labels. Only the bottom strip does;
 *     the strips share one timeline, so repeating it three times is noise.
 *
 * Returns:
 *   A JSX element.
 */
function DriftFactorStrip({ factor, chronological, labels, dividers, showAxis }) {
  // A summary with no verdict for this factor (insufficient_data, or the
  // empty `parts` the monitor writes when there was no traffic at all) is a
  // real gap — plotting it at "ổn" would claim somebody checked and found
  // nothing wrong.
  const data = chronological.map((summary) => LEVEL[summary.parts?.[factor.key]] ?? null);

  const dataset = {
    label: factor.label,
    data,
    borderColor: factor.color,
    backgroundColor: `${factor.color}1A`,
    pointStyle: chronological.map((summary) => POINT_STYLE[summary.parts?.[factor.key]] ?? "circle"),
    pointBackgroundColor: chronological.map(
      (summary) => POINT_COLOR[summary.parts?.[factor.key]] ?? "#94A3B8"
    ),
    pointBorderColor: chronological.map(
      (summary) => POINT_COLOR[summary.parts?.[factor.key]] ?? "#94A3B8"
    ),
    pointRadius: 5,
    borderWidth: 2,
    // Stepped, because a verdict holds until the next run measures a new one.
    // A sloped line would suggest the severity passed through values nobody
    // ever measured.
    stepped: "before",
    spanGaps: false,
    fill: true,
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      y: {
        // min/max must land exactly on integer ticks (Chart.js generates
        // ticks starting at `min` in steps of `stepSize`) or the label
        // callback below never matches a tick value and the axis renders
        // with no text at all.
        min: -1,
        max: 3,
        ticks: { stepSize: 1, callback: levelLabel, font: { size: 11 } },
        grid: { color: "#F1F5F9" },
      },
      x: {
        ticks: {
          display: showAxis,
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 6,
          font: { size: 10 },
        },
        grid: { display: false },
      },
    },
    plugins: {
      legend: { display: false },
      dayDividers: { ...dividers, showLabels: showAxis },
      tooltip: {
        callbacks: {
          title: (items) => chronological[items[0].dataIndex].run_id,
          label: (item) => {
            const summary = chronological[item.dataIndex];
            const verdict = summary.parts?.[factor.key];
            const lines = [
              `${factor.label}: ${STATUS_META[verdict]?.label ?? verdict ?? "chưa đo"}`,
              `n_predictions: ${summary.n_predictions} · n_ground_truth: ${summary.n_ground_truth}`,
              `window_hours: ${summary.window_hours}`,
            ];
            if (Object.keys(summary.current_metrics ?? {}).length > 0) {
              lines.push(
                Object.entries(summary.current_metrics)
                  .map(([key, value]) => `${key}=${Number(value).toFixed(3)}`)
                  .join(" · ")
              );
            }
            return lines;
          },
        },
      },
    },
  };

  return (
    <div className="drift-strip">
      <div className="drift-strip-head">
        <span className="drift-strip-dot" style={{ background: factor.color }} />
        <div>
          <p className="drift-strip-label">{factor.label}</p>
          <p className="drift-strip-hint">{factor.hint}</p>
        </div>
      </div>
      <div className={`drift-strip-canvas ${showAxis ? "drift-strip-canvas-axis" : ""}`}>
        <Line data={{ labels, datasets: [dataset] }} options={options} plugins={[dayDividers]} />
      </div>
    </div>
  );
}

/**
 * Says in words what the three strips show, so the chart does not have to be
 * decoded before it can be acted on.
 *
 * Args:
 *   reading: What readHistory() returned, or null.
 *
 * Returns:
 *   A JSX element, or null when there is no history to read.
 */
function DriftVerdictLine({ reading }) {
  if (reading === null) return null;
  const { changes, comparable, recentHigh, recentCount, versions } = reading;

  return (
    <div className="verdict-line">
      <p className="verdict-headline">
        {recentHigh === 0
          ? `Không lần đo nào trong ${recentCount} lần gần nhất ở mức cao.`
          : `${recentHigh}/${recentCount} lần đo gần nhất ở mức cao.`}
      </p>

      {changes.length === 0 ? (
        <p className="verdict-detail">Lần đo mới nhất giữ nguyên cả ba mức so với lần trước.</p>
      ) : (
        <p className="verdict-detail">
          So với lần đo trước:{" "}
          {changes.map((change, index) => (
            <span key={change.key}>
              {index > 0 && ", "}
              <b>{change.label}</b>{" "}
              <span
                className={
                  change.worse === true
                    ? "verdict-worse"
                    : change.worse === false
                      ? "verdict-better"
                      : ""
                }
              >
                {STATUS_META[change.from]?.label ?? change.from} →{" "}
                {STATUS_META[change.to]?.label ?? change.to}
              </span>
            </span>
          ))}
          .
        </p>
      )}

      {!comparable && (
        <p className="verdict-warn">
          Hai lần đo cuối thuộc <b>hai model version khác nhau</b> (v{reading.previous.model_version} rồi v
          {reading.latest.model_version}), nên thay đổi ở trên không phải là xu hướng của cùng một model.
        </p>
      )}
      {comparable && versions.length > 1 && (
        <p className="verdict-warn">
          Biểu đồ gồm {versions.length} model version ({versions.map((version) => `v${version}`).join(", ")}) — các
          điểm trước lần đổi version không so trực tiếp với các điểm sau được.
        </p>
      )}
    </div>
  );
}

/**
 * Plots the metric the performance verdict is made from, with the value the
 * train stage measured as the baseline.
 *
 * Three severity levels cannot say "how much worse"; this can. The baseline
 * is drawn per point rather than as one flat line because it belongs to the
 * champion of that measurement, and the champion changes.
 *
 * Args:
 *   chronological: Summaries oldest first.
 *   labels: The x labels, shared with the strips.
 *   dividers: Day boundaries, shared with the strips.
 *   taskType: Decides which metric is plotted.
 *
 * Returns:
 *   A JSX element, or null when no measurement carries the metric.
 */
function MetricTrendChart({ chronological, labels, dividers, taskType }) {
  const metric = primaryMetric(taskType);
  if (metric === null) return null;

  const current = chronological.map((summary) => summary.current_metrics?.[metric] ?? null);
  // reference_metrics was added to the monitor stage on 2026-09-22; every
  // summary written before that lacks it, so the baseline is simply absent
  // for those points instead of being back-filled with a guess.
  // Only baselines that say which standard they were measured under. For a
  // few hours on 2026-09-22 this field held the training metrics instead, and
  // those are a different number of a different kind — drawing them on the
  // same dashed line would show a jump that never happened to the model.
  const reference = chronological.map((summary) =>
    summary.reference_source === "test_metrics" ? (summary.reference_metrics?.[metric] ?? null) : null
  );
  if (current.every((value) => value === null)) return null;

  const measuredCount = current.filter((value) => value !== null).length;
  const referenceCount = reference.filter((value) => value !== null).length;

  const data = {
    labels,
    datasets: [
      {
        label: `${metric} đo được`,
        data: current,
        borderColor: "#DB2777",
        backgroundColor: "#DB277722",
        pointRadius: 4,
        borderWidth: 2,
        spanGaps: false,
        fill: false,
      },
      {
        label: `${metric} trên tập test`,
        data: reference,
        borderColor: "#94A3B8",
        borderDash: [5, 4],
        // Not 0: reference_metrics only exists from 2026-09-22 on, so early
        // in a history there is a single value and a line through one point
        // draws nothing at all.
        pointRadius: 3,
        pointBackgroundColor: "#94A3B8",
        borderWidth: 2,
        spanGaps: true,
        fill: false,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      y: {
        ticks: { callback: (value) => formatNumber(value), font: { size: 11 } },
        grid: { color: "#F1F5F9" },
      },
      x: {
        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 10 } },
        grid: { display: false },
      },
    },
    plugins: {
      legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
      dayDividers: { ...dividers, showLabels: true },
      tooltip: {
        callbacks: {
          title: (items) => chronological[items[0].dataIndex].run_id,
          label: (item) => {
            const summary = chronological[item.dataIndex];
            const measured = summary.current_metrics?.[metric];
            const trained = summary.reference_metrics?.[metric];
            if (item.datasetIndex === 1) return `${metric} trên tập test: ${formatNumber(trained)}`;
            const ratio =
              measured !== undefined && trained
                ? ` (gấp ${(measured / trained).toFixed(2)} lần so với tập test)`
                : "";
            return [
              `${metric} đo được: ${formatNumber(measured)}${ratio}`,
              `trên ${summary.n_ground_truth} kết quả thật`,
            ];
          },
        },
      },
    },
  };

  return (
    <div className="drift-strip">
      <div className="drift-strip-head">
        <span className="drift-strip-dot" style={{ background: "#DB2777" }} />
        <div>
          <p className="drift-strip-label">{metric.toUpperCase()} thật sự đo được</p>
          <p className="drift-strip-hint">
            Đường nét đứt là {metric} <b>trên tập test</b> — đúng con số ở tab Models, và đúng mốc mà mức Performance
            drift ở trên được chấm dựa vào.
          </p>
        </div>
      </div>
      <div className="drift-strip-canvas drift-strip-canvas-axis">
        <Line data={data} options={options} plugins={[dayDividers]} />
      </div>
      {referenceCount < measuredCount && (
        <p className="chart-gap-note">
          Mốc &ldquo;tập test&rdquo; chỉ có ở {referenceCount}/{measuredCount} lần đo — báo cáo viết trước ngày
          22/9/2026 không lưu chỉ số này, nên không có gì để vẽ ở những điểm cũ.
        </p>
      )}
    </div>
  );
}

function DriftHistoryChart({ history, taskType }) {
  const chronological = [...history].reverse();
  const labels = chronological.map((summary) => axisTime(summary.computed_at));
  const dividers = dayBoundaries(chronological);
  const gaps = chronological.filter((summary) => summary.parts?.performance === "insufficient_data");
  const reading = readHistory(history);

  return (
    <div>
      <DriftVerdictLine reading={reading} />

      {DRIFT_FACTORS.map((factor, index) => (
        <DriftFactorStrip
          key={factor.key}
          factor={factor}
          chronological={chronological}
          labels={labels}
          dividers={dividers}
          showAxis={index === DRIFT_FACTORS.length - 1}
        />
      ))}

      <MetricTrendChart
        chronological={chronological}
        labels={labels}
        dividers={dividers}
        taskType={taskType}
      />

      <p className="chart-gap-note">
        Mỗi điểm là <b>một lần đo</b>, không phải một mốc thời gian — các điểm cách đều nhau kể cả khi hai lần đo cách
        nhau vài phút hay vài ngày. Vạch đứng dọc là chỗ sang ngày mới. Kết luận ở trên tính trên {RECENT_WINDOW} lần
        đo gần nhất.
        {gaps.length > 0 && (
          <>
            {" "}
            Khoảng trống trên dải Performance drift = chưa đủ dữ liệu (không phải mức thấp hơn &ldquo;ổn&rdquo;), tại:{" "}
            {gaps.map((summary) => formatAbsoluteTime(summary.computed_at)).join(", ")}.
          </>
        )}
      </p>
    </div>
  );
}

/**
 * Renders the Drift screen: a traffic simulator that makes the model get
 * used, then the three separate severity parts (never merged into one badge,
 * brief §1 principle 2), one history strip per part, and a placeholder for
 * the Evidently report until a serving decision exists for it (§4.5).
 *
 * Args:
 *   onRetrain: Called with a task_type string when the user clicks the
 *     retrain call to action, so the parent can switch to Overview with
 *     that task type pre-filled.
 *
 * Returns:
 *   A JSX page element.
 */
export default function Drift({ onRetrain, onOpenData }) {
  const client = useClient();
  const pushToast = useToast();
  const [models, setModels] = useState([]);
  const [modelName, setModelName] = useState("");
  const [latestState, setLatestState] = useState({ status: "loading" });
  const [history, setHistory] = useState([]);

  useEffect(() => {
    client
      .listModels()
      .then((body) => {
        setModels(body.models);
        if (body.models.length > 0) setModelName(body.models[0].name);
        // With no models there is nothing to select and load() never runs, so
        // say so here — otherwise the screen sits on its skeleton forever.
        else setLatestState({ status: "no-models" });
      })
      .catch(() => setModels([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function load() {
    if (!modelName) return;
    setLatestState({ status: "loading" });
    setHistory([]);
    try {
      const [latest, historyBody] = await Promise.allSettled([
        client.driftLatest(modelName),
        client.driftHistory(modelName, 20),
      ]);
      const historyList = historyBody.status === "fulfilled" ? historyBody.value.history : [];
      setHistory(historyList);
      if (latest.status === "fulfilled") {
        setLatestState({ status: "data", summary: latest.value });
      } else if (latest.reason?.kind === "notfound") {
        setLatestState({ status: "empty" });
      } else {
        setLatestState({ status: "error", error: latest.reason });
      }
    } catch (error) {
      setLatestState({ status: "error", error });
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelName, client]);

  function copyReportKey(reportKey) {
    navigator.clipboard?.writeText(reportKey);
    pushToast({ type: "success", text: "Đã sao chép report_key" });
  }

  const isStale =
    latestState.status === "data" &&
    Date.now() - new Date(latestState.summary.computed_at).getTime() > STALE_THRESHOLD_MS;
  const selectedModel = models.find((model) => model.name === modelName);

  return (
    <div className="page-grid-single">
      {selectedModel && (
        <TrafficSimulator
          modelName={selectedModel.name}
          taskType={selectedModel.task_type}
          onFinished={load}
        />
      )}

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Drift</h2>
            <p className="section-sub">
              Ba loại drift tách biệt, không gộp thành một điểm số (data, prediction, performance), và riêng một mục
              data quality của input.
            </p>
          </div>
          <div className="filters">
            <select value={modelName} onChange={(event) => setModelName(event.target.value)}>
              {models.map((model) => (
                <option key={model.name} value={model.name}>
                  {model.name}
                </option>
              ))}
            </select>
            <button className="btn-secondary" onClick={load}>
              <RefreshCw size={14} /> Tải lại
            </button>
          </div>
        </div>

        {latestState.status !== "no-models" && (
          <p className="hint-note">
            Báo cáo tính lúc thời điểm <code>computed_at</code> dưới đây. Traffic mới gửi có thể chưa được ghi và
            chưa có trong báo cáo này.
          </p>
        )}

        {latestState.status === "no-models" && (
          <EmptyState
            title="Chưa có model nào."
            description="Registry đang trống, nên không có gì để đo drift. Chạy pipeline để train model trước."
          />
        )}
        {latestState.status === "loading" && <LoadingSkeleton rows={4} />}
        {latestState.status === "error" && (
          <ErrorState kind="system" detail={latestState.error?.detail} onRetry={load} />
        )}
        {latestState.status === "empty" && (
          <EmptyState
            title="Chưa có báo cáo drift cho model này."
            description="Chưa có run nào của monitoring_dag. Bấm “Mô phỏng & tính drift” ở khối trên là có ngay."
          />
        )}
        {latestState.status === "data" && (
          <>
            <div className="drift-meta">
              <span>
                Model version: <b>v{latestState.summary.model_version}</b>
              </span>
              <span>
                Tính lúc: <RelativeTime iso={latestState.summary.computed_at} />
              </span>
              {isStale && <span className="chip-stale">báo cáo cũ</span>}
            </div>

            {latestState.summary.flush && !latestState.summary.flush.ok && (
              <div className="insufficient-notice">
                <TriangleAlert size={16} />
                <p>
                  Ghi prediction log xuống storage trước khi tính <b>thất bại</b> ({latestState.summary.flush.error}).
                  Một phần traffic vừa gửi có thể chưa có trong báo cáo này.
                </p>
              </div>
            )}

            <div className="severity-overview">
              {DRIFT_FACTORS.map((factor) => (
                <div className="severity-cell" key={factor.key}>
                  <p className="severity-cell-label" style={{ color: factor.color }}>
                    {factor.label}
                  </p>
                  <StatusBadge value={latestState.summary.parts[factor.key]} />
                  <p className="severity-cell-hint">{factor.hint}</p>
                  {latestState.summary.consecutive_warnings?.[factor.key] >= 2 && (
                    <p className="warn-note">
                      Cảnh báo {latestState.summary.consecutive_warnings[factor.key]} lần liên tiếp.
                    </p>
                  )}
                </div>
              ))}
            </div>

            <InputQuality quality={latestState.summary.input_quality} />

            {latestState.summary.parts.performance === "insufficient_data" && (
              <div className="insufficient-notice">
                <TriangleAlert size={16} />
                <p>
                  Chưa đủ kết quả thật để đo performance drift (n_ground_truth = {latestState.summary.n_ground_truth}).
                  Kết quả thật đến trễ hơn dự đoán. Đây <b>không phải</b> là ổn — chưa ai kiểm tra.
                </p>
              </div>
            )}

            <MetricComparison
              current={latestState.summary.current_metrics}
              // Only a baseline that declares which standard it was measured
              // under; see MetricTrendChart for why the older ones are not
              // comparable.
              reference={
                latestState.summary.reference_source === "test_metrics"
                  ? latestState.summary.reference_metrics
                  : null
              }
            />

            <GroupMetrics groups={latestState.summary.group_metrics} taskType={latestState.summary.task_type} />

            {history.length > 0 && (
              <div className="chart-wrap">
                <DriftHistoryChart history={history} taskType={latestState.summary.task_type} />
              </div>
            )}

            <EvidentlyReport
              url={client.driftReportUrl?.(modelName, latestState.summary.run_id) ?? null}
              reportKey={latestState.summary.report_key}
              onCopyKey={copyReportKey}
            />

            {latestState.summary.severity === "high" && (
              <div className="retrain-box">
                <p>
                  Có mục ở mức <b>Cao</b>. Retrain trên đúng data cũ thì model mới sẽ học y hệt model cũ — nên tạo data
                  version từ traffic thực tế trước, rồi retrain trên data version đó.
                </p>
                <div className="row-actions">
                  <button className="btn-secondary" onClick={() => onOpenData?.()}>
                    1. Tạo data version từ traffic →
                  </button>
                  <button className="btn-primary" onClick={() => onRetrain?.(latestState.summary.task_type)}>
                    2. Retrain model này →
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </section>

    </div>
  );
}
