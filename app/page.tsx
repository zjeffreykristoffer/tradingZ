"use client";

import { useEffect, useState, useRef } from "react";

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
  holding_time_opt: number | null;   // minutes
  holding_time_base: number | null;  // minutes
  holding_time_pess: number | null;  // minutes
}

interface ApiResponse {
  assets: Record<string, Asset>;
  meta: { last_fetch: string; next_sync: number };
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function signalMeta(rec: string): { label: string; color: string; glow: string; tier: string } {
  if (rec.includes("STRONG BUY"))  return { label: rec, color: "#00e676", glow: "#00e67640", tier: "strong-buy" };
  if (rec.includes("STRONG SELL")) return { label: rec, color: "#ff1744", glow: "#ff174440", tier: "strong-sell" };
  if (rec.includes("WEAK BUY"))    return { label: rec, color: "#69f0ae", glow: "#69f0ae30", tier: "weak-buy" };
  if (rec.includes("WEAK SELL"))   return { label: rec, color: "#ff6d6d", glow: "#ff6d6d30", tier: "weak-sell" };
  if (rec.includes("BUY"))         return { label: rec, color: "#40c4ff", glow: "#40c4ff40", tier: "buy" };
  if (rec.includes("SELL"))        return { label: rec, color: "#ff9100", glow: "#ff910040", tier: "sell" };
  return { label: rec, color: "#546e7a", glow: "#546e7a20", tier: "neutral" };
}

function fmt(val: number | null, decimals = 5): string {
  if (val === null || val === undefined) return "—";
  return val.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Convert minutes into a compact human-readable string.
 * Examples: 15 → "15m", 75 → "1h 15m", 180 → "3h"
 */
function fmtMinutes(mins: number | null): string {
  if (mins === null || mins === undefined) return "—";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0)  return `${m}m`;
  if (m === 0)  return `${h}h`;
  return `${h}h ${m}m`;
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
      <div style={{
        height: "3px",
        background: "var(--track)",
        borderRadius: "2px",
        overflow: "hidden",
      }}>
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
/**
 * Visual timeline showing optimistic → base → pessimistic estimates.
 *
 * Layout (proportional):
 *   [opt]──────[base]──────────────[pess]
 *     ↑                               ↑
 *   fast exit                    slow exit
 *
 * The bar is scaled so pess always maps to 100% width.
 * A filled region covers 0 → opt (fast zone).
 * A dashed region covers opt → pess.
 * The base estimate is marked with a tick.
 */
function HoldingTimeBar({
  opt,
  base,
  pess,
  color,
}: {
  opt: number | null;
  base: number | null;
  pess: number | null;
  color: string;
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 200);
    return () => clearTimeout(t);
  }, []);

  if (opt === null || base === null || pess === null) {
    return (
      <div style={{ color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: "0.75rem", padding: "0.4rem 0" }}>—</div>
    );
  }

  const optPct  = (opt  / pess) * 100;
  const basePct = (base / pess) * 100;

  return (
    <div style={{ marginBottom: "0.2rem" }}>
      {/* Labels row */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        marginBottom: "0.5rem",
        alignItems: "flex-end",
      }}>
        {/* Left: optimistic */}
        <div style={{ textAlign: "left" }}>
          <div style={{ fontFamily: "var(--font-label)", fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", textTransform: "uppercase", marginBottom: "0.15rem" }}>
            Best case
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "#69f0ae", fontWeight: 600 }}>
            {fmtMinutes(opt)}
          </div>
        </div>

