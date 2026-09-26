import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useClient } from "../lib/DemoModeContext";
import LoadingSkeleton from "./LoadingSkeleton";
import { formatNumber } from "../lib/format";

/**
 * Formats the split points a training run logged (a JSON string) for reading.
 *
 * Args:
 *   raw: The `split_points` value from the card, a JSON string or null.
 *
 * Returns:
 *   A short text such as "original: T1 2023-11-02, T2 2024-10-15", or the raw
 *   value when it is not JSON.
 */
function describeSplitPoints(raw) {
  if (!raw || raw === "unknown") return "không ghi lại";
  try {
    return Object.entries(JSON.parse(raw))
      .map(([source, rule]) => `${source}: T1 ${rule.t1}, T2 ${rule.t2 ?? "—"}`)
      .join(" · ");
  } catch {
    return raw;
  }
}

/**
 * Shows the model card of one model version (要件定義書 CN-12): what it is for,
 * what it learned from, how good it is overall and per group, its decision
 * threshold, the columns it may not use, and where it is known to be weak.
 *
 * Args:
 *   modelName: The registered model.
 *   version: The version whose card to show.
 *   onClose: Called when the dialog is closed.
 *
 * Returns:
 *   A JSX modal. A version registered before cards existed shows why there is
 *   nothing, not an error.
 */
export default function ModelCardDialog({ modelName, version, onClose }) {
  const client = useClient();
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    client
      .modelCard(modelName, version)
      .then((card) => setState({ status: "data", card }))
      .catch((error) => setState({ status: error?.kind === "notfound" ? "none" : "error", error }));
  }, [client, modelName, version]);

  const card = state.card;
  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div className="modal-panel modal-wide" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>
            Model card — {modelName} v{version}
          </h3>
          <button className="icon-btn" onClick={onClose} aria-label="Đóng">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">
          {state.status === "loading" && <LoadingSkeleton rows={4} />}
          {state.status === "none" && (
            <p>
              Version này <b>chưa có model card</b> — nó được đăng ký trước khi hệ thống tạo model card, hoặc ngoài
              pipeline.
            </p>
          )}
          {state.status === "error" && <p className="field-error">Không đọc được model card: {state.error?.detail}</p>}
          {state.status === "data" && (
            <div className="model-card">
              <p>{card.purpose}</p>
              <table>
                <tbody>
                  <tr>
                    <th>Thuật toán</th>
                    <td>
                      {card.algorithm?.estimator ?? "—"}
                      {card.algorithm?.tuned === "True" && " (đã tuning)"}
                    </td>
                  </tr>
                  {card.algorithm?.decision_threshold !== null && card.algorithm?.decision_threshold !== undefined && (
                    <tr>
                      <th>Decision threshold</th>
                      <td>{Number(card.algorithm.decision_threshold).toFixed(3)} (chọn để recall ≥ 70%)</td>
                    </tr>
                  )}
                  <tr>
                    <th>Data version</th>
                    <td>
                      {card.data?.dataset_version ?? "—"} · data ID <code>{card.data?.data_id ?? "—"}</code>
                    </td>
                  </tr>
                  <tr>
                    <th>Split point</th>
                    <td>{describeSplitPoints(card.data?.split_points)}</td>
                  </tr>
                  <tr>
                    <th>Số dòng train</th>
                    <td>
                      {card.data?.train_rows ? formatNumber(Number(card.data.train_rows)) : "—"} · random seed{" "}
                      {card.data?.seed ?? "—"}
                    </td>
                  </tr>
                  <tr>
                    <th>Source code</th>
                    <td>
                      commit <code>{card.code?.git_commit ?? "—"}</code> · image <code>{card.code?.image_digest ?? "—"}</code>
                    </td>
                  </tr>
                  <tr>
                    <th>Metric trên test set</th>
                    <td>
                      {Object.entries(card.metrics?.test ?? {})
                        .map(([key, value]) => `${key} ${formatNumber(value)}`)
                        .join(" · ") || "—"}
                    </td>
                  </tr>
                  <tr>
                    <th>Cột không dùng làm feature</th>
                    <td>{(card.excluded_columns ?? []).join(", ")}</td>
                  </tr>
                </tbody>
              </table>
              <p className="section-sub">Hạn chế đã biết</p>
              <ul>
                {(card.known_limitations ?? []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
