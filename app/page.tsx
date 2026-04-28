"use client";

import { useEffect, useState, useRef, useCallback } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────
interface Asset {
  symbol: string;
  recommendation: string;
  confidence: number;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  lot_size: number | null;
  risk_usd: number | null;
  holding_time_opt: number | null;
  holding_time_base: number | null;
  holding_time_pess: number | null;
}

interface ApiResponse {
  assets: Record<string, Asset>;
  meta: { last_fetch: string; next_sync: number };
}

interface TradeEntry {
  id: number;
  timestamp: string;
  symbol: string;
  recommendation: string;
  confidence: number;
  entry: number;
  stop_loss: number;
  take_profit: number;
  lot_size: number | null;
  risk_usd: number | null;
}

interface ReportsResponse {
  total: number;
  entries: TradeEntry[];
}

type Tab = "dashboard" | "reports";

// ─── Helpers ─────────────────────────────────────────────────────────────────
function signalMeta(rec: string) {
  if (rec.includes("STRONG BUY"))  return { color: "#00e676", glow: "#00e67640", bg: "#00e67612" };
  if (rec.includes("STRONG SELL")) return { color: "#ff1744", glow: "#ff174440", bg: "#ff174412" };
  if (rec.includes("WEAK BUY"))    return { color: "#69f0ae", glow: "#69f0ae30", bg: "#69f0ae10" };
  if (rec.includes("WEAK SELL"))   return { color: "#ff6d6d", glow: "#ff6d6d30", bg: "#ff6d6d10" };
  if (rec.includes("BUY"))         return { color: "#40c4ff", glow: "#40c4ff40", bg: "#40c4ff12" };
  if (rec.includes("SELL"))        return { color: "#ff9100", glow: "#ff910040", bg: "#ff910012" };
  return { color: "#546e7a", glow: "#546e7a20", bg: "#546e7a10" };
}

function fmt(val: number | null, decimals = 5): string {
  if (val === null || val === undefined) return "—";
  return val.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtMinutes(mins: number | null): string {
  if (mins === null || mins === undefined) return "—";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

function fmtTimestamp(iso: string): { date: string; time: string } {
  const d = new Date(iso);
  return {
    date: d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }),
    time: d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }),
  };
}

