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
import { STATUS_META } from "../lib/constants";
import { formatAbsoluteTime } from "../lib/format";

const PARTS = ["feature", "prediction", "performance"];
const PART_LABELS = { feature: "Feature", prediction: "Prediction", performance: "Performance" };
const LEVEL = { ok: 0, warning: 1, high: 2 };
const POINT_STYLE = { ok: "circle", warning: "triangle", high: "rectRot" };
const POINT_COLOR = { ok: "#059669", warning: "#F59E0B", high: "#DC2626" };
const STALE_THRESHOLD_MS = 2 * 60 * 60 * 1000;

// A history point with an insufficient_data part is plotted as a genuine
// gap (null, spanGaps: false) rather than a low value — plotting it as "0"
// would say the same thing principle 1 forbids: that it is fine (brief §1,
// §4.5). The gaps are called out separately below the chart instead.
function buildChartData(history) {
  const chronological = [...history].reverse();
  const labels = chronological.map((summary) =>
    new Date(summary.computed_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })
  );
  const datasets = PARTS.map((part) => ({
    label: PART_LABELS[part],
    data: chronological.map((summary) => LEVEL[summary.parts[part]] ?? null),
    pointStyle: chronological.map((summary) => POINT_STYLE[summary.parts[part]] ?? "circle"),
    pointBackgroundColor: chronological.map((summary) => POINT_COLOR[summary.parts[part]] ?? "#94A3B8"),
    pointRadius: 6,
    borderColor: "#CBD5E1",
    spanGaps: false,
    tension: 0,
  }));
  return { chronological, labels, datasets };
}

function DriftHistoryChart({ history }) {
  const { chronological, labels, datasets } = buildChartData(history);
  const insufficientPoints = chronological.filter((summary) => summary.parts.performance === "insufficient_data");

  const options = {
    responsive: true,
    scales: {
      y: {
        // min/max must land exactly on integer ticks (Chart.js generates
        // ticks starting at `min` in steps of `stepSize`) or the label
        // callback below never matches a tick value and the axis renders
        // with no text at all.
        min: -1,
        max: 3,
        ticks: {
          stepSize: 1,
          callback: (value) => ({ 0: "ổn", 1: "cảnh báo", 2: "cao" })[value] ?? "",
        },
      },
    },
    plugins: {
      legend: { position: "top" },
      tooltip: {
        callbacks: {
          title: (items) => chronological[items[0].dataIndex].run_id,
          label: (item) => {
            const summary = chronological[item.dataIndex];
            const part = PARTS[item.datasetIndex];
            const lines = [
              `${PART_LABELS[part]}: ${STATUS_META[summary.parts[part]]?.label ?? summary.parts[part]}`,
              `n_predictions: ${summary.n_predictions} · n_ground_truth: ${summary.n_ground_truth}`,
              `window_hours: ${summary.window_hours}`,
            ];
            if (Object.keys(summary.current_metrics).length > 0) {
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
    <div>
      <Line data={{ labels, datasets }} options={options} />
      {insufficientPoints.length > 0 && (
        <p className="chart-gap-note">
          Khoảng trống trên dải Performance = chưa đủ dữ liệu (không phải mức thấp hơn "ổn"), tại:{" "}
          {insufficientPoints.map((summary) => formatAbsoluteTime(summary.computed_at)).join(", ")}.
        </p>
      )}
    </div>
  );
}

/**
 * Renders the Drift screen: three separate severity parts (never merged
 * into one badge, brief §1 principle 2), history chart, and a placeholder
 * for the Evidently report until a serving decision exists for it (§4.5).
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
    latestState.status === "data" && Date.now() - new Date(latestState.summary.computed_at).getTime() > STALE_THRESHOLD_MS;

  return (
    <div className="page-grid-single">
      <section className="card">
        <div className="section-head">
          <div>
            <h2>Drift</h2>
            <p className="section-sub">Ba phép đo tách biệt: feature, prediction, performance.</p>
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
            <button className="btn-primary" disabled={triggeringRun} onClick={() => setRunConfirmOpen(true)}>
              <Play size={14} /> Tính drift ngay
            </button>
          </div>
        </div>

        <p className="hint-note">
          Báo cáo tính lúc thời điểm <code>computed_at</code> dưới đây. Traffic mới gửi có thể chưa được ghi và chưa
          có trong báo cáo này.
        </p>

        {latestState.status === "loading" && <LoadingSkeleton rows={4} />}
        {latestState.status === "error" && (
          <ErrorState kind="system" detail={latestState.error?.detail} onRetry={load} />
        )}
        {latestState.status === "empty" && (
          <EmptyState
            title="Chưa có báo cáo drift cho model này."
            description="monitoring_dag chưa chạy lần nào (mặc định nó ở trạng thái paused; bật trong Airflow)."
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
              {PARTS.map((part) => (
                <div className="severity-cell" key={part}>
                  <p className="severity-cell-label">{PART_LABELS[part]}</p>
                  <StatusBadge value={latestState.summary.parts[part]} />
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
                <button className="icon-btn" onClick={() => copyReportKey(latestState.summary.report_key)} aria-label="Sao chép">
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
            sẽ không đổi. Muốn có báo cáo mới thì phải có traffic đi qua <code>serving</code> trước.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
