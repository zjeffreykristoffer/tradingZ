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

  // ✅ Convert all pairs into array
  const assets = Object.values(data);

  return (
    <div className="container">
      <h1>📊 Trading Dashboard</h1>

      {assets.map((asset: any, index: number) => {
        const hasTrade = asset.signal !== "NO TRADE";

        return (
          <div className="card" key={index}>
            <h2>{asset.symbol}</h2>

            <SignalBadge signal={asset.signal} />

            {/* ✅ Show for ALL trades except NO TRADE */}
            {hasTrade && (
              <>
                <Row label="Entry" value={asset.entry} />
                <Row label="Stop Loss" value={asset.stop_loss} />
                <Row label="Take Profit" value={asset.take_profit} />
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
