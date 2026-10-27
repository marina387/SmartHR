document.addEventListener("DOMContentLoaded", () => {
    const transferForm = document.getElementById('manualTransferForm');
    transferForm?.addEventListener('submit', async event => {
        event.preventDefault();
        const button = transferForm.querySelector('[type="submit"]');
        const error = document.getElementById('manualTransferError');
        button.disabled = true;
        error.hidden = true;
        try {
            const response = await fetch('/api/candidates/' + encodeURIComponent(transferForm.dataset.candidateId) + '/vacancies', {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({manual_transfer:true, mode:'transfer',
                    from_vacancy_id:transferForm.dataset.currentVacancy,
                    to_vacancy_id:document.getElementById('manualTransferVacancy').value,
                    comment:document.getElementById('manualTransferReason').value}),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Перенос не выполнен');
            window.location.reload();
        } catch (err) {
            error.textContent = err.message;
            error.hidden = false;
            button.disabled = false;
        }
    });
    const form = document.getElementById("editCandidateForm");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = form.querySelector('[type="submit"]');
        const error = document.getElementById("editCandidateError");
        button.disabled = true;
        error.hidden = true;
        try {
            const response = await fetch("/api/candidates/" + encodeURIComponent(form.dataset.candidateId), {
                method: "PATCH", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({...Object.fromEntries(new FormData(form)), rescore: true}),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Не удалось сохранить данные");
            window.location.reload();
        } catch (err) {
            error.textContent = err.message || "Ошибка соединения. Повторите сохранение";
            error.hidden = false;
            button.disabled = false;
        }
    });
});

function detailShowToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "app-notice " + (type || "green");
    toast.textContent = message;
    toast.setAttribute("role", type === "red" ? "alert" : "status");
    toast.setAttribute("aria-live", type === "red" ? "assertive" : "polite");
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), type === "red" ? 9000 : 4500);
}

function readJsonFromElement(elementId, fallback) {
    const element = document.getElementById(elementId);
    if (!element) return fallback;
    try {
        return JSON.parse(element.textContent || "null") || fallback;
    } catch (err) {
        return fallback;
    }
}

