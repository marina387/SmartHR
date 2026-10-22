// Общие скрипты HR Tech интерфейса

document.addEventListener('DOMContentLoaded', () => {

    // В DOMContentLoaded:
const loadingState = document.getElementById('loadingState');
if (loadingState) {
    // Показываем спиннер сразу
    loadingState.classList.remove('d-none');
    // Скрываем после полной загрузки страницы (когда данные уже в HTML)
    setTimeout(() => loadingState.classList.add('d-none'), 500);
}
    
    document.querySelectorAll('.quick-command').forEach((button) => {
        button.addEventListener('click', () => {
            const input = document.getElementById('chatInput');
            if (input) {
                input.value = button.dataset.command || '';
                input.focus();
            }
        });
    });
});
