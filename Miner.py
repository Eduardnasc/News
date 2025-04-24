import customtkinter as ctk
from tkinter import messagebox
import threading
import socket
import json
import random
import struct
import time
import pyrx
import csv
import os
from datetime import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from collections import deque
import psutil
import flash, jsonify, render_template_string, request, redirect, url_for, session, send_file
import multiprocessing
import requests

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

CONFIG_FILE = "miner_config.json"
XMR_TO_USD = 130
HASHES_PER_XMR = 2**256

POOLS = [
    ("pool.supportxmr.com", 3333),
    ("pool.hashvault.pro", 3333),
    ("xmr-eu1.nanopool.org", 14444),
    ("xmr.2miners.com", 2222)
]

def ping_pool_latency(host, port):
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=2):
            end = time.time()
        return (end - start) * 1000
    except:
        return float('inf')

def select_best_pool():
    latencies = [(host, port, ping_pool_latency(host, port)) for host, port in POOLS]
    latencies.sort(key=lambda x: x[2])
    return latencies[0][0], latencies[0][1]

def failover_monitor():
    while True:
        current_host, current_port = miner_stats["current_pool"].split(":")
        latency = ping_pool_latency(current_host, int(current_port))
        if latency == float('inf'):
            best_host, best_port = select_best_pool()
            miner_stats["current_pool"] = f"{best_host}:{best_port}"
        time.sleep(30)

miner_stats = {
    "hashrate": 0,
    "solutions": [],
    "current_pool": None,
    "earnings_xmr": 0,
    "earnings_usd": 0
}

USERS = {"admin": "admin123"}  # Login simples

app = Flask(__name__)
app.secret_key = 'segredo_muito_secreto'

dashboard_template = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Monero Miner Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  </head>
  <body class="bg-dark text-white">
    <div class="container py-5">
      <h1 class="mb-4">Painel do Minerador XMR</h1>
      <div class="row">
        <div class="col-md-4">
          <div class="card bg-secondary">
            <div class="card-body">
              <h5 class="card-title">Hashrate</h5>
              <p class="card-text" id="hashrate">0 H/s</p>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card bg-secondary">
            <div class="card-body">
              <h5 class="card-title">Pool Atual</h5>
              <p class="card-text" id="pool">-</p>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <div class="card bg-secondary">
            <div class="card-body">
              <h5 class="card-title">Ganhos Estimados</h5>
              <p class="card-text" id="earnings">0 XMR / $0</p>
            </div>
          </div>
        </div>
      </div>
      <div class="row mt-4">
        <div class="col-md-12">
          <canvas id="hashrateChart"></canvas>
        </div>
      </div>
      <div class="mt-4 text-end">
        <a href="/exportar" class="btn btn-success">Exportar Relatório</a>
      </div>
    </div>
    <script>
      async function updateData() {
        const res = await fetch('/status');
        const data = await res.json();
        document.getElementById('hashrate').innerText = `${data.hashrate.toFixed(2)} H/s`;
        document.getElementById('pool').innerText = data.current_pool || '-';
        document.getElementById('earnings').innerText = `${data.earnings_xmr.toFixed(6)} XMR / $${data.earnings_usd.toFixed(2)}`;
        if (chart.data.labels.length > 20) {
          chart.data.labels.shift();
          chart.data.datasets[0].data.shift();
        }
        chart.data.labels.push(new Date().toLocaleTimeString());
        chart.data.datasets[0].data.push(data.hashrate);
        chart.update();
      }
      const ctx = document.getElementById('hashrateChart').getContext('2d');
      const chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: [],
          datasets: [{
            label: 'Hashrate (H/s)',
            data: [],
            borderColor: 'rgb(75, 192, 192)',
            tension: 0.1
          }]
        },
        options: {
          scales: {
            y: {
              beginAtZero: true
            }
          }
        }
      });
      setInterval(updateData, 2000);
    </script>
  </body>
</html>
"""

login_template = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Login - XMR Miner</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  </head>
  <body class="bg-dark text-white d-flex align-items-center justify-content-center" style="height:100vh">
    <form class="w-25" method="post">
      <h2 class="mb-4 text-center">Login</h2>
      <div class="mb-3">
        <label for="username" class="form-label">Usuário</label>
        <input type="text" class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label for="password" class="form-label">Senha</label>
        <input type="password" class="form-control" name="password" required>
      </div>
      <button type="submit" class="btn btn-primary w-100">Entrar</button>
    </form>
  </body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if USERS.get(username) == password:
            session['user'] = username
            return redirect(url_for('dashboard'))
        else:
            return "<h3 style='color:red'>Login inválido</h3>" + login_template
    return render_template_string(login_template)

@app.route("/dashboard")
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template_string(dashboard_template)

@app.route("/status")
def status():
    return jsonify(miner_stats)

@app.route("/exportar")
def exportar():
    filename = "relatorio_mineracao.csv"
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Hashrate", "Pool", "Ganhos (XMR)", "Ganhos (USD)"])
        writer.writerow([
            miner_stats["hashrate"],
            miner_stats["current_pool"],
            miner_stats["earnings_xmr"],
            miner_stats["earnings_usd"]
        ])
    return send_file(filename, as_attachment=True)

def start_web_panel():
    best_host, best_port = select_best_pool()
    miner_stats["current_pool"] = f"{best_host}:{best_port}"
    threading.Thread(target=failover_monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    web_process = multiprocessing.Process(target=start_web_panel)
    web_process.start()

