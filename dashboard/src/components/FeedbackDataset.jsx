import { useCallback, useEffect, useRef, useState } from "react";
import { Recycle } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import { useToast } from "./Toast";
import { ApiError } from "../lib/api";
import ConfirmDialog from "./ConfirmDialog";
import RelativeTime from "./RelativeTime";
import { TaskStateBadge } from "./StatusBadge";
import { ACTIVE_TRAFFIC_STATES, DATASET_VERSION_PATTERN, FEEDBACK_STAGE } from "../lib/constants";
import { formatNumber } from "../lib/format";

const POLL_MS = 5000;
const TASK_TYPE_LABELS = { regression: "Dự đoán giá bán", classification: "Dự đoán nhu cầu cải tạo" };

/**
 * Turns a `yyyy-mm-dd` date input into the ISO time the API expects.
 *
 * Args:
 *   day: The input's value, possibly empty.
 *   endOfDay: True for the end of a period, so the chosen day is included.
 *
 * Returns:
 *   An ISO string in UTC, or undefined when the input is empty (the API then
 *   uses its default: the last 30 days).
 */
function toIso(day, endOfDay) {
  if (!day) return undefined;
  return `${day}T${endOfDay ? "23:59:59" : "00:00:00"}+00:00`;
}

/**
 * Renders "create a dataset version from real traffic" (要件定義書 CN-42,
 * 基本設計書 8.3 màn hình 2).
 *
 * Retraining on the same data teaches the new model what the old one knew, so
 * a market that moved stays wrong. This turns the predictions that got their
 * real outcome back into training data. The number of such predictions is
 * shown first; below the minimum the create button stays locked and says why,
 * because the build would be refused anyway.
 *
 * Args:
 *   None. Reads the API client from DemoModeContext.
 *
 * Returns:
 *   A JSX section element.
 */
