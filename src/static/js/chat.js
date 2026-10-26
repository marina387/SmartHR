// Логика чата и поддержка Enter для отправки

document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chatForm');
    const input = document.getElementById('chatInput');
    const messages = document.getElementById('chatMessages');
    const app = document.getElementById('chatApp');
    const status = document.getElementById('chatStatus');
    const sendButton = chatForm?.querySelector('[type=submit]');

    let candidateId = app?.dataset.candidateId || '';
    let vacancyId = app?.dataset.vacancyId || '';

    const history = [];
    const conversationStorageKey = `smarthr-chat:${candidateId || 'general'}:${vacancyId || 'none'}`;
    let conversationId = new URLSearchParams(window.location.search).get('conversation_id') || window.sessionStorage.getItem(conversationStorageKey);
    const drafts = new Map();
    let nextConversationOffset = null;
    let listLoading = false;
    let listGeneration = 0;

    if (!chatForm || !input || !messages) return;

    function rememberConversation() {
        const url = new URL(window.location.href);
        if (conversationId) {
            window.sessionStorage.setItem(conversationStorageKey, conversationId);
            url.searchParams.set('conversation_id', conversationId);
        } else {
            window.sessionStorage.removeItem(conversationStorageKey);
            url.searchParams.delete('conversation_id');
            url.searchParams.delete('candidate_id');
        }
        window.history.replaceState(null, '', url);
    }

    function markSelectedConversation() {
        document.querySelectorAll('.conversation-item').forEach(button => {
            const selected = button.dataset.id === conversationId;
            button.classList.toggle('is-active', selected);
            if (selected) button.setAttribute('aria-current', 'true');
            else button.removeAttribute('aria-current');
        });
    }

    function renderConversation(item) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'conversation-item';
        button.dataset.id = item.id;
        const title = document.createElement('span');
        title.className = 'conversation-item-title';
        title.textContent = item.title;
        const date = document.createElement('span');
        date.className = 'conversation-item-meta';
        const value = new Date(item.updated_at || item.created_at);
        const formatted = Number.isNaN(value.getTime()) ? '' : value.toLocaleString('ru-RU', {timeZone:'Asia/Yekaterinburg',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
        date.textContent = [formatted, `${item.message_count} сообщ.`].filter(Boolean).join(' · ');
        button.append(title, date);
        if (item.candidate_name) {
            const candidate = document.createElement('span');
            candidate.className = 'conversation-item-meta';
            candidate.textContent = item.candidate_name;
            button.appendChild(candidate);
        }
        button.addEventListener('click', async () => {
            if (input.disabled || conversationId === item.id) return;
            drafts.set(conversationId || 'new', input.value);
            input.disabled = true;
            sendButton.disabled = true;
            try { await restoreConversation(item.id); }
            finally { input.disabled = false; sendButton.disabled = false; }
        });
        document.getElementById('conversationList').appendChild(button);
    }

    async function loadConversations(reset = true) {
        if (!reset && (listLoading || nextConversationOffset === null)) return;
        const generation = reset ? ++listGeneration : listGeneration;
        listLoading = true;
        const listStatus = document.getElementById('conversationListStatus');
        const more = document.getElementById('loadMoreConversations');
        more.disabled = true;
        const offset = reset ? 0 : nextConversationOffset;
        try {
            const response = await fetch(`/api/chat/conversations?limit=30&offset=${offset}`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Не удалось загрузить диалоги');
            if (generation !== listGeneration) return;
            if (reset) document.getElementById('conversationList').replaceChildren();
            data.conversations.forEach(renderConversation);
            nextConversationOffset = data.next_offset;
            more.classList.toggle('d-none', nextConversationOffset === null);
            listStatus.textContent = document.getElementById('conversationList').childElementCount ? '' : 'Здесь появятся ваши сохранённые диалоги.';
            markSelectedConversation();
        } catch (error) {
            if (generation === listGeneration) listStatus.textContent = 'История недоступна. Нажмите кнопку обновления.';
        } finally {
            if (generation === listGeneration) { listLoading = false; more.disabled = false; }
        }
    }
    document.getElementById('refreshConversations').addEventListener('click', () => loadConversations());
    document.getElementById('loadMoreConversations').addEventListener('click', () => loadConversations(false));

    function fitChatHeight() {
        const top = app.getBoundingClientRect().top;
        app.style.setProperty('--chat-height', `${Math.max(340, window.innerHeight - top - 24)}px`);
    }
    fitChatHeight();
    window.addEventListener('resize', fitChatHeight);

    function nearBottom() {
        return messages.scrollHeight - messages.clientHeight - messages.scrollTop < 64;
    }

    function scrollToLatest() {
        // Ждём добавления источников, кнопок и пересчёта высоты сообщения.
        requestAnimationFrame(() => { messages.scrollTop = messages.scrollHeight; });
    }

    const documentQuery = new URLSearchParams(window.location.search).get('document_query');
    if (documentQuery) input.value = documentQuery;

    input.addEventListener('keydown' , (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            chatForm.requestSubmit();
        }
    });

    function appendMessage(role, content) {
        const followLatest = nearBottom();
        const message = document.createElement('div');
        message.className = `message ${role}`;
        const title = document.createElement('div');
        title.className = 'fw-semibold mb-1';
        title.textContent = role === 'user' ? 'Вы' : 'Ассистент';
        const body = document.createElement('div');
        body.textContent = content;
        body.style.whiteSpace = 'pre-wrap';
        message.append(title, body);
        messages.appendChild(message);
        if (followLatest) scrollToLatest();
        return message;
    }

    function appendFeedbackControls(messageElement, messageId, savedFeedback = null) {
        if (!messageId) return;
        const controls = document.createElement('div');
        controls.className = 'd-flex flex-wrap gap-1 mt-2';
        const options = [
            ['Полезно', 'useful'],
            ['Не полезно', 'not_useful'],
            ['Ошибка в фактах', 'factual_error'],
            ['Неверный источник', 'wrong_source'],
        ];
        options.forEach(([label, rating]) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-sm btn-outline-secondary';
            button.textContent = label;
            button.addEventListener('click', async () => {
                let correctedAnswer = '';
                let approvedForTraining = false;
                if (rating === 'factual_error') {
                    correctedAnswer = window.prompt('Введите исправленный ответ (можно оставить пустым):') || '';
                    approvedForTraining = Boolean(correctedAnswer) && window.confirm('Ответ проверен HR и может использоваться для обучения?');
                }
                button.disabled = true;
                try {
                    const response = await fetch(`/api/chat/messages/${messageId}/feedback`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            rating,
                            corrected_answer: correctedAnswer,
                            approved_for_training: approvedForTraining,
                        }),
                    });
                    const result = await response.json();
                    if (!response.ok) throw new Error(result.error || 'Оценка не сохранена');
                    controls.querySelectorAll('button').forEach((item) => { item.disabled = true; });
                    button.textContent = `${label} ✓`;
                } catch (error) {
                    appendMessage('assistant', `Ошибка сохранения обратной связи: ${error.message}`);
                    button.disabled = false;
                }
            });
            if (savedFeedback) {
                button.disabled = true;
                if (savedFeedback.rating === rating) button.textContent = `${label} ✓`;
            }
            controls.appendChild(button);
        });
        messageElement.appendChild(controls);
    }

    function updateContext(context) {
        if (!context) return;
        candidateId = context.candidate?.id || '';
        vacancyId = context.vacancy?.id || '';
        document.getElementById('currentCandidateName').textContent = context.candidate?.name || 'Кандидат не выбран';
        const position = (context.candidate?.position || '').trim();
        const vacancyTitle = (context.vacancy?.title || '').trim();
        const normalizeTitle = value => value.replace(/\s+/g, ' ').toLocaleLowerCase('ru');
        document.getElementById('currentCandidatePosition').textContent = position;
        const vacancyElement = document.getElementById('currentVacancyTitle');
        vacancyElement.textContent = vacancyTitle;
        vacancyElement.hidden = !vacancyTitle || normalizeTitle(position) === normalizeTitle(vacancyTitle);
        document.getElementById('compactChatContext').textContent = context.candidate?.name || 'Кандидат не выбран';
    }

    function appendSources(element, items) {
        if (!items?.length) return;
        const sources = document.createElement('div');
        sources.className = 'small text-muted mt-2';
        sources.textContent = 'Источники: ' + items.map(item => `${item.source}, фрагмент ${Number(item.chunk_id) + 1}`).join('; ');
        element.appendChild(sources);
        document.getElementById('currentDocumentTitle').textContent = items[0].title || items[0].source;
    }

    document.getElementById('newConversation').addEventListener('click', () => {
        if (input.disabled) return;
        drafts.set(conversationId || 'new', input.value);
        conversationId = null;
        rememberConversation();
        input.value = '';
        document.getElementById('currentConversationTitle').textContent = 'Новый диалог';
        markSelectedConversation();
        history.length = 0;
        updateContext({});
        messages.replaceChildren();
        document.getElementById('currentDocumentTitle').textContent = 'Документ не выбран';
        appendMessage('assistant', 'Начат новый диалог. Чем помочь?');
        status.textContent = 'Готов';
        input.focus({preventScroll: true});
    });

    function appendAction(assistantMessage, action) {
        if (action.status && action.status !== "pending") {
            const label = document.createElement("div");
            label.className = "small text-muted mt-2";
            label.textContent = `${action.label}: выполнено`;
            assistantMessage.appendChild(label);
            return;
        }
        if (!action.confirmation_token) return;
                const actionButton = document.createElement('button');
                actionButton.type = 'button';
                actionButton.className = 'btn btn-sm btn-warning mt-2';
                actionButton.textContent = action.label;
                actionButton.addEventListener('click', async () => {
                    if (!window.confirm(`Подтвердить действие: ${action.label}?`)) return;
                    actionButton.disabled = true;
                    const actionConversationId = conversationId;
                    try {
                        const actionResponse = await fetch('/api/chat/actions/confirm', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({confirmation_token: action.confirmation_token}),
                        });
                        const actionResult = await actionResponse.json();
                        if (!actionResponse.ok) throw new Error(actionResult.error || 'Действие не выполнено');
                        if (conversationId === actionConversationId) {
                            updateContext(actionResult.context);
                            appendMessage('assistant', 'Действие подтверждено и сохранено в SmartHR.');
                        }
                        loadConversations();
                        actionButton.textContent = 'Выполнено';
                    } catch (error) {
                        if (conversationId === actionConversationId) appendMessage('assistant', `Ошибка выполнения: ${error.message}`);
                        actionButton.disabled = false;
                    }
                });
                assistantMessage.appendChild(document.createElement('br'));
                assistantMessage.appendChild(actionButton);
            }

    async function restoreConversation(targetId = conversationId) {
        if (!targetId) return;
        status.textContent = 'Загружаю диалог…';
        try {
            const response = await fetch(`/api/chat/conversations/${encodeURIComponent(targetId)}`);
            if (!response.ok) {
                if (response.status === 404 && targetId === conversationId) {
                    conversationId = null;
                    rememberConversation();
                }
                throw new Error('Не удалось открыть диалог');
            }
            const conversation = await response.json();
            conversationId = conversation.id;
            rememberConversation();
            messages.replaceChildren();
            history.length = 0;
            document.getElementById('currentDocumentTitle').textContent = 'Документ не выбран';
            document.getElementById('currentConversationTitle').textContent = conversation.title || conversation.messages.find(item => item.role === 'user')?.content.slice(0,100) || 'Диалог';
            updateContext(conversation.context);
            conversation.messages.forEach((item) => {
                const messageElement = appendMessage(item.role, item.content);
                history.push({role: item.role, content: item.content});
                if (item.role === 'assistant') {
                    appendSources(messageElement, item.sources);
                    appendFeedbackControls(messageElement, item.id, item.feedback);
                    (item.actions || []).forEach(action => appendAction(messageElement, action));
                }
            });
            input.value = drafts.get(conversationId) || '';
            scrollToLatest();
            markSelectedConversation();
            status.textContent = 'Готов';
            if (window.bootstrap) bootstrap.Offcanvas.getInstance(document.getElementById('chatSidebar'))?.hide();
        } catch (_) {
            status.textContent = 'Не удалось открыть диалог. Попробуйте ещё раз.';
        }
    }

    input.disabled = true;
    sendButton.disabled = true;
    restoreConversation().finally(() => {
        if (documentQuery) input.value = documentQuery;
        input.disabled = false;
        sendButton.disabled = false;
    });
    loadConversations();

    chatForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const value = input.value.trim();
        if (!value || input.disabled) return;
        appendMessage('user', value);
        input.value = '';
        input.disabled = true;
        sendButton.disabled = true;
        status.textContent = 'Формирую ответ…';

        const payload = {
            message: value,
            conversation_id: conversationId,
            candidate_id: candidateId || null,
            vacancy_id: vacancyId || null,
            history,
        };

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Не удалось получить ответ');
            const isNewConversation = !conversationId;
            conversationId = data.conversation_id;
            rememberConversation();
            drafts.delete(conversationId);
            if (isNewConversation) document.getElementById('currentConversationTitle').textContent = value.slice(0,100);
            loadConversations();

            updateContext(data.context);
            const assistantMessage = appendMessage('assistant', data.answer);
            appendSources(assistantMessage, data.sources);
            if (data.suggested_action) appendAction(assistantMessage, data.suggested_action);
            appendFeedbackControls(assistantMessage, data.message_id);
            history.push({role: 'user', content: value}, {role: 'assistant', content: data.answer});
            if (history.length > 20) history.splice(0, history.length - 20);
            status.textContent = 'Готов';
        } catch (error) {
            appendMessage('assistant', `Ошибка: ${error.message}`);
            status.textContent = 'Ошибка';
        } finally {
            input.disabled = false;
            sendButton.disabled = false;
            input.focus({preventScroll: true});
        }
    });
});
