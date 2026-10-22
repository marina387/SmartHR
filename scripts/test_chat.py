from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import torch

# Загружаем базовую модель + LoRA-адаптер
base_model = "Qwen/Qwen2.5-0.5B-Instruct"
adapter_path = "models/chat_model_real"

tokenizer = AutoTokenizer.from_pretrained(adapter_path)
model = AutoModelForCausalLM.from_pretrained(base_model, torch_dtype=torch.float16, device_map="auto")
model = PeftModel.from_pretrained(model, adapter_path)

# Тестовый вопрос
prompt = """Ты HR-ассистент SmartHR. Используй только переданные данные, не придумывай факты.
Профиль кандидата:
Python-разработчик, 4 года опыта. Django, FastAPI, PostgreSQL, Docker.
Ожидаемая зарплата: 150000.
Вакансия: Senior Python Developer. Требования: Python, Django, Docker, опыт от 3 лет.
Вопрос: Оцени, подходит ли этот кандидат на вакансию? Назови ключевые совпадения и чего не хватает."""

messages = [{"role": "user", "content": prompt}]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt").to(model.device)

with torch.no_grad():
    outputs = model.generate(**inputs, max_new_tokens=200, temperature=0.3, do_sample=True)

response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print("ОТВЕТ МОДЕЛИ:")
print(response)