function exportCSV(entries: TradeEntry[]) {
  const headers = ["ID", "Date", "Time (UTC)", "Symbol", "Signal", "Confidence (%)", "Entry", "Stop Loss", "Take Profit", "Lot Size", "Risk (USD)"];
  const rows = entries.map((e) => {
    const d = new Date(e.timestamp);
    const date = d.toISOString().slice(0, 10);
    const time = d.toISOString().slice(11, 19);
    return [
      e.id,
      date,
      time,
      e.symbol,
      e.recommendation,
      e.confidence,
      e.entry,
      e.stop_loss,
      e.take_profit,
      e.lot_size ?? "",
      e.risk_usd ?? "",
    ].join(",");
  });

  const csv  = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `trade_report_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Confidence bar ──────────────────────────────────────────────────────────
function ConfidenceBar({ value, color }: { value: number; color: string }) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setWidth(value), 120);
    return () => clearTimeout(t);
  }, [value]);

  return (
    <div style={{ marginBottom: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem" }}>
        <span style={{ fontFamily: "var(--font-label)", fontSize: "0.65rem", letterSpacing: "0.12em", color: "var(--muted)", textTransform: "uppercase" }}>
          Confidence
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.9rem", color, fontWeight: 600 }}>
          {value}%
        </span>
      </div>
      <div style={{ height: "3px", background: "var(--track)", borderRadius: "2px", overflow: "hidden" }}>
        <div style={{
          height: "100%",
          width: `${width}%`,
          background: color,
          boxShadow: `0 0 8px ${color}`,
          transition: "width 0.9s cubic-bezier(0.22, 1, 0.36, 1)",
          borderRadius: "2px",
        }} />
      </div>
    </div>
  );
}

// ─── Data row ────────────────────────────────────────────────────────────────
function DataRow({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "0.55rem 0",
      borderBottom: "1px solid var(--divider)",
    }}>
      <span style={{ fontFamily: "var(--font-label)", fontSize: "0.62rem", letterSpacing: "0.12em", color: "var(--muted)", textTransform: "uppercase" }}>
        {label}
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.88rem", color: accent ?? "var(--text)", fontWeight: 500 }}>
        {value}
      </span>
    </div>
  );
}

// ─── Holding time range bar ──────────────────────────────────────────────────
function HoldingTimeBar({ opt, base, pess, color }: {
  opt: number | null; base: number | null; pess: number | null; color: string;
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 200);
    return () => clearTimeout(t);
  }, []);

  if (opt === null || base === null || pess === null) {
    return <div style={{ color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: "0.75rem", padding: "0.4rem 0" }}>—</div>;
  }

  const optPct  = (opt  / pess) * 100;
  const basePct = (base / pess) * 100;

  return (
    <div style={{ marginBottom: "0.2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem", alignItems: "flex-end" }}>
        <div style={{ textAlign: "left" }}>
          <div style={{ fontFamily: "var(--font-label)", fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", textTransform: "uppercase", marginBottom: "0.15rem" }}>Best case</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "#69f0ae", fontWeight: 600 }}>{fmtMinutes(opt)}</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-label)", fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", textTransform: "uppercase", marginBottom: "0.15rem" }}>Est. hold</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.95rem", color, fontWeight: 700 }}>{fmtMinutes(base)}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--font-label)", fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", textTransform: "uppercase", marginBottom: "0.15rem" }}>Worst case</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "#ff6d6d", fontWeight: 600 }}>{fmtMinutes(pess)}</div>
        </div>
      </div>
      <div style={{ position: "relative", height: "4px", background: "var(--track)", borderRadius: "3px", overflow: "visible" }}>
        <div style={{
          position: "absolute", left: 0, top: 0, height: "100%",
          width: animated ? `${optPct}%` : "0%",
          background: `linear-gradient(90deg, #69f0ae, ${color})`,
          borderRadius: "3px",
          transition: "width 1s cubic-bezier(0.22, 1, 0.36, 1)",
        }} />
        <div style={{
          position: "absolute", left: `${optPct}%`, top: 0, height: "100%",
          width: animated ? `${100 - optPct}%` : "0%",
          background: `repeating-linear-gradient(90deg, ${color}50 0px, ${color}50 4px, transparent 4px, transparent 8px)`,
          borderRadius: "0 3px 3px 0",
          transition: "width 1s cubic-bezier(0.22, 1, 0.36, 1) 0.1s",
        }} />
        <div style={{
          position: "absolute", left: `${basePct}%`, top: "-4px",
          transform: "translateX(-50%)", width: "2px", height: "12px",
          background: color, boxShadow: `0 0 6px ${color}`, borderRadius: "1px",
          opacity: animated ? 1 : 0, transition: "opacity 0.5s ease 0.8s",
        }} />
      </div>
    </div>
  );
}