async function createInterview(candidateId, candidateName, vacancyId) {
    const date = document.getElementById("interviewDate")?.value;
    const time = document.getElementById("interviewTime")?.value;
    const duration = document.getElementById("interviewDuration")?.value;
    const format = document.getElementById("interviewFormat")?.value;
    const notes = document.getElementById("interviewNotes")?.value || "";

    const payload = {
        candidate_id: candidateId,
        candidate_name: candidateName,
        vacancy_id: vacancyId || "VAC_001",
        date,
        time,
        duration,
        format,
        notes,
    };

    try {
        const response = await fetch("/api/interviews", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();

        if (!response.ok || data.error) {
            detailShowToast(data.error || "Не удалось сохранить интервью", "red");
            return;
        }

        if (data.warnings?.length) window.alert(data.warnings.join("\n"));
        detailShowToast(data.warnings?.length ? data.warnings.join(" ") : "Интервью запланировано", data.warnings?.length ? "yellow" : "green");
        setTimeout(() => window.location.reload(), 300);
    } catch (err) {
        detailShowToast("Ошибка: " + err.message, "red");
    }
}

async function deleteInterview(interviewId) {
    try {
        const response = await fetch("/api/interviews/" + encodeURIComponent(interviewId), {
            method: "DELETE",
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            detailShowToast(data.error || "Не удалось удалить интервью", "red");
            return;
        }
        detailShowToast("Интервью удалено", "yellow");
        setTimeout(() => window.location.reload(), 250);
    } catch (err) {
        detailShowToast("Ошибка: " + err.message, "red");
    }
}

async function saveFeedback(candidateId, vacancyId, originalScores) {
    const correctedScores = {};
    ["hard", "soft", "management", "education", "salary"].forEach((criterion) => {
        const value = document.getElementById("feedback_" + criterion)?.value;
        correctedScores[criterion] = value ? Number(value) : 1;
    });

    const payload = {
        candidate_id: candidateId,
        vacancy_id: vacancyId || "VAC_001",
        original_scores: originalScores,
        corrected_scores: correctedScores,
        comment: document.getElementById("feedbackComment")?.value || "",
    };

    try {
        const response = await fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            detailShowToast(data.error || "Не удалось сохранить обратную связь", "red");
            return;
        }
        detailShowToast("Исправление оценки сохранено", "green");
        setTimeout(() => window.location.reload(), 300);
    } catch (err) {
        detailShowToast("Ошибка: " + err.message, "red");
    }
}

let alternativeItems = [];

function percent(value) {
    return Math.round(Number(value || 0) * 1000) / 10 + "%";
}

function renderAlternativeComparison(item, currentVacancyId) {
    const body = document.getElementById("alternativeCompareBody");
    if (!body) return;
    body.innerHTML = "";
    const heading = document.createElement("h5");
    heading.textContent = item.vacancy_title;
    body.appendChild(heading);
    const summary = document.createElement("p");
    summary.className = "text-muted";
    summary.textContent = `Текущая вакансия ${currentVacancyId}: ${item.current_total}/100. Альтернатива: ${item.total}/100 (${item.score_improvement >= 0 ? "+" : ""}${item.score_improvement}).`;
    body.appendChild(summary);
    const table = document.createElement("table");
    table.className = "table table-sm align-middle";
    const tbody = document.createElement("tbody");
    const rows = [
        ["ML-вероятность", percent(item.model_probability)],
        ["Совпавшие навыки", (item.matched_skills || []).map((match) => `${match.required} ← ${match.candidate} (${match.match_type})`).join(", ") || "Нет"],
        ["Недостающие навыки", (item.missing_skills || []).join(", ") || "Нет"],
        ["Причина", item.reason || ""],
        ["Веса", Object.entries(item.used_weights || {}).map(([key, value]) => `${key}: ${value}%`).join(", ")],
    ];
    rows.forEach(([label, value]) => {
        const row = document.createElement("tr");
        const labelCell = document.createElement("th");
        labelCell.textContent = label;
        const valueCell = document.createElement("td");
        valueCell.textContent = value;
        row.append(labelCell, valueCell);
        tbody.appendChild(row);
    });
    table.appendChild(tbody);
    body.appendChild(table);
}

async function applyAlternative(candidateId, currentVacancyId, item, mode) {
    const verb = mode === "transfer" ? "перенести" : "добавить";
    if (!window.confirm(`Подтвердить действие: ${verb} кандидата в вакансию «${item.vacancy_title}»?`)) return;
    try {
        const response = await fetch(`/api/candidates/${encodeURIComponent(candidateId)}/vacancies`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                from_vacancy_id: currentVacancyId,
                to_vacancy_id: item.vacancy_id,
                mode,
                        comment: "Подтверждено в карточке кандидата",
            }),
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Операция не выполнена");
        detailShowToast(mode === "transfer" ? "Кандидат перенесён" : "Кандидат добавлен к вакансии", "green");
        setTimeout(() => window.location.reload(), 350);
    } catch (err) {
        detailShowToast("Ошибка: " + err.message, "red");
    }
}

function renderAlternatives(candidateId, currentVacancyId, items) {
    alternativeItems = items;
    const state = document.getElementById("alternativeVacanciesState");
    const list = document.getElementById("alternativeVacanciesList");
    if (!list || !state) return;
    list.innerHTML = "";
    if (!items.length) {
        state.textContent = "Подходящих альтернатив по заданным порогам не найдено.";
        return;
    }
    state.textContent = `Найдено рекомендаций: ${items.length}`;
    items.forEach((item, index) => {
        const col = document.createElement("div");
        col.className = "col-lg-4";
        const card = document.createElement("div");
        card.className = "border rounded-4 p-3 h-100";
        const title = document.createElement("h5");
        title.textContent = item.vacancy_title;
        const score = document.createElement("div");
        score.className = "fs-4 fw-bold text-success";
        score.textContent = `${item.total}/100`;
        const meta = document.createElement("div");
        meta.className = "small text-muted mb-3";
        meta.textContent = `ML: ${percent(item.model_probability)} · улучшение: +${item.score_improvement}`;
        const reason = document.createElement("p");
        reason.className = "small";
        reason.textContent = item.reason;
        const actions = document.createElement("div");
        actions.className = "d-flex flex-wrap gap-2";
        const compare = document.createElement("button");
        compare.className = "btn btn-sm btn-outline-secondary";
        compare.textContent = "Сравнить";
        compare.setAttribute("data-bs-toggle", "modal");
        compare.setAttribute("data-bs-target", "#alternativeCompareModal");
        compare.addEventListener("click", () => renderAlternativeComparison(alternativeItems[index], currentVacancyId));
        const add = document.createElement("button");
        add.className = "btn btn-sm btn-outline-primary";
        add.textContent = "Добавить";
        add.addEventListener("click", () => applyAlternative(candidateId, currentVacancyId, item, "add"));
        const transfer = document.createElement("button");
        transfer.className = "btn btn-sm btn-primary";
        transfer.textContent = "Перенести";
        transfer.addEventListener("click", () => applyAlternative(candidateId, currentVacancyId, item, "transfer"));
        actions.append(compare, add, transfer);
        card.append(title, score, meta, reason, actions);
        col.appendChild(card);
        list.appendChild(col);
    });
}

