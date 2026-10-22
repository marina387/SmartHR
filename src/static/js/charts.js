document.addEventListener("DOMContentLoaded", () => {
    const canvas = document.getElementById("funnelChart");
    const source = document.getElementById("funnelData");
    if (!canvas || !source || typeof Chart === "undefined") return;
    const data = JSON.parse(source.textContent || "{}");
    const stages = data.stages || [];
    new Chart(canvas, {
        type: "bar",
        data: {
            labels: stages.map((item) => item.label),
            datasets: [{
                label: data.group_by === "candidates" ? "Уникальные кандидаты" : "Рассмотрения",
                data: stages.map((item) => item.count),
                backgroundColor: "rgba(79, 70, 229, 0.75)",
                borderColor: "#4f46e5",
                borderWidth: 1,
            }],
        },
        options: {
            responsive: true,
            onClick: (_event, elements) => {
                if (!elements.length) return;
                const stage = stages[elements[0].index];
                const params = new URLSearchParams({ funnel_stage: stage.key });
                if (data.vacancy_id) params.set("vacancy_id", data.vacancy_id);
                window.location.href = "/candidates?" + params.toString();
            },
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        },
    });
});
