import { Inbox } from "lucide-react";

/**
 * Renders the "nothing here yet" state — explicitly not an error (brief §3.2
 * and §3.3: every screen must tell empty apart from broken).
 *
 * Args:
 *   title: Short headline explaining why the screen is empty.
 *   description: Optional longer explanation or next step.
 *   action: Optional JSX action element (e.g. a button) rendered below.
 *
 * Returns:
 *   A JSX empty-state block.
 *
 * Example:
 *   <EmptyState title="Chưa có lần chạy nào" /> # -> icon + headline, no error styling
 */
export default function EmptyState({ title, description, action }) {
  return (
    <div className="empty-state">
      <Inbox size={28} className="empty-state-icon" />
      <p className="empty-state-title">{title}</p>
      {description && <p className="empty-state-desc">{description}</p>}
      {action}
    </div>
  );
}
