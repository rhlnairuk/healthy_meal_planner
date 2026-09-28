const state = {
  adults: 2,
  children: 1,
  week: null, // null = current week
  currentSlot: "breakfasts",
  planData: null,
};

function loadHouseholdFromStorage() {
  const saved = JSON.parse(localStorage.getItem("household") || "{}");
  if (saved.adults) state.adults = saved.adults;
  if (saved.children !== undefined) state.children = saved.children;
  document.getElementById("adults").value = state.adults;
  document.getElementById("children").value = state.children;
}

function saveHouseholdToStorage() {
  localStorage.setItem("household", JSON.stringify({ adults: state.adults, children: state.children }));
}

function setStatus(message, kind) {
  const el = document.getElementById("status");
  el.textContent = message;
  el.className = "status" + (kind ? " " + kind : "");
  if (kind === "ok") {
    setTimeout(() => { if (el.textContent === message) el.textContent = ""; }, 3000);
  }
}

async function api(path, options) {
  const res = await fetch(path, options);
  let body = null;
  try { body = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const message = (body && body.error) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return body;
}

// ---- tabs ----

function initTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    });
  });

  document.querySelectorAll(".slot-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".slot-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.currentSlot = btn.dataset.slot;
      loadRecipeEditor();
    });
  });
}

// ---- plan view ----

const MEAL_SLOTS_LABELS = [["Breakfast", "breakfast"], ["Lunch", "lunch"], ["Dinner", "dinner"], ["Snack", "snack"]];

function renderDays(containerId, days, recipeLookup) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  for (const day of days) {
    const card = document.createElement("div");
    card.className = "day-card";

    const name = document.createElement("div");
    name.className = "day-name";
    name.textContent = day.day;
    card.appendChild(name);

    for (const [label, key] of MEAL_SLOTS_LABELS) {
      const row = document.createElement("div");
      row.className = "meal-row";

      const b = document.createElement("b");
      b.textContent = label + ": ";
      row.appendChild(b);

      const link = document.createElement("button");
      link.type = "button";
      link.className = "meal-link";
      link.textContent = day[key];
      link.addEventListener("click", () => openRecipeModal(recipeLookup[day[key]]));
      row.appendChild(link);

      card.appendChild(row);
    }
    container.appendChild(card);
  }
}

function recipesByName(recipes) {
  const map = {};
  for (const recipe of recipes) map[recipe.name] = recipe;
  return map;
}

function formatIngredient(ing) {
  return ing.unit === "unit" ? `${ing.quantity} x ${ing.name}` : `${ing.quantity}${ing.unit} ${ing.name}`;
}

function openRecipeModal(recipe) {
  const title = document.getElementById("recipe-modal-title");
  const ingredientsEl = document.getElementById("recipe-modal-ingredients");
  const stepsEl = document.getElementById("recipe-modal-steps");

  title.textContent = recipe ? recipe.name : "Recipe not found";
  ingredientsEl.innerHTML = recipe && recipe.ingredients.length
    ? recipe.ingredients.map((i) => `<li>${formatIngredient(i)}</li>`).join("")
    : `<li class="note">No ingredients recorded.</li>`;
  stepsEl.innerHTML = recipe && recipe.steps.length
    ? recipe.steps.map((s) => `<li>${s}</li>`).join("")
    : `<li class="note">No steps recorded.</li>`;

  document.getElementById("recipe-modal").classList.remove("hidden");
}

function closeRecipeModal() {
  document.getElementById("recipe-modal").classList.add("hidden");
}

function initRecipeModal() {
  document.getElementById("recipe-modal-close").addEventListener("click", closeRecipeModal);
  document.querySelector("#recipe-modal .modal-backdrop").addEventListener("click", closeRecipeModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeRecipeModal();
  });
}

// ---- shopping ticks (client-side only, per week) ----

function ticksStorageKey(weekKey) {
  return "grocery-ticks:" + weekKey;
}

function tickId(listName, display) {
  return listName + "|" + display;
}

function loadTicks(weekKey) {
  try {
    return new Set(JSON.parse(localStorage.getItem(ticksStorageKey(weekKey)) || "[]"));
  } catch (e) {
    return new Set();
  }
}

