import { useEffect, useRef, useState } from "react";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import RelativeTime from "../components/RelativeTime";
import { TaskStateBadge } from "../components/StatusBadge";
import { STAGE_ORDER, STAGE_LABELS } from "../lib/constants";
import { formatDuration, durationBetween, runIdTimestamp } from "../lib/format";
import { ApiError } from "../lib/api";

const ACTIVE_RUN_STATES = new Set(["queued", "running"]);
const STUCK_QUEUED_SECONDS = 60;

const LINEAR_STAGES = ["extract", "validate", "prepare_dataset_for_train", "train", "evaluate", "branch_on_gates"];
const PASS_BRANCH = ["register", "deploy"];
const FAIL_BRANCH = ["stop_no_deploy"];

function buildTaskMap(tasks) {
  const map = new Map(STAGE_ORDER.map((id) => [id, { task_id: id, state: null, try_number: 0, duration: null }]));
  for (const task of tasks ?? []) map.set(task.task_id, task);
  return map;
}

function StageNode({ task }) {
  return (
    <div className="stage-node">
      <TaskStateBadge state={task.state} size="sm" />
      <strong>{STAGE_LABELS[task.task_id]}</strong>
      <small>
        {task.state === null ? "chưa chạy" : formatDuration(task.duration)}
        {task.try_number > 1 ? ` · lần thử ${task.try_number}` : ""}
      </small>
    </div>
  );
}

