const TEMPLATE_CRITERIA = ["hard", "soft", "management", "education", "salary"];

function templatesShowToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "toast " + (type || "green");
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

function getTemplatesPageData() {
    const element = document.getElementById("templatesPageData") || document.getElementById("vacanciesPageData");
    if (!element) {
        return { templates: [], default_weights: { hard: 50, soft: 30, management: 10, education: 5, salary: 5 } };
    }
    try {
        return JSON.parse(element.textContent || "{}");
    } catch (err) {
        return { templates: [], default_weights: { hard: 50, soft: 30, management: 10, education: 5, salary: 5 } };
    }
}

function readTemplateLines(fieldId) {
    const element = document.getElementById(fieldId);
    if (!element) return [];
    return element.value
        .split("\n")
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
}

function setTemplateWeights(weights) {
    TEMPLATE_CRITERIA.forEach((criterion) => {
        const slider = document.getElementById("templateWeight_" + criterion);
        const valueLabel = document.getElementById("templateWeightValue_" + criterion);
        const value = Number(weights?.[criterion] || 0);
        if (slider) slider.value = String(value);
        if (valueLabel) valueLabel.textContent = String(value);
    });
    updateTemplateWeightTotal();
}

function readTemplateWeights() {
    const weights = {};
    TEMPLATE_CRITERIA.forEach((criterion) => {
        const slider = document.getElementById("templateWeight_" + criterion);
        weights[criterion] = Number(slider ? slider.value : 0);
    });
    return weights;
}

function updateTemplateWeightTotal() {
    const total = TEMPLATE_CRITERIA.reduce((sum, criterion) => {
        const slider = document.getElementById("templateWeight_" + criterion);
        const value = Number(slider ? slider.value : 0);
        const label = document.getElementById("templateWeightValue_" + criterion);
        if (label) label.textContent = String(value);
        return sum + value;
    }, 0);

    const totalEl = document.getElementById("templateWeightTotal");
    const hintEl = document.getElementById("templateWeightHint");
    const saveBtn = document.getElementById("saveTemplateBtn");

    if (totalEl) totalEl.textContent = String(total);

    const valid = total === 100;
    if (hintEl) {
        hintEl.className = valid ? "small text-success" : "small text-danger";
        hintEl.textContent = valid ? "Сумма корректна. Шаблон можно сохранить." : "Сумма должна быть ровно 100%.";
    }
    if (saveBtn) saveBtn.disabled = !valid;

    return valid;
}

function resetTemplateModal(defaultWeights) {
    const modalTitle = document.getElementById("templateModalTitle");
    const idField = document.getElementById("templateId");
    const fields = ["templateName", "templateDescription", "templateCriticalRequirements", "templateSkills", "templateExperience", "templateEducation"];

    if (modalTitle) modalTitle.textContent = "Новый шаблон";
    if (idField) idField.value = "";
    fields.forEach((fieldId) => {
        const element = document.getElementById(fieldId);
        if (element) element.value = "";
    });
    setTemplateWeights(defaultWeights);
}

function fillTemplateModal(template) {
    const modalTitle = document.getElementById("templateModalTitle");
    const idField = document.getElementById("templateId");
    const fields = {
        templateName: template.name || template.title || "",
        templateDescription: template.description || "",
        templateCriticalRequirements: Array.isArray(template.critical_requirements) ? template.critical_requirements.join("\n") : "",
        templateSkills: Array.isArray(template.skills) ? template.skills.join("\n") : "",
        templateExperience: template.experience_required || "",
        templateEducation: template.education_required || "",
    };

    if (modalTitle) modalTitle.textContent = "Редактирование шаблона";
    if (idField) idField.value = template.id || "";
    Object.entries(fields).forEach(([fieldId, value]) => {
        const element = document.getElementById(fieldId);
        if (element) element.value = value;
    });
    const weights = template.weights || getTemplatesPageData().default_weights;
    setTemplateWeights(weights);
}

async function saveTemplate() {
    if (!updateTemplateWeightTotal()) {
        templatesShowToast("Сумма весов должна быть 100%", "red");
        return;
    }

    const payload = {
        name: (document.getElementById("templateName")?.value || "").trim(),
        category: (document.getElementById("templateCategory")?.value || "").trim(),
        description: (document.getElementById("templateDescription")?.value || "").trim(),
        critical_requirements: readTemplateLines("templateCriticalRequirements"),
        skills: readTemplateLines("templateSkills"),
        experience_required: (document.getElementById("templateExperience")?.value || "").trim(),
        education_required: (document.getElementById("templateEducation")?.value || "").trim(),
        weights: readTemplateWeights(),
    };

    if (!payload.name) {
        templatesShowToast("Название шаблона обязательно", "red");
        return;
    }

    const templateId = (document.getElementById("templateId")?.value || "").trim();
    const url = templateId ? "/api/templates/" + encodeURIComponent(templateId) : "/api/templates";
    const method = templateId ? "PUT" : "POST";
    const saveBtn = document.getElementById("saveTemplateBtn");

    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "Сохранение...";
    }

    try {
        const response = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            templatesShowToast(data.error || "Не удалось сохранить шаблон", "red");
            return;
        }

        templatesShowToast("Шаблон сохранён", "green");
        setTimeout(() => window.location.reload(), 300);
    } catch (err) {
        templatesShowToast("Ошибка: " + err.message, "red");
    } finally {
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = "Сохранить шаблон";
            updateTemplateWeightTotal();
        }
    }
}

async function deleteTemplate(templateId) {
    if (!window.confirm("Удалить шаблон?")) return;

    try {
        const response = await fetch("/api/templates/" + encodeURIComponent(templateId), { method: "DELETE" });
        const data = await response.json();
        if (!response.ok || data.error) {
            templatesShowToast(data.error || "Не удалось удалить шаблон", "red");
            return;
        }
        templatesShowToast("Шаблон удалён", "yellow");
        setTimeout(() => window.location.reload(), 250);
    } catch (err) {
        templatesShowToast("Ошибка: " + err.message, "red");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const pageData = getTemplatesPageData();
    const defaultWeights = pageData.default_weights || { hard: 50, soft: 30, management: 10, education: 5, salary: 5 };

    const newButton = document.getElementById("newTemplateBtn");
    if (newButton) {
        newButton.addEventListener("click", () => resetTemplateModal(defaultWeights));
    }

    document.querySelectorAll(".template-edit-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const raw = button.getAttribute("data-template") || "{}";
            try {
                fillTemplateModal(JSON.parse(raw));
                const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById("templateModal"));
                modal.show();
            } catch (err) {
                templatesShowToast("Не удалось открыть шаблон", "red");
            }
        });
    });

    document.querySelectorAll(".template-delete-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const templateId = button.getAttribute("data-template-id") || "";
            if (!templateId) return;
            deleteTemplate(templateId);
        });
    });

    TEMPLATE_CRITERIA.forEach((criterion) => {
        const slider = document.getElementById("templateWeight_" + criterion);
        if (slider) {
            slider.addEventListener("input", updateTemplateWeightTotal);
        }
    });

    const saveBtn = document.getElementById("saveTemplateBtn");
    if (saveBtn) {
        saveBtn.addEventListener("click", saveTemplate);
    }

    resetTemplateModal(defaultWeights);
});