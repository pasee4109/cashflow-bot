import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { accounts as acctApi, grid } from "../api";

const DEFAULT_PARAMS = { grid_levels: 5, buyback_ticks: 3, allocation_pct: 30, ladder_weights: [1, 2, 3, 4, 5] };

export default function Dashboard() {
  const [active, setActive] = useState(undefined); // undefined=loading, null=none
  const [portfolio, setPortfolio] = useState([]);
  const [selected, setSelected] = useState([]);
  const [params, setParams] = useState(DEFAULT_PARAMS);
  const [previews, setPreviews] = useState({});
  const [sessions, setSessions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  async function loadActive() {
    const list = await acctApi.list();
    setActive(list.find((a) => a.is_active) || null);
  }
  async function loadSessions() {
    try { setSessions(await grid.sessions()); } catch { /* none */ }
  }
  async function loadLogs() {
    try { setLogs(await grid.logs()); } catch { /* none */ }
  }

  useEffect(() => { loadActive(); }, []);
  useEffect(() => {
    if (!active) return;
    loadSessions();
    loadLogs();
    const t = setInterval(() => { loadSessions(); loadLogs(); }, 6000);
    return () => clearInterval(t);
  }, [active]);

  async function refreshPortfolio() {
    setErr(""); setBusy("portfolio");
    try { setPortfolio(await grid.portfolio()); }
    catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  }

  function toggleSymbol(sym) {
    setSelected((s) => (s.includes(sym) ? s.filter((x) => x !== sym) : [...s, sym]));
  }

  async function buildPreviews() {
    setErr(""); setBusy("preview");
    const out = {};
    try {
      for (const sym of selected) {
        out[sym] = await grid.preview({ symbol: sym, ...params });
      }
      setPreviews(out);
    } catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  }

  async function deploy() {
    if (selected.length === 0) return;
    if (!confirm(`Deploy grids for ${selected.join(", ")}? This places live orders.`)) return;
    setErr(""); setBusy("deploy");
    try {
      await grid.deploy({ symbols: selected, ...params });
      await loadSessions(); await loadLogs();
    } catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  }

  async function sessionAction(fn) {
    try { await fn(); await loadSessions(); await loadLogs(); }
    catch (e) { setErr(e.message); }
  }

  if (active === undefined) return <div className="page">Loading…</div>;
  if (active === null)
    return (
      <div className="page">
        <div className="banner err">
          No active Settrade account. <Link to="/accounts">Bind & activate an account</Link> to start.
        </div>
      </div>
    );

  return (
    <div className="page">
      <div className="active-bar">
        <span className="pill blue">ACTIVE</span>
        <b>{active.label}</b>
        <span className="muted">{active.account_type} · broker {active.broker_id} · acct {active.account_no}</span>
        <Link to="/accounts" className="muted right">manage / switch →</Link>
      </div>

      {err && <div className="banner err">{err}</div>}

      {/* Grid parameters */}
      <div className="card">
        <h3>Grid parameters</h3>
        <div className="params">
          <label>Levels
            <input type="number" min="2" max="10" value={params.grid_levels}
              onChange={(e) => setParams({ ...params, grid_levels: +e.target.value })} />
          </label>
          <label>Buyback ticks
            <input type="number" min="1" max="10" value={params.buyback_ticks}
              onChange={(e) => setParams({ ...params, buyback_ticks: +e.target.value })} />
          </label>
          <label>Allocation %
            <input type="number" min="5" max="100" value={params.allocation_pct}
              onChange={(e) => setParams({ ...params, allocation_pct: +e.target.value })} />
          </label>
          <label>Ladder weights
            <input value={params.ladder_weights.join(",")}
              onChange={(e) => setParams({ ...params, ladder_weights: e.target.value.split(",").map((x) => +x.trim()).filter((n) => n) })} />
          </label>
        </div>
      </div>

      {/* Portfolio */}
      <div className="card">
        <div className="card-head">
          <h3>Portfolio</h3>
          <button className="btn sm" onClick={refreshPortfolio} disabled={busy === "portfolio"}>
            {busy === "portfolio" ? "Fetching…" : "Refresh portfolio"}
          </button>
        </div>
        {portfolio.length === 0 ? (
          <div className="muted">No positions loaded. Click “Refresh portfolio”.</div>
        ) : (
          <table className="tbl">
            <thead><tr><th></th><th>Symbol</th><th>Market</th><th>Volume</th><th>Avg cost</th><th>Mkt price</th><th>Unreal. PnL</th></tr></thead>
            <tbody>
              {portfolio.map((r) => (
                <tr key={r.symbol}>
                  <td><input type="checkbox" checked={selected.includes(r.symbol)} onChange={() => toggleSymbol(r.symbol)} /></td>
                  <td><b>{r.symbol}</b></td>
                  <td>{r.market_type}</td>
                  <td>{r.volume}</td>
                  <td>{r.avg_cost.toFixed(2)}</td>
                  <td>{r.market_price.toFixed(2)}</td>
                  <td className={r.unrealized_pnl >= 0 ? "pos" : "neg"}>{r.unrealized_pnl.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {selected.length > 0 && (
          <div className="actions">
            <button className="btn sm" onClick={buildPreviews} disabled={busy === "preview"}>
              {busy === "preview" ? "Computing…" : `Preview grid (${selected.length})`}
            </button>
            <button className="btn sm primary" onClick={deploy} disabled={busy === "deploy"}>
              {busy === "deploy" ? "Deploying…" : "🚀 Deploy grids"}
            </button>
          </div>
        )}
      </div>

      {/* Previews */}
      {Object.entries(previews).map(([sym, p]) => (
        <div className="card" key={sym}>
          <h3>Preview — {sym}</h3>
          <div className="metrics">
            <Metric label="Last" value={p.last_price.toFixed(2)} />
            <Metric label="ATR" value={p.atr_value.toFixed(2)} />
            <Metric label="Tick" value={p.tick_size} />
            <Metric label="Holding" value={p.holding} />
            <Metric label="Alloc vol" value={p.alloc_volume} />
            <Metric label="Total sell" value={p.total_sell_volume} />
          </div>
          <table className="tbl">
            <thead><tr><th>Lv</th><th>Sell @</th><th>Vol</th><th>Spread</th><th>Buyback @</th><th>Cashflow/unit</th></tr></thead>
            <tbody>
              {p.levels.map((l) => (
                <tr key={l.level}>
                  <td>L{l.level}</td>
                  <td>{l.sell_price.toFixed(2)}</td>
                  <td>{l.volume}</td>
                  <td className="pos">+{l.spread.toFixed(2)} ({l.spread_pct.toFixed(2)}%)</td>
                  <td>{l.buyback_price.toFixed(2)}</td>
                  <td>{l.cashflow_per_unit.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted">Range {p.price_range} · max ±1 ATR = {p.atr_value.toFixed(2)}</div>
        </div>
      ))}

      {/* Sessions */}
      {sessions.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>Grid sessions</h3>
            <button className="btn sm danger" onClick={() => sessionAction(grid.stopAll)}>Stop all monitors</button>
          </div>
          <table className="tbl">
            <thead><tr><th>Symbol</th><th>Session</th><th>Status</th><th>Sells</th><th>Buybacks</th><th>Open</th><th>PnL</th><th></th></tr></thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.session_id}>
                  <td><b>{s.symbol}</b></td>
                  <td><code>{s.session_id}</code></td>
                  <td><span className={`pill ${s.status === "active" ? "blue" : ""}`}>{s.status}</span></td>
                  <td>{s.sells_matched}</td>
                  <td>{s.buys_matched}</td>
                  <td>{s.orders_active}</td>
                  <td className={s.total_pnl >= 0 ? "pos" : "neg"}>{s.total_pnl.toFixed(2)}</td>
                  <td className="row-actions">
                    {s.status === "active" && (
                      <button className="btn xs" onClick={() => sessionAction(() => grid.stop(s.session_id))}>Pause</button>
                    )}
                    {s.status !== "closed" && (
                      <button className="btn xs danger" onClick={() => sessionAction(() => grid.cancel(s.session_id))}>Cancel</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Logs */}
      <div className="card">
        <h3>Activity log</h3>
        <div className="logterm">
          {logs.length === 0 && <div className="muted">No log entries yet.</div>}
          {logs.map((l, i) => (
            <div key={i} className={`logline lvl-${l.level.toLowerCase()}`}>
              <span className="ts">{new Date(l.timestamp).toLocaleTimeString()}</span>
              <span className="lvl">[{l.level}]</span> {l.message}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <div className="m-val">{value}</div>
      <div className="m-lbl">{label}</div>
    </div>
  );
}
