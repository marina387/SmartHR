const VACANCY_CRITERIA = ["hard", "soft", "management", "education", "salary"];

function vacancyEditShowToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "app-notice " + (type || "green");
    toast.textContent = message;
    toast.setAttribute("role", type === "red" ? "alert" : "status");
    toast.setAttribute("aria-live", type === "red" ? "assertive" : "polite");
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), type === "red" ? 9000 : 4500);
}

function getVacancyEditData() {
    const dataElement = document.getElementById("vacancyEditData");
    if (!dataElement) return { vacancy: null, default_weights: null, is_edit: false, template_id: null };
    try {
        return JSON.parse(dataElement.textContent || "{}");
    } catch (err) {
        return { vacancy: null, default_weights: null, is_edit: false, template_id: null };
    }
}

function createEditableItem(value = "") {
    const wrap = document.createElement("div");
    wrap.className = "d-flex gap-2";

    const input = document.createElement("input");
    input.className = "form-control editable-item";
    input.value = value;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn btn-outline-danger";
    removeBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
    removeBtn.addEventListener("click", () => wrap.remove());

    wrap.appendChild(input);
    wrap.appendChild(removeBtn);
    return wrap;
}

function appendEditableItem(containerId, value = "") {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.appendChild(createEditableItem(value));
}

function readEditableItems(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return [];
    return [...container.querySelectorAll(".editable-item")]
        .map((input) => input.value.trim())
        .filter((item) => item.length > 0);
}

function setWeights(weights) {
    VACANCY_CRITERIA.forEach((criterion) => {
        const input = document.getElementById("vacancyWeight_" + criterion);
        const valueLabel = document.getElementById("vacancyWeightValue_" + criterion);
        const value = Number(weights[criterion] || 0);
        if (input) input.value = String(value);
        if (valueLabel) valueLabel.textContent = String(value);
    });
    updateWeightTotal();
}

function readWeights() {
    const weights = {};
    VACANCY_CRITERIA.forEach((criterion) => {
        const input = document.getElementById("vacancyWeight_" + criterion);
        weights[criterion] = Number(input ? input.value : 0);
    });
    return weights;
}

function updateWeightTotal() {
    const total = VACANCY_CRITERIA.reduce((sum, criterion) => {
        const input = document.getElementById("vacancyWeight_" + criterion);
        const value = Number(input ? input.value : 0);
        const label = document.getElementById("vacancyWeightValue_" + criterion);
        if (label) label.textContent = String(value);
        return sum + value;
    }, 0);

    const totalEl = document.getElementById("vacancyWeightTotal");
    const hintEl = document.getElementById("vacancyWeightHint");
    const saveBtn = document.getElementById("saveVacancyBtn");

    if (totalEl) totalEl.textContent = String(total);

    const valid = total === 100;
    if (hintEl) {
        hintEl.className = valid ? "small text-success" : "small text-danger";
        hintEl.textContent = valid
            ? "Сумма корректна. Вакансию можно сохранить."
            : "Сумма должна быть ровно 100%.";
    }
    if (saveBtn) saveBtn.disabled = !valid;

    return valid;
}

function buildVacancyPayload() {
    const data = getVacancyEditData();
    return {
        title: (document.getElementById("vacancyTitle")?.value || "").trim(),
        category: (document.getElementById("vacancyCategory")?.value || "").trim(),
        description: (document.getElementById("vacancyDescription")?.value || "").trim(),
        critical_requirements: readEditableItems("criticalRequirementsList"),
        skills: readEditableItems("skillsList"),
        required_skills: readEditableItems("criticalRequirementsList"),
        experience_required: (document.getElementById("vacancyExperience")?.value || "").trim(),
        education_required: (document.getElementById("vacancyEducation")?.value || "").trim(),
        min_experience: Number(document.getElementById("vacancyMinExperience")?.value || 0),
        max_experience: Number(document.getElementById("vacancyMaxExperience")?.value || 40),
        specialization: (document.getElementById("vacancySpecialization")?.value || "").trim(),
        required_education: (document.getElementById("vacancyRequiredEducation")?.value || "none").trim(),
        english_required: (document.getElementById("vacancyEnglish")?.value || "A1").trim(),
        management_required: Boolean(document.getElementById("vacancyManagementRequired")?.checked),
        min_salary: Number(document.getElementById("vacancyMinSalary")?.value || 0),
        max_salary: Number(document.getElementById("vacancyMaxSalary")?.value || 0),
        weights: readWeights(),
        status: (document.getElementById("vacancyStatus")?.value || "active").trim(),
        template_id: data.template_id || (data.vacancy && data.vacancy.template_id) || undefined,
    };
}

async function saveVacancy(vacancyId) {
    if (!updateWeightTotal()) {
        vacancyEditShowToast("Сумма весов должна быть 100%", "red");
        return;
    }

    const payload = buildVacancyPayload();
    if (!payload.title) {
        vacancyEditShowToast("Название вакансии обязательно", "red");
        return;
    }

    const saveBtn = document.getElementById("saveVacancyBtn");
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "Сохранение...";
    }

    const isEdit = Boolean(vacancyId);
    const url = isEdit ? "/api/vacancies/" + encodeURIComponent(vacancyId) : "/api/vacancies";
    const method = isEdit ? "PUT" : "POST";

    try {
        const response = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            vacancyEditShowToast(data.error || "Не удалось сохранить вакансию", "red");
            return;
        }

        vacancyEditShowToast("Вакансия сохранена", "green");
        setTimeout(() => {
            window.location.href = "/vacancies";
        }, 300);
    } catch (err) {
        vacancyEditShowToast("Ошибка: " + err.message, "red");
    } finally {
        if (saveBtn) {
            saveBtn.textContent = "Сохранить вакансию";
            updateWeightTotal();
        }
    }
}

function initVacancyForm(vacancy, defaultWeights) {
    const criticalContainer = document.getElementById("criticalRequirementsList");
    const skillsContainer = document.getElementById("skillsList");

    if (criticalContainer) criticalContainer.innerHTML = "";
    if (skillsContainer) skillsContainer.innerHTML = "";

    (vacancy?.critical_requirements || [""]).forEach((item) => appendEditableItem("criticalRequirementsList", item));
    (vacancy?.skills || [""]).forEach((item) => appendEditableItem("skillsList", item));

    setWeights(vacancy?.weights || defaultWeights || { hard: 50, soft: 30, management: 10, education: 5, salary: 5 });
}

document.addEventListener("DOMContentLoaded", () => {
    const data = getVacancyEditData();
    const vacancy = data.vacancy || null;
    const defaultWeights = data.default_weights || { hard: 50, soft: 30, management: 10, education: 5, salary: 5 };

    initVacancyForm(vacancy, defaultWeights);

    const addCriticalBtn = document.getElementById("addCriticalRequirementBtn");
    if (addCriticalBtn) {
        addCriticalBtn.addEventListener("click", () => appendEditableItem("criticalRequirementsList", ""));
    }

    const addSkillBtn = document.getElementById("addSkillBtn");
    if (addSkillBtn) {
        addSkillBtn.addEventListener("click", () => appendEditableItem("skillsList", ""));
    }

    VACANCY_CRITERIA.forEach((criterion) => {
        const slider = document.getElementById("vacancyWeight_" + criterion);
        if (!slider) return;
        slider.addEventListener("input", updateWeightTotal);
    });

    const saveBtn = document.getElementById("saveVacancyBtn");
    if (saveBtn) {
        saveBtn.addEventListener("click", () => saveVacancy(vacancy?.id || ""));
    }

    updateWeightTotal();
});