// ─── Asset card ──────────────────────────────────────────────────────────────
function AssetCard({ asset }: { asset: Asset }) {
  const sig     = signalMeta(asset.recommendation);
  const noTrade = asset.entry === null;

  return (
    <div style={{
      background: "var(--card)",
      border: "1px solid var(--border)",
      borderTop: `2px solid ${sig.color}`,
      borderRadius: "4px",
      padding: "1.5rem",
      boxShadow: `0 4px 24px ${sig.glow}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.2rem" }}>
        <span style={{ fontFamily: "var(--font-display)", fontSize: "1rem", letterSpacing: "0.15em", color: "var(--text)", textTransform: "uppercase" }}>
          {asset.symbol}
        </span>
        <span style={{
          fontFamily: "var(--font-label)", fontSize: "0.6rem", letterSpacing: "0.2em",
          color: sig.color, background: sig.bg,
          border: `1px solid ${sig.color}40`, borderRadius: "2px",
          padding: "0.2rem 0.5rem", textTransform: "uppercase",
        }}>
          {asset.recommendation}
        </span>
      </div>

      <ConfidenceBar value={asset.confidence} color={sig.color} />

      {!noTrade ? (
        <>
          <SectionLabel>Trade Parameters</SectionLabel>
          <DataRow label="Entry"     value={fmt(asset.entry)} />
          <DataRow label="Stop Loss" value={fmt(asset.stop_loss)}   accent="#ff6d6d" />
          <DataRow label="Target"    value={fmt(asset.take_profit)} accent="#69f0ae" />
          <SectionLabel style={{ marginTop: "1rem" }}>Risk Management</SectionLabel>
          <DataRow label="Lot Size" value={asset.lot_size !== null ? `${asset.lot_size} lots` : "—"} />
          <DataRow label="Risk"     value={asset.risk_usd !== null ? `$${asset.risk_usd.toFixed(2)}` : "—"} accent="#ffcc02" />
          <SectionLabel style={{ marginTop: "1rem", marginBottom: "0.6rem" }}>Estimated Holding Time</SectionLabel>
          <HoldingTimeBar
            opt={asset.holding_time_opt}
            base={asset.holding_time_base}
            pess={asset.holding_time_pess}
            color={sig.color}
          />
        </>
      ) : (
        <div style={{ color: "var(--muted)", fontFamily: "var(--font-label)", fontSize: "0.7rem", letterSpacing: "0.1em", textAlign: "center", padding: "1rem 0" }}>
          NO TRADE CONDITIONS MET
        </div>
      )}
    </div>
  );
}

function SectionLabel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      fontFamily: "var(--font-label)", fontSize: "0.58rem", letterSpacing: "0.18em",
      color: "var(--muted)", textTransform: "uppercase",
      marginBottom: "0.2rem", paddingTop: "0.1rem", ...style,
    }}>
      {children}
    </div>
  );
}

// ─── Countdown ring ──────────────────────────────────────────────────────────
function CountdownRing({ seconds, total }: { seconds: number; total: number }) {
  const r    = 10;
  const circ = 2 * Math.PI * r;
  const dash = circ * (seconds / total);

  return (
    <svg width="28" height="28" style={{ transform: "rotate(-90deg)" }}>
      <circle cx="14" cy="14" r={r} fill="none" stroke="var(--track)" strokeWidth="2" />
      <circle cx="14" cy="14" r={r} fill="none" stroke="var(--muted)" strokeWidth="2"
        strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
        style={{ transition: "stroke-dasharray 0.9s linear" }} />
    </svg>
  );
}

// ─── Signal badge (inline) ───────────────────────────────────────────────────
function SignalBadge({ rec }: { rec: string }) {
  const s = signalMeta(rec);
  return (
    <span style={{
      fontFamily: "var(--font-label)", fontSize: "0.58rem", letterSpacing: "0.14em",
      color: s.color, background: s.bg, border: `1px solid ${s.color}40`,
      borderRadius: "2px", padding: "0.18rem 0.45rem", textTransform: "uppercase",
      whiteSpace: "nowrap",
    }}>
      {rec}
    </span>
  );
}

// ─── Reports view ────────────────────────────────────────────────────────────
function ReportsView({ apiBase }: { apiBase: string }) {
  const [entries,       setEntries]       = useState<TradeEntry[]>([]);
  const [total,         setTotal]         = useState(0);
  const [loading,       setLoading]       = useState(true);
  const [error,         setError]         = useState(false);
  const [symbolFilter,  setSymbolFilter]  = useState("ALL");
  const [sortKey,       setSortKey]       = useState<keyof TradeEntry>("id");
  const [sortAsc,       setSortAsc]       = useState(false);

  const SYMBOLS = ["ALL", "NZDUSD", "EURUSD", "GOLD"];

  const fetchReports = useCallback(async (sym: string) => {
    setLoading(true);
    try {
      const param = sym !== "ALL" ? `&symbol=${sym}` : "";
      const res   = await fetch(`${apiBase}/dashboard/reports?limit=500${param}`, { cache: "no-store" });
      if (!res.ok) throw new Error();
      const json: ReportsResponse = await res.json();
      setEntries(json.entries);
      setTotal(json.total);
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => { fetchReports(symbolFilter); }, [symbolFilter, fetchReports]);

  const toggleSort = (key: keyof TradeEntry) => {
    if (sortKey === key) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(false); }
  };

  const sorted = [...entries].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    if (av < bv) return sortAsc ? -1 : 1;
    if (av > bv) return sortAsc ? 1  : -1;
    return 0;
  });

  const SortIcon = ({ col }: { col: keyof TradeEntry }) => (
    <span style={{ opacity: sortKey === col ? 1 : 0.3, marginLeft: "4px", fontSize: "0.6rem" }}>
      {sortKey === col ? (sortAsc ? "▲" : "▼") : "▼"}
    </span>
  );

  const thStyle: React.CSSProperties = {
    fontFamily: "var(--font-label)", fontSize: "0.58rem", letterSpacing: "0.14em",
    color: "var(--muted)", textTransform: "uppercase", fontWeight: 400,
    padding: "0.7rem 0.75rem", textAlign: "left", cursor: "pointer",
    borderBottom: "1px solid var(--border)", whiteSpace: "nowrap",
    userSelect: "none",
  };

  const tdStyle: React.CSSProperties = {
    fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "var(--text)",
    padding: "0.65rem 0.75rem", borderBottom: "1px solid var(--divider)",
    whiteSpace: "nowrap",
  };

  return (
    <div style={{ animation: "fadeIn 0.3s ease forwards" }}>

      {/* Toolbar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", flexWrap: "wrap", gap: "0.75rem" }}>

        {/* Symbol filter pills */}
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          {SYMBOLS.map((s) => (
            <button key={s} onClick={() => setSymbolFilter(s)} style={{
              fontFamily: "var(--font-label)", fontSize: "0.6rem", letterSpacing: "0.14em",
              textTransform: "uppercase", padding: "0.3rem 0.7rem",
              borderRadius: "2px", border: "1px solid",
              cursor: "pointer", transition: "all 0.15s",
              borderColor: symbolFilter === s ? "var(--accent)" : "var(--border)",
              background:  symbolFilter === s ? "var(--accent-dim)" : "transparent",
              color:       symbolFilter === s ? "var(--accent)" : "var(--muted)",
            }}>
              {s}
            </button>
          ))}
        </div>

        {/* Right controls */}
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <span style={{ fontFamily: "var(--font-label)", fontSize: "0.6rem", color: "var(--muted)", letterSpacing: "0.1em" }}>
            {total} RECORD{total !== 1 ? "S" : ""}
          </span>
          <button onClick={() => fetchReports(symbolFilter)} style={{
            fontFamily: "var(--font-label)", fontSize: "0.6rem", letterSpacing: "0.12em",
            textTransform: "uppercase", padding: "0.3rem 0.7rem",
            borderRadius: "2px", border: "1px solid var(--border)",
            background: "transparent", color: "var(--muted)", cursor: "pointer",
          }}>
            ↻ Refresh
          </button>
          <button onClick={() => exportCSV(sorted)} disabled={sorted.length === 0} style={{
            fontFamily: "var(--font-label)", fontSize: "0.6rem", letterSpacing: "0.12em",
            textTransform: "uppercase", padding: "0.3rem 0.8rem",
            borderRadius: "2px", border: "1px solid var(--accent)",
            background: "var(--accent-dim)", color: "var(--accent)", cursor: "pointer",
            opacity: sorted.length === 0 ? 0.4 : 1,
          }}>
            ↓ Export CSV
          </button>
        </div>
      </div>

      {/* States */}
      {loading && (
        <div style={{ textAlign: "center", padding: "3rem 0", fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--muted)", letterSpacing: "0.1em" }}>
          LOADING RECORDS…
        </div>
      )}

      {error && !loading && (
        <div style={{ textAlign: "center", padding: "3rem 0", fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "#ff1744", letterSpacing: "0.1em" }}>
          FAILED TO LOAD REPORTS
        </div>
      )}

      {!loading && !error && sorted.length === 0 && (
        <div style={{
          textAlign: "center", padding: "4rem 0",
          fontFamily: "var(--font-label)", fontSize: "0.7rem",
          color: "var(--muted)", letterSpacing: "0.1em",
          border: "1px dashed var(--border)", borderRadius: "4px",
        }}>
          NO TRADE RECORDS YET — SIGNALS WILL APPEAR HERE ONCE THE DASHBOARD SYNCS
        </div>
      )}

      {!loading && !error && sorted.length > 0 && (
        <div style={{ overflowX: "auto", borderRadius: "4px", border: "1px solid var(--border)" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "720px" }}>
            <thead>
              <tr style={{ background: "var(--card)" }}>
                <th style={thStyle} onClick={() => toggleSort("timestamp")}>
                  Date &amp; Time <SortIcon col="timestamp" />
                </th>
                <th style={thStyle} onClick={() => toggleSort("symbol")}>
                  Symbol <SortIcon col="symbol" />
                </th>
                <th style={thStyle} onClick={() => toggleSort("recommendation")}>
                  Signal <SortIcon col="recommendation" />
                </th>
                <th style={{ ...thStyle, textAlign: "right" }} onClick={() => toggleSort("confidence")}>
                  Conf. <SortIcon col="confidence" />
                </th>
                <th style={{ ...thStyle, textAlign: "right" }} onClick={() => toggleSort("entry")}>
                  Entry <SortIcon col="entry" />
                </th>
                <th style={{ ...thStyle, textAlign: "right" }} onClick={() => toggleSort("stop_loss")}>
                  Stop Loss <SortIcon col="stop_loss" />
                </th>
                <th style={{ ...thStyle, textAlign: "right" }} onClick={() => toggleSort("take_profit")}>
                  Take Profit <SortIcon col="take_profit" />
                </th>
                <th style={{ ...thStyle, textAlign: "right" }} onClick={() => toggleSort("lot_size")}>
                  Lots <SortIcon col="lot_size" />
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((e, i) => {
                const { date, time } = fmtTimestamp(e.timestamp);
                const isBuy = e.recommendation.includes("BUY");
                return (
                  <tr key={e.id} style={{ background: i % 2 === 0 ? "transparent" : "var(--row-alt)" }}>
                    {/* Date & Time */}
                    <td style={tdStyle}>
                      <div style={{ color: "var(--text)" }}>{date}</div>
                      <div style={{ color: "var(--muted)", fontSize: "0.7rem", marginTop: "1px" }}>{time} UTC</div>
                    </td>
                    {/* Symbol */}
                    <td style={{ ...tdStyle, letterSpacing: "0.1em", fontWeight: 600 }}>
                      {e.symbol}
                    </td>
                    {/* Signal badge */}
                    <td style={tdStyle}>
                      <SignalBadge rec={e.recommendation} />
                    </td>
                    {/* Confidence */}
                    <td style={{ ...tdStyle, textAlign: "right", color: signalMeta(e.recommendation).color }}>
                      {e.confidence}%
                    </td>
                    {/* Entry */}
                    <td style={{ ...tdStyle, textAlign: "right" }}>
                      {fmt(e.entry)}
                    </td>
                    {/* SL */}
                    <td style={{ ...tdStyle, textAlign: "right", color: "#ff6d6d" }}>
                      {fmt(e.stop_loss)}
                    </td>
                    {/* TP */}
                    <td style={{ ...tdStyle, textAlign: "right", color: "#69f0ae" }}>
                      {fmt(e.take_profit)}
                    </td>
                    {/* Lots */}
                    <td style={{ ...tdStyle, textAlign: "right", color: "#ffcc02" }}>
                      {e.lot_size !== null ? e.lot_size : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────
export default function Home() {
  const [tab,         setTab]         = useState<Tab>("dashboard");
  const [assets,      setAssets]      = useState<Asset[]>([]);
  const [lastFetch,   setLastFetch]   = useState<string | null>(null);
  const [countdown,   setCountdown]   = useState(0);
  const [syncTotal,   setSyncTotal]   = useState(300);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(false);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";
  const API_URL  = `${API_BASE}/dashboard/all`;

  const fetchData = async () => {
    try {
      const res = await fetch(API_URL, { cache: "no-store" });
      if (!res.ok) throw new Error();
      const json: ApiResponse = await res.json();
      setAssets(Object.values(json.assets));
      setLastFetch(json.meta.last_fetch);
      setSyncTotal(json.meta.next_sync);
      setCountdown(json.meta.next_sync);
      setError(false);
      setLoading(false);
    } catch {
      setError(true);
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  useEffect(() => {
    if (!countdown) return;
    const id = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) { fetchData(); return 0; }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [countdown]);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@600;700;800&family=DM+Sans:wght@300;400&display=swap');

        :root {
          --font-display: 'Syne', sans-serif;
          --font-mono:    'Space Mono', monospace;
          --font-label:   'DM Sans', sans-serif;

          --bg:         #080c0f;
          --card:       #0d1217;
          --border:     #1a2530;
          --divider:    #111c24;
          --track:      #1a2530;
          --text:       #e2eaf0;
          --muted:      #4a6070;
          --row-alt:    #0a1018;

          --accent:     #40c4ff;
          --accent-dim: #40c4ff12;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
          background: var(--bg);
          color: var(--text);
          min-height: 100vh;
          font-family: var(--font-label);
          background-image:
            linear-gradient(rgba(255,255,255,0.012) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.012) 1px, transparent 1px);
          background-size: 32px 32px;
        }

        .page-wrap {
          max-width: 1100px;
          margin: 0 auto;
          padding: 2.5rem 1.25rem 4rem;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
          margin-bottom: 1.75rem;
        }

        .header-title {
          font-family: var(--font-display);
          font-weight: 800;
          font-size: 1.2rem;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: var(--text);
        }

        .header-sub {
          font-family: var(--font-label);
          font-size: 0.62rem;
          letter-spacing: 0.1em;
          color: var(--muted);
          margin-top: 0.2rem;
          text-transform: uppercase;
        }

        .header-right {
          display: flex;
          align-items: center;
          gap: 0.6rem;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          color: var(--muted);
        }

        .tab-bar {
          display: flex;
          gap: 0;
          margin-bottom: 1.75rem;
          border-bottom: 1px solid var(--border);
        }

        .tab-btn {
          font-family: var(--font-label);
          font-size: 0.65rem;
          letter-spacing: 0.16em;
          text-transform: uppercase;
          padding: 0.6rem 1.25rem;
          background: transparent;
          border: none;
          cursor: pointer;
          color: var(--muted);
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          transition: color 0.15s, border-color 0.15s;
        }

        .tab-btn.active {
          color: var(--text);
          border-bottom-color: var(--accent);
        }

        .dashboard-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 1rem;
        }

        @media (max-width: 820px) {
          .dashboard-grid { grid-template-columns: 1fr 1fr; }
        }

        @media (max-width: 520px) {
          .dashboard-grid { grid-template-columns: 1fr; }
        }

        .center {
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 100vh;
          font-family: var(--font-mono);
          font-size: 0.8rem;
          color: var(--muted);
          letter-spacing: 0.1em;
        }

        .dot {
          width: 6px; height: 6px;
          border-radius: 50%;
          background: #00e676;
          box-shadow: 0 0 6px #00e676;
          animation: pulse 2s infinite;
        }

        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

        .fade-in {
          animation: fadeIn 0.4s ease forwards;
          opacity: 0;
        }

        @keyframes fadeIn { to { opacity: 1; } }

        button:focus { outline: none; }
      `}</style>

      {error && (
        <div className="center" style={{ color: "#ff1744", letterSpacing: "0.12em" }}>
          ⚠ BACKEND OFFLINE
        </div>
      )}

      {loading && !error && (
        <div className="center">INITIALISING…</div>
      )}

      {!loading && !error && (
        <div className="page-wrap fade-in">

          {/* Header */}
          <div className="header">
            <div>
              <div className="header-title">Signal Terminal</div>
              <div className="header-sub">
                {lastFetch ? new Date(lastFetch).toLocaleString() : "—"}
              </div>
            </div>
            <div className="header-right">
              <CountdownRing seconds={countdown} total={syncTotal} />
              {countdown}s
              <div className="dot" />
            </div>
          </div>

          {/* Tab bar */}
          <div className="tab-bar">
            <button className={`tab-btn ${tab === "dashboard" ? "active" : ""}`} onClick={() => setTab("dashboard")}>
              Dashboard
            </button>
            <button className={`tab-btn ${tab === "reports" ? "active" : ""}`} onClick={() => setTab("reports")}>
              Trade Reports
            </button>
          </div>

          {/* Dashboard tab */}
          {tab === "dashboard" && (
            <div className="dashboard-grid">
              {assets.map((asset, i) => (
                <div key={asset.symbol} style={{ animationDelay: `${i * 80}ms` }} className="fade-in">
                  <AssetCard asset={asset} />
                </div>
              ))}
            </div>
          )}

          {/* Reports tab */}
          {tab === "reports" && (
            <ReportsView apiBase={API_BASE} />
          )}

        </div>
      )}
    </>
  );
}
