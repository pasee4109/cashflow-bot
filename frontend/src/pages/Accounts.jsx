import { useEffect, useState } from "react";
import { accounts as api } from "../api";

const EMPTY = {
  label: "", broker_id: "", app_id: "", app_secret: "", app_code: "",
  account_no: "", pin: "", account_type: "derivative",
};

export default function Accounts() {
  const [list, setList] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tg, setTg] = useState({ open: null, bot_token: "", chat_id: "" });

  async function load() {
    setList(await api.list());
  }
  useEffect(() => {
    load();
  }, []);

  function note(type, text) {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 6000);
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.create(form);
      setForm(EMPTY);
      await load();
      note("ok", "Account bound. Encrypted and stored.");
    } catch (e) {
      note("err", e.message);
    } finally {
      setBusy(false);
    }
  }

  async function act(fn, okText) {
    try {
      const r = await fn();
      await load();
      note("ok", okText(r));
    } catch (e) {
      note("err", e.message);
    }
  }

  const upd = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="page">
      <h2>Settrade Accounts</h2>
      <p className="muted">
        Bind one or more Settrade Open-API accounts. Credentials are encrypted at
        rest; the <b>active</b> account drives the dashboard. Switch any time.
      </p>

      {msg && <div className={msg.type === "ok" ? "banner ok" : "banner err"}>{msg.text}</div>}

      <div className="banner ok demo-cta">
        <span>🧪 อยากลองดู UI ก่อนมีบัญชี Settrade จริง? สร้าง <b>บัญชีเดโม</b> ที่มีข้อมูลจำลองครบ:</span>
        <span className="demo-btns">
          <button className="btn sm" onClick={() => act(() => api.createDemo("derivative"), () => "Demo TFEX account created")}>
            + Demo TFEX
          </button>
          <button className="btn sm ghost" onClick={() => act(() => api.createDemo("equity"), () => "Demo SET account created")}>
            + Demo SET
          </button>
        </span>
      </div>

      <div className="cols">
        <div className="card">
          <h3>Bound accounts</h3>
          {list.length === 0 && <div className="muted">No accounts yet.</div>}
          <div className="acct-list">
            {list.map((a) => (
              <div key={a.id} className={`acct ${a.is_active ? "active" : ""}`}>
                <div className="acct-head">
                  <strong>{a.label}</strong>
                  {a.is_active && <span className="pill blue">ACTIVE</span>}
                  {a.is_demo && <span className="pill amber">DEMO</span>}
                  <span className="pill">{a.account_type}</span>
                </div>
                <div className="acct-meta">
                  Broker <code>{a.broker_id}</code> · App <code>{a.app_id_masked}</code> ·
                  Acct <code>{a.account_no}</code> · PIN {a.has_pin ? "saved" : "—"}
                </div>
                <div className="acct-actions">
                  {!a.is_active && (
                    <button className="btn sm" onClick={() => act(() => api.activate(a.id), () => `Switched to ${a.label}`)}>
                      Set active
                    </button>
                  )}
                  <button className="btn sm ghost" onClick={() =>
                    act(() => api.connect(a.id), (r) =>
                      `Connected — deriv:${r.derivatives} equity:${r.equity} data:${r.market_data}`)}>
                    Test connect
                  </button>
                  <button className="btn sm ghost" onClick={() =>
                    setTg({ open: tg.open === a.id ? null : a.id, bot_token: "", chat_id: "" })}>
                    Telegram
                  </button>
                  <button className="btn sm danger" onClick={() => {
                    if (confirm(`Delete account "${a.label}"?`))
                      act(() => api.remove(a.id), () => "Account deleted");
                  }}>
                    Delete
                  </button>
                </div>
                {tg.open === a.id && (
                  <div className="tg-form">
                    <div className="muted">แจ้งเตือนผ่าน Telegram (เว้นว่างทั้งคู่ = ปิด)</div>
                    <input placeholder="Bot Token" value={tg.bot_token}
                      onChange={(e) => setTg({ ...tg, bot_token: e.target.value })} />
                    <input placeholder="Chat ID" value={tg.chat_id}
                      onChange={(e) => setTg({ ...tg, chat_id: e.target.value })} />
                    <button className="btn sm" onClick={() =>
                      act(() => api.telegram(a.id, { bot_token: tg.bot_token, chat_id: tg.chat_id }),
                        (r) => (r.enabled ? "Telegram alerts enabled" : "Telegram alerts disabled"))
                        .then(() => setTg({ open: null, bot_token: "", chat_id: "" }))}>
                      Save
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Bind a new account</h3>
          <form onSubmit={submit} className="form">
            <label>Label<input value={form.label} onChange={upd("label")} placeholder="TFEX Main" required /></label>
            <label>Account type
              <select value={form.account_type} onChange={upd("account_type")}>
                <option value="derivative">Derivative (TFEX)</option>
                <option value="equity">Equity (SET)</option>
              </select>
            </label>
            <label>Broker ID<input value={form.broker_id} onChange={upd("broker_id")} placeholder="e.g. SANDBOX / 041" required /></label>
            <label>App ID<input value={form.app_id} onChange={upd("app_id")} required /></label>
            <label>App Secret<input type="password" value={form.app_secret} onChange={upd("app_secret")} required /></label>
            <label>App Code<input value={form.app_code} onChange={upd("app_code")} required /></label>
            <label>Account No<input value={form.account_no} onChange={upd("account_no")} required /></label>
            <label>PIN<input type="password" value={form.pin} onChange={upd("pin")} placeholder="needed to place orders" /></label>
            <button className="btn" disabled={busy}>{busy ? "Saving…" : "Bind account"}</button>
          </form>
        </div>
      </div>
    </div>
  );
}
