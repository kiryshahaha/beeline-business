// Модуль-посредник для обновления access_token из apiFetch.
// AuthProvider регистрирует свой setToken сюда, чтобы apiFetch мог
// обновить React state после успешного рефреша без прямой зависимости от контекста.

let _setToken = null;

export function registerTokenSetter(setter) {
  _setToken = setter;
}

export function updateToken(newToken) {
  if (_setToken) _setToken(newToken);
}
