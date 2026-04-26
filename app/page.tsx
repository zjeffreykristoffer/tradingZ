"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [data, setData] = useState<any>(null);
  const [meta, setMeta] = useState<any>(null);
  const [countdown, setCountdown] = useState(0);
  const [history, setHistory] = useState<any[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const API = process.env.NEXT_PUBLIC_API_URL;

  const fetchData = async () => {
    const res = await fetch(`${API}/dashboard/all`, { cache: "no-store" });
    const json = await res.json();

    setData(json.data);
    setMeta(json.meta);
    setCountdown(json.meta.next_sync);
  };

  const fetchHistory = async () => {
    let url = `${API}/history?start=${start}&end=${end}`;
    const res = await fetch(url);
    const json = await res.json();
    setHistory(json.data);
  };

  useEffect(() => {
    fetchData();
    fetchHistory();
  }, []);

  useEffect(() => {
    if (!countdown) return;

    const i = setInterval(() => {
      setCountdown((p) => {
        if (p <= 1) {
          fetchData();
          fetchHistory();
          return 0;
        }
        return p - 1;
      });
    }, 1000);

    return () => clearInterval(i);
  }, [countdown]);

  return (
    <div className="container">
      <h1>📊 Trading Dashboard</h1>

      <div>
        Last Sync:{" "}
        {meta?.last_fetch
          ? new Date(meta.last_fetch).toLocaleString()
          : "-"}{" "}
        | Refresh in: {countdown}s
      </div>

      {data &&
        Object.values(data).map((a: any, i) => (
          <div key={i} className="card">
            <h2>{a.symbol}</h2>
            <div>{a.signal}</div>

            <div>Confidence: {a.confidence}%</div>
            <div>Trend: {a.trend}</div>

            {a.signal !== "NO TRADE" && (
              <>
                <div>Entry: {a.entry}</div>
                <div>SL: {a.stop_loss}</div>
                <div>TP: {a.take_profit}</div>
              </>
            )}

            <div>RSI: {a.rsi}</div>
            <div>ATR: {a.atr}</div>
          </div>
        ))}

      <h2>📜 Trade History</h2>

      <div>
        <input type="date" onChange={(e) => setStart(e.target.value)} />
        <input type="date" onChange={(e) => setEnd(e.target.value)} />
        <button onClick={fetchHistory}>Filter</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>Signal</th>
            <th>Entry</th>
            <th>SL</th>
            <th>TP</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {history.map((t, i) => (
            <tr key={i}>
              <td>{new Date(t.timestamp).toLocaleString()}</td>
              <td>{t.symbol}</td>
              <td>{t.signal}</td>
              <td>{t.entry}</td>
              <td>{t.stop_loss}</td>
              <td>{t.take_profit}</td>
              <td>{t.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
