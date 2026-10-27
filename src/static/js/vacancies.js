function vacanciesShowToast(message, type) {
    const toast = document.createElement("div");
    toast.className = "app-notice " + (type || "green");
    toast.textContent = message;
    toast.setAttribute("role", type === "red" ? "alert" : "status");
    toast.setAttribute("aria-live", type === "red" ? "assertive" : "polite");
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), type === "red" ? 9000 : 4500);
}

async function deleteVacancy(vacancyId) {
    if (!window.confirm("Удалить вакансию?")) return;

    try {
        const response = await fetch("/api/vacancies/" + encodeURIComponent(vacancyId), { method: "DELETE" });
        const data = await response.json();
        if (!response.ok || data.error) {
            vacanciesShowToast(data.error || "Не удалось удалить вакансию", "red");
            return;
        }
        vacanciesShowToast("Вакансия удалена", "yellow");
        setTimeout(() => window.location.reload(), 250);
    } catch (err) {
        vacanciesShowToast("Ошибка: " + err.message, "red");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".vacancy-delete-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const vacancyId = button.getAttribute("data-vacancy-id") || "";
            if (!vacancyId) return;
            deleteVacancy(vacancyId);
        });
    });
});
