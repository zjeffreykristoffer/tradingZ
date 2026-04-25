"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState(false);

  const API_URL = `${process.env.NEXT_PUBLIC_API_URL}/dashboard/all`;

  const fetchData = async () => {
    try {
      const res = await fetch(API_URL, { cache: "no-store" });

      if (!res.ok) throw new Error("API error");

      const json = await res.json();
      setData(json);
      setError(false);
    } catch (err) {
      console.error(err);
      setError(true);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return <div className="center text-red-500">Backend offline</div>;
  }

  if (!data) {
    return <div className="center">Loading...</div>;
  }

  const gold = data.GOLD;

  // ✅ ONLY hide when NO TRADE
  const hasTrade = gold.signal !== "NO TRADE";

  return (
    <div className="container">
      <h1>📊 Trading Dashboard</h1>

      <div className="card">
        <h2>{gold.symbol}</h2>

        <SignalBadge signal={gold.signal} />

        {/* ✅ Shows for WEAK + STRONG trades */}
        {hasTrade && (
          <>
            <Row label="Entry" value={gold.entry} />
            <Row label="Stop Loss" value={gold.stop_loss} />
            <Row label="Take Profit" value={gold.take_profit} />
          </>
        )}

        <Row label="RSI" value={gold.rsi} />
        <Row label="ATR" value={gold.atr} />
        <Row label="EMA50" value={gold.ema50} />
        <Row label="EMA200" value={gold.ema200} />
      </div>
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

  if (signal.includes("BUY")) color = "green";
  if (signal.includes("SELL")) color = "red";

  return (
    <div style={{ background: color }} className="badge">
      {signal}
    </div>
  );
}
