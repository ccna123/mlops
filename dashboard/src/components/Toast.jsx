import { createContext, useCallback, useContext, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

const ToastContext = createContext(null);

/**
 * Provides a `pushToast` function to the component tree and renders the
 * toast stack. Toasts auto-dismiss after ~4.2 seconds.
 *
 * Args:
 *   children: React children to render inside the provider.
 *
 * Returns:
 *   The provider element wrapping children, plus the rendered toast stack.
 */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const pushToast = useCallback((toast) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev, { id, ...toast }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  return (
    <ToastContext.Provider value={pushToast}>
      {children}
      <div className="toast-stack">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.type === "error" ? "toast-error" : "toast-success"}`}>
            {toast.type === "error" ? <XCircle size={16} /> : <CheckCircle2 size={16} />}
            <span>{toast.text}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/**
 * Reads the `pushToast` function from the nearest ToastProvider.
 *
 * Args:
 *   None.
 *
 * Returns:
 *   A function `(toast: {type: "success"|"error", text: string}) => void`.
 *
 * Raises:
 *   Error: If called outside a ToastProvider.
 */
export function useToast() {
  const pushToast = useContext(ToastContext);
  if (!pushToast) throw new Error("useToast must be used within ToastProvider");
  return pushToast;
}