// Renders the 9 real ml_pipeline tasks in the fixed order from
// STAGE_ORDER (never the API's own array order, brief §4.1), with the two
// post-gate branches drawn side by side the way the DAG actually forks.
function PipelineStageStrip({ tasks }) {
  const map = buildTaskMap(tasks);
  return (
    <div className="stage-strip">
      <div className="stage-row">
        {LINEAR_STAGES.map((id) => (
          <StageNode key={id} task={map.get(id)} />
        ))}
      </div>
      <div className="stage-branches">
        <div className="stage-branch">
          <p className="stage-branch-label">Đạt cổng</p>
          <div className="stage-row">
            {PASS_BRANCH.map((id) => (
              <StageNode key={id} task={map.get(id)} />
            ))}
          </div>
        </div>
        <div className="stage-branch">
          <p className="stage-branch-label">Không đạt cổng</p>
          <div className="stage-row">
            {FAIL_BRANCH.map((id) => (
              <StageNode key={id} task={map.get(id)} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Renders the Overview screen: pick a task type, trigger a pipeline run,
 * and watch the most recent run's stage progress (brief §4.1).
 *
 * Args:
 *   prefillTaskType: Optional task_type string to pre-select the form with,
 *     passed in from the Drift screen's "retrain" call to action.
 *   onConsumePrefill: Called once the prefill has been applied, so the
 *     caller can clear it and avoid re-applying it on every render.
 *
 * Returns:
 *   A JSX page element.
 */
export default function Overview({ prefillTaskType, onConsumePrefill }) {
  const client = useClient();
  const pushToast = useToast();

  const [runsState, setRunsState] = useState({ status: "loading" });
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [runDetailError, setRunDetailError] = useState(null);

  const [taskType, setTaskType] = useState("");
  const [estimators, setEstimators] = useState(null);
  const [estimatorName, setEstimatorName] = useState("");
  const [datasetVersion, setDatasetVersion] = useState("v1");
  const [useAllRows, setUseAllRows] = useState(false);
  const [sampleRows, setSampleRows] = useState("1000");
  const [forceReprocess, setForceReprocess] = useState(false);
  const [tuneHyperparameters, setTuneHyperparameters] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [triggering, setTriggering] = useState(false);

  const pollRef = useRef(null);

  useEffect(() => {
    if (prefillTaskType) {
      chooseTaskType(prefillTaskType);
      onConsumePrefill?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillTaskType, onConsumePrefill]);

  useEffect(() => {
    client
      .listEstimators()
      .then(setEstimators)
      .catch(() => setEstimators(null));
  }, [client]);

  // The two task types offer different estimators, so a name chosen for one
  // is usually invalid for the other — the API would answer 422.
  function chooseTaskType(next) {
    setTaskType(next);
    setEstimatorName("");
  }

  async function loadRuns() {
    setRunsState({ status: "loading" });
    try {
      const body = await client.listRuns(3);
      setRunsState({ status: "data", runs: body.runs });
      if (body.runs.length > 0) setSelectedRunId(body.runs[0].run_id);
    } catch (error) {
      setRunsState({ status: "error", error });
    }
  }

  useEffect(() => {
    loadRuns();
    // client only changes when demo mode toggles, which should reload from scratch
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function loadRunDetail(runId) {
    setRunDetailError(null);
    try {
      const detail = await client.getRun(runId);
      setRunDetail(detail);
      return detail;
    } catch (error) {
      setRunDetailError(error);
      return null;
    }
  }

  // Polls the selected run's detail every ~5s only while it is
  // queued/running, and stops on success or failed (brief §3.5).
  useEffect(() => {
    if (!selectedRunId) {
      setRunDetail(null);
      return undefined;
    }
    let cancelled = false;
    clearTimeout(pollRef.current);

    async function tick() {
      const detail = await loadRunDetail(selectedRunId);
      if (!cancelled && detail && (detail.state === "queued" || detail.state === "running")) {
        pollRef.current = setTimeout(tick, 5000);
      }
    }
    tick();

    return () => {
      cancelled = true;
      clearTimeout(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId, client]);

  // Only one training run at a time: while any recent run is still queued or
  // running, the trigger stays locked. Airflow enforces the same rule with
  // max_active_runs=1 — this is the half the user can see.
  const activeRun =
    runsState.status === "data" ? runsState.runs.find((run) => ACTIVE_RUN_STATES.has(run.state)) : null;

  // Age comes from the run id's own timestamp, not from when this page first
  // saw the run, so a run that has been stuck for an hour warns immediately
  // instead of staying silent for the first minute after every reload.
  const queuedAt = runDetail?.state === "queued" ? runIdTimestamp(runDetail.run_id) : null;
  const stuckQueued = queuedAt !== null && (Date.now() - queuedAt.getTime()) / 1000 > STUCK_QUEUED_SECONDS;

  function openConfirm() {
    if (!taskType || activeRun) return;
    setConfirmOpen(true);
  }

  async function confirmTrigger() {
    setTriggering(true);
    const payload = { task_type: taskType, force_reprocess: forceReprocess, dataset_version: datasetVersion };
    if (!useAllRows) payload.sample_rows = Number(sampleRows);
    // "" means let the DAG pick its own default, so the default lives in one
    // place instead of being copied here.
    if (estimatorName) payload.estimator_name = estimatorName;
    payload.tune_hyperparameters = tuneHyperparameters;
    try {
      const result = await client.triggerRun(payload);
      pushToast({ type: "success", text: `Đã tạo run ${result.run_id}` });
      setConfirmOpen(false);
      const newRun = {
        run_id: result.run_id,
        state: result.state ?? "queued",
        task_type: taskType,
        started_at: null,
        ended_at: null,
      };
      setRunsState((prev) => ({
        status: "data",
        runs: [newRun, ...(prev.status === "data" ? prev.runs : [])].slice(0, 3),
      }));
      setSelectedRunId(newRun.run_id);
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      const message = typeof detail === "string" ? detail : "Không gửi được yêu cầu.";
      pushToast({ type: "error", text: `Không thể bắt đầu train: ${message}` });
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="card">
        <div className="section-head">
          <div>
            <h2>Bắt đầu pipeline</h2>
            <p className="section-sub">Một lần train thật sẽ được đưa vào hàng đợi của Airflow.</p>
          </div>
        </div>

        <div className="field">
          <label>Loại model *</label>
          <div className="segmented">
            <button
              type="button"
              className={taskType === "regression" ? "segmented-active" : ""}
              onClick={() => chooseTaskType("regression")}
            >
              Hồi quy giá nhà
            </button>
            <button
              type="button"
              className={taskType === "classification" ? "segmented-active" : ""}
              onClick={() => chooseTaskType("classification")}
            >
              Phân loại cần cải tạo
            </button>
          </div>
        </div>

        <label className="field">
          <span>Thuật toán</span>
          <select
          className="rounded-xl border border-slate-200 bg-white p-2 shadow-sm"
            value={estimatorName}
            disabled={!taskType || !estimators}
            onChange={(event) => setEstimatorName(event.target.value)}
          >
            <option value="">Mặc định của pipeline</option>
            {taskType &&
              estimators &&
              estimators[taskType].map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
          </select>
        </label>
        {!taskType && <p className="hint-note">Chọn loại model trước để thấy thuật toán tương ứng.</p>}

        <div className="field-row">
          <label className="field">
            <span>Phiên bản dữ liệu</span>
            <input value={datasetVersion} onChange={(event) => setDatasetVersion(event.target.value)} />
          </label>
          <label className="field">
            <span>Số dòng train (lấy ngẫu nhiên từ train set)</span>
            <input
              type="number"
              min="1"
              disabled={useAllRows}
              value={sampleRows}
              onChange={(event) => setSampleRows(event.target.value)}
            />
          </label>
        </div>

        <label className="checkbox-row">
          <input type="checkbox" checked={useAllRows} onChange={(event) => setUseAllRows(event.target.checked)} />
          Dùng toàn bộ train set (chậm hơn và tốn RAM hơn đáng kể). Test set luôn giữ nguyên, không phụ thuộc số
          dòng train.
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={forceReprocess}
            onChange={(event) => setForceReprocess(event.target.checked)}
          />
          Xử lý lại dữ liệu từ đầu
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={tuneHyperparameters}
            onChange={(event) => setTuneHyperparameters(event.target.checked)}
          />
          Hyperparameter tuning (time-based cross-validation, chậm hơn — bỏ trống thì dùng hyperparameter mặc định)
        </label>

        <button className="btn-primary" disabled={!taskType || Boolean(activeRun)} onClick={openConfirm}>
          Bắt đầu train →
        </button>
        {activeRun && (
          <p className="hint-note">
            Đang có một run chưa xong (<code>{activeRun.run_id}</code> —{" "}
            {activeRun.state === "running" ? "đang chạy" : "đang chờ"}). Chờ run đó kết thúc rồi mới bắt đầu run mới.
          </p>
        )}
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Run đang chọn</h2>
            {selectedRunId && <p className="section-sub mono">{selectedRunId}</p>}
          </div>
        </div>
        {!selectedRunId && <PipelineStageStrip tasks={[]} />}
        {selectedRunId && runDetailError && (
          <ErrorState
            kind={runDetailError.kind === "notfound" ? "notfound" : "system"}
            detail={runDetailError.detail}
            onRetry={() => loadRunDetail(selectedRunId)}
          />
        )}
        {selectedRunId && !runDetailError && !runDetail && <LoadingSkeleton rows={4} />}
        {selectedRunId && !runDetailError && runDetail && (
          <>
            <PipelineStageStrip tasks={runDetail.tasks} />
            {stuckQueued && (
              <p className="warn-note">
                Run đã chờ hơn một phút mà chưa bắt đầu. Nguyên nhân thường gặp nhất: DAG <code>ml_pipeline</code>{" "}
                đang bị paused trong Airflow — scheduler sẽ không chạy task nào cho tới khi DAG được mở. API không
                cho biết DAG có paused hay không, nên hãy kiểm tra ở Airflow UI (cổng 8080).
              </p>
            )}
          </>
        )}
      </section>

      <section className="card">
        <div className="section-head">
          <div>
            <h2>Lần chạy gần đây</h2>
            <p className="section-sub">Chọn một dòng để xem tiến độ.</p>
          </div>
        </div>
        {runsState.status === "loading" && <LoadingSkeleton rows={3} />}
        {runsState.status === "error" && (
          <ErrorState
            kind={runsState.error.kind === "notfound" ? "notfound" : "system"}
            detail={runsState.error.detail}
            onRetry={loadRuns}
          />
        )}
        {runsState.status === "data" && runsState.runs.length === 0 && (
          <EmptyState title="Chưa có lần chạy nào." description="Chọn loại model và bắt đầu train." />
        )}
        {runsState.status === "data" && runsState.runs.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>RUN ID</th>
                  <th>TRẠNG THÁI</th>
                  <th>LOẠI</th>
                  <th>BẮT ĐẦU</th>
                  <th>THỜI LƯỢNG</th>
                </tr>
              </thead>
              <tbody>
                {runsState.runs.map((run) => (
                  <tr
                    key={run.run_id}
                    className={selectedRunId === run.run_id ? "row-selected" : ""}
                    onClick={() => setSelectedRunId(run.run_id)}
                  >
                    <td className="mono truncate" title={run.run_id}>
                      {run.run_id}
                    </td>
                    <td>
                      <TaskStateBadge state={run.state} size="sm" />
                    </td>
                    <td>{run.task_type ?? "—"}</td>
                    <td>
                      <RelativeTime iso={run.started_at} />
                    </td>
                    <td>{formatDuration(durationBetween(run.started_at, run.ended_at))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {confirmOpen && (
        <ConfirmDialog
          title="Xác nhận bắt đầu train"
          confirmLabel="Bắt đầu train"
          busy={triggering}
          onConfirm={confirmTrigger}
          onCancel={() => setConfirmOpen(false)}
        >
          <p>
            Model: <b>{taskType === "regression" ? "Hồi quy giá nhà" : "Phân loại cần cải tạo"}</b>
          </p>
          <p>
            Thuật toán: <b>{estimatorName || "mặc định của pipeline (xgboost)"}</b>
          </p>
          <p>
            Hyperparameter: <b>{tuneHyperparameters ? "tuning bằng time-based cross-validation" : "mặc định"}</b>
          </p>
          <p>
            Phiên bản dữ liệu: <b>{datasetVersion}</b>
          </p>
          <p>
            Số dòng train: <b>{useAllRows ? "toàn bộ train set" : `${sampleRows} dòng, lấy ngẫu nhiên từ train set`}</b>
          </p>
          <p>
            Xử lý lại dữ liệu: <b>{forceReprocess ? "có" : "không"}</b>
          </p>
          {useAllRows && (
            <p className="warn-note">
              Toàn bộ dữ liệu (2.012.000 dòng) cần nhiều RAM và thời gian hơn đáng kể so với một run nhỏ, trên máy
              16GB.
            </p>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
