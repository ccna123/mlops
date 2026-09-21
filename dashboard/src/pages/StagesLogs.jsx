import { useEffect, useState } from "react";
import LoadingSkeleton from "../components/LoadingSkeleton";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import { STAGE_ORDER, STAGE_LABELS } from "../lib/constants";
import { useClient } from "../lib/DemoModeContext";

const LEVELS = ["", "INFO", "WARNING", "ERROR"];

// A lone attempt with no served log comes back as 200 with Airflow's own
// error text inside `lines`, not a 404 (brief §4.2) — recognized by content,
// since there is no reliable line position to key off instead.
function isNoServedLogBanner(line) {
  return line.startsWith("*** Could not read served logs") || line.startsWith("*** !!!! Please make sure");
}

function levelOf(line) {
  if (/\bERROR\b/.test(line)) return "error";
  if (/\bWARNING\b/.test(line)) return "warning";
  return null;
}

function LogViewer({ lines, truncated, taskState, hasFilters, onClearFilters }) {
  if (lines.length === 0) {
    return hasFilters ? (
      <EmptyState
        title="Không có dòng nào khớp bộ lọc."
        action={
          <button className="btn-secondary" onClick={onClearFilters}>
            Xóa lọc
          </button>
        }
      />
    ) : (
      <EmptyState title="Task này không có output." description="Đây không phải lỗi — không phải stage nào cũng ghi log." />
    );
  }
  return (
    <div className="log">
      <div className="logbar">
        {lines.length} dòng
        {truncated && <span className="log-truncated"> · Đã cắt ở 2.000 dòng, hãy lọc để thấy phần còn lại</span>}
      </div>
      {taskState === "skipped" && (
        <div className="log-banner">Task này đã bị bỏ qua (skipped) — chỉ có phần khởi động của Airflow, không có output của stage.</div>
      )}
      {lines.some(isNoServedLogBanner) && <div className="log-banner">Airflow không có log cho lần thử này.</div>}
      <div className="log-body">
        {lines.map((line, index) => {
          const level = levelOf(line);
          const muted = isNoServedLogBanner(line) || line.startsWith("***");
          return (
            <div key={index} className={`log-line ${level ? `log-${level}` : ""} ${muted ? "log-muted" : ""}`}>
              {line || " "}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Renders the Stages & Logs screen: pick a run and a stage, fetch its log
 * on demand, filter server-side by level/keyword (brief §4.2).
 *
 * Args:
 *   None. Reads the API client from DemoModeContext.
 *
 * Returns:
 *   A JSX page element.
 */
export default function StagesLogs() {
  const client = useClient();
  const [runs, setRuns] = useState({ status: "loading" });
  const [runId, setRunId] = useState(null);
  const [runDetail, setRunDetail] = useState(null);
  const [stage, setStage] = useState("extract");
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const [logState, setLogState] = useState({ status: "idle" });

  useEffect(() => {
    async function load() {
      setRuns({ status: "loading" });
      try {
        const body = await client.listRuns(3);
        setRuns({ status: "data", runs: body.runs });
        if (body.runs.length > 0) setRunId(body.runs[0].run_id);
      } catch (error) {
        setRuns({ status: "error", error });
      }
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  useEffect(() => {
    if (!runId) return;
    setRunDetail(null);
    setLogState({ status: "idle" });
    client
      .getRun(runId)
      .then(setRunDetail)
      .catch(() => setRunDetail(null));
  }, [runId, client]);

  const tasksById = new Map((runDetail?.tasks ?? []).map((task) => [task.task_id, task]));
  const currentTask = tasksById.get(stage);

  async function fetchLogs() {
    if (!runId) return;
    const tryNumber = currentTask?.try_number ?? 0;
    // A task with state null (or missing try_number) has never run — do not
    // call the log endpoint at all, per brief §4.2's closing note.
    if (!currentTask || currentTask.state === null || tryNumber < 1) {
      setLogState({ status: "not-started" });
      return;
    }
    setLogState({ status: "loading" });
    try {
      const body = await client.getLogs(runId, { stage, level: level || undefined, q: q || undefined, tryNumber });
      setLogState({ status: "data", lines: body.lines, truncated: body.truncated });
    } catch (error) {
      setLogState({ status: "error", error });
    }
  }

  function clearFilters() {
    setLevel("");
    setQ("");
  }

  return (
    <div className="page-grid-single">
      <section className="card">
        <div className="section-head">
          <div>
            <h2>Nhật ký stage</h2>
            <p className="section-sub">Log chỉ được lấy khi bạn bấm tải — không stream, không tự làm mới.</p>
          </div>
        </div>

        <div className="tabs">
          {STAGE_ORDER.map((id) => {
            const task = tasksById.get(id);
            const disabled = !runDetail || !task || task.state === null;
            return (
              <button
                key={id}
                className={`tab ${stage === id ? "tab-active" : ""} ${disabled ? "tab-disabled" : ""}`}
                onClick={() => {
                  setStage(id);
                  setLogState({ status: "idle" });
                }}
              >
                {STAGE_LABELS[id]}
              </button>
            );
          })}
        </div>

        <div className="filters">
          {runs.status === "data" && (
            <select value={runId ?? ""} onChange={(event) => setRunId(event.target.value)}>
              {runs.runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.run_id}
                </option>
              ))}
            </select>
          )}
          <select value={level} onChange={(event) => setLevel(event.target.value)}>
            {LEVELS.map((value) => (
              <option key={value} value={value}>
                {value === "" ? "Tất cả mức" : value}
              </option>
            ))}
          </select>
          <input placeholder="Tìm trong log…" value={q} onChange={(event) => setQ(event.target.value)} />
          <button className="btn-primary" onClick={fetchLogs}>
            Tải log
          </button>
        </div>

        {runs.status === "loading" && <LoadingSkeleton rows={3} />}
        {runs.status === "error" && <ErrorState kind="system" detail={runs.error.detail} />}

        {runs.status === "data" && logState.status === "idle" && (
          <EmptyState title="Chọn run và stage, rồi bấm tải log." />
        )}
        {logState.status === "not-started" && (
          <EmptyState title="Chưa chạy, chưa có log." description="Task này chưa bắt đầu hoặc đã bị bỏ qua." />
        )}
        {logState.status === "loading" && <LoadingSkeleton rows={6} className="log-skeleton" />}
        {logState.status === "error" && (
          <ErrorState
            kind={logState.error.kind === "notfound" ? "notfound" : "system"}
            detail={logState.error.detail}
            onRetry={fetchLogs}
          />
        )}
        {logState.status === "data" && (
          <LogViewer
            lines={logState.lines}
            truncated={logState.truncated}
            taskState={currentTask?.state}
            hasFilters={Boolean(level || q)}
            onClearFilters={clearFilters}
          />
        )}
      </section>
    </div>
  );
}
