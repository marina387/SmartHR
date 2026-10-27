// Attach the server-issued CSRF token only to requests sent to this origin.
(() => {
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, options = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin === location.origin) {
            const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
            if (token) headers.set('X-CSRF-Token', token);
            options = {...options, headers};
        }
        return originalFetch(input, options);
    };
    document.addEventListener('submit', event => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post') return;
        if (new URL(form.action, location.href).origin !== location.origin) return;
        if (!form.querySelector('[name="csrf_token"]')) {
            const field = document.createElement('input');
            field.type = 'hidden'; field.name = 'csrf_token'; field.value = token || '';
            form.appendChild(field);
        }
    }, true);
})();
