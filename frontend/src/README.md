# Исходники frontend

`app/` — Next.js App Router: layout.jsx, главная page.jsx, глобальные стили,
CSS-модуль и favicon. Сейчас главная страница — исходный шаблон Next.js,
диспетчерские экраны ещё не реализованы.

`api/health.js` содержит обращение к health backend. `features/`, `components/`,
`hooks/`, `lib/` пока содержат файлы-заглушки example.js для будущего разделения кода.
Не считайте наличие этих папок завершёнными пользовательскими функциями.

Из frontend: `npm ci`, `npm run dev`, `npm run lint`, `npm run build`.
API-контракты новых маршрутов и обмена описаны в backend и docs; сохранение данных
пока доступно через HTTP/Swagger/Bruno, готового экрана загрузки в этом шаблоне нет.