        {/* Centre: base */}
        <div style={{ textAlign: "center" }}>
          <div style={{ fontFamily: "var(--font-label)", fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", textTransform: "uppercase", marginBottom: "0.15rem" }}>
            Est. hold
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.95rem", color, fontWeight: 700 }}>
            {fmtMinutes(base)}
          </div>
        </div>

        {/* Right: pessimistic */}
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--font-label)", fontSize: "0.55rem", letterSpacing: "0.1em", color: "var(--muted)", textTransform: "uppercase", marginBottom: "0.15rem" }}>
            Worst case
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "0.78rem", color: "#ff6d6d", fontWeight: 600 }}>
            {fmtMinutes(pess)}
          </div>
        </div>
      </div>

      {/* Track */}
      <div style={{
        position: "relative",
        height: "4px",
        background: "var(--track)",
        borderRadius: "3px",
        overflow: "visible",
      }}>
        {/* Fast-zone fill (0 → opt) */}
        <div style={{
          position: "absolute",
          left: 0,
          top: 0,
          height: "100%",
          width: animated ? `${optPct}%` : "0%",
          background: `linear-gradient(90deg, #69f0ae, ${color})`,
          borderRadius: "3px",
          transition: "width 1s cubic-bezier(0.22, 1, 0.36, 1)",
        }} />

        {/* Dashed zone (opt → pess) — rendered as a low-opacity fill */}
        <div style={{
          position: "absolute",
          left: `${optPct}%`,
          top: 0,
          height: "100%",
          width: animated ? `${100 - optPct}%` : "0%",
          background: `repeating-linear-gradient(90deg, ${color}50 0px, ${color}50 4px, transparent 4px, transparent 8px)`,
          borderRadius: "0 3px 3px 0",
          transition: "width 1s cubic-bezier(0.22, 1, 0.36, 1) 0.1s",
        }} />

        {/* Base tick marker */}
        <div style={{
          position: "absolute",
          left: `${basePct}%`,
          top: "-4px",
          transform: "translateX(-50%)",
          width: "2px",
          height: "12px",
          background: color,
          boxShadow: `0 0 6px ${color}`,
          borderRadius: "1px",
          opacity: animated ? 1 : 0,
          transition: "opacity 0.5s ease 0.8s",
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
      border: `1px solid var(--border)`,
      borderTop: `2px solid ${sig.color}`,
      borderRadius: "4px",
      padding: "1.5rem",
      boxShadow: `0 4px 24px ${sig.glow}`,
      transition: "box-shadow 0.3s ease",
    }}>

      {/* Symbol */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.2rem" }}>
        <span style={{ fontFamily: "var(--font-display)", fontSize: "1rem", letterSpacing: "0.15em", color: "var(--text)", textTransform: "uppercase" }}>
          {asset.symbol}
        </span>
        <span style={{
          fontFamily: "var(--font-label)",
          fontSize: "0.6rem",
          letterSpacing: "0.2em",
          color: sig.color,
          background: `${sig.color}18`,
          border: `1px solid ${sig.color}40`,
          borderRadius: "2px",
          padding: "0.2rem 0.5rem",
          textTransform: "uppercase",
        }}>
          {sig.label}
        </span>
      </div>

      {/* Confidence bar */}
      <ConfidenceBar value={asset.confidence} color={sig.color} />

      {/* Trade parameters */}
      {!noTrade ? (
        <>
          <SectionLabel>Trade Parameters</SectionLabel>
          <DataRow label="Entry"     value={fmt(asset.entry)} />
          <DataRow label="Stop Loss" value={fmt(asset.stop_loss)}   accent="#ff6d6d" />
          <DataRow label="Target"    value={fmt(asset.take_profit)} accent="#69f0ae" />

          <SectionLabel style={{ marginTop: "1rem" }}>Risk Management</SectionLabel>
          <DataRow label="Lot Size" value={asset.lot_size !== null ? `${asset.lot_size} lots` : "—"} />
          <DataRow label="Risk"     value={asset.risk_usd !== null ? `$${asset.risk_usd.toFixed(2)}` : "—"} accent="#ffcc02" />

          {/* Holding time section */}
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
      fontFamily: "var(--font-label)",
      fontSize: "0.58rem",
      letterSpacing: "0.18em",
      color: "var(--muted)",
      textTransform: "uppercase",
      marginBottom: "0.2rem",
      paddingTop: "0.1rem",
      ...style,
    }}>
      {children}
    </div>
  );
}

// ─── Countdown ring ──────────────────────────────────────────────────────────
function CountdownRing({ seconds, total }: { seconds: number; total: number }) {
  const r    = 10;
  const circ = 2 * Math.PI * r;
  const pct  = seconds / total;
  const dash = circ * pct;

  return (
    <svg width="28" height="28" style={{ transform: "rotate(-90deg)" }}>
      <circle cx="14" cy="14" r={r} fill="none" stroke="var(--track)" strokeWidth="2" />
      <circle
        cx="14" cy="14" r={r}
        fill="none"
        stroke="var(--muted)"
        strokeWidth="2"
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        style={{ transition: "stroke-dasharray 0.9s linear" }}
      />
    </svg>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────
export default function Home() {
  const [assets, setAssets]       = useState<Asset[]>([]);
  const [lastFetch, setLastFetch] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [syncTotal, setSyncTotal] = useState(300);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(false);

  const API_URL = `${process.env.NEXT_PUBLIC_API_URL}/dashboard/all`;

  const fetchData = async () => {
    try {
      const res = await fetch(API_URL, { cache: "no-store" });
      if (!res.ok) throw new Error("API error");

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

  // countdown + auto-refresh
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

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@600;700;800&family=DM+Sans:wght@300;400&display=swap');

        :root {
          --font-display: 'Syne', sans-serif;
          --font-mono:    'Space Mono', monospace;
          --font-label:   'DM Sans', sans-serif;

          --bg:      #080c0f;
          --card:    #0d1217;
          --border:  #1a2530;
          --divider: #111c24;
          --track:   #1a2530;
          --text:    #e2eaf0;
          --muted:   #4a6070;
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
          max-width: 680px;
          margin: 0 auto;
          padding: 2.5rem 1.25rem 4rem;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
          margin-bottom: 2.5rem;
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

        .grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
        }

        @media (max-width: 520px) {
          .grid { grid-template-columns: 1fr; }
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

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }

        .fade-in {
          animation: fadeIn 0.4s ease forwards;
          opacity: 0;
        }

        @keyframes fadeIn {
          to { opacity: 1; }
        }
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

          {/* Cards */}
          <div className="grid">
            {assets.map((asset, i) => (
              <div key={asset.symbol} style={{ animationDelay: `${i * 80}ms` }} className="fade-in">
                <AssetCard asset={asset} />
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
