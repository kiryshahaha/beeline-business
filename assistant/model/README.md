# Дообученная модель помощника

Файл модели в репозиторий не кладётся (2,1 ГБ). Чтобы запустить помощника
с дообученной моделью:

1. Положите GGUF сюда под именем `model.gguf`
   (результат `finetune/` — `qwen35-2b-beeline-q8_0.gguf`).
2. В `.env` укажите `ASSISTANT_MODEL=qwen3.5-beeline:2b`.
3. `docker compose up --build assistant` — сервис `ollama-pull` создаст модель
   из файла вместо скачивания стандартной `qwen3.5:2b`.

Как модель обучена и как собрать GGUF заново — [`../finetune/README.md`](../finetune/README.md).
