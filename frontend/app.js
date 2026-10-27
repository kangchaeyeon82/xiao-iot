const API = window.API_BASE;
const POLL_MS = 2000;
const $ = (id) => document.getElementById(id);

let mode = "login";
let pollTimer = null;
let chart = null;
let ledOn = false;
let ledSeq = 0; // LED 명령마다 증가. 명령 전에 출발한 조회 결과는 버린다

// ---------- 토큰 저장 ----------
const store = {
  get token() { try { return localStorage.getItem("token"); } catch { return null; } },
  get email() { try { return localStorage.getItem("email"); } catch { return null; } },
  save(token, email) {
    try { localStorage.setItem("token", token); localStorage.setItem("email", email); } catch {}
  },
  clear() { try { localStorage.removeItem("token"); localStorage.removeItem("email"); } catch {} },
};

// ---------- API 호출 ----------
async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = store.token;
  if (auth) {
    if (!token) throw new Error("unauthorized");
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetch(API + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && auth) {
    // 요청 도중 사용자가 로그아웃한 경우는 조용히 무시
    if (store.token === token) logout("세션이 만료되었습니다. 다시 로그인하세요.");
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const d = data.detail;
    const msg = Array.isArray(d) ? d.map((e) => e.msg).join(", ") : d || `오류 ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

// ---------- 로그인 / 회원가입 ----------
function setMode(m) {
  mode = m;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.mode === m));
  $("auth-submit").textContent = m === "login" ? "로그인" : "회원가입";
  $("password").autocomplete = m === "login" ? "current-password" : "new-password";
  showAuthMsg("");
}

function showAuthMsg(text, type = "") {
  const el = $("auth-msg");
  el.textContent = text;
  el.className = `msg ${type}`;
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setMode(t.dataset.mode)));

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("email").value.trim();
  const password = $("password").value;
  const btn = $("auth-submit");
  btn.disabled = true;
  showAuthMsg(mode === "login" ? "로그인 중…" : "가입 중…");
  try {
    const path = mode === "login" ? "/auth/login" : "/auth/signup";
    const data = await api(path, { method: "POST", body: { email, password }, auth: false });
    if (!data.access_token) {
      // 이메일 인증이 켜져 있으면 토큰 없이 돌아온다
      showAuthMsg(data.message || "가입 완료. 이메일 인증 후 로그인하세요.", "ok");
      setMode("login");
      return;
    }
    store.save(data.access_token, email);
    $("password").value = "";
    showDashboard();
  } catch (err) {
    showAuthMsg(err.message, "error");
  } finally {
    btn.disabled = false;
  }
});

function logout(message = "") {
  store.clear();
  clearInterval(pollTimer);
  pollTimer = null;
  $("dash-view").hidden = true;
  $("auth-view").hidden = false;
  setMode("login");
  if (message) showAuthMsg(message, "error");
}
$("logout").addEventListener("click", () => logout());

// ---------- 대시보드 ----------
function showDashboard() {
  $("auth-view").hidden = true;
  $("dash-view").hidden = false;
  $("user-email").textContent = store.email || "";
  $("api-base").textContent = API;
  initChart();
  refresh();
  clearInterval(pollTimer);
  pollTimer = setInterval(refresh, POLL_MS);
}

function fmtTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString("en-GB", { hour12: false }) : "-";
}

function renderLed(on) {
  ledOn = on;
  $("led-bulb").classList.toggle("on", on);
  $("led-toggle").textContent = on ? "LED 끄기" : "LED 켜기";
}

async function refresh() {
  if (!store.token) return;
  const seq = ledSeq;
  try {
    const [latest, led, history] = await Promise.all([
      api("/sensors/latest"),
      api("/led"),
      api("/sensors/history?limit=60"),
    ]);
    const r = latest.reading;
    $("temp").textContent = r?.temperature != null ? r.temperature.toFixed(1) : "-";
    $("rssi").textContent = r?.rssi ?? "-";
    $("last-seen").textContent = fmtTime(latest.last_seen);
    $("online-dot").className = `dot ${latest.online ? "on" : "off"}`;
    $("online-text").textContent = latest.online ? "온라인" : "오프라인";
    if (seq === ledSeq && !$("led-toggle").disabled) renderLed(led.on);
    updateChart(history);
  } catch (err) {
    if (err.message !== "unauthorized") {
      $("online-text").textContent = `서버 연결 실패: ${err.message}`;
      $("online-dot").className = "dot off";
    }
  }
}

$("led-toggle").addEventListener("click", async () => {
  const btn = $("led-toggle");
  const target = !ledOn;
  ledSeq++;
  btn.disabled = true;
  $("led-msg").textContent = "명령 전송 중…";
  try {
    const res = await api("/led", { method: "POST", body: { on: target } });
    renderLed(res.on);
    $("led-msg").textContent = `${res.on ? "켜기" : "끄기"} 명령 저장됨 · 장치는 최대 2초 안에 반영`;
  } catch (err) {
    $("led-msg").textContent = `실패: ${err.message}`;
  } finally {
    ledSeq++; // 명령 처리 중에 출발한 조회도 무효
    btn.disabled = false;
  }
});

// ---------- 차트 ----------
function initChart() {
  if (chart || !window.Chart) return;
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue("--accent").trim();
  const muted = css.getPropertyValue("--muted").trim();
  const grid = css.getPropertyValue("--border").trim();
  chart = new Chart($("chart"), {
    type: "line",
    data: { labels: [], datasets: [{ label: "온도 °C", data: [], borderColor: accent, borderWidth: 2, pointRadius: 0, tension: 0.3 }] },
    options: {
      animation: false,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: muted, maxTicksLimit: 6 }, grid: { color: grid } },
        y: { ticks: { color: muted }, grid: { color: grid } },
      },
    },
  });
}

function updateChart(rows) {
  if (!chart) return;
  chart.data.labels = rows.map((r) => fmtTime(r.created_at));
  chart.data.datasets[0].data = rows.map((r) => r.temperature);
  chart.update();
}

// ---------- 시작 ----------
if (store.token) showDashboard();
else logout();
