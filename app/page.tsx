"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [data, setData] = useState<any>(null);
  const [meta, setMeta] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState(false);

  const API_URL = `${process.env.NEXT_PUBLIC_API_URL}/dashboard/all`;

  const fetchData = async () => {
    try {
      const res = await fetch(API_URL, { cache: "no-store" });

      if (!res.ok) throw new Error("API error");

      const json = await res.json();

      setData(json.data);
      setMeta(json.meta);
      setStats(json.stats);
      setTrades(json.trades);

      setCountdown(json.meta?.next_sync || 0);

      setError(false);
    } catch (err) {
      console.error(err);
      setError(true);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Countdown logic
  useEffect(() => {
    if (!countdown) return;

    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          fetchData();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [countdown]);

  if (error) {
    return <div className="center text-red-500">Backend offline</div>;
  }

  if (!data) {
    return <div className="center">Loading...</div>;
  }

  const assets = Object.values(data);

  return (
    <div className="container">
      <h1>📊 Trading Dashboard</h1>

      {/* HEADER */}
      <div className="flex justify-between items-center mb-4 text-sm text-gray-400">
        <div>
          Last Sync:{" "}
          {meta?.last_fetch
            ? new Date(meta.last_fetch).toLocaleString()
            : "—"}
        </div>

        <div>Refresh in: {countdown}s</div>
      </div>

      {/* 📈 STATS */}
      <div className="card">
        <h2>📈 Performance</h2>
        <Row label="Wins" value={stats?.wins} />
        <Row label="Losses" value={stats?.losses} />
        <Row label="Total Trades" value={stats?.total} />
        <Row label="Winrate" value={`${stats?.winrate ?? 0}%`} />
      </div>

      {/* 🧾 TRADE LOG */}
      <div className="card">
        <h2>🧾 Recent Trades</h2>

        {trades?.length === 0 && <div>No trades yet</div>}

        {trades?.map((t: any, i: number) => (
          <div key={i} className="row">
            <span>
              {t.symbol} {t.direction}
            </span>
            <span
              style={{
                color:
                  t.status === "WIN"
                    ? "limegreen"
                    : t.status === "LOSS"
                    ? "red"
                    : "orange",
              }}
            >
              {t.status}
            </span>
          </div>
        ))}
      </div>

      {/* 📊 ASSETS */}
      {assets.map((asset: any, index: number) => {
        const hasTrade = asset.signal !== "NO TRADE";

        return (
          <div className="card" key={index}>
            <h2>{asset.symbol}</h2>

            <SignalBadge signal={asset.signal} />

            {hasTrade && (
              <>
                <Row label="Entry" value={asset.entry} />
                <Row label="Stop Loss" value={asset.stop_loss} />
                <Row label="Take Profit" value={asset.take_profit} />
                <Row label="R:R" value={asset.risk_reward} />
              </>
            )}

            <Row label="RSI" value={asset.rsi} />
            <Row label="ATR" value={asset.atr} />
            <Row label="EMA50" value={asset.ema50} />
            <Row label="EMA200" value={asset.ema200} />
          </div>
        );
      })}
    </div>
  );
}

function Row({ label, value }: any) {
  return (
    <div className="row">
      <span>{label}</span>
      <span>{value ?? "-"}</span>
    </div>
  );
}

function SignalBadge({ signal }: any) {
  let color = "#666";

  if (signal.includes("STRONG BUY")) color = "darkgreen";
  else if (signal.includes("BUY")) color = "green";
  else if (signal.includes("STRONG SELL")) color = "darkred";
  else if (signal.includes("SELL")) color = "red";
  else if (signal.includes("WEAK")) color = "orange";

  return (
    <div style={{ background: color }} className="badge">
      {signal}
    </div>
  );
}
