const API = "https://your-backend.onrender.com"; // 🔴 replace this

async function load() {
  try {
    const res = await fetch(`${API}/trade/BTCUSD`);
    const data = await res.json();

    document.getElementById("balance").innerText = "Balance: $" + data.balance;
    document.getElementById("signal").innerText = "Signal: " + data.signal;
    document.getElementById("price").innerText = "Price: " + data.price;

    if (data.trade) {
      document.getElementById("trade").innerHTML = `
        <h3>Entry: ${data.trade.entry.toFixed(2)}</h3>
        <h3>TP: ${data.trade.tp.toFixed(2)}</h3>
        <h3>SL: ${data.trade.sl.toFixed(2)}</h3>
      `;
    } else {
      document.getElementById("trade").innerHTML = "";
    }

    document.getElementById("winrate").innerText = "Winrate: " + data.winrate + "%";
    document.getElementById("wins").innerText = "Wins: " + data.wins;
    document.getElementById("losses").innerText = "Losses: " + data.losses;

  } catch (e) {
    console.log("ERROR:", e);
  }
}

// run immediately
load();

// refresh every 5 seconds
setInterval(load, 5000);
