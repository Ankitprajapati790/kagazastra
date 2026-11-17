// Authenticated client/admin panels.
(() => {
    let csrfToken = "";

    function showMessage(text, isError = false) {
        const element = document.getElementById("panelMessage") || document.getElementById("authMessage");
        if (!element) return;
        element.textContent = text;
        element.className = `mt-4 rounded-lg p-3 text-sm ${isError ? "bg-rose-100 text-rose-800" : "bg-emerald-100 text-emerald-800"}`;
    }

    async function api(url, options = {}) {
        const headers = new Headers(options.headers || {});
        if (options.body && typeof options.body !== "string") {
            headers.set("Content-Type", "application/json");
            options.body = JSON.stringify(options.body);
        }
        if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase()) && csrfToken) {
            headers.set("X-CSRF-Token", csrfToken);
        }
        const response = await fetch(url, { ...options, headers, credentials: "same-origin" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.detail || "Request failed.");
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value == null ? "" : String(value);
    }

    function formatDate(value) {
        if (!value) return "—";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
    }

    function addCell(row, value, className = "p-3") {
        const cell = document.createElement("td");
        cell.className = className;
        cell.textContent = value == null ? "" : String(value);
        row.appendChild(cell);
        return cell;
    }

    function addEmptyRow(body, columns, message) {
        const row = document.createElement("tr");
        const cell = addCell(row, message);
        cell.colSpan = columns;
        cell.className += " text-center text-slate-500";
        body.replaceChildren(row);
    }

        async function loadSession(expectedRole) {
        const session = await api("/api/auth/me");
        csrfToken = session.csrf_token;
        localStorage.setItem('csrf_token', csrfToken); // ✅ YEH LINE ADD KAREIN
        if (session.user.role !== expectedRole) {
            window.location.replace(session.user.role === "admin" ? "/admin" : "/client");
            return null;
        }
        setText("panelUser", session.user.full_name);
        return session.user;
    }

    function setupLoginPage() {
        const loginForm = document.getElementById("loginForm");
        if (!loginForm) return false;

        const registerForm = document.getElementById("registerForm");
        document.getElementById("showLogin").addEventListener("click", () => {
            loginForm.classList.remove("hidden");
            registerForm.classList.add("hidden");
        });
        document.getElementById("showRegister").addEventListener("click", () => {
            registerForm.classList.remove("hidden");
            loginForm.classList.add("hidden");
        });

            async function authenticate(form, endpoint) {
            const button = form.querySelector("button[type=submit], button:not([type])");
            if (button) button.disabled = true;
            const payload = Object.fromEntries(new FormData(form).entries());
            try {
                const session = await api(`/api/auth/${endpoint}`, { method: "POST", body: payload });
                csrfToken = session.csrf_token;
                
                // ✅ YEH LINE ADD KI GAYI HAI (Token Save karne ke liye)
                localStorage.setItem('csrf_token', csrfToken);
                
                window.location.replace(session.user.role === "admin" ? "/admin" : "/client");
            } catch (error) {
                showMessage(error.message, true);
            } finally {
                if (button) button.disabled = false;
            }
        }

        loginForm.addEventListener("submit", (event) => {
            event.preventDefault();
            authenticate(loginForm, "login");
        });
        registerForm.addEventListener("submit", (event) => {
            event.preventDefault();
            authenticate(registerForm, "register");
        });
        
        api("/api/auth/me").then((session) => {
            // ✅ YEH LINE ADD KI GAYI HAI (Agar pehle se logged in hain toh token save karega)
            localStorage.setItem('csrf_token', session.csrf_token);
            
            window.location.replace(session.user.role === "admin" ? "/admin" : "/client");
        }).catch(() => {});
        return true;
    }

    async function loadClientPanel() {
        try {
            const user = await loadSession("client");
            if (!user) return;
            await refreshClientDashboard();
        } catch (error) {
            if (error.status === 401) window.location.replace("/login");
            else showMessage(error.message, true);
        }

        document.getElementById("planRequestForm").addEventListener("submit", async (event) => {
            event.preventDefault();
            const planId = new FormData(event.currentTarget).get("plan_id");
            try {
                const result = await api("/api/billing/create-upi-order", {
                    method: "POST",
                    body: { plan_id: planId },
                });
                showMessage(`${result.message} Request ID: ${result.transaction_id}`);
                await refreshClientDashboard();
            } catch (error) {
                showMessage(error.message, true);
            }
        });
    }

    async function refreshClientDashboard() {
        const data = await api("/api/client/dashboard");
        setText("clientName", data.user.full_name);
        setText("clientEmail", data.user.email);
        setText("usageCount", data.usage_count);
        setText("activePlan", data.active_plan ? data.active_plan.name : "No active plan");
        setText("planExpiry", data.active_plan ? `Expires ${formatDate(data.active_plan.expires_at)}` : "");

        const payments = document.getElementById("clientPayments");
        if (!data.payments.length) {
            addEmptyRow(payments, 3, "No plan requests yet.");
        } else {
            const rows = data.payments.map((payment) => {
                const row = document.createElement("tr");
                addCell(row, payment.plan_name);
                addCell(row, `₹${payment.amount}`);
                addCell(row, payment.status);
                return row;
            });
            payments.replaceChildren(...rows);
        }

        const usage = document.getElementById("clientUsage");
        if (!data.usage.length) {
            addEmptyRow(usage, 3, "Sign in while using a tool to record activity.");
        } else {
            const rows = data.usage.map((event) => {
                const row = document.createElement("tr");
                addCell(row, event.feature.replaceAll("_", " "));
                addCell(row, event.detail);
                addCell(row, formatDate(event.created_at));
                return row;
            });
            usage.replaceChildren(...rows);
        }
    }

    async function loadAdminUsers(search = "") {
        const result = await api(`/api/admin/users?search=${encodeURIComponent(search)}`);
        const body = document.getElementById("adminUsers");
        if (!result.users.length) {
            addEmptyRow(body, 4, "No client accounts found.");
            return;
        }

        const rows = result.users.map((user) => {
            const row = document.createElement("tr");
            addCell(row, `${user.full_name}\n${user.email}`);
            addCell(row, formatDate(user.created_at));
            addCell(row, user.active ? "Active" : "Suspended");
            const actionCell = document.createElement("td");
            actionCell.className = "p-3";
            const button = document.createElement("button");
            button.dataset.userId = user.id;
            button.dataset.active = String(!user.active);
            button.className = `rounded-lg px-3 py-1.5 text-xs font-bold text-white ${user.active ? "bg-rose-600" : "bg-emerald-700"}`;
            button.textContent = user.active ? "Suspend" : "Activate";
            actionCell.appendChild(button);
            row.appendChild(actionCell);
            return row;
        });
        body.replaceChildren(...rows);
    }

    async function loadAdminPayments(status = "all") {
        const result = await api(`/api/admin/payments?status=${encodeURIComponent(status)}`);
        const body = document.getElementById("adminPayments");
        if (!result.payments.length) {
            addEmptyRow(body, 4, "No payment requests found.");
            return;
        }

        const rows = result.payments.map((payment) => {
            const row = document.createElement("tr");
            addCell(row, `${payment.client_name || "Unknown client"}\n${payment.plan_name}`);
            addCell(row, `₹${payment.amount}`);
            addCell(row, payment.status);
            const actionCell = document.createElement("td");
            actionCell.className = "p-3";
            if (payment.status === "pending") {
                for (const [statusValue, label, color] of [
                    ["paid", "Approve", "bg-emerald-700"],
                    ["rejected", "Reject", "bg-rose-600"],
                ]) {
                    const button = document.createElement("button");
                    button.dataset.transactionId = payment.transaction_id;
                    button.dataset.status = statusValue;
                    button.className = `mr-1 mb-1 rounded px-2 py-1 text-xs font-bold text-white ${color}`;
                    button.textContent = label;
                    actionCell.appendChild(button);
                }
            } else {
                actionCell.textContent = "Reviewed";
            }
            row.appendChild(actionCell);
            return row;
        });
        body.replaceChildren(...rows);
    }

    async function loadAdminPanel() {
        try {
            const user = await loadSession("admin");
            if (!user) return;
            const result = await api("/api/admin/dashboard");
            const stats = result.stats;
            const statItems = [
                ["Clients", stats.clients],
                ["Active clients", stats.active_clients],
                ["Pending payments", stats.pending_payments],
                ["Approved payments", stats.approved_payments],
                ["Rejected payments", stats.rejected_payments],
                ["Tool usage", stats.usage_events],
            ];
            const cards = statItems.map(([title, value]) => {
                const card = document.createElement("article");
                card.className = "rounded-xl border bg-white p-4 shadow-sm";
                const label = document.createElement("p");
                label.className = "text-sm text-slate-500";
                label.textContent = title;
                const count = document.createElement("p");
                count.className = "mt-2 text-2xl font-bold";
                count.textContent = String(value);
                card.append(label, count);
                return card;
            });
            document.getElementById("adminStats").replaceChildren(...cards);
            await Promise.all([loadAdminUsers(), loadAdminPayments()]);
        } catch (error) {
            if (error.status === 401) window.location.replace("/login");
            else showMessage(error.message, true);
        }

        document.getElementById("userSearchForm").addEventListener("submit", async (event) => {
            event.preventDefault();
            try {
                await loadAdminUsers(document.getElementById("userSearch").value);
            } catch (error) {
                showMessage(error.message, true);
            }
        });
        document.getElementById("paymentFilter").addEventListener("change", async (event) => {
            try {
                await loadAdminPayments(event.target.value);
            } catch (error) {
                showMessage(error.message, true);
            }
        });
        document.getElementById("adminUsers").addEventListener("click", async (event) => {
            const button = event.target.closest("button[data-user-id]");
            if (!button) return;
            try {
                await api(`/api/admin/users/${encodeURIComponent(button.dataset.userId)}`, {
                    method: "PATCH",
                    body: { active: button.dataset.active === "true" },
                });
                await loadAdminUsers(document.getElementById("userSearch").value);
            } catch (error) {
                showMessage(error.message, true);
            }
        });
        document.getElementById("adminPayments").addEventListener("click", async (event) => {
            const button = event.target.closest("button[data-transaction-id]");
            if (!button) return;
            try {
                await api(`/api/admin/payments/${encodeURIComponent(button.dataset.transactionId)}`, {
                    method: "PATCH",
                    body: { status: button.dataset.status },
                });
                await Promise.all([loadAdminPayments(document.getElementById("paymentFilter").value), refreshAdminStats()]);
            } catch (error) {
                showMessage(error.message, true);
            }
        });
    }

    async function refreshAdminStats() {
        const result = await api("/api/admin/dashboard");
        const stats = result.stats;
        const values = [stats.clients, stats.active_clients, stats.pending_payments, stats.approved_payments, stats.rejected_payments, stats.usage_events];
        document.querySelectorAll("#adminStats article p.mt-2").forEach((element, index) => {
            element.textContent = String(values[index]);
        });
    }

    document.querySelectorAll(".logoutButton").forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                await api("/api/auth/logout", { method: "POST" });
                window.location.replace("/login");
            } catch (error) {
                showMessage(error.message, true);
            }
        });
    });

    if (!setupLoginPage()) {
        if (document.getElementById("clientName")) loadClientPanel();
        if (document.getElementById("adminStats")) loadAdminPanel();
    }
})();