export default function FeedbackDataset() {
  const client = useClient();
  const pushToast = useToast();
  const [taskType, setTaskType] = useState("regression");
  const [sourceVersion, setSourceVersion] = useState("");
  const [startDay, setStartDay] = useState("");
  const [endDay, setEndDay] = useState("");
  const [newVersion, setNewVersion] = useState("");
  const [preview, setPreview] = useState({ status: "idle" });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [run, setRun] = useState(null);
  const timer = useRef(null);
  const wasRunning = useRef(false);

  const nameValid = DATASET_VERSION_PATTERN.test(newVersion);
  const sourceValid = sourceVersion === "" || DATASET_VERSION_PATTERN.test(sourceVersion);
  const running = run !== null && ACTIVE_TRAFFIC_STATES.has(run.state);
  const canCreate =
    preview.status === "data" && preview.body.enough && nameValid && sourceValid && !running && !starting;

  async function checkPreview() {
    setPreview({ status: "loading" });
    try {
      const body = await client.feedbackPreview(taskType, toIso(startDay, false), toIso(endDay, true));
      setPreview({ status: "data", body });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      setPreview({ status: "error", detail: typeof detail === "string" ? detail : "lỗi không xác định" });
    }
  }

  const refreshStatus = useCallback(async () => {
    try {
      const body = await client.feedbackStatus();
      setRun(body.run);
      const active = body.run !== null && ACTIVE_TRAFFIC_STATES.has(body.run.state);
      if (wasRunning.current && !active) {
        pushToast({
          type: body.run?.state === "success" ? "success" : "error",
          text:
            body.run?.state === "success"
              ? "Đã tạo data version từ traffic thực tế. Chọn nó ở màn Tổng quan để retrain."
              : `Tạo data version kết thúc ở trạng thái ${body.run?.state}. Xem log trên Airflow.`,
        });
      }
      wasRunning.current = active;
    } catch {
      // A failed poll is not a failed run; the next tick tries again.
    }
  }, [client, pushToast]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (!run || !ACTIVE_TRAFFIC_STATES.has(run.state)) return undefined;
    timer.current = setInterval(refreshStatus, POLL_MS);
    return () => clearInterval(timer.current);
  }, [run, refreshStatus]);

  async function confirmCreate() {
    setStarting(true);
    try {
      const result = await client.feedbackRun({
        task_type: taskType,
        new_version: newVersion,
        source_version: sourceVersion || null,
        period_start: toIso(startDay, false) ?? null,
        period_end: toIso(endDay, true) ?? null,
      });
      setConfirmOpen(false);
      wasRunning.current = true;
      setRun({ run_id: result.run_id, state: result.state, tasks: [] });
      pushToast({ type: "success", text: `Đã bắt đầu tạo ${newVersion}: run ${result.run_id}` });
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : null;
      pushToast({
        type: "error",
        text: `Không tạo được: ${typeof detail === "string" ? detail : "lỗi không xác định"}`,
      });
    } finally {
      setStarting(false);
    }
  }

  const task = (run?.tasks ?? []).find((item) => item.task_id === FEEDBACK_STAGE.id);

  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>
            <Recycle size={16} /> Tạo data version từ traffic thực tế
          </h2>
          <p className="section-sub">
            Những căn nhà đã được dự đoán và đã có ground truth trở thành training data mới. Retrain trên đúng data cũ
            thì không sửa được drift.
          </p>
        </div>
      </div>

      <div className="simulator-controls">
        <label>
          <span>Bài toán</span>
          <select
            value={taskType}
            disabled={running}
            onChange={(event) => {
              setTaskType(event.target.value);
              setPreview({ status: "idle" });
            }}
          >
            {Object.entries(TASK_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Data version nguồn</span>
          <input
            value={sourceVersion}
            disabled={running}
            placeholder="bỏ trống = data version của champion"
            onChange={(event) => setSourceVersion(event.target.value)}
          />
        </label>
        <label>
          <span>Từ ngày</span>
          <input
            type="date"
            value={startDay}
            disabled={running}
            onChange={(event) => {
              setStartDay(event.target.value);
              setPreview({ status: "idle" });
            }}
          />
        </label>
        <label>
          <span>Đến ngày</span>
          <input
            type="date"
            value={endDay}
            disabled={running}
            onChange={(event) => {
              setEndDay(event.target.value);
              setPreview({ status: "idle" });
            }}
          />
        </label>
      </div>
      <p className="hint-note">Bỏ trống khoảng thời gian = 30 ngày gần nhất.</p>
      {!sourceValid && <p className="field-error">Tên data version nguồn không hợp lệ.</p>}

      <div className="simulator-controls">
        <button className="btn-secondary" disabled={running || preview.status === "loading"} onClick={checkPreview}>
          Đếm số cặp dự đoán / ground truth
        </button>
        {preview.status === "loading" && <span className="hint-note">Đang đếm…</span>}
        {preview.status === "error" && <span className="field-error">{preview.detail}</span>}
        {preview.status === "data" && (
          <span>
            <b>{formatNumber(preview.body.matched)}</b> căn nhà có ground truth (tối thiểu{" "}
            {formatNumber(preview.body.minimum)}).
          </span>
        )}
      </div>
      {preview.status === "data" && !preview.body.enough && (
        <p className="warn-note">
          Chưa đủ {formatNumber(preview.body.minimum)} cặp: test set (20% feedback mới nhất) sẽ quá nhỏ để tin được.
          Gửi thêm traffic ở màn Giám sát drift rồi đếm lại.
        </p>
      )}

      <div className="simulator-controls">
        <label>
          <span>Tên data version mới *</span>
          <input
            value={newVersion}
            disabled={running}
            placeholder="ví dụ v1-fb1"
            onChange={(event) => setNewVersion(event.target.value)}
          />
        </label>
        <button className="btn-primary" disabled={!canCreate} onClick={() => setConfirmOpen(true)}>
          {running ? "Đang tạo…" : "Tạo data version"}
        </button>
      </div>
      {newVersion && !nameValid && (
        <p className="field-error">Chỉ chữ, số, dấu chấm, gạch dưới, gạch nối; bắt đầu bằng chữ hoặc số.</p>
      )}

      {run && (
        <div className={`traffic-status ${running ? "traffic-status-live" : ""}`}>
          <TaskStateBadge state={task?.state ?? run.state} size="sm" />
          <span>
            {FEEDBACK_STAGE.label}:{" "}
            {running ? (
              "đang chạy — màn hình tự cập nhật khi xong."
            ) : (
              <>lần gần nhất {run.ended_at ? <RelativeTime iso={run.ended_at} /> : "chưa rõ lúc nào"}.</>
            )}
          </span>
        </div>
      )}

      {confirmOpen && preview.status === "data" && (
        <ConfirmDialog
          title="Tạo data version từ traffic thực tế?"
          confirmLabel="Tạo data version"
          busy={starting}
          onConfirm={confirmCreate}
          onCancel={() => setConfirmOpen(false)}
        >
          <p>
            Tạo <b>{newVersion}</b> cho bài toán <b>{TASK_TYPE_LABELS[taskType]}</b> từ data version{" "}
            <b>{sourceVersion || "mà champion đã học"}</b>.
          </p>
          <p>
            Thêm <b>{formatNumber(preview.body.matched)}</b> feedback record. Record gốc của cùng căn nhà sẽ bị{" "}
            <b>thay thế</b> (con số chính xác ghi trong nguồn gốc của data version sau khi tạo).
          </p>
          <p className="warn-note">
            Test set của data version mới = 20% feedback mới nhất. Data version nguồn giữ nguyên, không bị sửa.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
