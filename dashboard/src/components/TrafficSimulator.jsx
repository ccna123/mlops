import { useCallback, useEffect, useRef, useState } from "react";
import { Radio, Send } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import { ApiError } from "../lib/api";
import ConfirmDialog from "./ConfirmDialog";
import RelativeTime from "./RelativeTime";
import { TaskStateBadge } from "./StatusBadge";
import { ACTIVE_TRAFFIC_STATES, SCENARIO_META, SIMULATE_STAGES } from "../lib/constants";
import { formatDuration } from "../lib/format";

const DEFAULT_COUNT = 300;
const MAX_COUNT = 5000; // matches the API's cap; a larger value is a 422
const POLL_MS = 5000;

const TASK_TYPE_LABELS = { regression: "hồi quy giá nhà", classification: "phân loại cần cải tạo" };

/**
 * Renders the two stages of a simulate run the way Overview renders the
 * pipeline: one node per task, in the order they run.
 *
 * Args:
 *   tasks: The run's task list from GET /simulate/status, in any order.
 *
 * Returns:
 *   A JSX element.
 */
function SimulateStages({ tasks }) {
  // Airflow returns the tasks in no particular order, so the order comes from
  // SIMULATE_STAGES and a task the API has not reported yet shows as "chưa
  // chạy" rather than vanishing from the strip.
  const byId = new Map((tasks ?? []).map((task) => [task.task_id, task]));

  return (
    <div className="stage-row">
      {SIMULATE_STAGES.map((stage) => {
        const task = byId.get(stage.id);
        return (
          <div className="stage-node" key={stage.id}>
            <TaskStateBadge state={task?.state ?? null} size="sm" />
            <strong>{stage.label}</strong>
            <small>{task?.duration ? formatDuration(task.duration) : stage.hint}</small>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Renders the traffic simulator: one button that makes a real model get used
 * and then measures what that did to it.
 *
 * Drift is computed from predictions serving has logged, so on a dev box with
 * no real callers there is nothing to measure until somebody produces
 * traffic. Sending the traffic and recomputing drift used to be two buttons
 * with a wait in between that only Airflow could tell you about; the DAG
 * chains them now, and this shows both stages while they run.
 *
 * Args:
 *   modelName: The registered model the traffic is aimed at, shown so the
 *     user can see it matches the model selected below.
 *   taskType: "regression" or "classification"; decides which /predict
 *     endpoint the agent calls.
 *   onFinished: Called once when a run that was going has stopped, so the
 *     screen can reload the report the run just produced.
 *
 * Returns:
 *   A JSX section element.
 */
export default function TrafficSimulator({ modelName, taskType, onFinished }) {
  const client = useClient();
  const pushToast = useToast();
  const [scenarios, setScenarios] = useState([]);
  const [scenario, setScenario] = useState("none");
  const [count, setCount] = useState(DEFAULT_COUNT);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [run, setRun] = useState(null);
  const timer = useRef(null);
  const wasRunning = useRef(false);

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
      // Fire only on the edge from going to stopped. Without the ref, every
      // poll of an already-finished run would reload the report again.
      const active = body.run !== null && ACTIVE_TRAFFIC_STATES.has(body.run.state);
      if (wasRunning.current && !active) {
        wasRunning.current = false;
        onFinished?.();
        pushToast({
          type: body.run?.state === "success" ? "success" : "error",
          text:
            body.run?.state === "success"
              ? "Đã gửi traffic và tính lại drift xong."
              : `Chuỗi mô phỏng kết thúc ở trạng thái ${body.run?.state}.`,
        });
      }
      wasRunning.current = active;
    } catch {
      // A failed poll is not a failed run; the next tick tries again.
    }
  }, [client, onFinished, pushToast]);

  useEffect(() => {
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

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
      pushToast({ type: "success", text: `Đã bắt đầu: run ${result.run_id}` });
      setConfirmOpen(false);
      wasRunning.current = true;
      setRun({ run_id: result.run_id, state: result.state, started_at: null, ended_at: null, tasks: [] });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({
        type: "error",
        text: `Không chạy được mô phỏng: ${typeof detail === "string" ? detail : "lỗi không xác định"}`,
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
            Một nút làm cả hai việc: agent gửi request thật tới <code>serving</code>, xong thì tự tính lại drift.
          </p>
        </div>
      </div>

      <div className="simulator-controls">
        <label>
          <span>Kịch bản</span>
          <select
            value={scenario}
            disabled={running}
            onChange={(event) => setScenario(event.target.value)}
          >
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
            disabled={running}
            onChange={(event) => setCount(event.target.value)}
          />
        </label>
        <button
          className="btn-primary"
          disabled={sending || running || !countIsValid || !taskType}
          onClick={() => setConfirmOpen(true)}
        >
          <Send size={14} /> {running ? "Đang chạy…" : "Mô phỏng & tính drift"}
        </button>
      </div>

      {meta && <p className="scenario-hint">{meta.hint}</p>}
      {!countIsValid && <p className="warn-note">Số request phải từ 1 tới {MAX_COUNT}.</p>}

      {run && (
        <>
          <SimulateStages tasks={run.tasks} />
          <div className={`traffic-status ${running ? "traffic-status-live" : ""}`}>
            <TaskStateBadge state={run.state} size="sm" />
            {running ? (
              <span>Đang chạy — màn hình tự cập nhật khi xong, không cần mở Airflow.</span>
            ) : (
              <span>
                Lần chạy gần nhất {run.ended_at ? <RelativeTime iso={run.ended_at} /> : "chưa rõ lúc nào"}
                {run.state === "success" && " — báo cáo drift bên dưới đã tính theo traffic đó."}
              </span>
            )}
          </div>
        </>
      )}

      {confirmOpen && (
        <ConfirmDialog
          title="Chạy mô phỏng?"
          confirmLabel="Chạy"
          busy={sending}
          onConfirm={confirmSend}
          onCancel={() => setConfirmOpen(false)}
        >
          <p>
            Gửi <b>{count}</b> request theo kịch bản <b>{meta?.label ?? scenario}</b> tới model{" "}
            <code>{modelName}</code> ({TASK_TYPE_LABELS[taskType] ?? taskType}), rồi tự chạy{" "}
            <code>monitoring_dag</code> để tính lại drift.
          </p>
          <p className="warn-note">
            Đây là traffic <b>thật</b>: mỗi request đi qua container <code>serving</code> và được ghi vào inference
            log, y như một người dùng thật gọi API. Bước tính drift khởi động container <code>ml-monitor</code> cho
            <b> cả hai model</b>.
          </p>
          <p className="hint-note">
            Cả chuỗi mất khoảng một tới hai phút. Đóng trình duyệt giữa chừng cũng không sao — chuỗi chạy trong
            Airflow, không chạy trong trang này.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