function saveTicks(weekKey, ticks) {
  if (ticks.size) localStorage.setItem(ticksStorageKey(weekKey), JSON.stringify([...ticks]));
  else localStorage.removeItem(ticksStorageKey(weekKey));
}

function setTicked(weekKey, listName, display, ticked) {
  const ticks = loadTicks(weekKey);
  if (ticked) ticks.add(tickId(listName, display));
  else ticks.delete(tickId(listName, display));
  saveTicks(weekKey, ticks);
}

// sections: [{ title, listName, items }] - returns "" when nothing is left to buy.
function buildShoppingListText(sections, ticks) {
  const blocks = [];
  for (const section of sections) {
    const lines = section.items
      .filter((item) => !ticks.has(tickId(section.listName, item.display)))
      .map((item) => "- " + item.display);
    if (lines.length) blocks.push([section.title, ...lines].join("\n"));
  }
  return blocks.join("\n\n");
}

function shoppingSections(data) {
  const sections = [{ title: "Weekly groceries", listName: "weekly", items: data.this_week.weekly_grocery }];
  if (data.biweekly_due) {
    sections.push({ title: "Biweekly pantry staples", listName: "biweekly", items: data.biweekly.items });
  }
  sections.push({ title: "Extra items", listName: "adhoc", items: data.this_week.adhoc });
  return sections;
}

async function copyShoppingList() {
  const data = state.planData;
  if (!data) return;
  const text = buildShoppingListText(shoppingSections(data), loadTicks(data.week_key));
  if (!text) {
    setStatus("Nothing left to buy - every item is ticked.", "ok");
    return;
  }
  try {
    if (!navigator.clipboard) throw new Error("Clipboard is not available (needs HTTPS or localhost).");
    await navigator.clipboard.writeText(text);
    setStatus("Shopping list copied.", "ok");
  } catch (e) {
    setStatus("Could not copy: " + e.message, "error");
  }
}

function clearTicks() {
  const data = state.planData;
  if (!data) return;
  localStorage.removeItem(ticksStorageKey(data.week_key));
  document.querySelectorAll("#tab-this-week .item-list li.checked").forEach((li) => {
    li.classList.remove("checked");
    li.querySelector("input[type=checkbox]").checked = false;
  });
  setStatus("Ticks cleared.", "ok");
}

function initShoppingControls() {
  document.getElementById("copy-shopping-list").addEventListener("click", copyShoppingList);
  document.getElementById("clear-ticks").addEventListener("click", clearTicks);
}

// opts.checkable = { weekKey, listName } adds a persisted tick-off checkbox per item.
function renderItemList(containerId, items, opts) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = (opts && opts.emptyMessage) || "(nothing)";
    container.appendChild(li);
    return;
  }
  const checkable = opts && opts.checkable;
  const ticks = checkable ? loadTicks(checkable.weekKey) : null;
  items.forEach((item, index) => {
    const li = document.createElement("li");
    if (checkable) {
      const label = document.createElement("label");
      label.className = "item-label";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = ticks.has(tickId(checkable.listName, item.display));
      li.classList.toggle("checked", box.checked);
      box.addEventListener("change", () => {
        li.classList.toggle("checked", box.checked);
        setTicked(checkable.weekKey, checkable.listName, item.display, box.checked);
      });
      const text = document.createElement("span");
      text.textContent = item.display;
      label.append(box, text);
      li.appendChild(label);
    } else {
      const label = document.createElement("span");
      label.textContent = item.display;
      li.appendChild(label);
    }
    if (opts && opts.onRemove) {
      const btn = document.createElement("button");
      btn.className = "secondary";
      btn.textContent = "Remove";
      btn.addEventListener("click", () => opts.onRemove(index));
      li.appendChild(btn);
    }
    container.appendChild(li);
  });
}

