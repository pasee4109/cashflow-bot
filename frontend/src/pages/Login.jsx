import { useState } from "react";
import { auth } from "../api";
import { useAuth } from "../AuthContext.jsx";

export default function Login() {
  const { config, refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function devLogin(e) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await auth.devLogin(email || "dev@example.com");
      await refresh();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>📈 TFEX Cashflow Ladder</h1>
        <p className="muted">
          Automated grid trading on TFEX via the Settrade API. Sign in, then bind
          your Settrade account(s).
        </p>

        {config.google_enabled ? (
          <a className="btn google" href={auth.googleLoginUrl}>
            <span className="g">G</span> Sign in with Google
          </a>
        ) : (
          <div className="notice">
            Google Sign-In isn’t configured on the server. Set <code>GOOGLE_CLIENT_ID</code>
            /<code>GOOGLE_CLIENT_SECRET</code> in the backend <code>.env</code> to enable it.
          </div>
        )}

        {config.dev_login_enabled && (
          <form onSubmit={devLogin} className="devlogin">
            <div className="sep">developer login</div>
            <input
              type="email"
              placeholder="email (optional)"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button className="btn" disabled={busy}>
              {busy ? "Signing in…" : "Continue (dev)"}
            </button>
          </form>
        )}
        {err && <div className="error">{err}</div>}
      </div>
    </div>
  );
}
