function manualShowToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "toast " + (type || "green");
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

async function saveManualCandidate() {
    const nameInput = document.getElementById("manualCandidateName");
    const positionInput = document.getElementById("manualCandidatePosition");
    const vacancyInput = document.getElementById("manualCandidateVacancy");
    const resumeTextInput = document.getElementById("manualCandidateText");
    const saveButton = document.getElementById("manualCandidateSaveBtn");

    if (!nameInput || !positionInput || !resumeTextInput) {
        return;
    }

    const payload = {
        name: nameInput.value.trim(),
        position: positionInput.value.trim(),
        vacancy_id: vacancyInput ? vacancyInput.value : "VAC_001",
        resume_text: resumeTextInput.value.trim(),
    };

    if (!payload.name || !payload.position || !payload.resume_text) {
        manualShowToast("Заполните имя, должность и текст резюме", "red");
        return;
    }

    if (saveButton) {
        saveButton.disabled = true;
        saveButton.textContent = "Сохранение...";
    }

    try {
        const response = await fetch("/api/candidates/manual", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await response.json();

        if (!response.ok || data.error) {
            manualShowToast(data.error || "Не удалось добавить кандидата", "red");
            return;
        }

        manualShowToast("Кандидат добавлен: " + data.name, "green");

        const modalElement = document.getElementById("manualCandidateModal");
        if (modalElement) {
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) {
                modal.hide();
            }
        }

        setTimeout(() => window.location.reload(), 400);
    } catch (err) {
        manualShowToast("Ошибка: " + err.message, "red");
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.textContent = "Сохранить кандидата";
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const saveButton = document.getElementById("manualCandidateSaveBtn");
    if (saveButton) {
        saveButton.addEventListener("click", saveManualCandidate);
    }
});
