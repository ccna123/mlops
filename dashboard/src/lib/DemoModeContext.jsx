import { createContext, useContext, useState } from "react";
import { api } from "./api";
import { demoApi } from "./demoApi";

const DemoModeContext = createContext(null);

/**
 * Provides the demo-mode flag and its setter to the component tree.
 *
 * Args:
 *   children: React children to render inside the provider.
 *
 * Returns:
 *   The provider element wrapping children.
 */
export function DemoModeProvider({ children }) {
  const [demo, setDemo] = useState(false);
  return <DemoModeContext.Provider value={{ demo, setDemo }}>{children}</DemoModeContext.Provider>;
}

/**
 * Reads the current demo-mode flag and its setter.
 *
 * Args:
 *   None.
 *
 * Returns:
 *   An object with `demo` (boolean) and `setDemo` (function).
 *
 * Raises:
 *   Error: If called outside a DemoModeProvider.
 */
export function useDemoMode() {
  const ctx = useContext(DemoModeContext);
  if (!ctx) throw new Error("useDemoMode must be used within DemoModeProvider");
  return ctx;
}

/**
 * Picks the real or demo API client based on the current demo-mode flag.
 *
 * Args:
 *   None.
 *
 * Returns:
 *   The `api` object when demo mode is off, or `demoApi` when it is on.
 *   Both expose the same method names, so callers never branch on which
 *   one they got.
 *
 * Example:
 *   const client = useClient();
 *   const runs = await client.listRuns(); # -> real fetch, or fixture data
 */
export function useClient() {
  const { demo } = useDemoMode();
  return demo ? demoApi : api;
}
