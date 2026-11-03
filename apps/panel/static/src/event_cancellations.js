(() => {
  const dialog = document.getElementById("cancellationDialog");
  if (!dialog) return;
  const find = (selector) => dialog.querySelector(selector);
  const form = find("[data-cancellation-form]");
  const status = find("[data-cancellation-status]");
  const results = find("[data-cancellation-results]");
  const deleteFound = find("[data-delete-found]");
  const confirmation = find("[data-cancellation-confirm]");
  let busy = false;
  let pendingScope = null;

  function setStatus(message, error = false) {
    status.textContent = message;
    status.className = `task-status task-status--${error ? "error" : "success"}`;
    status.hidden = false;
  }

  function invalidateResults() {
    results.hidden = true;
    deleteFound.disabled = true;
    confirmation.hidden = true;
    pendingScope = null;
    find("[data-all-departments]").hidden = Boolean(form.querySelector("input[name=departments]:checked"));
  }

  async function request(url, data, method) {
    const options = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (method === "POST") {
      options.body = data;
      options.headers["X-CSRFToken"] = form.elements.csrfmiddlewaretoken.value;
    } else {
      const query = new URLSearchParams();
      for (const [key, value] of data) {
        if (key !== "csrfmiddlewaretoken") query.append(key, value);
      }
      url += `?${query}`;
    }
    const response = await fetch(url, options);
    if (response.redirected || !response.headers.get("content-type")?.includes("application/json")) {
      throw new Error(dialog.dataset.error);
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || dialog.dataset.error);
    return payload;
  }

  async function run(operation) {
    if (busy) return;
    busy = true;
    const controls = [...dialog.querySelectorAll("button, input")];
    const disabledStates = controls.map((control) => control.disabled);
    controls.forEach((control) => { control.disabled = true; });
    dialog.setAttribute("aria-busy", "true");
    try {
      await operation();
    } catch (error) {
      setStatus(error.message || dialog.dataset.error, true);
    } finally {
      controls.forEach((control, index) => { control.disabled = disabledStates[index]; });
      deleteFound.disabled = results.hidden || Number(find("[data-cancellation-count]").textContent) === 0;
      dialog.removeAttribute("aria-busy");
      busy = false;
    }
  }

  async function loadResults(data) {
    const payload = await request(dialog.dataset.url, data, "GET");
    const rows = find("[data-cancellation-rows]");
    rows.replaceChildren();
    for (const item of payload.cancellations) {
      const row = document.createElement("tr");
      for (const value of [item.date, item.department]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      }
      rows.append(row);
    }
    find("[data-cancellation-count]").textContent = String(payload.count);
    find("[data-cancellation-truncated]").hidden = payload.count <= payload.cancellations.length;
    results.hidden = false;
  }

  document.querySelectorAll("[data-open-cancellations]").forEach((button) => {
    button.addEventListener("click", () => dialog.showModal());
  });
  dialog.querySelectorAll("[data-close-cancellations]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
  dialog.addEventListener("close", () => { confirmation.hidden = true; pendingScope = null; });
  form.addEventListener("input", invalidateResults);
  find("[data-department-search]").addEventListener("input", (event) => {
    const query = event.target.value.trim().toLocaleLowerCase();
    dialog.querySelectorAll("[data-department-tag]").forEach((tag) => {
      tag.hidden = !tag.textContent.toLocaleLowerCase().includes(query);
    });
  });
  find("[data-department-search]").addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });
  find("[data-clear-departments]").addEventListener("click", () => {
    form.querySelectorAll("input[name=departments]").forEach((input) => { input.checked = false; });
    invalidateResults();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    run(async () => {
      invalidateResults();
      const payload = await request(dialog.dataset.url, data, "POST");
      setStatus(`${dialog.dataset.created} ${payload.created}. ${dialog.dataset.existing} ${payload.existing}.`);
      await loadResults(data);
    });
  });
  find("[data-find-cancellations]").addEventListener("click", () => {
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    run(async () => {
      invalidateResults();
      status.hidden = true;
      await loadResults(data);
    });
  });
  for (const [selector, scope] of [["[data-delete-found]", "range"], ["[data-delete-all]", "all"]]) {
    find(selector).addEventListener("click", () => {
      pendingScope = scope;
      find("[data-cancellation-confirm-text]").textContent = scope === "all" ? dialog.dataset.confirmAll : dialog.dataset.confirmRange;
      confirmation.hidden = false;
      find("[data-confirm-delete]").focus();
    });
  }
  find("[data-cancel-delete]").addEventListener("click", () => { confirmation.hidden = true; pendingScope = null; });
  find("[data-confirm-delete]").addEventListener("click", () => {
    if (!pendingScope) return;
    const scope = pendingScope;
    const data = new FormData(form);
    data.set("scope", scope);
    if (scope === "all") data.set("confirm_all", "yes");
    const refreshResults = form.checkValidity();
    run(async () => {
      invalidateResults();
      const payload = await request(dialog.dataset.deleteUrl, data, "POST");
      setStatus(`${dialog.dataset.deleted} ${payload.deleted}.`);
      if (refreshResults) await loadResults(data);
    });
  });
})();
