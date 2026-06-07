import { createContext, useContext, useEffect, useState } from "react";
import { auth } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [config, setConfig] = useState({ google_enabled: false, dev_login_enabled: true });
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      setUser(await auth.me());
    } catch {
      setUser(null);
    }
  }

  useEffect(() => {
    (async () => {
      try {
        setConfig(await auth.config());
      } catch {
        /* ignore */
      }
      await refresh();
      setLoading(false);
    })();
  }, []);

  async function logout() {
    await auth.logout();
    setUser(null);
  }

  return (
    <AuthCtx.Provider value={{ user, config, loading, refresh, logout, setUser }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
