function interviewsShowToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "toast " + (type || "green");
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

function setInterviewActionStatus(text, className) {
    const badge = document.getElementById("interviewActionStatus");
    if (!badge) return;
    badge.className = "badge " + className;
    badge.textContent = text;
}

async function updateInterviewStatus(interviewId, status) {
    try {
        setInterviewActionStatus("Сохранение...", "bg-warning text-dark");
        const response = await fetch("/api/interviews/" + encodeURIComponent(interviewId), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status }),
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            interviewsShowToast(data.error || "Не удалось обновить статус", "red");
            setInterviewActionStatus("Ошибка обновления", "bg-danger");
            return;
        }
        if (data.warnings?.length) window.alert(data.warnings.join("\n"));
        interviewsShowToast(data.warnings?.length ? data.warnings.join(" ") : "Статус интервью обновлён", data.warnings?.length ? "yellow" : "green");
        setInterviewActionStatus("Статус обновлён", "bg-success");
        setTimeout(() => window.location.reload(), 250);
    } catch (err) {
        interviewsShowToast("Ошибка: " + err.message, "red");
        setInterviewActionStatus("Ошибка обновления", "bg-danger");
    }
}

async function deleteInterview(interviewId) {
    try {
        setInterviewActionStatus("Удаление...", "bg-warning text-dark");
        const response = await fetch("/api/interviews/" + encodeURIComponent(interviewId), {
            method: "DELETE",
        });
        const data = await response.json();
        if (!response.ok || data.error) {
            interviewsShowToast(data.error || "Не удалось удалить интервью", "red");
            setInterviewActionStatus("Ошибка удаления", "bg-danger");
            return;
        }
        interviewsShowToast("Интервью удалено", "yellow");
        setInterviewActionStatus("Интервью удалено", "bg-secondary");
        setTimeout(() => window.location.reload(), 250);
    } catch (err) {
        interviewsShowToast("Ошибка: " + err.message, "red");
        setInterviewActionStatus("Ошибка удаления", "bg-danger");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const notice = document.getElementById('interviewNotice');
    const savedNotice = window.sessionStorage.getItem('smarthr-interview-notice');
    if (savedNotice && notice) {
        try {
            const data = JSON.parse(savedNotice);
            notice.textContent = data.text;
            notice.className = `alert ${data.warning ? 'alert-warning' : 'alert-success'}`;
        } catch (_) { /* Устаревшее уведомление можно пропустить. */ }
        window.sessionStorage.removeItem('smarthr-interview-notice');
    }

    const modalElement = document.getElementById('editInterviewModal');
    const editForm = document.getElementById('editInterviewForm');
    const saveButton = document.getElementById('saveInterviewChanges');
    const editError = document.getElementById('editInterviewError');
    let editingId = null;
    let saving = false;
    document.querySelectorAll('.interview-edit-btn').forEach(button => {
        button.addEventListener('click', () => {
            const interview = JSON.parse(button.dataset.interview);
            editingId = interview.id;
            document.getElementById('editInterviewCandidate').textContent = interview.candidate_name;
            document.getElementById('editInterviewVacancy').textContent = `Вакансия: ${interview.vacancy_id} · ${interview.id}`;
            document.getElementById('editInterviewDate').value = interview.date;
            document.getElementById('editInterviewTime').value = interview.time;
            document.getElementById('editInterviewDuration').value = interview.duration;
            document.getElementById('editInterviewFormat').value = interview.format === 'online' ? 'online' : 'office';
            document.getElementById('editInterviewStatus').value = interview.status || 'scheduled';
            document.getElementById('editInterviewNotes').value = interview.notes || '';
            editError.classList.add('d-none');
            bootstrap.Modal.getOrCreateInstance(modalElement).show();
        });
    });
    modalElement?.addEventListener('hide.bs.modal', event => {
        if (saving) event.preventDefault();
    });
    editForm?.addEventListener('submit', async event => {
        event.preventDefault();
        if (saving || !editingId || !editForm.reportValidity()) return;
        saving = true;
        saveButton.disabled = true;
        saveButton.textContent = 'Сохранение…';
        editError.classList.add('d-none');
        try {
            const payload = {
                date: document.getElementById('editInterviewDate').value,
                time: document.getElementById('editInterviewTime').value,
                duration: Number(document.getElementById('editInterviewDuration').value),
                format: document.getElementById('editInterviewFormat').value,
                status: document.getElementById('editInterviewStatus').value,
                notes: document.getElementById('editInterviewNotes').value.trim(),
            };
            const response = await fetch(`/api/interviews/${encodeURIComponent(editingId)}`, {
                method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Не удалось сохранить интервью');
            const warnings = data.warnings || [];
            window.sessionStorage.setItem('smarthr-interview-notice', JSON.stringify({
                text: 'Изменения интервью сохранены.' + (warnings.length ? ' ' + warnings.join(' ') : ''),
                warning: warnings.length > 0,
            }));
            window.location.reload();
        } catch (error) {
            editError.textContent = error.message;
            editError.classList.remove('d-none');
            saving = false;
            saveButton.disabled = false;
            saveButton.textContent = 'Сохранить изменения';
        }
    });

    document.querySelectorAll(".interview-status-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const interviewId = button.getAttribute("data-id") || "";
            const status = button.getAttribute("data-status") || "";
            if (!interviewId || !status) return;
            updateInterviewStatus(interviewId, status);
        });
    });

    document.querySelectorAll(".interview-delete-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const interviewId = button.getAttribute("data-id") || "";
            if (!interviewId) return;
            deleteInterview(interviewId);
        });
    });
});
