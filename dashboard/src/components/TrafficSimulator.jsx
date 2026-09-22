import { useCallback, useEffect, useRef, useState } from "react";
import { Radio, Send } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import { ApiError } from "../lib/api";
import ConfirmDialog from "./ConfirmDialog";
import RelativeTime from "./RelativeTime";
import { TaskStateBadge } from "./StatusBadge";
import { ACTIVE_TRAFFIC_STATES, SCENARIO_META } from "../lib/constants";

const DEFAULT_COUNT = 300;
const MAX_COUNT = 5000; // matches the API's cap; a larger value is a 422
const POLL_MS = 5000;

const TASK_TYPE_LABELS = { regression: "hồi quy giá nhà", classification: "phân loại cần cải tạo" };

/**
 * Renders the traffic simulator: the button that makes a real model get used.
 *
 * Drift is computed from predictions serving has logged, so on a dev box with
 * no real callers there is nothing to measure until somebody produces
 * traffic. This sends a bounded batch through the live serving container and
 * then says when it has finished, because "queued" alone leaves the user
 * guessing when the drift report is worth recomputing.
 *
 * Args:
 *   modelName: The registered model the traffic is aimed at, shown so the
 *     user can see it matches the model selected below.
 *   taskType: "regression" or "classification"; decides which /predict
 *     endpoint the agent calls.
 *
 * Returns:
 *   A JSX section element, or null while the task type is unknown.
 */
export default function TrafficSimulator({ modelName, taskType }) {
  const client = useClient();
  const pushToast = useToast();
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState("none");
  const [count, setCount] = useState(DEFAULT_COUNT);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [run, setRun] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    client
      .listScenarios()
      .then((body) => setScenarios(body.scenarios))
      // A failed list leaves no options rather than a hardcoded fallback: a
      // scenario this build invented would be rejected by the API anyway.
      .catch(() => setScenarios([]));
  }, [client]);

  const refreshStatus = useCallback(async () => {
    try {
      const body = await client.simulateStatus();
      setRun(body.run);
      return body.run;
    } catch {
      return null;
    }
  }, [client]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Poll only while a run is actually moving, and stop as soon as it settles.
  useEffect(() => {
    if (!run || !ACTIVE_TRAFFIC_STATES.has(run.state)) return undefined;
    timer.current = setInterval(refreshStatus, POLL_MS);
    return () => clearInterval(timer.current);
  }, [run, refreshStatus]);

  async function confirmSend() {
    setSending(true);
    try {
      const result = await client.simulate({ scenario, task_type: taskType, count: Number(count) });
      pushToast({ type: "success", text: `Đã gửi traffic: run ${result.run_id}` });
      setConfirmOpen(false);
      setRun({ run_id: result.run_id, state: result.state, started_at: null, ended_at: null });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({
        type: "error",
        text: `Không gửi được traffic: ${typeof detail === "string" ? detail : "lỗi không xác định"}`,
      });
    } finally {
      setSending(false);
    }
  }

  const meta = SCENARIO_META[scenario];
  const countIsValid = Number(count) > 0 && Number(count) <= MAX_COUNT;
  const running = run !== null && ACTIVE_TRAFFIC_STATES.has(run.state);

  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>
            <Radio size={16} /> Mô phỏng model được dùng thật
          </h2>
          <p className="section-sub">
            Agent gửi request thật tới <code>serving</code> để model dự đoán. Có traffic thì mới có gì
            để đo drift.
          </p>
        </div>
      </div>

      <div className="simulator-controls">
        <label>
          <span>Kịch bản</span>
          <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
            {scenarios.map((name) => (
              <option key={name} value={name}>
                {SCENARIO_META[name]?.label ?? name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Số request</span>
          <input
            type="number"
            min={1}
            max={MAX_COUNT}
            value={count}
            onChange={(event) => setCount(event.target.value)}
          />
        </label>
        <button
          className="btn-primary"
          disabled={sending || running || !countIsValid || !taskType}
          onClick={() => setConfirmOpen(true)}
        >
          <Send size={14} /> Gửi traffic
        </button>
      </div>

      {meta && <p className="scenario-hint">{meta.hint}</p>}
      {!countIsValid && <p className="warn-note">Số request phải từ 1 tới {MAX_COUNT}.</p>}

      {run && (
        <div className={`traffic-status ${running ? "traffic-status-live" : ""}`}>
          <TaskStateBadge state={run.state} size="sm" />
          {running ? (
            <span>Đang gửi traffic tới serving…</span>
          ) : (
            <span>
              Lần gửi gần nhất {run.ended_at ? <RelativeTime iso={run.ended_at} /> : "chưa rõ lúc nào"}
              {run.state === "success" && " — giờ bấm “Tính drift ngay” bên dưới để đo lại."}
            </span>
          )}
        </div>
      )}

      {confirmOpen && (
        <ConfirmDialog
          title="Gửi traffic mô phỏng?"
          confirmLabel="Gửi traffic"
          busy={sending}
          onConfirm={confirmSend}
          onCancel={() => setConfirmOpen(false)}
        >
          <p>
            Gửi <b>{count}</b> request theo kịch bản <b>{meta?.label ?? scenario}</b> tới model{" "}
            <code>{modelName}</code> ({TASK_TYPE_LABELS[taskType] ?? taskType}).
          </p>
          <p className="warn-note">
            Đây là traffic <b>thật</b>: mỗi request đi qua container <code>serving</code> và được ghi
            vào inference log, y như một người dùng thật gọi API.
          </p>
          <p className="hint-note">
            Agent gửi lần lượt từng request nên vài trăm request mất một lúc. Drift chưa đổi ngay khi
            gửi xong — phải bấm “Tính drift ngay” sau đó.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
