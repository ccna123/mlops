import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import { Copy, Play, RefreshCw, TriangleAlert } from "lucide-react";
import "../lib/chartSetup";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import { ApiError } from "../lib/api";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import StatusBadge from "../components/StatusBadge";
import MetricTile from "../components/MetricTile";
import RelativeTime from "../components/RelativeTime";
import TrafficSimulator from "../components/TrafficSimulator";
import { DRIFT_FACTORS, STATUS_META } from "../lib/constants";
import { formatAbsoluteTime } from "../lib/format";

const LEVEL = { ok: 0, warning: 1, high: 2 };
const POINT_STYLE = { ok: "circle", warning: "triangle", high: "rectRot" };
const POINT_COLOR = { ok: "#059669", warning: "#F59E0B", high: "#DC2626" };
const STALE_THRESHOLD_MS = 2 * 60 * 60 * 1000;

function levelLabel(value) {
  return { 0: "ổn", 1: "cảnh báo", 2: "cao" }[value] ?? "";
}

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
 *   showAxis: Whether to draw the x axis labels. Only the bottom strip does;
 *     the strips share one timeline, so repeating it three times is noise.
 *
 * Returns:
 *   A JSX element.
 */
function DriftFactorStrip({ factor, chronological, labels, showAxis }) {
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
        <Line data={{ labels, datasets: [dataset] }} options={options} />
      </div>
    </div>
  );
}

function DriftHistoryChart({ history }) {
  const chronological = [...history].reverse();
  const labels = chronological.map((summary) =>
    new Date(summary.computed_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })
  );
  const gaps = chronological.filter((summary) => summary.parts?.performance === "insufficient_data");

  return (
    <div>
      {DRIFT_FACTORS.map((factor, index) => (
        <DriftFactorStrip
          key={factor.key}
          factor={factor}
          chronological={chronological}
          labels={labels}
          showAxis={index === DRIFT_FACTORS.length - 1}
        />
      ))}
      {gaps.length > 0 && (
        <p className="chart-gap-note">
          Khoảng trống trên dải Performance drift = chưa đủ dữ liệu (không phải mức thấp hơn &ldquo;ổn&rdquo;), tại:{" "}
          {gaps.map((summary) => formatAbsoluteTime(summary.computed_at)).join(", ")}.
        </p>
      )}
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
export default function Drift({ onRetrain }) {
  const client = useClient();
  const pushToast = useToast();
  const [models, setModels] = useState([]);
  const [modelName, setModelName] = useState("");
  const [latestState, setLatestState] = useState({ status: "loading" });
  const [history, setHistory] = useState([]);
  const [runConfirmOpen, setRunConfirmOpen] = useState(false);
  const [triggeringRun, setTriggeringRun] = useState(false);

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

  async function confirmTriggerRun() {
    setTriggeringRun(true);
    try {
      const result = await client.triggerDriftRun();
      pushToast({ type: "success", text: `Đã tạo run tính drift ${result.run_id}` });
      setRunConfirmOpen(false);
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({
        type: "error",
        text: `Không tính được drift: ${typeof detail === "string" ? detail : "lỗi không xác định"}`,
      });
    } finally {
      setTriggeringRun(false);
    }
  }

  const isStale =
    latestState.status === "data" &&
    Date.now() - new Date(latestState.summary.computed_at).getTime() > STALE_THRESHOLD_MS;
  const selectedModel = models.find((model) => model.name === modelName);

  return (
    <div className="page-grid-single">
      {selectedModel && (
        <TrafficSimulator modelName={selectedModel.name} taskType={selectedModel.task_type} />
      )}

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Drift</h2>
            <p className="section-sub">
              Ba phép đo tách biệt, không gộp thành một điểm số: data, model, performance.
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
            <button
              className="btn-primary"
              disabled={triggeringRun || models.length === 0}
              onClick={() => setRunConfirmOpen(true)}
            >
              <Play size={14} /> Tính drift ngay
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
            description="Chưa có run nào của monitoring_dag. Gửi traffic ở khối trên, rồi bấm Tính drift ngay."
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

            <div className="severity-overview">
              {DRIFT_FACTORS.map((factor) => (
                <div className="severity-cell" key={factor.key}>
                  <p className="severity-cell-label" style={{ color: factor.color }}>
                    {factor.label}
                  </p>
                  <StatusBadge value={latestState.summary.parts[factor.key]} />
                  <p className="severity-cell-hint">{factor.hint}</p>
                </div>
              ))}
            </div>

            {latestState.summary.parts.performance === "insufficient_data" && (
              <div className="insufficient-notice">
                <TriangleAlert size={16} />
                <p>
                  Chưa đủ kết quả thật để đo performance drift (n_ground_truth = {latestState.summary.n_ground_truth}).
                  Kết quả thật đến trễ hơn dự đoán. Đây <b>không phải</b> là ổn — chưa ai kiểm tra.
                </p>
              </div>
            )}

            {Object.keys(latestState.summary.current_metrics).length > 0 && (
              <div className="metric-row">
                {Object.entries(latestState.summary.current_metrics).map(([key, value]) => (
                  <MetricTile key={key} name={key} value={value} />
                ))}
              </div>
            )}

            {history.length > 0 && (
              <div className="chart-wrap">
                <DriftHistoryChart history={history} />
              </div>
            )}

            <div className="evidently-placeholder">
              <p>Báo cáo Evidently đầy đủ chưa xem được từ dashboard.</p>
              <div className="report-key-row">
                <code>{latestState.summary.report_key}</code>
                <button
                  className="icon-btn"
                  onClick={() => copyReportKey(latestState.summary.report_key)}
                  aria-label="Sao chép"
                >
                  <Copy size={14} />
                </button>
              </div>
            </div>

            {latestState.summary.severity === "high" && (
              <button className="btn-primary" onClick={() => onRetrain?.(latestState.summary.task_type)}>
                Retrain model này →
              </button>
            )}
          </>
        )}
      </section>

      {runConfirmOpen && (
        <ConfirmDialog
          title="Tính drift ngay?"
          confirmLabel="Tính drift ngay"
          busy={triggeringRun}
          onConfirm={confirmTriggerRun}
          onCancel={() => setRunConfirmOpen(false)}
        >
          <p>
            Chạy <code>monitoring_dag</code> một lần. Nó tính drift cho <b>cả hai model</b> — không chọn riêng được
            model nào.
          </p>
          <p className="warn-note">
            Khởi động hai container <code>ml-monitor</code> thật, mỗi container đọc cửa sổ dự đoán và dữ liệu tham
            chiếu. Báo cáo chưa có ngay khi lệnh trả về; bấm "Tải lại" sau ít phút để xem kết quả.
          </p>
          <p className="hint-note">
            Nếu không có dự đoán mới nào trong cửa sổ, run vẫn báo thành công nhưng <b>không sinh báo cáo</b> —
            monitor trả <code>insufficient_data</code> và cố ý không ghi verdict từ số liệu rỗng, nên màn hình này
            sẽ không đổi. Muốn có báo cáo mới thì phải gửi traffic ở khối trên trước.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
