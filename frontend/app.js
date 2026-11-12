// Клиентская часть BizFlow. Обычный JavaScript без сборщика:
// статику раздаёт nginx, все данные приходят из REST API по пути /api.
const API = "/api";
const STAGES = { new: "Новая", negotiation: "Переговоры", won: "Успешно", lost: "Отказ" };
const PAGE_TITLES = {
  dashboard: "Сводка", clients: "Клиенты", deals: "Сделки",
  tasks: "Задачи", events: "Автоматизация", users: "Сотрудники",
};

let token = localStorage.getItem("bizflow_token");
let me = null;
let clientsCache = [];
let dealsCache = [];

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v) => Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 0 });
const fmtDate = (s) => (s ? new Date(s).toLocaleDateString("ru-RU") : "—");
const fmtTime = (s) => new Date(s).toLocaleString("ru-RU");

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(API + path, { ...options, headers });
  const served = res.headers.get("X-Served-By");
  if (served) $("#instance").textContent = served;
  if (res.status === 401 && token) { logout(); throw new Error("Сессия истекла"); }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
    throw new Error(detail || `Ошибка ${res.status}`);
  }
  return body;
}

// ---------- вход и регистрация ----------

document.querySelectorAll("[data-auth]").forEach((btn) => btn.addEventListener("click", () => {
  document.querySelectorAll("[data-auth]").forEach((b) => b.classList.toggle("active", b === btn));
  $("#login-form").classList.toggle("hidden", btn.dataset.auth !== "login");
  $("#register-form").classList.toggle("hidden", btn.dataset.auth !== "register");
  $("#auth-error").textContent = "";
}));

async function submitAuth(form, path) {
  const data = Object.fromEntries(new FormData(form));
  try {
    const res = await api(path, { method: "POST", body: JSON.stringify(data) });
    token = res.access_token;
    localStorage.setItem("bizflow_token", token);
    await start();
  } catch (e) {
    $("#auth-error").textContent = e.message;
  }
}

$("#login-form").addEventListener("submit", (e) => { e.preventDefault(); submitAuth(e.target, "/auth/login"); });
$("#register-form").addEventListener("submit", (e) => { e.preventDefault(); submitAuth(e.target, "/auth/register"); });
$("#logout").addEventListener("click", logout);

// Сброс всего, что осталось от предыдущего пользователя: кэшей списков и
// уже отрисованных таблиц. Иначе после смены пользователя на экране и в
// формах на мгновение остались бы данные чужой компании.
function resetState() {
  me = null;
  clientsCache = [];
  dealsCache = [];
  window._tasks = [];
  for (const id of ["#clients-body", "#deals-body", "#tasks-body", "#events-body", "#users-body", "#stat-cards", "#stage-bars"]) {
    $(id).innerHTML = "";
  }
  $("#client-search").value = "";
  $("#deal-filter").value = "";
  $("#instance").textContent = "—";
  $("#me-name").textContent = "";
  $("#me-company").textContent = "";
}

