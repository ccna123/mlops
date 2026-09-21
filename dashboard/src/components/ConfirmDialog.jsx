import { X } from "lucide-react";

/**
 * Renders the modal confirmation required before the three real writes in
 * the API (brief §3.4): triggering a pipeline run, promoting a champion,
 * and overwriting an existing dataset version on upload.
 *
 * Args:
 *   title: Short dialog headline (e.g. "Bắt đầu train?").
 *   children: JSX body describing exactly what will be sent.
 *   confirmLabel: Text for the confirm button (never generic "OK", per
 *     the brief's rule that it must name the action, e.g. "Bắt đầu train").
 *   danger: When true, styles the confirm button as destructive (used for
 *     the dataset-overwrite dialog).
 *   busy: When true, disables both buttons and shows a sending state.
 *   onConfirm: Called when the confirm button is pressed.
 *   onCancel: Called when the cancel button, backdrop, or close icon is
 *     pressed.
 *
 * Returns:
 *   A JSX modal overlay and panel.
 */
export default function ConfirmDialog({ title, children, confirmLabel, danger, busy, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" role="presentation" onClick={onCancel}>
      <div className="modal-panel" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onCancel} aria-label="Đóng" disabled={busy}>
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">
          <button className="btn-ghost" onClick={onCancel} disabled={busy}>
            Hủy
          </button>
          <button className={danger ? "btn-danger" : "btn-primary"} onClick={onConfirm} disabled={busy}>
            {busy ? "Đang gửi…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