async function loadAlternatives(candidateId, currentVacancyId) {
    const state = document.getElementById("alternativeVacanciesState");
    if (state) state.textContent = "Поиск рекомендаций...";
    try {
        const url = `/api/candidates/${encodeURIComponent(candidateId)}/alternative-vacancies?current_vacancy_id=${encodeURIComponent(currentVacancyId)}&limit=3`;
        const response = await fetch(url);
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Не удалось получить рекомендации");
        renderAlternatives(candidateId, currentVacancyId, data.alternatives || []);
        if (state && data.warning) state.textContent = data.warning + ' ' + (state.textContent || '');
    } catch (err) {
        if (state) state.textContent = "Ошибка поиска: " + err.message;
    }
}

async function updateCandidateStage(candidateId, vacancyId) {
    const select = document.getElementById("candidateStageSelect");
    const state = document.getElementById("candidateStageState");
    const stage = select?.value || "";
    if (!stage) return;
    if (select) select.disabled = true;
    if (state) state.textContent = "Сохранение...";
    try {
        const response = await fetch(`/api/candidates/${encodeURIComponent(candidateId)}/stage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ vacancy_id: vacancyId, stage, reason: "Обновлено в карточке кандидата" }),
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Этап не обновлён");
        if (state) state.textContent = "Сохранено";
        detailShowToast("Этап сохранён", "green");
    } catch (err) {
        const detailData = readJsonFromElement("candidateDetailData", {});
        if (select && detailData.current_stage) select.value = detailData.current_stage;
        if (state) state.textContent = "Не удалось сохранить";
        detailShowToast("Ошибка: " + err.message, "red");
    } finally {
        if (select) select.disabled = false;
    }
}

async function runRetentionAction(candidateId, action) {
    const isRestore = action === "restore";
    if (!isRestore && !window.confirm("Проверить кандидата по всем активным вакансиям и отправить в архив, если совпадений нет?")) return;
    try {
        const suffix = isRestore ? "restore" : "retention-check";
        const response = await fetch(`/api/candidates/${encodeURIComponent(candidateId)}/${suffix}`, { method: "POST" });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Операция не выполнена");
        const message = isRestore ? "Кандидат восстановлен" : data.archived ? "Кандидат перемещён в архив" : `Кандидат оставлен активным: ${data.reason}`;
        detailShowToast(message, data.archived || isRestore ? "green" : "yellow");
        setTimeout(() => window.location.reload(), 500);
    } catch (err) {
        detailShowToast("Ошибка: " + err.message, "red");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const detailData = readJsonFromElement("candidateDetailData", {});
    const candidateId = detailData.candidate_id || "";
    const candidateName = detailData.candidate_name || "";
    const vacancyId = detailData.vacancy_id || "VAC_001";
    const originalScores = detailData.original_scores || {};

    const interviewSaveBtn = document.getElementById("saveInterviewBtn");
    if (interviewSaveBtn) {
        interviewSaveBtn.addEventListener("click", () => createInterview(candidateId, candidateName, vacancyId));
    }

    document.querySelectorAll(".delete-interview-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const interviewId = button.getAttribute("data-interview-id") || "";
            if (!interviewId) return;
            deleteInterview(interviewId);
        });
    });

    const feedbackSaveBtn = document.getElementById("saveFeedbackBtn");
    if (feedbackSaveBtn) {
        feedbackSaveBtn.addEventListener("click", () => saveFeedback(candidateId, vacancyId, originalScores));
    }

    const refreshAlternativesBtn = document.getElementById("refreshAlternativesBtn");
    if (refreshAlternativesBtn) refreshAlternativesBtn.addEventListener("click", () => loadAlternatives(candidateId, vacancyId));
    if (candidateId) loadAlternatives(candidateId, vacancyId);
    const candidateStageSelect = document.getElementById("candidateStageSelect");
    if (candidateStageSelect) candidateStageSelect.addEventListener("change", () => updateCandidateStage(candidateId, vacancyId));
    const retentionCheckBtn = document.getElementById("retentionCheckBtn");
    if (retentionCheckBtn) retentionCheckBtn.addEventListener("click", () => runRetentionAction(candidateId, "check"));
    const restoreCandidateBtn = document.getElementById("restoreCandidateBtn");
    if (restoreCandidateBtn) restoreCandidateBtn.addEventListener("click", () => runRetentionAction(candidateId, "restore"));
});