async function loadPlan() {
  const params = new URLSearchParams({ adults: state.adults, children: state.children });
  if (state.week) params.set("week", state.week);
  const data = await api("/api/plan?" + params.toString());
  state.planData = data;

  document.getElementById("household-summary").textContent =
    `Week ${data.week_number} - ${data.household.description}`;

  renderDays("this-week-days", data.this_week.days, recipesByName(data.this_week.recipes));
  renderItemList("weekly-grocery", data.this_week.weekly_grocery, {
    emptyMessage: "(nothing needed)",
    checkable: { weekKey: data.week_key, listName: "weekly" },
  });
  renderItemList("this-week-adhoc", data.this_week.adhoc, {
    emptyMessage: "(none added)",
    onRemove: (index) => removeAdhocItem(data.week_number, index),
    checkable: { weekKey: data.week_key, listName: "adhoc" },
  });

  const biweeklyTitle = document.getElementById("biweekly-title");
  const biweeklyNote = document.getElementById("biweekly-note");
  const biweeklyList = document.getElementById("biweekly-grocery");
  if (data.biweekly_due) {
    biweeklyTitle.textContent = "Biweekly grocery list (pantry staples - covers this week and next)";
    biweeklyNote.textContent = "";
    renderItemList("biweekly-grocery", data.biweekly.items, {
      emptyMessage: "Fully covered by pantry surplus from previous shops - nothing new to buy.",
      checkable: { weekKey: data.week_key, listName: "biweekly" },
    });
  } else {
    biweeklyTitle.textContent = "Biweekly grocery list (pantry staples)";
    biweeklyList.innerHTML = "";
    biweeklyNote.textContent = "Not due this week - covered by last week's biweekly shop.";
  }

  renderDays("next-week-days", data.next_week.days, recipesByName(data.next_week.recipes));

  await loadAdhocEditorList(data.week_number);
}

async function removeAdhocItem(weekNumber, index) {
  try {
    await api(`/api/adhoc/${weekNumber}/${index}`, { method: "DELETE" });
    await loadPlan();
    setStatus("Removed.", "ok");
  } catch (e) {
    setStatus(e.message, "error");
  }
}

// ---- recipes editor ----

function ingredientRow(ing) {
  const row = document.createElement("div");
  row.className = "ingredient-row";
  row.innerHTML = `
    <input type="text" name="ing-name" placeholder="Ingredient name" value="${ing ? ing.name : ""}" required>
    <input type="number" name="ing-qty" placeholder="Qty (per adult)" step="any" min="0" value="${ing ? ing.quantity : ""}" required>
    <select name="ing-unit">
      <option value="g" ${ing && ing.unit === "g" ? "selected" : ""}>g</option>
      <option value="ml" ${ing && ing.unit === "ml" ? "selected" : ""}>ml</option>
      <option value="unit" ${ing && ing.unit === "unit" ? "selected" : ""}>unit</option>
    </select>
    <button type="button" class="secondary remove-row">x</button>
  `;
  row.querySelector(".remove-row").addEventListener("click", () => row.remove());
  return row;
}

function stepRow(step) {
  const row = document.createElement("div");
  row.className = "step-row";
  row.innerHTML = `
    <input type="text" name="step-text" placeholder="Cooking step" value="${step || ""}">
    <button type="button" class="secondary remove-row">x</button>
  `;
  row.querySelector(".remove-row").addEventListener("click", () => row.remove());
  return row;
}

function resetRecipeForm() {
  document.getElementById("recipe-form").reset();
  document.getElementById("recipe-form").dataset.editIndex = "";
  const ingredients = document.getElementById("recipe-ingredients");
  const steps = document.getElementById("recipe-steps");
  ingredients.innerHTML = "";
  steps.innerHTML = "";
  ingredients.appendChild(ingredientRow());
  steps.appendChild(stepRow());
  document.querySelector("#recipe-form button[type=submit]").textContent = "Save recipe";
}

function populateRecipeForm(recipe, index) {
  document.getElementById("recipe-form").dataset.editIndex = index;
  document.getElementById("recipe-name").value = recipe.name;
  const ingredients = document.getElementById("recipe-ingredients");
  const steps = document.getElementById("recipe-steps");
  ingredients.innerHTML = "";
  steps.innerHTML = "";
  (recipe.ingredients || []).forEach((ing) => ingredients.appendChild(ingredientRow(ing)));
  if (!recipe.ingredients || !recipe.ingredients.length) ingredients.appendChild(ingredientRow());
  (recipe.steps || []).forEach((s) => steps.appendChild(stepRow(s)));
  if (!recipe.steps || !recipe.steps.length) steps.appendChild(stepRow());
  document.querySelector("#recipe-form button[type=submit]").textContent = "Update recipe";
  window.scrollTo({ top: document.getElementById("recipe-form").offsetTop - 20, behavior: "smooth" });
}