function logout() {
  token = null;
  localStorage.removeItem("bizflow_token");
  resetState();
  if ($("#modal").open) $("#modal").close();
  history.replaceState(null, "", location.pathname);
  $("#app-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
}

// ---------- навигация ----------

function showPage() {
  const page = (location.hash || "#dashboard").slice(1);
  document.querySelectorAll("[data-view]").forEach((s) => s.classList.toggle("hidden", s.dataset.view !== page));
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  $("#page-title").textContent = PAGE_TITLES[page] || "";
  ({ dashboard: loadDashboard, clients: loadClients, deals: loadDeals,
     tasks: loadTasks, events: loadEvents, users: loadUsers }[page] || loadDashboard)();
}
window.addEventListener("hashchange", showPage);

// ---------- страницы ----------

async function loadDashboard() {
  const s = await api("/stats");
  const cards = [
    ["Клиентов", s.clients], ["Сделок", s.deals],
    ["Выиграно, ₽", money(s.won_amount)], ["В работе, ₽", money(s.pipeline_amount)],
    ["Открытых задач", s.open_tasks], ["Кэш статистики", s.cache === "hit" ? "из Redis" : "пересчитан"],
  ];
  $("#stat-cards").innerHTML = cards.map(([t, v]) => `<div class="card"><div class="muted">${t}</div><div class="value">${v}</div></div>`).join("");
  const max = Math.max(1, ...Object.values(s.deals_by_stage));
  $("#stage-bars").innerHTML = Object.entries(STAGES).map(([k, label]) => {
    const n = s.deals_by_stage[k] || 0;
    return `<div class="bar-row"><span>${label}</span><div class="bar"><i class="st-${k}" style="width:${(n / max) * 100}%"></i></div><b>${n}</b></div>`;
  }).join("");
}

async function loadClients() {
  const q = $("#client-search").value.trim();
  clientsCache = await api(`/clients${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  $("#clients-body").innerHTML = clientsCache.map((c) => `
    <tr><td>${esc(c.name)}</td><td>${esc(c.email || "—")}</td><td>${esc(c.phone || "—")}</td>
    <td>${fmtDate(c.created_at)}</td>
    <td class="actions"><button class="btn small" data-edit-client="${c.id}">Изменить</button>
    <button class="btn small danger" data-del="clients/${c.id}">Удалить</button></td></tr>`).join("")
    || `<tr><td colspan="5" class="muted">Клиентов пока нет</td></tr>`;
}
let searchTimer;
$("#client-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadClients, 300); });

async function loadDeals() {
  const stage = $("#deal-filter").value;
  dealsCache = await api(`/deals${stage ? `?stage=${stage}` : ""}`);
  $("#deals-body").innerHTML = dealsCache.map((d) => `
    <tr><td>${esc(d.title)}</td><td>${esc(d.client_name || "—")}</td><td class="num">${money(d.amount)}</td>
    <td><select data-stage="${d.id}" class="stage st-${d.stage}">${Object.entries(STAGES).map(([k, l]) =>
      `<option value="${k}" ${k === d.stage ? "selected" : ""}>${l}</option>`).join("")}</select></td>
    <td class="actions"><button class="btn small" data-edit-deal="${d.id}">Изменить</button>
    <button class="btn small danger" data-del="deals/${d.id}">Удалить</button></td></tr>`).join("")
    || `<tr><td colspan="5" class="muted">Сделок нет</td></tr>`;
}
$("#deal-filter").addEventListener("change", loadDeals);

async function loadTasks() {
  const tasks = await api("/tasks");
  const today = new Date().toISOString().slice(0, 10);
  $("#tasks-body").innerHTML = tasks.map((t) => `
    <tr class="${t.status === "done" ? "done" : ""}">
    <td><input type="checkbox" data-toggle-task="${t.id}" ${t.status === "done" ? "checked" : ""}></td>
    <td>${esc(t.title)}</td>
    <td class="${t.status === "open" && t.due_date && t.due_date < today ? "overdue" : ""}">${fmtDate(t.due_date)}</td>
    <td>${t.source === "automation" ? '<span class="tag">авто</span>' : "вручную"}</td>
    <td class="actions"><button class="btn small danger" data-del="tasks/${t.id}">Удалить</button></td></tr>`).join("")
    || `<tr><td colspan="5" class="muted">Задач нет</td></tr>`;
  window._tasks = tasks;
}

async function loadEvents() {
  const events = await api("/events");
  $("#events-body").innerHTML = events.map((e) => `
    <tr><td>${fmtTime(e.created_at)}</td><td><code>${esc(e.kind)}</code></td>
    <td class="payload">${esc(e.payload)}</td><td><code>${esc(e.processed_by)}</code></td></tr>`).join("")
    || `<tr><td colspan="4" class="muted">Событий пока не было</td></tr>`;
}

async function loadUsers() {
  const users = await api("/users");
  $("#users-body").innerHTML = users.map((u) => `
    <tr><td>${esc(u.full_name)}</td><td>${esc(u.email)}</td><td>${u.role === "admin" ? "Администратор" : "Менеджер"}</td></tr>`).join("");
}

// ---------- действия в таблицах ----------

document.addEventListener("click", async (e) => {
  const t = e.target;
  try {
    if (t.dataset.del) {
      if (!confirm("Удалить запись?")) return;
      await api(`/${t.dataset.del}`, { method: "DELETE" });
      showPage();
    } else if (t.dataset.editClient) {
      const c = clientsCache.find((x) => x.id === +t.dataset.editClient);
      openForm("client", c);
    } else if (t.dataset.editDeal) {
      const d = dealsCache.find((x) => x.id === +t.dataset.editDeal);
      openForm("deal", d);
    } else if (t.dataset.new) {
      openForm(t.dataset.new);
    } else if (t.dataset.toggleTask) {
      const task = window._tasks.find((x) => x.id === +t.dataset.toggleTask);
      await api(`/tasks/${task.id}`, { method: "PUT", body: JSON.stringify({ ...task, status: t.checked ? "done" : "open" }) });
      loadTasks();
    }
  } catch (err) { alert(err.message); }
});

document.addEventListener("change", async (e) => {
  if (!e.target.dataset.stage) return;
  const d = dealsCache.find((x) => x.id === +e.target.dataset.stage);
  try {
    await api(`/deals/${d.id}`, { method: "PUT", body: JSON.stringify({ ...d, stage: e.target.value }) });
    loadDeals();
  } catch (err) { alert(err.message); }
});

// ---------- модальная форма ----------

const FORMS = {
  client: { title: "Клиент", path: "/clients", fields: [
    ["name", "Название", "text", true], ["email", "E-mail", "email"], ["phone", "Телефон", "text"], ["note", "Комментарий", "textarea"]] },
  deal: { title: "Сделка", path: "/deals", fields: [
    ["title", "Название", "text", true], ["amount", "Сумма, ₽", "number"], ["client_id", "Клиент", "client"], ["stage", "Этап", "stage"]] },
  task: { title: "Задача", path: "/tasks", fields: [
    ["title", "Что сделать", "text", true], ["due_date", "Срок", "date"]] },
  user: { title: "Сотрудник", path: "/users", fields: [
    ["full_name", "Имя", "text", true], ["email", "E-mail", "email", true], ["password", "Пароль", "password", true], ["role", "Роль", "role"]] },
};

async function openForm(kind, obj = null) {
  const f = FORMS[kind];
  // справочник клиентов для формы сделки загружается полностью при каждом
  // открытии: clientsCache содержит результат поиска в таблице и может быть неполным
  const clientOptions = kind === "deal" ? await api("/clients") : [];
  $("#modal-title").textContent = (obj ? "Изменить: " : "Новый объект: ") + f.title.toLowerCase();
  $("#modal-error").textContent = "";
  $("#modal-fields").innerHTML = f.fields.map(([name, label, type, req]) => {
    const v = obj?.[name] ?? "";
    let input;
    if (type === "textarea") input = `<textarea name="${name}">${esc(v)}</textarea>`;
    else if (type === "client") input = `<select name="${name}"><option value="">— без клиента —</option>${clientOptions.map((c) => `<option value="${c.id}" ${c.id === v ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>`;
    else if (type === "stage") input = `<select name="${name}">${Object.entries(STAGES).map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${l}</option>`).join("")}</select>`;
    else if (type === "role") input = `<select name="${name}"><option value="manager">Менеджер</option><option value="admin">Администратор</option></select>`;
    else input = `<input name="${name}" type="${type}" value="${esc(v)}" ${req ? "required" : ""}>`;
    return `<label>${label}${input}</label>`;
  }).join("");
  const dlg = $("#modal");
  dlg.showModal();
  dlg.onclose = async () => {
    if (dlg.returnValue !== "save") return;
    const data = Object.fromEntries(new FormData($("#modal-form")));
    for (const k of Object.keys(data)) if (data[k] === "") data[k] = null;
    if ("amount" in data) data.amount = Number(data.amount || 0);
    if ("client_id" in data && data.client_id) data.client_id = Number(data.client_id);
    try {
      await api(obj ? `${f.path}/${obj.id}` : f.path, { method: obj ? "PUT" : "POST", body: JSON.stringify(data) });
      showPage();
    } catch (err) { alert(err.message); }
  };
}

// ---------- запуск ----------

async function start() {
  if (!token) { logout(); return; }
  resetState();
  try {
    me = await api("/auth/me");
  } catch { logout(); return; }
  $("#me-name").textContent = me.full_name;
  $("#me-company").textContent = `${me.company_name} · тариф «${me.plan}»`;
  document.querySelectorAll(".admin-only").forEach((el) => el.classList.toggle("hidden", me.role !== "admin"));
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  showPage();
}

start();