async function loadRecipeEditor() {
  const recipes = await api(`/api/recipes/${state.currentSlot}`);
  const container = document.getElementById("recipe-editor-list");
  container.innerHTML = "";
  recipes.forEach((recipe, index) => {
    const card = document.createElement("div");
    card.className = "editor-card";
    const ingredients = recipe.ingredients.map((i) => `${i.quantity}${i.unit === "unit" ? "" : i.unit} ${i.name}`).join(", ");
    card.innerHTML = `
      <h4>${recipe.name}</h4>
      <p class="note">${ingredients}</p>
      <div class="row-actions">
        <button class="secondary edit-btn">Edit</button>
        <button class="danger delete-btn">Delete</button>
      </div>
    `;
    card.querySelector(".edit-btn").addEventListener("click", () => populateRecipeForm(recipe, index));
    card.querySelector(".delete-btn").addEventListener("click", () => deleteRecipe(index));
    container.appendChild(card);
  });
  resetRecipeForm();
}

async function deleteRecipe(index) {
  if (!confirm("Delete this recipe?")) return;
  try {
    await api(`/api/recipes/${state.currentSlot}/${index}`, { method: "DELETE" });
    setStatus("Recipe deleted.", "ok");
    await loadRecipeEditor();
    await loadPlan();
  } catch (e) {
    setStatus(e.message, "error");
  }
}

function collectRecipeFormData() {
  const name = document.getElementById("recipe-name").value.trim();
  const ingredients = [...document.querySelectorAll("#recipe-ingredients .ingredient-row")].map((row) => ({
    name: row.querySelector('[name="ing-name"]').value.trim(),
    quantity: parseFloat(row.querySelector('[name="ing-qty"]').value),
    unit: row.querySelector('[name="ing-unit"]').value,
  })).filter((ing) => ing.name);
  const steps = [...document.querySelectorAll("#recipe-steps .step-row input")]
    .map((input) => input.value.trim())
    .filter(Boolean);
  return { name, ingredients, steps };
}

function initRecipeForm() {
  document.getElementById("add-ingredient-row").addEventListener("click", () => {
    document.getElementById("recipe-ingredients").appendChild(ingredientRow());
  });
  document.getElementById("add-step-row").addEventListener("click", () => {
    document.getElementById("recipe-steps").appendChild(stepRow());
  });
  document.getElementById("recipe-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const editIndex = form.dataset.editIndex;
    const payload = collectRecipeFormData();
    try {
      if (editIndex !== "" && editIndex !== undefined) {
        await api(`/api/recipes/${state.currentSlot}/${editIndex}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("Recipe updated.", "ok");
      } else {
        await api(`/api/recipes/${state.currentSlot}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("Recipe added.", "ok");
      }
      await loadRecipeEditor();
      await loadPlan();
    } catch (e2) {
      setStatus(e2.message, "error");
    }
  });
}

// ---- long-life ingredients editor ----

async function loadLongLifeEditor() {
  const entries = await api("/api/long-life");
  const container = document.getElementById("long-life-list");
  container.innerHTML = "";
  entries.forEach((entry, index) => {
    const card = document.createElement("div");
    card.className = "editor-card";
    card.innerHTML = `
      <h4>${entry.name}</h4>
      <p class="note">Pack size: ${entry.pack_size}${entry.unit === "unit" ? "" : entry.unit}</p>
      <div class="row-actions">
        <button class="secondary edit-btn">Edit</button>
        <button class="danger delete-btn">Delete</button>
      </div>
    `;
    card.querySelector(".edit-btn").addEventListener("click", () => populateLongLifeForm(entry, index));
    card.querySelector(".delete-btn").addEventListener("click", () => deleteLongLife(index));
    container.appendChild(card);
  });
}

function resetLongLifeForm() {
  const form = document.getElementById("long-life-form");
  form.reset();
  form.dataset.editIndex = "";
  document.getElementById("long-life-form-title").textContent = "Add a pantry staple";
  document.querySelector("#long-life-form button[type=submit]").textContent = "Save";
  document.getElementById("ll-cancel-edit").hidden = true;
}

function populateLongLifeForm(entry, index) {
  const form = document.getElementById("long-life-form");
  form.dataset.editIndex = index;
  document.getElementById("ll-name").value = entry.name;
  document.getElementById("ll-unit").value = entry.unit;
  document.getElementById("ll-pack-size").value = entry.pack_size;
  document.getElementById("long-life-form-title").textContent = "Update pantry staple";
  document.querySelector("#long-life-form button[type=submit]").textContent = "Update pantry staple";
  document.getElementById("ll-cancel-edit").hidden = false;
  window.scrollTo({ top: form.offsetTop - 20, behavior: "smooth" });
}

async function deleteLongLife(index) {
  if (!confirm("Remove this pantry staple classification? The ingredient will fall back to the weekly perishable list.")) return;
  try {
    await api(`/api/long-life/${index}`, { method: "DELETE" });
    setStatus("Removed.", "ok");
    resetLongLifeForm(); // a pending edit index may now point at a different entry
    await loadLongLifeEditor();
    await loadPlan();
  } catch (e) {
    setStatus(e.message, "error");
  }
}

function initLongLifeForm() {
  document.getElementById("ll-cancel-edit").addEventListener("click", resetLongLifeForm);
  document.getElementById("long-life-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const editIndex = e.target.dataset.editIndex;
    const payload = {
      name: document.getElementById("ll-name").value.trim(),
      unit: document.getElementById("ll-unit").value,
      pack_size: parseFloat(document.getElementById("ll-pack-size").value),
    };
    try {
      if (editIndex !== "" && editIndex !== undefined) {
        await api(`/api/long-life/${editIndex}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("Pantry staple updated.", "ok");
      } else {
        await api("/api/long-life", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("Pantry staple added.", "ok");
      }
      resetLongLifeForm();
      await loadLongLifeEditor();
      await loadPlan();
    } catch (e2) {
      setStatus(e2.message, "error");
    }
  });
}

// ---- ad-hoc items editor ----

async function loadAdhocEditorList(weekNumber) {
  const items = await api(`/api/adhoc?week=${weekNumber}`);
  renderItemList("adhoc-list", items, {
    emptyMessage: "(none added)",
    onRemove: (index) => removeAdhocItem(weekNumber, index),
  });
}

function initAdhocForm() {
  document.getElementById("adhoc-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const weekNumber = state.planData ? state.planData.week_number : state.week;
    const payload = {
      name: document.getElementById("adhoc-name").value.trim(),
      quantity: parseFloat(document.getElementById("adhoc-quantity").value),
      unit: document.getElementById("adhoc-unit").value,
    };
    try {
      await api(`/api/adhoc?week=${weekNumber}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setStatus("Item added.", "ok");
      e.target.reset();
      document.getElementById("adhoc-quantity").value = 1;
      await loadPlan();
    } catch (e2) {
      setStatus(e2.message, "error");
    }
  });
}

// ---- household controls ----

function initHouseholdControls() {
  document.getElementById("apply-household").addEventListener("click", async () => {
    state.adults = parseInt(document.getElementById("adults").value, 10) || 2;
    state.children = parseInt(document.getElementById("children").value, 10) || 0;
    const weekVal = document.getElementById("week").value;
    state.week = weekVal ? parseInt(weekVal, 10) : null;
    saveHouseholdToStorage();
    try {
      await loadPlan();
      setStatus("Updated.", "ok");
    } catch (e) {
      setStatus(e.message, "error");
    }
  });

  document.getElementById("reset-pantry").addEventListener("click", async () => {
    if (!confirm("Forget tracked pantry surplus and start over?")) return;
    try {
      await api("/api/reset-pantry", { method: "POST" });
      setStatus("Pantry surplus tracking reset.", "ok");
      await loadPlan();
    } catch (e) {
      setStatus(e.message, "error");
    }
  });
}

// ---- init ----

async function init() {
  loadHouseholdFromStorage();
  initTabs();
  initHouseholdControls();
  initRecipeForm();
  initLongLifeForm();
  initAdhocForm();
  initRecipeModal();
  initShoppingControls();
  try {
    await loadPlan();
    await loadRecipeEditor();
    await loadLongLifeEditor();
  } catch (e) {
    setStatus(e.message, "error");
  }
}

init();
